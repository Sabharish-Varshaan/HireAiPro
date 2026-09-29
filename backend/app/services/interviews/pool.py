"""Interview template + validated question pool, prepared at authoring time.

The candidate-time path is a database lookup: the deterministic selector picks the competency and difficulty
(importance x uncertainty x required bonus x prerequisite logic), and the next question comes from this pool.
Models are used here, before the candidate arrives, never to invent the next question while they wait.
"""

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
from app.models.questions import Question
from app.models.skills import Skill
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.ai_gateway.vector_store import TenantScope
from app.services.interviews.selector import LEVELS, Candidate
from app.services.knowledge.service import retrieve, to_source_refs
from app.services.questions.validator import content_hash

logger = logging.getLogger(__name__)

POOL_SKILLS = 12  # every confirmed competency of a normal job, so the candidate path never leaves the pool
MIN_READY_SKILLS = 3
MIN_PER_SKILL = 2
GENERATION_CONCURRENCY = 3
RUBRIC_CRITERIA = ["Technical accuracy of the concepts used", "Depth of reasoning", "Completeness relative to the question",
                   "Clarity of communication"]


class _Q(BaseModel):
    question_text: str
    reason_for_question: str


def norm(text: str) -> str:
    return " ".join(text.lower().split())


async def _competencies(db: AsyncSession, job_id: uuid.UUID) -> list[dict]:
    rows = (await db.execute(select(JobSkill, Skill.canonical_name).join(Skill, Skill.id == JobSkill.skill_id).where(
        JobSkill.job_id == job_id, JobSkill.confirmed.is_(True), JobSkill.skill_id.is_not(None))
        .order_by(JobSkill.importance.desc()))).all()
    return [{"skill_id": str(js.skill_id), "name": name, "importance": js.importance,
             "required": str(js.requirement_type) == "required", "minimum_level": js.minimum_level} for js, name in rows]


async def upsert_template(db: AsyncSession, job: Job, *, reset: bool = False) -> InterviewTemplate:
    comps = await _competencies(db, job.id)
    max_turns = get_settings().INTERVIEW_MAX_TURNS
    config = {"competencies": comps, "min_questions": min(3, max_turns), "max_questions": max_turns,
              "recommended_minutes": max_turns * 4, "difficulty_range": [LEVELS[0], LEVELS[-1]],
              "rubric": {"criteria": RUBRIC_CRITERIA, "version": "interview_rubric_v1"},
              "question_sources": ["company question bank", "platform question bank", "knowledge-grounded generation"],
              "selection": "priority = importance x required bonus x (1 - confidence) x 0.5^asks; difficulty follows the last answer"}
    t = await db.scalar(select(InterviewTemplate).where(InterviewTemplate.job_id == job.id))
    if t is None:
        t = InterviewTemplate(job_id=job.id, config=config, status="PREPARING")
        db.add(t)
    else:
        t.config = config
        if reset:
            t.version += 1
            t.status, t.error = "PREPARING", None
    await db.flush()
    return t


async def _asked_texts(db: AsyncSession, interview: Interview) -> set[str]:
    """Everything this candidate already saw for the application: earlier interview turns and assessment questions."""
    texts = {norm(t) for t in (await db.scalars(select(InterviewTurn.question_text).where(InterviewTurn.interview_id == interview.id))).all()}
    ids = (await db.scalars(select(AssessmentQuestion.question_id).join(AssessmentAnswer, AssessmentAnswer.assessment_question_id == AssessmentQuestion.id)
                            .join(AssessmentAttempt, AssessmentAttempt.id == AssessmentAnswer.attempt_id)
                            .where(AssessmentAttempt.application_id == interview.application_id))).all()
    if ids:
        texts |= {norm(t) for t in (await db.scalars(select(Question.question_text).where(Question.id.in_(ids)))).all()}
    return texts


async def fill_pool(job_id: uuid.UUID) -> dict:
    """Idempotent: only missing (skill, difficulty) slots are filled. Bank questions first, then grounded generation."""
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None:
            raise ValueError("job not found")
        t = await upsert_template(db, job)
        t.status, t.error = "PREPARING", None
        await db.commit()
        comps = (await _competencies(db, job_id))[:POOL_SKILLS]
        have = {(str(r.skill_id), r.difficulty) for r in (await db.scalars(select(InterviewPoolQuestion).where(InterviewPoolQuestion.template_id == t.id))).all()}
        taken = {norm(r) for r in (await db.scalars(select(InterviewPoolQuestion.question_text).where(InterviewPoolQuestion.template_id == t.id))).all()}
        template_id, org_id, title = t.id, job.organization_id, job.title
        missing = [(c, d) for c in comps for d in LEVELS if (c["skill_id"], d) not in have]

        # 1) approved technical questions from the company / platform bank
        added, from_bank = 0, 0
        for c in comps:
            bank = (await db.scalars(select(Question).where(
                Question.skill_id == uuid.UUID(c["skill_id"]), Question.question_type == QuestionType.TECHNICAL,
                Question.status.in_([QS.VALIDATED.value, QS.APPROVED.value, QS.ACTIVE.value]),
                (Question.visibility == Visibility.PLATFORM_PUBLIC) | (Question.organization_id == org_id)))).all()
            for d in LEVELS:
                if (c["skill_id"], d) not in have:
                    q = next((q for q in bank if q.difficulty == d and norm(q.question_text) not in taken), None)
                    if q:
                        db.add(InterviewPoolQuestion(template_id=template_id, skill_id=q.skill_id, difficulty=d, question_text=q.question_text,
                                                     reason="approved question bank", source="question_bank", source_question_id=q.id,
                                                     content_hash=content_hash(q.question_text)))
                        have.add((c["skill_id"], d)); taken.add(norm(q.question_text)); added += 1; from_bank += 1
        await db.commit()

    # 2) grounded generation for the slots still empty (context retrieved once per skill; model calls overlap)
    todo = [(c, d) for c, d in missing if (c["skill_id"], d) not in have]
    ctx: dict[str, tuple[str, list]] = {}
    for c in {c["skill_id"]: c for c, _ in todo}.values():
        docs = retrieve(f"{c['name']} core concepts", TenantScope(organization_id=org_id), skill_ids=[uuid.UUID(c["skill_id"])], top_k=20, top_n=2)
        ctx[c["skill_id"]] = ("\n\n".join(x.text[:600] for x in docs), to_source_refs(docs))
    sem = asyncio.Semaphore(GENERATION_CONCURRENCY)
    gw = get_ai_gateway()

    async def gen(c: dict, d: str):
        text, refs = ctx[c["skill_id"]]
        async with sem:
            try:
                q = await gw.generate_structured(
                    (f"CONTEXT:\n{text}\n\n" if text else "")
                    + f"Ask ONE {d} open-ended interview question about '{c['name']}' for a '{title}' role. "
                      "Do not include the answer or hints.",
                    _Q, task_type="interview_pool_question", related_entity_type="job", related_entity_id=job_id)
            except Exception as exc:  # a failed slot only leaves a gap that the runtime fallback covers
                logger.warning("pool generation failed for %s/%s: %s", c["name"], d, exc)
                return None
        return c, d, q, refs

    made = [r for r in await asyncio.gather(*(gen(c, d) for c, d in todo)) if r]
    async with AsyncSessionLocal() as db:
        for c, d, q, refs in made:
            text = q.question_text.strip()
            if not 15 <= len(text) <= 500 or norm(text) in taken:
                continue
            db.add(InterviewPoolQuestion(template_id=template_id, skill_id=uuid.UUID(c["skill_id"]), difficulty=d, question_text=text,
                                         reason=q.reason_for_question.strip()[:500], source="generated", source_refs=refs or None,
                                         content_hash=content_hash(text)))
            taken.add(norm(text)); added += 1
        await db.flush()
        rows = (await db.scalars(select(InterviewPoolQuestion).where(InterviewPoolQuestion.template_id == template_id))).all()
        per_skill: dict[str, int] = {}
        for r in rows:
            per_skill[str(r.skill_id)] = per_skill.get(str(r.skill_id), 0) + 1
        covered = sum(1 for c in comps if per_skill.get(c["skill_id"], 0) >= MIN_PER_SKILL)
        tpl = await db.get(InterviewTemplate, template_id)
        ok = covered >= min(MIN_READY_SKILLS, len(comps)) and len(comps) > 0
        tpl.status = "READY" if ok else "FAILED"
        tpl.error = None if ok else f"only {covered}/{min(MIN_READY_SKILLS, len(comps))} competencies have >= {MIN_PER_SKILL} pool questions"
        await db.commit()
        return {"status": tpl.status, "questions": len(rows), "added": added, "from_bank": from_bank, "generated": added - from_bank,
                "competencies": len(comps), "covered": covered}


async def pool_status(db: AsyncSession, job_id: uuid.UUID) -> dict:
    t = await db.scalar(select(InterviewTemplate).where(InterviewTemplate.job_id == job_id))
    if t is None:
        return {"status": "MISSING", "ready": False}
    n = len((await db.scalars(select(InterviewPoolQuestion.id).where(InterviewPoolQuestion.template_id == t.id))).all())
    return {"status": t.status, "ready": t.status == "READY", "questions": n, "version": t.version, "error": t.error}


def _difficulty_order(want: str) -> list[str]:
    i = LEVELS.index(want) if want in LEVELS else 1
    return sorted(LEVELS, key=lambda d: (abs(LEVELS.index(d) - i), LEVELS.index(d)))


async def select_from_pool(db: AsyncSession, interview: Interview, ranked: list[Candidate], window: int = 2) -> tuple[InterviewPoolQuestion, Candidate] | None:
    """First unseen pool question for the best-ranked competency (exact difficulty, else the nearest); falls through the
    selection window. Returns None when the pool cannot serve (the caller then uses the slower live path)."""
    t = await db.scalar(select(InterviewTemplate).where(InterviewTemplate.job_id == interview.job_id))
    if t is None or not ranked:
        return None
    seen = await _asked_texts(db, interview)
    for cand in ranked[:window]:
        rows = (await db.scalars(select(InterviewPoolQuestion).where(
            InterviewPoolQuestion.template_id == t.id, InterviewPoolQuestion.skill_id == cand.skill_id))).all()
        for d in _difficulty_order(cand.difficulty):
            q = next((r for r in rows if r.difficulty == d and norm(r.question_text) not in seen), None)
            if q is not None:
                return q, cand
    return None
