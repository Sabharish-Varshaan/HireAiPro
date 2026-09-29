"""Deterministic hiring-pipeline progression.

Nothing here calls a model: which stage is available, when the next one unlocks and how the coarse ApplicationStatus follows are all
plain rules. `ApplicationStatus` stays the coarse projection that the rest of the product already understands; the per-stage truth is
`application_stage_progress`."""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import Application
from app.models.assessments import Assessment
from app.models.enums import ApplicationStatus as AS
from app.models.jobs import Job
from app.models.pipeline import ApplicationStageProgress, HiringStage
from app.services.applications.service import transition_application
from app.services.pipeline import stages as S


class StageLocked(Exception):
    def __init__(self, message: str, stage_type: str | None = None):
        super().__init__(message)
        self.stage_type = stage_type


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ------------------------------------------------------------------ pipeline definition
async def stages_for_job(db: AsyncSession, job_id: uuid.UUID) -> list[HiringStage]:
    return list((await db.scalars(select(HiringStage).where(HiringStage.job_id == job_id).order_by(HiringStage.order_index))).all())


async def ensure_pipeline(db: AsyncSession, job: Job) -> list[HiringStage]:
    """Returns the job's stages, creating the default pipeline the first time. The default (technical assessment + technical interview)
    is exactly what every pre-pipeline job did, and it adopts the job's existing single assessment."""
    rows = await stages_for_job(db, job.id)
    if rows:
        return rows
    legacy = await db.scalar(select(Assessment).where(Assessment.job_id == job.id, Assessment.stage_type.is_(None)).order_by(Assessment.created_at))
    for i, t in enumerate(S.ALL_STAGES):
        d = S.DEFAULTS[t]
        st = HiringStage(job_id=job.id, stage_type=t, order_index=i, enabled=d["enabled"], required=True, duration_minutes=d["duration_minutes"],
                         question_count=None if t == S.TECH_INTERVIEW else d["question_count"], proctored=True, status="DRAFT", config=default_config(t))
        if t == S.TECHNICAL and legacy is not None:
            st.assessment_id = legacy.id
            st.status = "PUBLISHED" if legacy.status == "PUBLISHED" else "READY"
            st.duration_minutes = legacy.total_duration_minutes or st.duration_minutes
            legacy.stage_type = S.TECHNICAL
        db.add(st)
    await db.flush()
    return await stages_for_job(db, job.id)


def default_config(stage_type: str) -> dict:
    if stage_type == S.APTITUDE:
        first = S.APTITUDE_CATEGORIES[:3]  # quantitative, logical and analytical reasoning: an even split that adds up to exactly 100
        return {"categories": {c: (34 if i == 0 else 33) for i, c in enumerate(first)}, "difficulty": {"easy": 30, "medium": 50, "hard": 20},
                "shuffle_questions": True, "shuffle_options": True}
    if stage_type == S.TECHNICAL:
        return {"mcq_share": 40, "difficulty": {"easy": 30, "medium": 50, "hard": 20}, "shuffle_questions": True, "shuffle_options": True}
    if stage_type == S.CODING:
        return {"languages": list(S.CODING_LANGUAGES), "difficulty": "medium", "shuffle_questions": False, "shuffle_options": False}
    if stage_type == S.TECH_INTERVIEW:
        return {"min_questions": 6, "max_questions": 10, "max_asks_per_competency": 4}
    return {"categories": list(S.HR_CATEGORIES[:5]) + ["availability and logistics"], "min_questions": 5, "max_questions": 8}


def enabled_stages(rows: list[HiringStage]) -> list[HiringStage]:
    return [r for r in rows if r.enabled]


async def stage_by_type(db: AsyncSession, job_id: uuid.UUID, stage_type: str) -> HiringStage | None:
    return await db.scalar(select(HiringStage).where(HiringStage.job_id == job_id, HiringStage.stage_type == stage_type))


async def stage_for_assessment(db: AsyncSession, assessment: Assessment) -> HiringStage | None:
    """The stage an assessment belongs to (legacy single assessments adopt the technical stage)."""
    st = await db.scalar(select(HiringStage).where(HiringStage.assessment_id == assessment.id))
    if st is not None:
        return st
    job = await db.get(Job, assessment.job_id)
    await ensure_pipeline(db, job)
    return await db.scalar(select(HiringStage).where(HiringStage.assessment_id == assessment.id))


# ------------------------------------------------------------------ progress
_PAST_ASSESSMENT = {AS.ASSESSMENT_COMPLETED.value, AS.INTERVIEW_PENDING.value, AS.INTERVIEW_COMPLETED.value, AS.UNDER_REVIEW.value,
                    AS.SHORTLISTED.value, AS.OFFER.value}
_PAST_INTERVIEW = {AS.INTERVIEW_COMPLETED.value, AS.UNDER_REVIEW.value, AS.SHORTLISTED.value, AS.OFFER.value}


async def progress_rows(db: AsyncSession, application_id: uuid.UUID) -> list[tuple[HiringStage, ApplicationStageProgress]]:
    rows = (await db.execute(select(HiringStage, ApplicationStageProgress).join(
        ApplicationStageProgress, ApplicationStageProgress.hiring_stage_id == HiringStage.id)
        .where(ApplicationStageProgress.application_id == application_id).order_by(HiringStage.order_index))).all()
    return [(s, p) for s, p in rows]


async def ensure_progress(db: AsyncSession, application: Application) -> list[tuple[HiringStage, ApplicationStageProgress]]:
    """One progress row per ENABLED stage. Applications that already moved on (created before the pipeline existed) are backfilled from
    their coarse status so nothing they completed is asked again."""
    existing = await progress_rows(db, application.id)
    job = await db.get(Job, application.job_id)
    stages = enabled_stages(await ensure_pipeline(db, job))
    have = {s.id for s, _ in existing}
    if stages and all(s.id in have for s in stages):
        return existing
    status = str(application.status.value if hasattr(application.status, "value") else application.status)
    prior_done = True
    for st in stages:
        if st.id in have:
            prior_done = prior_done and next(p for s, p in existing if s.id == st.id).status in S.DONE
            continue
        done = (S.is_assessment(st.stage_type) and status in _PAST_ASSESSMENT) or (S.is_interview(st.stage_type) and status in _PAST_INTERVIEW)
        state = S.COMPLETED if done else (S.AVAILABLE if prior_done else S.LOCKED)
        db.add(ApplicationStageProgress(application_id=application.id, hiring_stage_id=st.id, status=state,
                                        completed_at=_now() if done else None))
        prior_done = prior_done and done
    await db.flush()
    return await progress_rows(db, application.id)


def _first(rows, pred):
    return next(((s, p) for s, p in rows if pred(s, p)), None)


async def require_stage_open(db: AsyncSession, application: Application, stage: HiringStage) -> ApplicationStageProgress:
    """Server-side gate used by every stage start: only an AVAILABLE or IN_PROGRESS stage can be entered."""
    if str(application.status) in (AS.REJECTED.value,):
        raise StageLocked("This application is closed", stage.stage_type)
    rows = await ensure_progress(db, application)
    hit = _first(rows, lambda s, p: s.id == stage.id)
    if hit is None:
        raise StageLocked(f"{S.label(stage.stage_type)} is not part of this hiring process", stage.stage_type)
    prog = hit[1]
    if prog.status in (S.LOCKED,):
        raise StageLocked(f"{S.label(stage.stage_type)} is not available yet: finish the earlier stages first", stage.stage_type)
    if prog.status in S.DONE:
        raise StageLocked(f"{S.label(stage.stage_type)} is already completed", stage.stage_type)
    return prog


async def mark_started(db: AsyncSession, application: Application, stage: HiringStage, actor_id: uuid.UUID | None,
                       ref: dict | None = None) -> ApplicationStageProgress:
    prog = await require_stage_open(db, application, stage)
    if prog.status == S.AVAILABLE:
        prog.status = S.IN_PROGRESS
        prog.started_at = _now()
    if ref:
        prog.result_reference = ref
    await db.flush()
    await sync_status(db, application, actor_id, started=True, stage=stage)
    return prog


async def complete_stage(db: AsyncSession, application: Application, stage: HiringStage, actor_id: uuid.UUID | None,
                         ref: dict | None = None) -> bool:
    """Completes a stage and unlocks the next enabled one. Idempotent. Returns True when the pipeline just finished and the caller should
    commit and then compute the match (the match reads committed evidence)."""
    rows = await ensure_progress(db, application)
    hit = _first(rows, lambda s, p: s.id == stage.id)
    if hit is None:
        return False
    prog = hit[1]
    if prog.status not in S.DONE:
        prog.status = S.COMPLETED
        prog.completed_at = _now()
        if ref:
            prog.result_reference = ref
    from app.services.pipeline import qualification as Q

    # Deterministic qualification: freeze the round score, apply the threshold. Only a passing gate unlocks the next round.
    rr = await Q.evaluate_round(db, application, stage)
    if Q.passes_gate(stage, rr):
        await Q.unlock_next(db, application.id, stage)
    await db.flush()
    return await sync_status(db, application, actor_id, stage=stage)


async def finalize_pending(db: AsyncSession, application_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> bool:
    """Rounds whose evaluation was still running (or whose scoring provider failed) are evaluated now. Returns True when the pipeline finished."""
    from app.services.pipeline import qualification as Q

    application = await db.get(Application, application_id)
    done = False
    for st, p in await progress_rows(db, application_id):
        rr = await Q.latest_result(db, application_id, st.id)
        if p.status == S.COMPLETED and rr is not None and rr.decision == Q.PENDING:
            rr = await Q.evaluate_round(db, application, st)
            if Q.passes_gate(st, rr):
                await Q.unlock_next(db, application_id, st)
            done = await sync_status(db, application, actor_id, stage=st) or done
    await db.flush()
    return done


async def skip_stage(db: AsyncSession, application: Application, stage: HiringStage, actor_id: uuid.UUID | None) -> bool:
    if stage.required:
        raise StageLocked(f"{S.label(stage.stage_type)} is required and cannot be skipped", stage.stage_type)
    prog = await require_stage_open(db, application, stage)
    prog.status = S.SKIPPED
    prog.completed_at = _now()
    rows = await progress_rows(db, application.id)
    idx = next(i for i, (s, _) in enumerate(rows) if s.id == stage.id)
    for s, p in rows[idx + 1:]:
        if p.status == S.LOCKED:
            p.status = S.AVAILABLE
        break
    await db.flush()
    return await sync_status(db, application, actor_id, stage=stage)


# ------------------------------------------------------------------ coarse status projection
async def _step(db, application, target: AS, actor_id, note: str) -> None:
    from app.services.applications.state_machine import can_transition

    current = AS(str(application.status.value if hasattr(application.status, "value") else application.status))
    if current == target or not can_transition(current, target):
        return
    await transition_application(db, application, target, actor_id, note)


async def sync_status(db: AsyncSession, application: Application, actor_id: uuid.UUID | None, *, started: bool = False,
                      stage: HiringStage | None = None) -> bool:
    """Moves the coarse status to match stage progress (forward only; recruiter decisions are never overridden)."""
    rows = await progress_rows(db, application.id)
    if not rows:
        return False
    assess = [p for s, p in rows if S.is_assessment(s.stage_type)]
    inter = [p for s, p in rows if S.is_interview(s.stage_type)]
    all_assess_done = bool(assess) and all(p.status in S.DONE for p in assess)
    any_assess_started = any(p.status in (S.IN_PROGRESS, *S.DONE) for p in assess)
    all_inter_done = bool(inter) and all(p.status in S.DONE for p in inter)
    any_inter_started = any(p.status in (S.IN_PROGRESS, *S.DONE) for p in inter)
    status = str(application.status.value if hasattr(application.status, "value") else application.status)
    if status not in {AS.APPLIED.value, AS.ASSESSMENT_PENDING.value, AS.ASSESSMENT_COMPLETED.value, AS.INTERVIEW_PENDING.value,
                      AS.INTERVIEW_COMPLETED.value}:
        return False
    compute_match = False
    if await _halted(db, application.id, rows):  # a round ended without qualifying: the candidate waits for a human, not for the next round
        chain = ([AS.ASSESSMENT_COMPLETED] if status in (AS.ASSESSMENT_PENDING.value, AS.APPLIED.value) else [AS.INTERVIEW_COMPLETED]) + [AS.UNDER_REVIEW]
        for tgt in chain:
            await _step(db, application, tgt, actor_id if tgt != AS.UNDER_REVIEW else None,
                        "round not qualified: hiring team review" if tgt == AS.UNDER_REVIEW else "round completed")
        await db.flush()
        return True
    if inter and any_inter_started and (not assess or all_assess_done):
        if assess:
            await _step(db, application, AS.ASSESSMENT_COMPLETED, actor_id, "assessment submitted")
        await _step(db, application, AS.INTERVIEW_PENDING, actor_id, "interview started")
        if all_inter_done:
            await _step(db, application, AS.INTERVIEW_COMPLETED, actor_id, "interview completed")
            await _step(db, application, AS.UNDER_REVIEW, None, "ready for recruiter review")
            compute_match = True
    elif assess and all_assess_done:
        await _step(db, application, AS.ASSESSMENT_COMPLETED, actor_id, "assessment submitted")
        if not inter:
            await _step(db, application, AS.UNDER_REVIEW, None, "ready for recruiter review")
            compute_match = True
    elif assess and any_assess_started:
        await _step(db, application, AS.ASSESSMENT_PENDING, actor_id, "assessment started")
    await db.flush()
    return compute_match


async def _halted(db: AsyncSession, application_id: uuid.UUID, rows) -> bool:
    """True when a finished round did not let the candidate through (not qualified / held / manual) and a later round is still locked."""
    from app.services.pipeline import qualification as Q

    for i, (st, p) in enumerate(rows):
        if p.status != S.COMPLETED or i + 1 >= len(rows) or rows[i + 1][1].status != S.LOCKED:
            continue
        rr = await Q.latest_result(db, application_id, st.id)
        if rr is not None and rr.decision != Q.PENDING and not Q.passes_gate(st, rr):
            return True
    return False


# ------------------------------------------------------------------ views
async def journey(db: AsyncSession, application: Application) -> list[dict]:
    """Ordered stages for this application (enabled only) with their status. Candidate-safe: no content, keys or scores."""
    rows = await ensure_progress(db, application)
    return [{"stage_id": s.id, "stage_type": s.stage_type, "label": S.label(s.stage_type), "order": i + 1, "status": p.status,
             "started_at": p.started_at, "completed_at": p.completed_at, "duration_minutes": s.duration_minutes,
             "assessment_id": s.assessment_id if S.is_assessment(s.stage_type) else None,
             "kind": "assessment" if S.is_assessment(s.stage_type) else "interview", "required": s.required}
            for i, (s, p) in enumerate(rows)]
