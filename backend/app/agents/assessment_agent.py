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
from pydantic_ai import RunContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import ToolLog, build_agent, run_agent
from app.models.assessments import Assessment
from app.models.enums import QuestionStatus as QS, QuestionType
from app.models.jobs import Job
from app.models.questions import Question
from app.schemas.assessment_generation import AssessmentPlan, AssessmentSectionPlan
from app.services.assessments import generator as gen
from app.services.assessments.blueprint import Blueprint, SkillAllocation
from app.services.audit import audit

MAX_GENERATION_ATTEMPTS_PER_SLOT = 2


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
1. call get_job_competencies, then build_assessment_blueprint.
2. For EVERY skill_index in the blueprint, in order:
   search_company_questions(skill_index); if slots remain, search_platform_questions(skill_index);
   if slots still remain, retrieve_knowledge(skill_index) then generate_missing_question(skill_index).
3. Optionally call validate_question on any generated question id you want to double-check.
4. Finally call create_assessment exactly once and return the AssessmentPlan it gives you."""

assessment_agent = build_agent(AssessmentPlan, AssessmentDeps, INSTRUCTIONS)


def _w(d: AssessmentDeps, skill_index: int) -> SkillWork:
    if not d.work:
        raise ValueError("call build_assessment_blueprint first")
    return d.work[skill_index]


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
async def search_company_questions(ctx: RunContext[AssessmentDeps], skill_index: int) -> dict:
    """Fill open slots for this skill from the company's own private question bank."""
    d, w = ctx.deps, _w(ctx.deps, skill_index)
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
async def search_platform_questions(ctx: RunContext[AssessmentDeps], skill_index: int) -> dict:
    """Fill remaining slots from approved platform-wide questions."""
    d, w = ctx.deps, _w(ctx.deps, skill_index)
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
async def retrieve_knowledge(ctx: RunContext[AssessmentDeps], skill_index: int) -> dict:
    """Check how much approved knowledge exists to ground generated questions for this skill."""
    d, w = ctx.deps, _w(ctx.deps, skill_index)
    docs = gen.retrieve_knowledge(w.alloc.skill_name, w.alloc.skill_id, d.job.organization_id, QuestionType.TECHNICAL)
    w.knowledge_chunks = len(docs)
    d.log.record("retrieve_knowledge", skill_index=skill_index, chunks=len(docs))
    return {"skill": w.alloc.skill_name, "grounding_chunks": len(docs), "titles": sorted({x.payload.get("title") for x in docs})}


async def _generate_for(d: AssessmentDeps, skill_index: int) -> dict:
    w = _w(d, skill_index)
    created = []
    for qtype in list(w.need):
        slot = 0
        attempts = 0
        while w.remaining(qtype) > 0 and attempts < w.need[qtype] * MAX_GENERATION_ATTEMPTS_PER_SLOT:
            q = await gen.generate_missing_question(
                d.db, job_id=d.job.id, organization_id=d.job.organization_id, skill_id=w.alloc.skill_id,
                skill_name=w.alloc.skill_name, qtype=qtype, difficulty="medium", slot=slot,
            )
            slot += 1
            attempts += 1
            if QS(q.status) == QS.VALIDATED and q.id not in w.all_ids():
                w.picked.setdefault(qtype, []).append(q.id)
                w.generated += 1
                w.grounded += 1 if q.source_refs else 0
                created.append(str(q.id))
                await audit(d.db, d.actor_user_id, "question_generated", "question", q.id,
                            organization_id=d.job.organization_id, metadata={"grounded": bool(q.source_refs)})
    return {"created_question_ids": created, **_summary(w)}


@assessment_agent.tool
async def generate_missing_question(ctx: RunContext[AssessmentDeps], skill_index: int) -> dict:
    """Generate, validate and index questions for this skill's remaining slots (RAG-grounded when knowledge exists)."""
    result = await _generate_for(ctx.deps, skill_index)
    ctx.deps.log.record("generate_missing_question", skill_index=skill_index, created=len(result["created_question_ids"]))
    return result


@assessment_agent.tool
async def validate_question(ctx: RunContext[AssessmentDeps], question_id: str) -> dict:
    """Return the stored deterministic validation report for a question."""
    q = await ctx.deps.db.get(Question, uuid.UUID(question_id))
    ctx.deps.log.record("validate_question", question_id=question_id)
    return {"status": str(q.status), "report": q.validation_report} if q else {"error": "not found"}


async def _create(d: AssessmentDeps) -> AssessmentPlan:
    d.assessment = await gen.get_or_create_assessment(d.db, d.job.id, d.title, d.blueprint)
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
    d.assessment.plan = plan.model_dump(mode="json")
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
        await assessment_agent.run(f"Build the assessment for job '{job.title}'.", deps=deps)
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
        required_tools={"get_job_competencies", "build_assessment_blueprint", "create_assessment"},
    )
    await db.commit()
    return plan


async def _disabled():
    raise RuntimeError("LLM orchestration disabled for this call")
