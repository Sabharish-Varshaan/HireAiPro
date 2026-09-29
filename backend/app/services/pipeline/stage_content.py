"""Builds the content of the three assessment stages (aptitude, technical, coding). Interview stages are prepared by services/interviews/pool.

Selection order is the same everywhere: the company's private questions, then approved platform questions, then generation for the slots that
remain uncovered. Allocation (how many of what) is deterministic; correctness is never delegated to a model without an independent check
(aptitude answers are re-solved independently, coding tests are executed in Judge0 by the existing generator)."""

import logging
import uuid
from types import SimpleNamespace

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assessment_agent import AssessmentDeps, SkillWork, _drop_cross_skill_duplicates, _generate_for
from app.agents.runtime import ToolLog
from app.core.database import AsyncSessionLocal
from app.models.assessments import Assessment, AssessmentQuestion, AssessmentSection
from app.models.enums import QuestionStatus as QS, QuestionType, Visibility
from app.models.jobs import Job
from app.models.pipeline import HiringStage
from app.models.questions import Question
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.assessments import generator as gen
from app.services.assessments.blueprint import Blueprint, SkillAllocation
from app.services.audit import audit
from app.services.pipeline import stages as S
from app.services.questions.validator import AMBIGUOUS_MCQ, content_hash

logger = logging.getLogger(__name__)
USABLE = [QS.VALIDATED.value, QS.APPROVED.value, QS.ACTIVE.value]
DIFFICULTIES = ("easy", "medium", "hard")


class StageContentError(Exception):
    pass


# ------------------------------------------------------------------ pure allocation
def largest_remainder(total: int, weights: dict[str, float]) -> dict[str, int]:
    """Splits `total` proportionally to `weights`, deterministically (ties by key)."""
    s = sum(weights.values()) or 1.0
    exact = {k: total * v / s for k, v in weights.items()}
    out = {k: int(x) for k, x in exact.items()}
    left = total - sum(out.values())
    for k in sorted(exact, key=lambda k: (-(exact[k] - out[k]), k))[:left]:
        out[k] += 1
    return out


def aptitude_slots(total: int, categories: dict[str, float], difficulty: dict[str, float]) -> list[tuple[str, str]]:
    """(category, difficulty) per question: category counts from the recruiter's mix, difficulty mix applied inside each category."""
    slots: list[tuple[str, str]] = []
    for cat, n in largest_remainder(total, categories).items():
        for diff, m in largest_remainder(n, {d: difficulty.get(d, 0) for d in DIFFICULTIES}).items():
            slots += [(cat, diff)] * m
    return sorted(slots, key=lambda x: (x[0], DIFFICULTIES.index(x[1])))


def technical_allocations(skills: list[dict], total: int, mcq_share: float) -> list[SkillAllocation]:
    """Non-coding blueprint: every confirmed skill gets questions in proportion to its importance (the most important skills first when there
    are more skills than questions); each skill's share is split into multiple-choice and written by the recruiter's MCQ share."""
    ranked = sorted(skills, key=lambda s: (-s["importance"], s["skill_name"]))
    used = ranked[:total] if len(ranked) > total else ranked
    counts = largest_remainder(total, {str(s["skill_id"]): s["importance"] for s in used})
    weight_sum = sum(s["importance"] for s in used) or 1.0
    out = []
    for s in used:
        n = counts[str(s["skill_id"])]
        if n <= 0:
            continue
        mcq = round(n * mcq_share / 100.0)
        out.append(SkillAllocation(skill_id=s["skill_id"], skill_name=s["skill_name"], weight=s["importance"] / weight_sum,
                                   mcq_count=mcq, technical_count=n - mcq, coding_count=0))
    return out


def coding_allocations(skills: list[dict], problems: int) -> list[SkillAllocation]:
    """One coding problem per skill, problem-solving skills first, then by importance; wraps around when problems > skills."""
    def rank(s):
        name = s["skill_name"].lower()
        ps = "problem solving" in name or "algorithm" in name or "data structure" in name
        return (not ps, -s["importance"], s["skill_name"])

    ranked = sorted(skills, key=rank)
    if not ranked:
        return []
    per: dict[str, int] = {}
    for i in range(problems):
        s = ranked[i % len(ranked)]
        per[str(s["skill_id"])] = per.get(str(s["skill_id"]), 0) + 1
    total_w = sum(s["importance"] for s in ranked) or 1.0
    return [SkillAllocation(skill_id=s["skill_id"], skill_name=s["skill_name"], weight=s["importance"] / total_w, mcq_count=0, technical_count=0,
                            coding_count=per[str(s["skill_id"])]) for s in ranked if str(s["skill_id"]) in per]


# ------------------------------------------------------------------ assessment row
async def stage_assessment(db: AsyncSession, job: Job, stage: HiringStage, title: str, blueprint: dict | None) -> Assessment:
    a = await db.get(Assessment, stage.assessment_id) if stage.assessment_id else None
    if a is None:
        a = await db.scalar(select(Assessment).where(Assessment.job_id == job.id, Assessment.stage_type == stage.stage_type))
    if a is not None and a.status == "PUBLISHED":
        raise StageContentError(f"{S.label(stage.stage_type)} is already published and cannot be regenerated")
    if a is None:
        a = Assessment(job_id=job.id, title=title, status="DRAFT", stage_type=stage.stage_type)
        db.add(a)
        await db.flush()
    else:
        await db.execute(delete(AssessmentQuestion).where(AssessmentQuestion.assessment_id == a.id))
        await db.execute(delete(AssessmentSection).where(AssessmentSection.assessment_id == a.id))
    cfg = stage.config or {}
    a.title, a.blueprint, a.stage_type = title, blueprint, stage.stage_type
    a.total_duration_minutes = stage.duration_minutes or S.DEFAULTS[stage.stage_type]["duration_minutes"]
    a.config = {"duration_minutes": a.total_duration_minutes, "randomize_questions": bool(cfg.get("shuffle_questions", True)),
                "randomize_options": bool(cfg.get("shuffle_options", True)),
                **({"allowed_languages": cfg["languages"]} if stage.stage_type == S.CODING and cfg.get("languages") else {})}
    stage.assessment_id = a.id
    await db.flush()
    return a


# ------------------------------------------------------------------ technical / coding
async def generate_skill_stage(db: AsyncSession, job: Job, stage: HiringStage, actor_id: uuid.UUID | None) -> dict:
    """Technical (MCQ + written, never coding) or Coding (coding only) assessment from the confirmed requirements."""
    skills = await gen.get_confirmed_job_skills(db, job.id)
    if not skills:
        raise StageContentError("Confirm the job's skill requirements first")
    cfg = stage.config or {}
    total = int(stage.question_count or S.DEFAULTS[stage.stage_type]["question_count"])
    if stage.stage_type == S.TECHNICAL:
        allocs = technical_allocations(skills, total, float(cfg.get("mcq_share", 40)))
        difficulty = "medium"
    else:
        allocs = coding_allocations(skills, total)
        difficulty = cfg.get("difficulty", "medium") if cfg.get("difficulty") in DIFFICULTIES else "medium"
    if not allocs:
        raise StageContentError("No questions could be planned for this stage")
    bp = Blueprint(allocations=allocs, total_questions=sum(a.mcq_count + a.technical_count + a.coding_count for a in allocs),
                   estimated_duration_minutes=stage.duration_minutes or 0)
    log = ToolLog()
    d = AssessmentDeps(db=db, job=job, title=f"{job.title} — {S.label(stage.stage_type)}", actor_user_id=actor_id, log=log, blueprint=bp, difficulty=difficulty)
    d.work = [SkillWork(alloc=a, need={QuestionType.MCQ: a.mcq_count, QuestionType.TECHNICAL: a.technical_count, QuestionType.CODING: a.coding_count})
              for a in allocs]
    for i, w in enumerate(d.work):
        for qtype in list(w.need):
            n = w.remaining(qtype)
            if n > 0:
                found = await gen.search_company_questions(db, job.organization_id, w.alloc.skill_id, qtype, n, w.all_ids())
                w.picked.setdefault(qtype, []).extend(q.id for q in found)
                w.reused_company += len(found)
        w.company_searched = True
        for qtype in list(w.need):
            n = w.remaining(qtype)
            if n > 0:
                found = await gen.search_platform_questions(db, w.alloc.skill_id, qtype, n, w.all_ids())
                w.picked.setdefault(qtype, []).extend(q.id for q in found)
                w.reused_platform += len(found)
        w.platform_searched = True
        if any(w.remaining(t) > 0 for t in w.need):
            await _generate_for(d, i)
    dropped = await _drop_cross_skill_duplicates(d)
    blueprint_json = {"allocations": [{"skill_id": str(a.skill_id), "skill_name": a.skill_name, "mcq_count": a.mcq_count,
                                       "technical_count": a.technical_count, "coding_count": a.coding_count} for a in allocs], "total_questions": bp.total_questions}
    a = await stage_assessment(db, job, stage, d.title, blueprint_json)
    covered = missing = 0
    for i, w in enumerate(d.work):
        ids = [qid for t in (QuestionType.MCQ, QuestionType.TECHNICAL, QuestionType.CODING) for qid in w.picked.get(t, [])]
        if ids:
            await gen.add_section(db, a, w.alloc.skill_name, i, ids)
        covered += len(ids)
        missing += sum(max(0, w.remaining(t)) for t in w.need)
    a.plan = {"stage_type": stage.stage_type, "covered_slots": covered, "missing_slots": missing, "dropped_duplicates": dropped,
              "reused_company": sum(w.reused_company for w in d.work), "reused_platform": sum(w.reused_platform for w in d.work),
              "generated": sum(w.generated for w in d.work)}
    stage.status = "READY" if covered else "DRAFT"
    await audit(db, actor_id, "stage_generated", "assessment", a.id, organization_id=job.organization_id,
                metadata={"stage_type": stage.stage_type, "questions": covered, "missing": missing})
    await db.flush()
    return {"assessment_id": str(a.id), **a.plan}


# ------------------------------------------------------------------ aptitude
class _AptQ(BaseModel):
    question_text: str
    options: list[str]
    correct_option_index: int
    explanation: str = ""
    sub_category: str = ""


class _Solve(BaseModel):
    answer_index: int


APT_CATEGORY_HINT = {
    "Quantitative Aptitude": "arithmetic, percentages, ratios, time and work, speed and distance, simple algebra; every number must be exactly computable",
    "Logical Reasoning": "series, coding-decoding, syllogisms, seating or ordering puzzles with a single valid answer",
    "Analytical Reasoning": "constraint puzzles and multi-step deductions with a single valid answer",
    "Data Interpretation": "a small table or set of figures written in the question text, then a question that needs calculation from it",
    "Verbal Ability": "vocabulary in context, sentence correction, reading a short passage included in the question",
}


def check_aptitude(q: _AptQ) -> str | None:
    """Deterministic structure check; returns why a candidate is unusable."""
    opts = [o.strip() for o in q.options]
    if len(q.question_text.strip()) < 15:
        return "question too short"
    if len(opts) != 4 or any(not o for o in opts) or len({o.lower() for o in opts}) != 4:
        return "needs exactly four distinct non-empty options"
    if not 0 <= q.correct_option_index < 4:
        return "correct option out of range"
    if AMBIGUOUS_MCQ.search(q.question_text) or any(AMBIGUOUS_MCQ.search(o) for o in opts):
        return "'all/none of the above' is ambiguous"
    return None


async def _apt_pick_existing(db: AsyncSession, org_id: uuid.UUID, cat: str, diff: str, used: set[uuid.UUID], platform: bool) -> Question | None:
    stmt = select(Question).where(Question.domain == "APTITUDE", Question.category == cat, Question.difficulty == diff,
                                  Question.question_type == QuestionType.MCQ, Question.status.in_(USABLE))
    stmt = stmt.where(Question.visibility == Visibility.PLATFORM_PUBLIC) if platform else stmt.where(
        Question.organization_id == org_id, Question.visibility == Visibility.COMPANY_PRIVATE)
    for q in (await db.scalars(stmt.order_by(Question.created_at))).all():
        if q.id not in used:
            return q
    return None


async def _apt_generate(db: AsyncSession, job: Job, cat: str, diff: str, slot: int, taken_hashes: set[str], attempts: int = 3) -> Question | None:
    gw = get_ai_gateway()
    hint = APT_CATEGORY_HINT.get(cat, "a clear, self-contained problem with one correct answer")
    for attempt in range(attempts):
        try:
            q = await gw.generate_structured(
                f"Write ONE {diff} multiple-choice aptitude question in the category '{cat}' ({hint}). Exactly four options, exactly one correct. "
                "The question must be fully self-contained (include any data or passage). Do not use 'all/none of the above'. "
                f"Give the 0-based index of the correct option and a one-sentence explanation. Variation seed: {slot}-{attempt}.",
                _AptQ, task_type="aptitude_generation", related_entity_type="job", related_entity_id=job.id)
        except Exception as exc:  # a failed slot is reported as uncovered
            logger.warning("aptitude generation failed (%s/%s): %s", cat, diff, exc)
            continue
        why = check_aptitude(q)
        h = content_hash(q.question_text)
        if why or h in taken_hashes:
            continue
        try:  # independent re-solve: a wrong answer key is the worst failure an aptitude question can have
            solved = await gw.generate_structured(
                "Solve this question independently and carefully. Return only the 0-based index of the correct option.\n\n"
                f"QUESTION: {q.question_text}\nOPTIONS: {q.options}", _Solve, task_type="aptitude_verification",
                related_entity_type="job", related_entity_id=job.id, temperature=0.0)
        except Exception as exc:
            logger.warning("aptitude verification failed: %s", exc)
            continue
        if solved.answer_index != q.correct_option_index:
            continue
        row = Question(question_text=q.question_text.strip(), question_type=QuestionType.MCQ, skill_id=None, domain="APTITUDE", category=cat,
                       sub_category=(q.sub_category or None), difficulty=diff, options=[o.strip() for o in q.options],
                       correct_option_index=q.correct_option_index, source_type="AI_GENERATED", organization_id=job.organization_id,
                       visibility=Visibility.COMPANY_PRIVATE, status=QS.VALIDATED, provenance="AI_GENERATED_COMPANY_PRIVATE", content_hash=h,
                       generation_key=f"apt:{job.id}:{cat}:{diff}:{slot}:{attempt}:{uuid.uuid4().hex[:8]}",
                       validation_report={"ok": True, "checks": {"structure": True, "independent_solve_agrees": True}, "reasons": []})
        db.add(row)
        await db.flush()
        return row
    return None


async def generate_aptitude_stage(db: AsyncSession, job: Job, stage: HiringStage, actor_id: uuid.UUID | None) -> dict:
    cfg = stage.config or {}
    categories = {k: float(v) for k, v in (cfg.get("categories") or {}).items() if float(v) > 0}
    if not categories:
        raise StageContentError("Choose at least one aptitude category")
    total = int(stage.question_count or S.DEFAULTS[S.APTITUDE]["question_count"])
    slots = aptitude_slots(total, categories, cfg.get("difficulty") or {"easy": 30, "medium": 50, "hard": 20})
    used: set[uuid.UUID] = set()
    taken = set((await db.scalars(select(Question.content_hash).where(Question.organization_id == job.organization_id, Question.domain == "APTITUDE"))).all())
    picked: dict[str, list[uuid.UUID]] = {}
    reused_company = reused_platform = generated = 0
    missing: list[str] = []
    for i, (cat, diff) in enumerate(slots):
        q = await _apt_pick_existing(db, job.organization_id, cat, diff, used, platform=False)
        if q is not None:
            reused_company += 1
        else:
            q = await _apt_pick_existing(db, job.organization_id, cat, diff, used, platform=True)
            if q is not None:
                reused_platform += 1
            else:
                q = await _apt_generate(db, job, cat, diff, i, taken)
                if q is not None:
                    generated += 1
                    taken.add(q.content_hash or "")
        if q is None:
            missing.append(f"{cat} ({diff})")
            continue
        used.add(q.id)
        picked.setdefault(cat, []).append(q.id)
    blueprint_json = {"categories": categories, "difficulty": cfg.get("difficulty"), "total_questions": total}
    a = await stage_assessment(db, job, stage, f"{job.title} — {S.label(S.APTITUDE)}", blueprint_json)
    for i, (cat, ids) in enumerate(picked.items()):
        await gen.add_section(db, a, cat, i, ids)
    covered = sum(len(v) for v in picked.values())
    a.plan = {"stage_type": S.APTITUDE, "covered_slots": covered, "missing_slots": len(missing), "uncovered": missing,
              "reused_company": reused_company, "reused_platform": reused_platform, "generated": generated}
    stage.status = "READY" if covered else "DRAFT"
    await audit(db, actor_id, "stage_generated", "assessment", a.id, organization_id=job.organization_id,
                metadata={"stage_type": S.APTITUDE, "questions": covered, "missing": len(missing)})
    await db.flush()
    return {"assessment_id": str(a.id), **a.plan}


async def check_domain_mix(db: AsyncSession, stage: HiringStage) -> str | None:
    """A stage's assessment may only hold questions of its own domain (no aptitude in technical, no coding in technical, and so on)."""
    rows = (await db.scalars(select(Question).join(AssessmentQuestion, AssessmentQuestion.question_id == Question.id)
                             .where(AssessmentQuestion.assessment_id == stage.assessment_id))).all()
    for q in rows:
        why = S.question_domain_problem(stage.stage_type, q)
        if why:
            return why
    return None


async def _mark_job_ready(db: AsyncSession, job_id: uuid.UUID) -> None:
    from app.models.enums import JobStatus

    job = await db.get(Job, job_id)
    if job is not None and JobStatus(job.status) == JobStatus.REQUIREMENTS_CONFIRMED:
        job.status = JobStatus.ASSESSMENT_READY


# ------------------------------------------------------------------ entry point
async def generate_stage(job_id: uuid.UUID, stage_type: str, actor_id: uuid.UUID | None) -> dict:
    """Idempotent: rebuilds an unpublished stage in place. Interview stages prepare their template and pool instead."""
    if S.is_interview(stage_type):
        from app.services.interviews.pool import fill_pool

        async with AsyncSessionLocal() as db:
            stage = await db.scalar(select(HiringStage).where(HiringStage.job_id == job_id, HiringStage.stage_type == stage_type))
            if stage is None or not stage.enabled:
                raise StageContentError(f"{S.label(stage_type)} is not enabled")
            if stage.status == "PUBLISHED":
                raise StageContentError(f"{S.label(stage_type)} is already published")
        res = await fill_pool(job_id, stage_type)
        async with AsyncSessionLocal() as db:
            stage = await db.scalar(select(HiringStage).where(HiringStage.job_id == job_id, HiringStage.stage_type == stage_type))
            stage.status = "READY" if res.get("status") == "READY" else "DRAFT"
            await _mark_job_ready(db, job_id)
            await db.commit()
        return res
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        stage = await db.scalar(select(HiringStage).where(HiringStage.job_id == job_id, HiringStage.stage_type == stage_type))
        if job is None or stage is None or not stage.enabled:
            raise StageContentError(f"{S.label(stage_type)} is not enabled")
        if stage_type == S.APTITUDE:
            res = await generate_aptitude_stage(db, job, stage, actor_id)
        else:
            res = await generate_skill_stage(db, job, stage, actor_id)
        await _mark_job_ready(db, job_id)
        await db.commit()
        return res
