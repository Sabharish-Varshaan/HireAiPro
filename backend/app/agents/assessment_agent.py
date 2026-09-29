"""Assessment Agent (PydanticAI).

Orchestration only. The blueprint is deterministic, retrieval is
deterministic and tenant-scoped, validation is deterministic. The agent
walks the skills, decides for each whether company/platform questions cover
the slots or generation is needed, and finally creates the assessment.
The AssessmentPlan it returns is rebuilt from the selections the tools
recorded, not from numbers the model writes.
"""

import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.agents.runtime import ToolLog, build_agent, run_agent, run_llm_agent
from app.models.assessments import Assessment
from app.models.enums import QuestionStatus as QS, QuestionType
from app.models.jobs import Job
from app.models.questions import Question
from app.schemas.assessment_generation import AssessmentPlan, AssessmentSectionPlan
from app.services.assessments import generator as gen
from app.services.assessments.blueprint import Blueprint, SkillAllocation
from app.services.audit import audit



@dataclass
class SkillWork:
    alloc: SkillAllocation
    need: dict[QuestionType, int]
    picked: dict[QuestionType, list[uuid.UUID]] = field(default_factory=dict)
    reused_company: int = 0
    reused_platform: int = 0
    generated: int = 0
    grounded: int = 0
    knowledge_chunks: int | None = None
    company_searched: bool = False
    platform_searched: bool = False
    generation_attempts: int = 0
    rejections: dict[QuestionType, list[str]] = field(default_factory=dict)  # compact reasons, per type

    def remaining(self, qtype: QuestionType) -> int:
        return self.need.get(qtype, 0) - len(self.picked.get(qtype, []))

    def all_ids(self) -> set[uuid.UUID]:
        return {i for ids in self.picked.values() for i in ids}


@dataclass
class AssessmentDeps:
    db: AsyncSession
    job: Job
    title: str
    actor_user_id: uuid.UUID | None
    log: ToolLog
    competencies: list[dict] = field(default_factory=list)
    blueprint: Blueprint | None = None
    work: list[SkillWork] = field(default_factory=list)
    assessment: Assessment | None = None


INSTRUCTIONS = """You assemble a hiring assessment from confirmed job competencies.
You have a small request budget: put independent tool calls (e.g. the searches for several skills) in the SAME response.
1. Call build_assessment_blueprint (it loads the confirmed competencies itself).
2. Call generate_missing_question with an empty list: for every skill it first reuses company, then
   platform questions, and only generates what's still missing. You can instead call
   search_company_questions / search_platform_questions / retrieve_knowledge first if you want to
   inspect coverage — all take a list of skill indexes (empty = all) and run in the order called.
3. Optionally call validate_question on a generated question id.
4. Finally call create_assessment exactly once, then reply with a one-line confirmation."""

assessment_agent = build_agent(AssessmentPlan, AssessmentDeps, INSTRUCTIONS, "assessment_agent")


def _w(d: AssessmentDeps, skill_index: int) -> SkillWork:
    if not d.work:
        raise ModelRetry("call build_assessment_blueprint first")
    if not 0 <= skill_index < len(d.work):
        raise ModelRetry(f"skill_index must be between 0 and {len(d.work) - 1}")
    return d.work[skill_index]


def _indexes(d: AssessmentDeps, skill_indexes: list[int] | None) -> list[int]:
    if not d.work:
        raise ModelRetry("call build_assessment_blueprint first")
    return list(range(len(d.work))) if not skill_indexes else skill_indexes


def _summary(w: SkillWork) -> dict:
    return {
        "skill": w.alloc.skill_name,
        "remaining": {t.value: w.remaining(t) for t in w.need if w.remaining(t) > 0},
    }


@assessment_agent.tool
async def get_job_competencies(ctx: RunContext[AssessmentDeps]) -> list[dict]:
    """Recruiter-confirmed skills for the job (unconfirmed ones are never used)."""
    d = ctx.deps
    d.competencies = await gen.get_confirmed_job_skills(d.db, d.job.id)
    d.log.record("get_job_competencies", count=len(d.competencies))
    return [
        {"skill": c["skill_name"], "requirement": str(c["requirement_type"]), "importance": c["importance"]}
        for c in d.competencies
    ]


@assessment_agent.tool
async def build_assessment_blueprint(ctx: RunContext[AssessmentDeps]) -> list[dict]:
    """Deterministic allocation of question counts/types per skill."""
    d = ctx.deps
    if not d.competencies:
        d.competencies = await gen.get_confirmed_job_skills(d.db, d.job.id)
    d.blueprint = gen.blueprint_for(d.competencies)
    d.work = [
        SkillWork(
            alloc=a,
            need={QuestionType.MCQ: a.mcq_count, QuestionType.TECHNICAL: a.technical_count, QuestionType.CODING: a.coding_count},
        )
        for a in d.blueprint.allocations
    ]
    d.log.record("build_assessment_blueprint", skills=len(d.work), total=d.blueprint.total_questions)
    return [{"skill_index": i, **_summary(w)} for i, w in enumerate(d.work)]


@assessment_agent.tool
async def search_company_questions(ctx: RunContext[AssessmentDeps], skill_indexes: list[int] | None = None) -> list[dict]:
    """Fill open slots from the company's own private question bank. Pass the skill indexes (empty = all skills)."""
    return [await _company(ctx.deps, i) for i in _indexes(ctx.deps, skill_indexes)]


async def _company(d: AssessmentDeps, skill_index: int) -> dict:
    w = _w(d, skill_index)
    for qtype in list(w.need):
        n = w.remaining(qtype)
        if n > 0:
            found = await gen.search_company_questions(d.db, d.job.organization_id, w.alloc.skill_id, qtype, n, w.all_ids())
            w.picked.setdefault(qtype, []).extend(q.id for q in found)
            w.reused_company += len(found)
    w.company_searched = True
    d.log.record("search_company_questions", skill_index=skill_index, reused=w.reused_company)
    return _summary(w)


@assessment_agent.tool
async def search_platform_questions(ctx: RunContext[AssessmentDeps], skill_indexes: list[int] | None = None) -> list[dict]:
    """Fill remaining slots from approved platform-wide questions (empty = all skills)."""
    return [await _platform(ctx.deps, i) for i in _indexes(ctx.deps, skill_indexes)]


async def _platform(d: AssessmentDeps, skill_index: int) -> dict:
    w = _w(d, skill_index)
    for qtype in list(w.need):
        n = w.remaining(qtype)
        if n > 0:
            found = await gen.search_platform_questions(d.db, w.alloc.skill_id, qtype, n, w.all_ids())
            w.picked.setdefault(qtype, []).extend(q.id for q in found)
            w.reused_platform += len(found)
    w.platform_searched = True
    d.log.record("search_platform_questions", skill_index=skill_index, reused=w.reused_platform)
    return _summary(w)


@assessment_agent.tool
async def retrieve_knowledge(ctx: RunContext[AssessmentDeps], skill_indexes: list[int] | None = None) -> list[dict]:
    """Check how much approved knowledge exists to ground generated questions (empty = all skills)."""
    return [await _knowledge(ctx.deps, i) for i in _indexes(ctx.deps, skill_indexes)]


async def _knowledge(d: AssessmentDeps, skill_index: int) -> dict:
    w = _w(d, skill_index)
    docs = gen.retrieve_knowledge(w.alloc.skill_name, w.alloc.skill_id, d.job.organization_id, QuestionType.TECHNICAL)
    w.knowledge_chunks = len(docs)
    d.log.record("retrieve_knowledge", skill_index=skill_index, chunks=len(docs))
    return {"skill": w.alloc.skill_name, "grounding_chunks": len(docs), "titles": sorted({x.payload.get("title") for x in docs})}


async def _generate_for(d: AssessmentDeps, skill_index: int) -> dict:
    w = _w(d, skill_index)
    # Never generate what the question banks already cover: run the searches
    # the agent skipped for this skill first.
    if not w.company_searched:
        await _company(d, skill_index)
    if not w.platform_searched:
        await _platform(d, skill_index)
    created = []
    per_slot = max(1, get_settings().ASSESSMENT_SLOT_GENERATION_ATTEMPTS)
    for qtype in list(w.need):
        slot_index = 0
        while w.remaining(qtype) > 0:
            # One slot: initial generation + bounded replacements. Each replacement is told
            # why the previous candidate failed and may not repeat a rejected candidate.
            reasons: list[str] = []
            rejected_hashes: set[str] = set()
            filled = False
            for attempt in range(per_slot):
                q = await gen.generate_missing_question(
                    d.db, job_id=d.job.id, organization_id=d.job.organization_id, skill_id=w.alloc.skill_id,
                    skill_name=w.alloc.skill_name, qtype=qtype, difficulty="medium",
                    slot=slot_index * 100 + attempt, avoid=list(reasons), rejected_hashes=set(rejected_hashes),
                )
                w.generation_attempts += 1
                if QS(q.status) == QS.VALIDATED and q.id not in w.all_ids():
                    w.picked.setdefault(qtype, []).append(q.id)
                    w.generated += 1
                    w.grounded += 1 if q.source_refs else 0
                    created.append(str(q.id))
                    await audit(d.db, d.actor_user_id, "question_generated", "question", q.id,
                                organization_id=d.job.organization_id,
                                metadata={"grounded": bool(q.source_refs), "attempt": attempt + 1})
                    filled = True
                    break
                why = "; ".join((q.validation_report or {}).get("reasons") or []) or f"not usable ({q.status})"
                reasons.append(why[:200])
                rejected_hashes.add(gen.content_hash(q.question_text))
                w.rejections.setdefault(qtype, []).append(why[:200])
            slot_index += 1
            if not filled:
                break  # this slot stays uncovered; do not burn further attempts on the same type
    return {"created_question_ids": created, **_summary(w)}


@assessment_agent.tool
async def generate_missing_question(ctx: RunContext[AssessmentDeps], skill_indexes: list[int] | None = None) -> list[dict]:
    """Generate, validate and index questions for remaining slots, RAG-grounded when knowledge exists (empty = all skills)."""
    out = []
    for i in _indexes(ctx.deps, skill_indexes):
        result = await _generate_for(ctx.deps, i)
        ctx.deps.log.record("generate_missing_question", skill_index=i, created=len(result["created_question_ids"]))
        out.append(result)
    return out


@assessment_agent.tool
async def validate_question(ctx: RunContext[AssessmentDeps], question_id: str) -> dict:
    """Return the stored deterministic validation report for a question."""
    q = await ctx.deps.db.get(Question, uuid.UUID(question_id))
    ctx.deps.log.record("validate_question", question_id=question_id)
    return {"status": str(q.status), "report": q.validation_report} if q else {"error": "not found"}


async def _drop_cross_skill_duplicates(d: AssessmentDeps) -> list[str]:
    """Never place the same problem twice in one assessment, even when it was picked
    under two different skills (e.g. a reworded coding task under both Data Structures
    and Algorithms). Uses the validator's duplicate threshold; later picks lose."""
    from app.services.ai_gateway.embeddings import embed
    from app.services.questions.validator import DUPLICATE_THRESHOLD

    order = [(w, t, qid) for w in d.work for t in (QuestionType.MCQ, QuestionType.TECHNICAL, QuestionType.CODING)
             for qid in w.picked.get(t, [])]
    if len(order) < 2:
        return []
    texts = [(await d.db.get(Question, qid)).question_text for _, _, qid in order]
    vecs = embed(texts)
    kept, dropped = [], []
    for (w, t, qid), v in zip(order, vecs):
        if any(sum(a * b for a, b in zip(v, k)) >= DUPLICATE_THRESHOLD for k in kept):
            w.picked[t].remove(qid)
            dropped.append(str(qid))
        else:
            kept.append(v)
    if dropped:
        d.log.record("drop_duplicate_questions", dropped=dropped)
    return dropped


async def _create(d: AssessmentDeps) -> AssessmentPlan:
    d.assessment = await gen.get_or_create_assessment(d.db, d.job.id, d.title, d.blueprint)
    dropped = await _drop_cross_skill_duplicates(d)
    sections, covered, missing, total = [], [], [], 0
    for i, w in enumerate(d.work):
        ids = [qid for t in (QuestionType.MCQ, QuestionType.TECHNICAL, QuestionType.CODING) for qid in w.picked.get(t, [])]
        if ids:
            await gen.add_section(d.db, d.assessment, w.alloc.skill_name, i, ids)
            covered.append(w.alloc.skill_id)
        if any(w.remaining(t) > 0 for t in w.need) or not ids:
            missing.append(w.alloc.skill_id)
        total += len(ids)
        sections.append(AssessmentSectionPlan(
            skill_id=w.alloc.skill_id, skill_name=w.alloc.skill_name, question_ids=ids,
            reused_company=w.reused_company, reused_platform=w.reused_platform,
            generated=w.generated, grounded=w.grounded,
        ))
    plan = AssessmentPlan(
        job_id=d.job.id, assessment_id=d.assessment.id, sections=sections, total_questions=total,
        covered_skills=covered, missing_coverage=missing,
        estimated_duration_minutes=d.blueprint.estimated_duration_minutes,
    )
    required = sum(sum(w.need.values()) for w in d.work)
    covered = sum(len(ids) for w in d.work for ids in w.picked.values())
    uncovered = [
        {"skill": w.alloc.skill_name, "question_type": t.value, "missing": w.remaining(t),
         "rejection_reasons": (w.rejections.get(t) or [])[-3:]}
        for w in d.work for t in w.need if w.remaining(t) > 0
    ]
    coverage = {
        "required_slots": required, "covered_slots": covered, "uncovered_slots": uncovered,
        "coverage_percentage": round(100 * covered / required, 1) if required else 100.0,
        "generation_attempts": sum(w.generation_attempts for w in d.work),
        "rejection_reasons": [r for w in d.work for rs in w.rejections.values() for r in rs][-20:],
        "attempts_per_slot": get_settings().ASSESSMENT_SLOT_GENERATION_ATTEMPTS,
    }
    d.assessment.plan = {**plan.model_dump(mode="json"), "dropped_duplicates": dropped, "coverage": coverage}
    await d.db.flush()
    return plan


@assessment_agent.tool
async def create_assessment(ctx: RunContext[AssessmentDeps]) -> AssessmentPlan:
    """Persist the assessment from the questions selected so far. Call once, at the end."""
    plan = await _create(ctx.deps)
    ctx.deps.log.record("create_assessment", assessment_id=plan.assessment_id, total=plan.total_questions)
    return plan


async def run_assessment_agent(
    db: AsyncSession, job: Job, title: str, actor_user_id: uuid.UUID | None, use_llm: bool = True
) -> AssessmentPlan:
    log = ToolLog()
    deps = AssessmentDeps(db=db, job=job, title=title, actor_user_id=actor_user_id, log=log)

    async def llm() -> AssessmentPlan:
        await run_llm_agent(assessment_agent, "assessment_agent", f"Build the assessment for job '{job.title}'.", deps, log)
        skipped = [w.alloc.skill_name for w in deps.work if not w.company_searched]
        if not deps.work or skipped or deps.assessment is None:
            raise RuntimeError(f"agent skipped skills or never created the assessment: {skipped}")
        return AssessmentPlan.model_validate(deps.assessment.plan)

    async def fallback() -> AssessmentPlan:
        deps.competencies = await gen.get_confirmed_job_skills(db, job.id)
        deps.blueprint = gen.blueprint_for(deps.competencies)
        if not deps.work:
            deps.work = [
                SkillWork(alloc=a, need={QuestionType.MCQ: a.mcq_count, QuestionType.TECHNICAL: a.technical_count, QuestionType.CODING: a.coding_count})
                for a in deps.blueprint.allocations
            ]
        for i, w in enumerate(deps.work):
            if not w.company_searched:
                for qtype in list(w.need):
                    n = w.remaining(qtype)
                    if n > 0:
                        found = await gen.search_company_questions(db, job.organization_id, w.alloc.skill_id, qtype, n, w.all_ids())
                        w.picked.setdefault(qtype, []).extend(q.id for q in found)
                        w.reused_company += len(found)
                w.company_searched = True
            if not w.platform_searched:
                for qtype in list(w.need):
                    n = w.remaining(qtype)
                    if n > 0:
                        found = await gen.search_platform_questions(db, w.alloc.skill_id, qtype, n, w.all_ids())
                        w.picked.setdefault(qtype, []).extend(q.id for q in found)
                        w.reused_platform += len(found)
                w.platform_searched = True
            if any(w.remaining(t) > 0 for t in w.need):
                await _generate_for(deps, i)
            log.record("fallback:skill", skill_index=i)
        return await _create(deps)

    plan = await run_agent(
        agent_type="assessment_agent", task=f"build_assessment:{job.id}", context_type="job", context_id=job.id,
        tool_log=log, run_llm=llm if use_llm else _disabled, fallback=fallback,
        required_tools={"build_assessment_blueprint", "create_assessment"},
    )
    await db.commit()
    return plan


async def _disabled():
    raise RuntimeError("LLM orchestration disabled for this call")
