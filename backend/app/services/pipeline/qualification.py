"""Round qualification: a deterministic threshold engine. No model is asked whether a candidate should advance.

    finished round -> frozen component scores -> weighted round score (0-100) -> score >= threshold ? QUALIFIED : NOT_QUALIFIED

* Score scale is 0-100 everywhere here (`pct`), whatever the component used (0-1 fractions, points, rubric dimensions).
* `score == threshold` qualifies. An incomplete or unscorable round never produces a pass/fail decision: it is EVALUATION_PENDING
  (still being scored) or MANUAL_REVIEW (a component is missing), and an infrastructure failure is never a candidate failure.
* Every evaluation is persisted (`round_results`) with the threshold and weights used, so it is reproducible after the company edits
  its settings. Editing settings never rewrites history; a re-evaluation is a separate audited action that adds a row.
* A human override never edits the score or threshold: it is recorded beside them with reason, actor, time and the previous decision.
"""

import datetime as dt
import math
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import Application
from app.models.assessments import AssessmentAnswer, AssessmentAttempt
from app.models.interviews import Interview, InterviewTurn
from app.models.pipeline import ApplicationStageProgress, HiringStage, RoundResult
from app.services.audit import audit
from app.services.pipeline import stages as S

QUALIFIED, NOT_QUALIFIED, MANUAL_REVIEW, PENDING = "QUALIFIED", "NOT_QUALIFIED", "MANUAL_REVIEW", "EVALUATION_PENDING"
EVALUATION_VERSION = "round_scoring_v1"
DECISION_LABEL = {QUALIFIED: "Qualified", NOT_QUALIFIED: "Not qualified", MANUAL_REVIEW: "Manual review", PENDING: "Evaluation pending"}

# Component keys a round can be weighted by, per stage type (percent weights; the sum must be 100).
COMPONENTS = {
    S.APTITUDE: (),
    S.TECHNICAL: ("mcq", "written"),
    S.CODING: ("coding",),
    S.TECH_INTERVIEW: ("accuracy", "reasoning", "completeness", "communication"),
    S.HR_INTERVIEW: (),
}
COMPONENT_LABEL = {"mcq": "Multiple choice", "written": "Written", "coding": "Coding", "accuracy": "Technical accuracy", "reasoning": "Reasoning",
                   "completeness": "Completeness", "communication": "Communication", "overall": "Overall"}
INTERVIEW_DEFAULT_WEIGHTS = {"accuracy": 40, "reasoning": 25, "completeness": 25, "communication": 10}  # the existing interview rubric composition


class SettingsError(ValueError):
    pass


def pct(fraction: float) -> float:
    """0-1 fraction -> 0-100 score, one decimal."""
    return round(max(0.0, min(1.0, float(fraction))) * 100, 1)


def decide(score: float | None, threshold: float | None) -> str:
    """The whole rule. `>=`: a score exactly at the threshold qualifies."""
    if score is None:
        return PENDING
    return QUALIFIED if score >= threshold else NOT_QUALIFIED  # type: ignore[operator]


def validate_settings(stage_type: str, threshold, auto_qualify: bool, weights) -> tuple[float | None, dict | None]:
    """Reject nonsense before it is stored. Threshold on the 0-100 scale; weights per component, adding to 100."""
    t = None
    if threshold is not None and threshold != "":
        try:
            t = float(threshold)
        except (TypeError, ValueError):
            raise SettingsError("The pass threshold must be a number")
        if not math.isfinite(t) or not 0 <= t <= 100:
            raise SettingsError("The pass threshold must be between 0 and 100")
    if stage_type == S.HR_INTERVIEW and t is not None:
        raise SettingsError("The HR interview has no score, so it has no pass threshold (a person decides after it)")
    if auto_qualify and t is None:
        raise SettingsError("Enter a pass threshold to qualify candidates automatically")
    w = None
    if weights:
        allowed = COMPONENTS.get(stage_type, ())
        if not allowed:
            raise SettingsError("This round is scored as a single result and has no component weights")
        if not isinstance(weights, dict) or any(k not in allowed for k in weights):
            raise SettingsError(f"Weights can only be set for: {', '.join(allowed)}")
        try:
            w = {k: float(v) for k, v in weights.items()}
        except (TypeError, ValueError):
            raise SettingsError("Weights must be numbers")
        if any(not math.isfinite(v) or v < 0 for v in w.values()) or abs(sum(w.values()) - 100) > 0.5:
            raise SettingsError("Component weights must be zero or more and add up to 100%")
    return t, w


# ------------------------------------------------------------------ scoring (frozen data -> components)
@dataclass
class Scored:
    score: float | None
    components: dict
    decision_hint: str | None = None  # PENDING / MANUAL_REVIEW when no score can be given
    reason: str | None = None


def combine(components: dict[str, float | None], weights: dict[str, float] | None) -> Scored:
    """Weighted 0-100 round score. A weighted component that has no score makes the round unscorable (never a misleading partial number)."""
    if not weights:
        vals = {k: v for k, v in components.items() if v is not None}
        return Scored(None, {}, MANUAL_REVIEW, "missing_component") if not vals else Scored(
            round(sum(vals.values()) / len(vals), 1), {k: {"score": v, "weight": None} for k, v in vals.items()})
    missing = [k for k in weights if weights[k] > 0 and components.get(k) is None]
    detail = {k: {"score": components.get(k), "weight": weights[k]} for k in weights}
    if missing:
        return Scored(None, detail, MANUAL_REVIEW, f"missing_component:{','.join(missing)}")
    total = sum(weights.values()) or 1.0
    return Scored(round(sum(components[k] * weights[k] for k in weights) / total, 1), detail)


async def score_assessment(db: AsyncSession, application: Application, stage: HiringStage) -> Scored:
    from app.services.assessments import versioning as ver

    attempt = await db.scalar(select(AssessmentAttempt).where(AssessmentAttempt.application_id == application.id,
                                                              AssessmentAttempt.assessment_id == stage.assessment_id))
    if attempt is None or str(attempt.status) not in ("SCORED", "AssessmentAttemptStatus.SCORED") or attempt.total_score is None:
        return Scored(None, {}, PENDING, "attempt_not_scored")
    fz = await ver.load_frozen(db, attempt)
    answers = {a.assessment_question_id: a for a in (await db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt.id))).all()}
    earned: dict[str, float] = {}
    total: dict[str, float] = {}
    for aq_id, q in fz.by_aq.items():
        key = {"MCQ": "mcq", "TECHNICAL": "written", "CODING": "coding"}.get(str(q.question_type).split(".")[-1], "mcq")
        total[key] = total.get(key, 0.0) + q.points
        a = answers.get(aq_id)
        earned[key] = earned.get(key, 0.0) + ((a.score or 0.0) if a else 0.0)
    comps = {k: pct(earned[k] / total[k]) if total[k] else None for k in total}
    if not stage.weights:
        s = pct(attempt.total_score)  # the attempt's own points-weighted total; the component split is informational
        return Scored(s, {k: {"score": v, "weight": None} for k, v in comps.items()} | {"overall": {"score": s, "weight": None}})
    return combine(comps, stage.weights)


async def score_interview(db: AsyncSession, application: Application, stage: HiringStage) -> Scored:
    itv = await db.scalar(select(Interview).where(Interview.application_id == application.id, Interview.stage_type == stage.stage_type))
    if itv is None or itv.status != "COMPLETED":
        return Scored(None, {}, PENDING, "interview_not_completed")
    turns = [t for t in (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == itv.id))).all() if t.student_answer_text]
    if not turns:
        return Scored(None, {}, MANUAL_REVIEW, "no_answers")
    if any(not t.rubric_evaluation or "concept_accuracy" not in t.rubric_evaluation for t in turns):
        return Scored(None, {}, PENDING, "answers_still_being_scored")  # provider slow or failed: not the candidate's fault
    avg = {k: sum(t.rubric_evaluation[key] for t in turns) / len(turns) for k, key in
           (("accuracy", "concept_accuracy"), ("reasoning", "reasoning"), ("completeness", "completeness"), ("communication", "communication"))}
    return combine({k: pct(v) for k, v in avg.items()}, stage.weights or INTERVIEW_DEFAULT_WEIGHTS)


async def score_round(db: AsyncSession, application: Application, stage: HiringStage) -> Scored:
    if stage.stage_type == S.HR_INTERVIEW:
        return Scored(None, {}, MANUAL_REVIEW, "no_score_for_this_round")
    if S.is_assessment(stage.stage_type):
        return await score_assessment(db, application, stage)
    return await score_interview(db, application, stage)


# ------------------------------------------------------------------ persistence and effects
async def latest_result(db: AsyncSession, application_id: uuid.UUID, stage_id: uuid.UUID) -> RoundResult | None:
    return await db.scalar(select(RoundResult).where(RoundResult.application_id == application_id, RoundResult.hiring_stage_id == stage_id)
                           .order_by(RoundResult.evaluation_version.desc()))


def effective(rr: RoundResult | None) -> str | None:
    """The decision that governs progression: a human override wins over the automatic one (which is never altered)."""
    if rr is None:
        return None
    if rr.override_decision == "ADVANCED":
        return QUALIFIED
    if rr.override_decision == "HELD":
        return MANUAL_REVIEW
    return rr.decision


def gates_open(stage: HiringStage) -> bool:
    """No threshold configured: the round only completes; there is no qualification gate (previous behaviour)."""
    return stage.pass_threshold is None and not stage.auto_qualify


async def evaluate_round(db: AsyncSession, application: Application, stage: HiringStage, *, actor=None, reevaluate: bool = False) -> RoundResult:
    """Freeze the components, compute the score, run the rule, persist. Idempotent unless `reevaluate` (which adds a version)."""
    prev = await latest_result(db, application.id, stage.id)
    if prev is not None and not reevaluate and prev.decision != PENDING:
        return prev
    sc = await score_round(db, application, stage)
    threshold = stage.pass_threshold
    if sc.score is None:
        decision, reason = sc.decision_hint or PENDING, sc.reason
    elif gates_open(stage):
        decision, reason = MANUAL_REVIEW, "no_threshold"
    elif not stage.auto_qualify:
        decision, reason = MANUAL_REVIEW, "automatic_qualification_off"
    else:
        decision = decide(sc.score, threshold)
        reason = "at_or_above_threshold" if decision == QUALIFIED else "below_threshold"
    version = (prev.evaluation_version + 1) if prev is not None else 1
    if prev is not None and prev.decision == PENDING and not reevaluate:
        rr = prev  # finishing a pending evaluation updates that row; nothing was decided yet
        version = prev.evaluation_version
    else:
        rr = RoundResult(application_id=application.id, hiring_stage_id=stage.id, evaluation_version=version)
        db.add(rr)
    rr.score, rr.threshold, rr.decision, rr.reason = sc.score, threshold, decision, reason
    rr.score_components = {"components": sc.components, "engine": EVALUATION_VERSION, "weights": stage.weights}
    rr.evaluated_at = dt.datetime.now(dt.timezone.utc)
    await db.flush()
    if reevaluate:
        await audit(db, actor, "round_reevaluated", "round_result", rr.id, metadata={"stage": stage.stage_type, "version": version, "decision": decision})
    return rr


async def unlock_next(db: AsyncSession, application_id: uuid.UUID, stage: HiringStage) -> ApplicationStageProgress | None:
    from app.services.pipeline import service as pl

    rows = await pl.progress_rows(db, application_id)
    idx = next((i for i, (s, _) in enumerate(rows) if s.id == stage.id), None)
    if idx is None:
        return None
    for _, p in rows[idx + 1:]:
        if p.status == S.LOCKED:
            p.status = S.AVAILABLE
        return p
    return None


def passes_gate(stage: HiringStage, rr: RoundResult | None) -> bool:
    """May the candidate move on right now? Open gate, a qualified result, or a human advance. Pending / failed / held results block."""
    if gates_open(stage):
        return True
    return effective(rr) == QUALIFIED


async def override(db: AsyncSession, application: Application, stage: HiringStage, *, actor, decision: str, reason: str) -> RoundResult:
    """Recruiter advances or holds a candidate. The automatic score, threshold and decision stay exactly as they were."""
    from app.services.pipeline import service as pl

    reason = (reason or "").strip()
    if len(reason) < 5:
        raise SettingsError("Give a reason for the override (at least 5 characters)")
    if decision not in ("ADVANCE", "HOLD"):
        raise SettingsError("Choose to advance or hold the candidate")
    rr = await latest_result(db, application.id, stage.id)
    if rr is None or rr.decision == PENDING:
        raise SettingsError("This round has no finished evaluation yet")
    before = effective(rr)
    rows = await pl.progress_rows(db, application.id)
    idx = next(i for i, (s, _) in enumerate(rows) if s.id == stage.id)
    nxt = rows[idx + 1][1] if idx + 1 < len(rows) else None
    if decision == "ADVANCE":
        if before == QUALIFIED:
            raise SettingsError("The candidate already qualifies for the next round")
        rr.override_decision = "ADVANCED"
        await unlock_next(db, application.id, stage)
    else:
        if before != QUALIFIED:
            raise SettingsError("The candidate is already not advancing")
        if nxt is not None and nxt.status not in (S.LOCKED, S.AVAILABLE):
            raise SettingsError("The next round has already started, so the candidate cannot be held")
        rr.override_decision = "HELD"
        if nxt is not None and nxt.status == S.AVAILABLE:
            nxt.status = S.LOCKED
    rr.override_reason, rr.override_by, rr.override_at, rr.override_previous = reason, getattr(actor, "id", actor), dt.datetime.now(dt.timezone.utc), before
    await audit(db, actor, "round_override", "round_result", rr.id, organization_id=None,
                metadata={"stage": stage.stage_type, "previous": before, "new": effective(rr), "reason": reason, "score": rr.score, "threshold": rr.threshold})
    await db.flush()
    return rr


def view(stage: HiringStage, rr: RoundResult | None, next_label: str | None, *, audience: str) -> dict | None:
    """What each audience may see. Students get score, requirement and a plain result (only where a requirement exists); companies get the full record."""
    if rr is None or rr.decision == PENDING:
        return {"decision": PENDING, "result_label": "Evaluating"} if audience == "student" and rr is not None else None
    eff = effective(rr)
    if audience == "student":
        if gates_open(stage) or rr.score is None:
            return None
        label = {QUALIFIED: "Qualified for the next round" if next_label else "Qualified", NOT_QUALIFIED: "Round completed", MANUAL_REVIEW: "Under review by the hiring team"}[eff]
        return {"score": rr.score, "threshold": rr.threshold, "decision": eff, "result_label": label, "next": next_label if eff == QUALIFIED else None}
    return {"score": rr.score, "threshold": rr.threshold, "automatic_decision": rr.decision, "decision": eff, "reason": rr.reason,
            "evaluated_at": rr.evaluated_at, "evaluation_version": rr.evaluation_version, "components": (rr.score_components or {}).get("components", {}),
            "override": ({"decision": rr.override_decision, "reason": rr.override_reason, "by": rr.override_by, "at": rr.override_at,
                          "previous": rr.override_previous} if rr.override_decision else None)}
