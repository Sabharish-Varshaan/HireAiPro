"""Career Agent (PydanticAI).

Gaps are calculated deterministically (`calculate_skill_gaps` tool →
app.services.career.gaps). The agent explains and orders them, pulling real
resources with `search_learning_resources`. `save_learning_path` is the
guard: it drops any skill that isn't a gap or a gap's prerequisite, drops
any resource id that isn't a stored resource for that skill (so resources
can't be invented), and moves prerequisites ahead of the skills that need
them.
"""

import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import ToolLog, build_agent, run_agent, run_llm_agent, tool_uuid
from app.models.career import LearningPath, LearningPathStep, LearningResource
from app.models.evidence import StudentSkill
from app.models.jobs import Job
from app.models.skills import Skill
from app.schemas.career import CareerRoadmap, CareerStep, ResourceRef
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.career import gaps as gap_service


class PlannedStep(BaseModel):
    skill_id: str
    rationale: str
    resource_ids: list[str] = Field(default_factory=list)
    resource_id: str | None = None  # models sometimes send a single id; folded into resource_ids

    def ids(self) -> list[str]:
        return self.resource_ids + ([self.resource_id] if self.resource_id else [])


@dataclass
class CareerDeps:
    db: AsyncSession
    student_id: uuid.UUID
    job: Job
    log: ToolLog
    gaps: list[dict] = field(default_factory=list)
    prereqs: dict[str, list[str]] = field(default_factory=dict)
    resources: dict[str, list[LearningResource]] = field(default_factory=dict)
    saved: CareerRoadmap | None = None


INSTRUCTIONS = """You are a career coach building a learning roadmap toward a target job.
You have a small request budget: put independent tool calls in the SAME response.
1. Call calculate_skill_gaps (it already includes each gap's prerequisites and stored resources).
   get_target_job / get_student_skills / get_skill_prerequisites / search_learning_resources are
   available if you need more detail (e.g. resources for a prerequisite).
2. Call save_learning_path ONCE with steps ordered prerequisites-first, each with a
   one-sentence rationale and resource_ids chosen ONLY from search_learning_resources
   results, plus a 2-3 sentence encouraging summary. Never invent resources.
3. Then reply with a one-line confirmation."""

career_agent = build_agent(CareerRoadmap, CareerDeps, INSTRUCTIONS, "career_agent")


@career_agent.tool
async def get_target_job(ctx: RunContext[CareerDeps]) -> dict:
    """Target job title and id."""
    ctx.deps.log.record("get_target_job")
    return {"job_id": str(ctx.deps.job.id), "title": ctx.deps.job.title}


@career_agent.tool
async def get_student_skills(ctx: RunContext[CareerDeps]) -> list[dict]:
    """The student's verified skill levels (from the deterministic SkillEstimator)."""
    d = ctx.deps
    rows = (await d.db.scalars(select(StudentSkill).where(StudentSkill.student_id == d.student_id))).all()
    out = []
    for r in rows:
        s = await d.db.get(Skill, r.skill_id)
        out.append({"skill": s.canonical_name if s else str(r.skill_id), "level": round(r.estimated_level, 2),
                    "confidence": round(r.confidence, 2)})
    d.log.record("get_student_skills", count=len(out))
    return out


@career_agent.tool
async def calculate_skill_gaps(ctx: RunContext[CareerDeps]) -> list[dict]:
    """Deterministic gaps: required level minus current level, ordered by gap × importance."""
    d = ctx.deps
    d.gaps = await gap_service.calculate_skill_gaps(d.db, d.student_id, d.job.id)
    d.log.record("calculate_skill_gaps", gaps=len(d.gaps))
    # Compact on purpose: this result is re-sent on every later model turn,
    # so it's capped (top 8 gaps, <=2 prerequisites/resources each).
    out = []
    for g in d.gaps[:8]:
        sid = str(g["skill_id"])
        pre = (await gap_service.get_prerequisites(d.db, g["skill_id"]))
        d.prereqs[sid] = [str(p.id) for p in pre]
        out.append({
            "id": sid, "skill": g["skill_name"], "gap": round(g["gap"], 2),
            "resources": [str(r.id) for r in (await _resources(d, sid))[:2]],
            "prereqs": [{"id": str(p.id), "skill": p.canonical_name,
                         "resources": [str(r.id) for r in (await _resources(d, str(p.id)))[:2]]} for p in pre[:2]],
        })
    for g in d.gaps[8:]:
        d.prereqs[str(g["skill_id"])] = [str(p.id) for p in await gap_service.get_prerequisites(d.db, g["skill_id"])]
    return out


@career_agent.tool
async def get_skill_prerequisites(ctx: RunContext[CareerDeps], skill_id: str) -> list[dict]:
    """Prerequisite skills from the taxonomy graph."""
    d = ctx.deps
    pre = await gap_service.get_prerequisites(d.db, tool_uuid(skill_id, "skill_id"))
    d.prereqs[skill_id] = [str(p.id) for p in pre]
    d.log.record("get_skill_prerequisites", skill_id=skill_id, count=len(pre))
    return [{"skill_id": str(p.id), "skill": p.canonical_name} for p in pre]


async def _resources(d: CareerDeps, skill_id: str) -> list[LearningResource]:
    if skill_id not in d.resources:
        d.resources[skill_id] = list(
            (
                await d.db.scalars(
                    select(LearningResource)
                    .where(LearningResource.skill_id == tool_uuid(skill_id, "skill_id"), LearningResource.status == "ACTIVE")
                    .order_by(LearningResource.difficulty)
                )
            ).all()
        )
    return d.resources[skill_id]


@career_agent.tool
async def search_learning_resources(ctx: RunContext[CareerDeps], skill_ids: list[str]) -> dict:
    """Curated learning resources stored for each of these skills."""
    out = {}
    for sid in skill_ids:
        rows = await _resources(ctx.deps, sid)
        out[sid] = [{"resource_id": str(r.id), "title": r.title, "provider": r.provider, "type": r.resource_type,
                     "difficulty": r.difficulty} for r in rows]
    ctx.deps.log.record("search_learning_resources", skills=len(skill_ids), found=sum(len(v) for v in out.values()))
    return out


async def _save(d: CareerDeps, planned: list[PlannedStep], summary: str) -> CareerRoadmap:
    if d.saved:
        return d.saved
    gap_ids = [str(g["skill_id"]) for g in d.gaps]
    allowed = set(gap_ids) | {p for ps in d.prereqs.values() for p in ps}
    have = {str(s.skill_id): s.estimated_level for s in
            (await d.db.scalars(select(StudentSkill).where(StudentSkill.student_id == d.student_id))).all()}

    order: list[str] = []
    for st in planned:  # anything not a known gap/prerequisite id (incl. malformed ids) is dropped
        if st.skill_id in allowed and st.skill_id not in order:
            order.append(st.skill_id)
    for g in gap_ids:  # never silently drop a gap the model forgot
        if g not in order:
            order.append(g)
    # prerequisites the student hasn't demonstrated go right before their dependent
    fixed: list[str] = []
    for sid in order:
        for pre in d.prereqs.get(sid, []):
            if pre not in fixed and have.get(pre, 0.0) < 0.5 and pre in allowed:
                fixed.append(pre)
        if sid not in fixed:
            fixed.append(sid)

    rationale = {st.skill_id: st.rationale for st in planned}
    chosen = {st.skill_id: st.ids() for st in planned}
    steps: list[CareerStep] = []
    for sid in fixed:
        valid = {str(r.id): r for r in await _resources(d, sid)}
        picked = [valid[r] for r in chosen.get(sid, []) if r in valid] or list(valid.values())[:2]
        skill = await d.db.get(Skill, uuid.UUID(sid))
        steps.append(CareerStep(
            skill_id=uuid.UUID(sid), skill_name=skill.canonical_name if skill else sid,
            rationale=rationale.get(sid) or ("Prerequisite for a gap skill." if sid not in gap_ids else "Closes a gap for this role."),
            is_prerequisite=sid not in gap_ids,
            resources=[ResourceRef(resource_id=r.id, title=r.title, provider=r.provider, url=r.url,
                                   resource_type=r.resource_type) for r in picked],
        ))

    path = LearningPath(student_id=d.student_id, target_job_id=d.job.id, gap_skill_ids=gap_ids, summary=summary)
    d.db.add(path)
    await d.db.flush()
    for i, s in enumerate(steps):
        d.db.add(LearningPathStep(
            learning_path_id=path.id, order_index=i, skill_id=s.skill_id,
            resource_id=s.resources[0].resource_id if s.resources else None,
            resource_ids=[str(r.resource_id) for r in s.resources], rationale=s.rationale,
        ))
    await d.db.flush()
    d.saved = CareerRoadmap(learning_path_id=path.id, target_job_id=d.job.id,
                            gap_skill_ids=[uuid.UUID(g) for g in gap_ids], steps=steps, summary=summary)
    return d.saved


@career_agent.tool
async def save_learning_path(ctx: RunContext[CareerDeps], steps: list[PlannedStep], summary: str) -> CareerRoadmap:
    """Persist the roadmap. Invalid skills/resources are dropped; prerequisites are ordered first."""
    rm = await _save(ctx.deps, steps, summary)
    ctx.deps.log.record("save_learning_path", steps=len(rm.steps), learning_path_id=rm.learning_path_id)
    return rm


class _Explain(BaseModel):
    summary: str
    rationales: dict[str, str] = Field(default_factory=dict)


async def build_career_roadmap(
    db: AsyncSession, student_id: uuid.UUID, target_job_id: uuid.UUID, use_llm: bool = True
) -> CareerRoadmap:
    job = await db.get(Job, target_job_id)
    log = ToolLog()
    deps = CareerDeps(db=db, student_id=student_id, job=job, log=log)

    async def llm() -> CareerRoadmap:
        await run_llm_agent(career_agent, "career_agent", f"Build my learning roadmap toward '{job.title}'.", deps, log)
        if deps.saved is None:
            raise RuntimeError("agent never called save_learning_path")
        return deps.saved

    async def fallback() -> CareerRoadmap:
        deps.gaps = await gap_service.calculate_skill_gaps(db, student_id, target_job_id)
        for g in deps.gaps:
            deps.prereqs[str(g["skill_id"])] = [str(p.id) for p in await gap_service.get_prerequisites(db, g["skill_id"])]
        names = [g["skill_name"] for g in deps.gaps]
        try:
            ex = await get_ai_gateway().generate_structured(
                "A student's skill gaps for the target role, most important first: " + ", ".join(names)
                + ". Write a 2-3 sentence encouraging summary and a one-sentence rationale per skill name.",
                _Explain, task_type="career_summary", related_entity_type="job", related_entity_id=target_job_id,
            )
        except Exception:  # noqa: BLE001 — explanation text is optional; the plan isn't
            ex = _Explain(summary="Roadmap built from your verified skill gaps for this role.")
        planned = [PlannedStep(skill_id=str(g["skill_id"]), rationale=ex.rationales.get(g["skill_name"], "")) for g in deps.gaps]
        log.record("fallback:save_learning_path", steps=len(planned))
        return await _save(deps, planned, ex.summary)

    rm = await run_agent(
        agent_type="career_agent", task=f"roadmap:{student_id}:{target_job_id}", context_type="job",
        context_id=target_job_id, tool_log=log, run_llm=llm if use_llm else _disabled, fallback=fallback,
        required_tools={"calculate_skill_gaps", "save_learning_path"},
    )
    await db.commit()
    return rm


async def _disabled():
    raise RuntimeError("LLM orchestration disabled for this call")
