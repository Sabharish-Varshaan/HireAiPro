"""Interview templates + question pools, prepared at authoring time for BOTH interview stages.

TECHNICAL_INTERVIEW: a frozen competency blueprint and a layered pool (per competency: core concept -> how/why -> scenario -> edge
case -> trade-off, 8 questions). The candidate-time path is a database lookup (depth.plan_next chooses the competency and layer, the
pool supplies the wording). Models run here, before the candidate arrives, never while they wait.

HR_INTERVIEW: a separate template and pool of job-relevant behavioural / logistics questions (company HR bank, curated platform
bank, questions built from the posting, optional generated ones), every entry checked by hr_safety."""

import asyncio
import logging
import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.assessments import AssessmentAnswer, AssessmentAttempt, AssessmentQuestion
from app.models.enums import QuestionStatus as QS, QuestionType, Visibility
from app.models.interviews import Interview, InterviewPoolQuestion, InterviewTemplate, InterviewTurn
from app.models.jobs import Job, JobSkill
from app.models.pipeline import HiringStage
from app.models.questions import Question
from app.models.skills import Skill
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.ai_gateway.vector_store import TenantScope
from app.services.interviews import depth
from app.services.interviews.hr_bank import PLATFORM_HR, logistics_questions
from app.services.interviews.hr_safety import BLOCKED_TOPICS_DESCRIPTION, is_safe_question
from app.services.interviews.selector import LEVELS
from app.services.knowledge.service import retrieve, to_source_refs
from app.services.pipeline import stages as S
from app.services.questions.validator import content_hash

logger = logging.getLogger(__name__)

POOL_SKILLS = 12          # competencies prepared (every confirmed competency of a normal job)
TARGET_PER_COMP = 8       # prepared questions per competency (the interview asks at most 4 of them)
MIN_PER_COMP = 5          # a competency counts as ready with at least this many, over MIN_LAYERS layers
MIN_LAYERS = 3
MIN_READY_SKILLS = 3
MAX_BANK_PER_COMP = 4
GENERATION_CONCURRENCY = 3
RUBRIC_CRITERIA = ["Technical accuracy of the concepts used", "Depth of reasoning", "Completeness relative to the question",
                   "Clarity of communication"]
BANK_LAYER = {"easy": 1, "medium": 3, "hard": 5}

LAYER_GUIDE = {
    1: "CORE CONCEPT: what it is and when it is used",
    2: "HOW AND WHY: how it works internally and why it behaves that way",
    3: "APPLIED SCENARIO: a realistic situation the candidate must solve or design for",
    4: "EDGE CASE OR FAILURE: what breaks or behaves unexpectedly, and how they would diagnose or handle it",
    5: "TRADE-OFF: compare two or more approaches and justify a choice under a changed constraint",
}


class _PQ(BaseModel):
    layer: int
    question_text: str
    reason_for_question: str = ""


class _PoolBatch(BaseModel):
    questions: list[_PQ]


class _HRQ(BaseModel):
    category: str
    question_text: str


class _HRBatch(BaseModel):
    questions: list[_HRQ]


def norm(text: str) -> str:
    return " ".join(text.lower().split())


async def _competencies(db: AsyncSession, job_id: uuid.UUID) -> list[dict]:
    rows = (await db.execute(select(JobSkill, Skill.canonical_name).join(Skill, Skill.id == JobSkill.skill_id).where(
        JobSkill.job_id == job_id, JobSkill.confirmed.is_(True), JobSkill.skill_id.is_not(None))
        .order_by(JobSkill.importance.desc()))).all()
    return [{"skill_id": str(js.skill_id), "name": name, "importance": js.importance,
             "required": str(js.requirement_type) == "required", "minimum_level": js.minimum_level} for js, name in rows]


async def _stage(db: AsyncSession, job_id: uuid.UUID, stage_type: str) -> HiringStage | None:
    return await db.scalar(select(HiringStage).where(HiringStage.job_id == job_id, HiringStage.stage_type == stage_type))


async def _template(db: AsyncSession, job_id: uuid.UUID, stage_type: str) -> InterviewTemplate | None:
    return await db.scalar(select(InterviewTemplate).where(InterviewTemplate.job_id == job_id, InterviewTemplate.stage_type == stage_type))


async def upsert_template(db: AsyncSession, job: Job, stage_type: str = S.TECH_INTERVIEW, *, reset: bool = False) -> InterviewTemplate:
    """Builds (or refreshes, while unpublished) the interview blueprint. Technical: competencies, question budget, per-competency range and
    target depth. HR: the configured categories. Stage settings (duration, question count) come from the job's hiring stage."""
    stage = await _stage(db, job.id, stage_type)
    cfg_stage = (stage.config or {}) if stage else {}
    duration = (stage.duration_minutes if stage and stage.duration_minutes else S.DEFAULTS[stage_type]["duration_minutes"])
    if stage_type == S.HR_INTERVIEW:
        lo, hi = int(cfg_stage.get("min_questions", 5)), int(cfg_stage.get("max_questions", 8))
        budget = min(hi, max(lo, (stage.question_count if stage and stage.question_count else lo)))
        config = {"stage_type": stage_type, "categories": cfg_stage.get("categories") or list(S.HR_CATEGORIES[:5]) + ["availability and logistics"],
                  "min_questions": lo, "max_questions": budget, "question_budget": budget, "recommended_minutes": duration,
                  "duration_minutes": duration,
                  "rubric": {"criteria": ["Job-relevant observations only"], "version": "hr_observation_v1"},
                  "question_sources": ["company HR question bank", "platform HR question bank", "questions from the job posting"],
                  "selection": "one question per configured category in rotation; no scoring",
                  "excluded_topics": BLOCKED_TOPICS_DESCRIPTION}
    else:
        comps = await _competencies(db, job.id)
        max_asks = int(cfg_stage.get("max_asks_per_competency", depth.DEFAULT_MAX_ASKS))
        budget = depth.question_budget(duration, stage.question_count if stage else None)
        blueprint = depth.build_blueprint(comps, budget, max_asks)
        config = {"stage_type": stage_type, "competencies": comps, "blueprint": blueprint, "question_budget": budget,
                  "min_questions": min(depth.question_budget(duration, None), budget), "max_questions": budget,
                  "recommended_minutes": duration, "duration_minutes": duration, "max_asks_per_competency": max_asks,
                  "difficulty_range": [LEVELS[0], LEVELS[-1]], "layers": {str(k): v for k, v in depth.LAYERS.items()},
                  "rubric": {"criteria": RUBRIC_CRITERIA, "version": "interview_rubric_v1"},
                  "question_sources": ["company question bank", "platform question bank", "knowledge-grounded generation"],
                  "selection": ("competency by blueprint share and remaining coverage; depth layer follows the previous answer's evidence "
                                "(strong: deeper, weak: fundamentals, uncertain: clarify)")}
    t = await _template(db, job.id, stage_type)
    if t is None:
        t = InterviewTemplate(job_id=job.id, stage_type=stage_type, config=config, status="PREPARING")
        db.add(t)
    else:
        t.config = config
        if reset:
            t.version += 1
            t.status, t.error = "PREPARING", None
    await db.flush()
    return t


async def _asked_texts(db: AsyncSession, interview: Interview) -> set[str]:
    """Everything this candidate already saw for the application: earlier interview turns (any interview stage) and assessment questions."""
    texts = {norm(t) for t in (await db.scalars(select(InterviewTurn.question_text).join(Interview, Interview.id == InterviewTurn.interview_id)
                                                 .where(Interview.application_id == interview.application_id))).all()}
    ids = (await db.scalars(select(AssessmentQuestion.question_id).join(AssessmentAnswer, AssessmentAnswer.assessment_question_id == AssessmentQuestion.id)
                            .join(AssessmentAttempt, AssessmentAttempt.id == AssessmentAnswer.attempt_id)
                            .where(AssessmentAttempt.application_id == interview.application_id))).all()
    if ids:
        texts |= {norm(t) for t in (await db.scalars(select(Question.question_text).where(Question.id.in_(ids)))).all()}
    return texts


# ------------------------------------------------------------------ technical pool
def _bank_filter(org_id):
    return (Question.visibility == Visibility.PLATFORM_PUBLIC) | (Question.organization_id == org_id)


async def fill_pool(job_id: uuid.UUID, stage_type: str = S.TECH_INTERVIEW) -> dict:
    """Idempotent. HR stage -> fill_hr_pool. Technical: bank questions first (capped), then ONE grounded batch call per competency
    that still lacks depth. Returns counts plus a per-competency depth report."""
    if stage_type == S.HR_INTERVIEW:
        return await fill_hr_pool(job_id)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None:
            raise ValueError("job not found")
        t = await upsert_template(db, job, stage_type)
        t.status, t.error = "PREPARING", None
        await db.commit()
        comps = (await _competencies(db, job_id))[:POOL_SKILLS]
        rows = (await db.scalars(select(InterviewPoolQuestion).where(InterviewPoolQuestion.template_id == t.id))).all()
        taken = {norm(r.question_text) for r in rows}
        per_comp: dict[str, list[InterviewPoolQuestion]] = {}
        for r in rows:
            per_comp.setdefault(str(r.skill_id), []).append(r)
        template_id, org_id, title = t.id, job.organization_id, job.title
        added = from_bank = 0

        # 1) approved company / platform questions (interview-domain first, written technical questions second)
        for c in comps:
            have = per_comp.setdefault(c["skill_id"], [])
            bank = (await db.scalars(select(Question).where(
                Question.skill_id == uuid.UUID(c["skill_id"]), Question.question_type == QuestionType.TECHNICAL,
                Question.domain.in_(("TECHNICAL_INTERVIEW", "TECHNICAL")),
                Question.status.in_([QS.VALIDATED.value, QS.APPROVED.value, QS.ACTIVE.value]), _bank_filter(org_id))
                .order_by(Question.domain.desc(), Question.created_at))).all()
            used = sum(1 for r in have if r.source == "question_bank")
            for q in bank:
                if used >= MAX_BANK_PER_COMP or len(have) >= TARGET_PER_COMP or norm(q.question_text) in taken:
                    continue
                layer = BANK_LAYER.get(q.difficulty, 3)
                row = InterviewPoolQuestion(template_id=template_id, skill_id=q.skill_id, difficulty=depth.LAYER_DIFFICULTY[layer], kind=depth.LAYER_KIND[layer],
                                            layer=layer, question_text=q.question_text, reason="approved question bank", source="question_bank",
                                            source_question_id=q.id, content_hash=content_hash(q.question_text))
                db.add(row)
                have.append(row); taken.add(norm(q.question_text)); added += 1; from_bank += 1; used += 1
        await db.commit()

    # 2) grounded generation, one call per competency that lacks depth (context retrieved once per competency; calls overlap)
    todo = [c for c in comps if len({r.layer for r in per_comp.get(c["skill_id"], [])}) < depth.MAX_LAYER or len(per_comp.get(c["skill_id"], [])) < TARGET_PER_COMP]
    ctx: dict[str, tuple[str, list]] = {}
    for c in todo:
        docs = retrieve(f"{c['name']} core concepts", TenantScope(organization_id=org_id), skill_ids=[uuid.UUID(c["skill_id"])], top_k=20, top_n=2)
        ctx[c["skill_id"]] = ("\n\n".join(x.text[:600] for x in docs), to_source_refs(docs))
    sem = asyncio.Semaphore(GENERATION_CONCURRENCY)
    gw = get_ai_gateway()

    async def gen(c: dict):
        have_layers = {}
        for r in per_comp.get(c["skill_id"], []):
            have_layers[r.layer] = have_layers.get(r.layer, 0) + 1
        want = [layer for layer in range(1, depth.MAX_LAYER + 1) if have_layers.get(layer, 0) < 2]
        if not want:
            return None
        text, refs = ctx[c["skill_id"]]
        guide = "\n".join(f"  layer {layer}: {LAYER_GUIDE[layer]}" for layer in want)
        prompt = ((f"CONTEXT:\n{text}\n\n" if text else "")
                  + f"Write interview questions on the competency '{c['name']}' for a '{title}' role. "
                    f"Produce exactly 2 questions for EACH of these depth layers:\n{guide}\n"
                    "Rules: each question is open-ended, stands on its own, and contains no answer, no hint and no multiple-choice options. "
                    "Do not repeat wording between questions. Return the layer number with every question.")
        async with sem:
            try:
                batch = await gw.generate_structured(prompt, _PoolBatch, task_type="interview_pool_batch", related_entity_type="job",
                                                     related_entity_id=job_id)
            except Exception as exc:  # a failed competency only leaves a gap that the runtime fallback covers
                logger.warning("pool generation failed for %s: %s", c["name"], exc)
                return None
        return c, batch, refs

    made = [r for r in await asyncio.gather(*(gen(c) for c in todo)) if r]
    async with AsyncSessionLocal() as db:
        for c, batch, refs in made:
            n_have = sum(1 for r in per_comp.get(c["skill_id"], []))
            for q in batch.questions:
                text = q.question_text.strip()
                if not 1 <= q.layer <= depth.MAX_LAYER or not 15 <= len(text) <= 500 or norm(text) in taken or n_have >= TARGET_PER_COMP + 2:
                    continue
                db.add(InterviewPoolQuestion(template_id=template_id, skill_id=uuid.UUID(c["skill_id"]), difficulty=depth.LAYER_DIFFICULTY[q.layer],
                                             kind=depth.LAYER_KIND[q.layer], layer=q.layer, question_text=text,
                                             reason=(q.reason_for_question or f"layer {q.layer}: {depth.LAYERS[q.layer]}").strip()[:500],
                                             source="generated", source_refs=refs or None, content_hash=content_hash(text)))
                taken.add(norm(text)); added += 1; n_have += 1
        await db.flush()
        rows = (await db.scalars(select(InterviewPoolQuestion).where(InterviewPoolQuestion.template_id == template_id))).all()
        report = _depth_report(rows, comps)
        covered = sum(1 for x in report if x["ready"])
        tpl = await db.get(InterviewTemplate, template_id)
        ok = covered >= min(MIN_READY_SKILLS, len(comps)) and len(comps) > 0
        tpl.status = "READY" if ok else "FAILED"
        tpl.error = None if ok else f"only {covered}/{min(MIN_READY_SKILLS, len(comps))} competencies have >= {MIN_PER_COMP} questions over {MIN_LAYERS} depth layers"
        await db.commit()
        return {"status": tpl.status, "questions": len(rows), "added": added, "from_bank": from_bank, "generated": added - from_bank,
                "competencies": len(comps), "covered": covered, "depth": report}


def _depth_report(rows: list, comps: list[dict]) -> list[dict]:
    out = []
    for c in comps:
        mine = [r for r in rows if str(r.skill_id) == c["skill_id"]]
        layers = sorted({r.layer for r in mine if r.layer})
        out.append({"skill_id": c["skill_id"], "name": c["name"], "questions": len(mine), "layers": layers,
                    "ready": len(mine) >= MIN_PER_COMP and len(layers) >= MIN_LAYERS})
    return out


# ------------------------------------------------------------------ HR pool
async def fill_hr_pool(job_id: uuid.UUID) -> dict:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None:
            raise ValueError("job not found")
        t = await upsert_template(db, job, S.HR_INTERVIEW)
        t.status, t.error = "PREPARING", None
        await db.commit()
        cats: list[str] = list(t.config["categories"])
        rows = (await db.scalars(select(InterviewPoolQuestion).where(InterviewPoolQuestion.template_id == t.id))).all()
        taken = {norm(r.question_text) for r in rows}
        template_id, org_id, title = t.id, job.organization_id, job.title
        added = 0

        def put(cat: str, text: str, source: str, qid=None) -> None:
            nonlocal added
            if norm(text) in taken or not is_safe_question(text):
                return
            db.add(InterviewPoolQuestion(template_id=template_id, skill_id=None, difficulty="medium", kind="behavioural", category=cat,
                                         question_text=text, reason=f"HR: {S.HR_CATEGORY_LABELS.get(cat, cat)}", source=source,
                                         source_question_id=qid, content_hash=content_hash(text)))
            taken.add(norm(text)); added += 1

        bank = (await db.scalars(select(Question).where(
            Question.domain == "HR_INTERVIEW", Question.status.in_([QS.VALIDATED.value, QS.APPROVED.value, QS.ACTIVE.value]),
            _bank_filter(org_id)).order_by(Question.created_at))).all()
        for q in bank:  # company (and approved platform) HR bank; anything sensitive is dropped by put()
            if q.category in cats:
                put(q.category, q.question_text, "question_bank", q.id)
        for cat in cats:
            if cat == "availability and logistics":
                for text in logistics_questions(job):
                    put(cat, text, "posting")
            else:
                for text in PLATFORM_HR.get(cat, [])[:4]:
                    put(cat, text, "platform_hr")
        await db.commit()

    # Optional: two role-contextualised questions for motivation / work preferences (guarded by the same safety filter).
    if any(c in cats for c in ("motivation", "work preferences")):
        try:
            batch = await get_ai_gateway().generate_structured(
                f"Write 2 short HR interview questions for a '{title}' role: one about the candidate's motivation for this kind of work and one about "
                f"their preferred way of working. Job-relevant only; never ask about {BLOCKED_TOPICS_DESCRIPTION}. "
                "Return each with category 'motivation' or 'work preferences'.",
                _HRBatch, task_type="interview_pool_batch", related_entity_type="job", related_entity_id=job_id)
        except Exception as exc:  # the curated bank is enough
            logger.info("HR question generation skipped: %s", exc)
            batch = None
        if batch:
            async with AsyncSessionLocal() as db:
                for q in batch.questions[:4]:
                    if q.category in cats:
                        text = q.question_text.strip()
                        if norm(text) not in taken and is_safe_question(text):
                            db.add(InterviewPoolQuestion(template_id=template_id, skill_id=None, difficulty="medium", kind="behavioural", category=q.category,
                                                         question_text=text, reason=f"HR: {S.HR_CATEGORY_LABELS.get(q.category, q.category)}",
                                                         source="generated", content_hash=content_hash(text)))
                            taken.add(norm(text)); added += 1
                await db.commit()

    async with AsyncSessionLocal() as db:
        rows = (await db.scalars(select(InterviewPoolQuestion).where(InterviewPoolQuestion.template_id == template_id))).all()
        by_cat: dict[str, int] = {}
        for r in rows:
            by_cat[r.category or ""] = by_cat.get(r.category or "", 0) + 1
        tpl = await db.get(InterviewTemplate, template_id)
        covered = sum(1 for c in cats if by_cat.get(c, 0) >= 1)
        ok = covered >= min(3, len(cats)) and len(rows) >= tpl.config["min_questions"]
        tpl.status = "READY" if ok else "FAILED"
        tpl.error = None if ok else "not enough safe HR questions for the configured categories"
        await db.commit()
        return {"status": tpl.status, "questions": len(rows), "added": added, "categories": by_cat, "covered": covered}


# ------------------------------------------------------------------ status / selection
async def pool_status(db: AsyncSession, job_id: uuid.UUID, stage_type: str = S.TECH_INTERVIEW) -> dict:
    t = await _template(db, job_id, stage_type)
    if t is None:
        return {"status": "MISSING", "ready": False}
    n = len((await db.scalars(select(InterviewPoolQuestion.id).where(InterviewPoolQuestion.template_id == t.id))).all())
    return {"status": t.status, "ready": t.status == "READY", "questions": n, "version": t.version, "error": t.error}


async def pool_rows(db: AsyncSession, template_id: uuid.UUID) -> list[InterviewPoolQuestion]:
    return list((await db.scalars(select(InterviewPoolQuestion).where(InterviewPoolQuestion.template_id == template_id)
                                  .order_by(InterviewPoolQuestion.created_at))).all())
