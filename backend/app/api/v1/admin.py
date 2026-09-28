import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.enums import SkillRelationType, UserRole
from app.models.institutions import Institution
from app.models.knowledge import KnowledgeSource
from app.models.misc import AgentRun, AIRun, AuditEvent, ProcessingJob
from app.models.organizations import Organization
from app.models.questions import Question
from app.models.skills import Skill, SkillAlias, SkillRelationship
from app.models.users import User
from app.services.audit import audit
from app.workers.jobs import upsert_job

router = APIRouter(prefix="/admin", tags=["admin"])
ADMIN = require_roles(UserRole.PLATFORM_ADMIN)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


class SkillIn(BaseModel):
    canonical_name: str
    category: str
    description: str | None = None


class SkillPatch(BaseModel):
    canonical_name: str | None = None
    category: str | None = None
    description: str | None = None
    is_active: bool | None = None


class AliasIn(BaseModel):
    alias: str


class RelationshipIn(BaseModel):
    to_skill_id: uuid.UUID
    relation_type: SkillRelationType


@router.get("/stats")
async def stats(user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    async def count(model, *where):
        return await db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    return {
        "users": await count(User), "organizations": await count(Organization), "institutions": await count(Institution),
        "skills": await count(Skill, Skill.is_active.is_(True)), "aliases": await count(SkillAlias),
        "questions": await count(Question), "ai_generated_questions": await count(Question, Question.source_type == "AI_GENERATED"),
        "questions_awaiting_review": await count(Question, Question.status.in_(["DRAFT", "VALIDATED"])),
        "knowledge_sources": await count(KnowledgeSource), "knowledge_failed": await count(KnowledgeSource, KnowledgeSource.status == "FAILED"),
        "ai_runs": await count(AIRun), "ai_runs_failed": await count(AIRun, AIRun.status == "FAILED"),
        "agent_runs": await count(AgentRun), "agent_runs_fallback": await count(AgentRun, AgentRun.used_fallback.is_(True)),
        "failed_jobs": await count(ProcessingJob, ProcessingJob.status == "FAILED"),
    }


@router.get("/users")
async def list_users(user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(User).order_by(User.created_at.desc()))).all()
    return [{"id": u.id, "email": u.email, "role": u.role, "full_name": u.full_name, "is_active": u.is_active,
             "created_at": u.created_at} for u in rows]


class UserUpdate(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}")
async def update_user(user_id: uuid.UUID, payload: UserUpdate, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if target.id == user.id:
        raise HTTPException(400, "You cannot deactivate your own account")
    target.is_active = payload.is_active
    await audit(db, user, "user_activated" if payload.is_active else "user_deactivated", "user", target.id,
                metadata={"email": target.email})
    await db.commit()
    return {"id": target.id, "is_active": target.is_active}


@router.get("/organizations")
async def list_organizations(user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    return [{"id": o.id, "name": o.name, "industry": o.industry, "created_at": o.created_at}
            for o in (await db.scalars(select(Organization))).all()]


@router.get("/institutions")
async def list_institutions(user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    return [{"id": i.id, "name": i.name, "created_at": i.created_at} for i in (await db.scalars(select(Institution))).all()]


# ---- taxonomy ---------------------------------------------------------------

@router.get("/skills")
async def list_skills(q: str | None = None, category: str | None = None, include_inactive: bool = False, limit: int = 100,
                      offset: int = 0, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    stmt = select(Skill)
    if q:
        alias_hits = select(SkillAlias.skill_id).where(SkillAlias.alias_normalized.contains(_norm(q)))
        stmt = stmt.where(or_(Skill.canonical_name.ilike(f"%{q}%"), Skill.id.in_(alias_hits)))
    if category:
        stmt = stmt.where(Skill.category == category)
    if not include_inactive:
        stmt = stmt.where(Skill.is_active.is_(True))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.scalars(stmt.order_by(Skill.canonical_name).offset(offset).limit(limit))).all()
    aliases = {}
    for a in (await db.scalars(select(SkillAlias).where(SkillAlias.skill_id.in_([r.id for r in rows])))).all():
        aliases.setdefault(a.skill_id, []).append({"id": a.id, "alias": a.alias})
    return {"total": total, "items": [
        {"id": s.id, "canonical_name": s.canonical_name, "category": s.category, "description": s.description,
         "is_active": s.is_active, "aliases": aliases.get(s.id, [])} for s in rows]}


@router.get("/skills/{skill_id}")
async def skill_detail(skill_id: uuid.UUID, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    s = await db.get(Skill, skill_id)
    if s is None:
        raise HTTPException(404, "Skill not found")
    rels = (await db.scalars(select(SkillRelationship).where(
        or_(SkillRelationship.from_skill_id == skill_id, SkillRelationship.to_skill_id == skill_id)))).all()
    names = {x.id: x.canonical_name for x in (await db.scalars(select(Skill).where(
        Skill.id.in_({r.from_skill_id for r in rels} | {r.to_skill_id for r in rels})))).all()}
    aliases = (await db.scalars(select(SkillAlias).where(SkillAlias.skill_id == skill_id))).all()
    return {
        "id": s.id, "canonical_name": s.canonical_name, "category": s.category, "description": s.description,
        "is_active": s.is_active, "aliases": [{"id": a.id, "alias": a.alias} for a in aliases],
        "relationships": [{"id": r.id, "from": names.get(r.from_skill_id), "from_skill_id": r.from_skill_id,
                           "to": names.get(r.to_skill_id), "to_skill_id": r.to_skill_id, "type": r.relation_type} for r in rels],
    }


@router.post("/skills")
async def create_skill(payload: SkillIn, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    """The only path that creates a permanent canonical skill — never reachable by AI code."""
    if await db.scalar(select(SkillAlias.id).where(SkillAlias.alias_normalized == _norm(payload.canonical_name))):
        raise HTTPException(409, "That name is already an alias of an existing skill")
    s = Skill(**payload.model_dump())
    db.add(s)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "Skill already exists") from exc
    await audit(db, user, "taxonomy_skill_created", "skill", s.id, metadata=payload.model_dump())
    await db.commit()
    return {"id": s.id}


@router.patch("/skills/{skill_id}")
async def update_skill(skill_id: uuid.UUID, payload: SkillPatch, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    s = await db.get(Skill, skill_id)
    if s is None:
        raise HTTPException(404, "Skill not found")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(s, k, v)
    await audit(db, user, "taxonomy_skill_deactivated" if changes.get("is_active") is False else "taxonomy_skill_updated",
                "skill", s.id, metadata=changes)
    try:
        await db.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "Another skill already has that name") from exc
    return {"id": s.id, **changes}


@router.post("/skills/{skill_id}/aliases")
async def add_alias(skill_id: uuid.UUID, payload: AliasIn, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    norm = _norm(payload.alias)
    if not norm:
        raise HTTPException(422, "Alias is empty")
    clash = await db.scalar(select(Skill.id).where(func.regexp_replace(func.lower(Skill.canonical_name), "[^a-z0-9]+", "", "g") == norm))
    if clash and clash != skill_id:
        raise HTTPException(409, "Alias would shadow another canonical skill")
    row = SkillAlias(skill_id=skill_id, alias=payload.alias, alias_normalized=norm)
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "Alias already in use") from exc
    await audit(db, user, "taxonomy_alias_added", "skill", skill_id, metadata={"alias": payload.alias})
    await db.commit()
    return {"id": row.id}


@router.delete("/aliases/{alias_id}")
async def delete_alias(alias_id: uuid.UUID, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    row = await db.get(SkillAlias, alias_id)
    if row is None:
        raise HTTPException(404, "Alias not found")
    await db.delete(row)
    await audit(db, user, "taxonomy_alias_removed", "skill", row.skill_id, metadata={"alias": row.alias})
    await db.commit()
    return {"deleted": True}


@router.post("/skills/{skill_id}/relationships")
async def add_relationship(skill_id: uuid.UUID, payload: RelationshipIn, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    if skill_id == payload.to_skill_id:
        raise HTTPException(422, "A skill can't relate to itself")
    if await db.get(Skill, payload.to_skill_id) is None:
        raise HTTPException(404, "Target skill not found")
    exists = await db.scalar(select(SkillRelationship.id).where(
        SkillRelationship.from_skill_id == skill_id, SkillRelationship.to_skill_id == payload.to_skill_id,
        SkillRelationship.relation_type == payload.relation_type.value))
    if exists:
        return {"id": exists}
    row = SkillRelationship(from_skill_id=skill_id, to_skill_id=payload.to_skill_id, relation_type=payload.relation_type)
    db.add(row)
    await db.flush()
    await audit(db, user, "taxonomy_relationship_added", "skill", skill_id,
                metadata={"to": str(payload.to_skill_id), "type": payload.relation_type.value})
    await db.commit()
    return {"id": row.id}


@router.delete("/relationships/{rel_id}")
async def delete_relationship(rel_id: uuid.UUID, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    row = await db.get(SkillRelationship, rel_id)
    if row is None:
        raise HTTPException(404, "Relationship not found")
    await db.delete(row)
    await audit(db, user, "taxonomy_relationship_removed", "skill", row.from_skill_id, metadata={"to": str(row.to_skill_id)})
    await db.commit()
    return {"deleted": True}


# ---- runs, jobs, audit ------------------------------------------------------

@router.get("/ai-runs")
async def list_ai_runs(status: str | None = None, task_type: str | None = None, limit: int = 200,
                       user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    stmt = select(AIRun)
    if status:
        stmt = stmt.where(AIRun.status == status)
    if task_type:
        stmt = stmt.where(AIRun.task_type == task_type)
    rows = (await db.scalars(stmt.order_by(AIRun.created_at.desc()).limit(limit))).all()
    return [{"id": r.id, "task_type": r.task_type, "provider": r.provider, "model": r.model, "prompt_version": r.prompt_version,
             "status": r.status, "latency_ms": round(r.latency_ms) if r.latency_ms else None, "schema_valid": r.schema_valid,
             "input_tokens": r.input_tokens, "cached_input_tokens": r.cached_input_tokens, "output_tokens": r.output_tokens,
             "estimated_cost_usd": r.estimated_cost_usd, "retry_count": r.retry_count, "fallback_used": r.fallback_used,
             "fallback_reason": r.fallback_reason, "tool_call_success": r.tool_call_success,
             "error": r.error, "related_entity_type": r.related_entity_type, "related_entity_id": r.related_entity_id,
             "started_at": r.started_at, "ended_at": r.ended_at, "created_at": r.created_at} for r in rows]


@router.get("/agent-runs")
async def list_agent_runs(agent_type: str | None = None, status: str | None = None, limit: int = 200,
                          user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    stmt = select(AgentRun)
    if agent_type:
        stmt = stmt.where(AgentRun.agent_type == agent_type)
    if status:
        stmt = stmt.where(AgentRun.status == status)
    rows = (await db.scalars(stmt.order_by(AgentRun.created_at.desc()).limit(limit))).all()
    return [{"id": r.id, "agent_type": r.agent_type, "task": r.task, "status": r.status, "used_fallback": r.used_fallback,
             "context_type": r.context_type, "context_id": r.context_id, "tool_calls": r.tool_calls or [],
             "error": r.error, "started_at": r.started_at, "ended_at": r.ended_at} for r in rows]


@router.get("/jobs")
async def list_jobs(status: str | None = None, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    stmt = select(ProcessingJob)
    if status:
        stmt = stmt.where(ProcessingJob.status == status)
    rows = (await db.scalars(stmt.order_by(ProcessingJob.updated_at.desc()).limit(200))).all()
    return [{"id": r.id, "job_key": r.job_key, "job_type": r.job_type, "status": r.status, "attempts": r.attempts,
             "error": r.error, "payload": r.payload, "updated_at": r.updated_at} for r in rows]


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(job_id: uuid.UUID, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    """Re-dispatches a job. Safe because every task is idempotent."""
    job = await db.get(ProcessingJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    p = job.payload or {}
    from app.workers import tasks_jobs, tasks_knowledge, tasks_matching, tasks_questions, tasks_reports, tasks_resumes

    dispatch = {
        "jd_processing": lambda: tasks_jobs.process_jd_task.delay(p["job_id"]),
        "resume_processing": lambda: tasks_resumes.process_resume_task.delay(p["student_id"], p["document_id"]),
        "knowledge_ingestion": lambda: tasks_knowledge.ingest_task.delay(p["source_id"], str(user.id)),
        "assessment_generation": lambda: tasks_questions.generate_assessment_task.delay(p["job_id"], p.get("title", "Assessment"), str(user.id)),
        "bulk_matching": lambda: tasks_matching.recompute_job_matches_task.delay(p["job_id"]),
        "report_generation": lambda: tasks_reports.institution_report_task.delay(p["institution_id"]),
    }
    if job.job_type not in dispatch:
        raise HTTPException(422, f"Don't know how to retry {job.job_type}")
    await upsert_job(job.job_key, job.job_type, p)
    dispatch[job.job_type]()
    await audit(db, user, "job_retried", "processing_job", job.id, metadata={"job_key": job.job_key})
    await db.commit()
    return {"status": "PENDING", "job_key": job.job_key}


@router.get("/audit-logs")
async def list_audit_logs(action: str | None = None, entity_type: str | None = None, limit: int = 300,
                          user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    stmt = select(AuditEvent, User.email).outerjoin(User, User.id == AuditEvent.actor_user_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    rows = (await db.execute(stmt.order_by(AuditEvent.created_at.desc()).limit(limit))).all()
    return [{"id": r.id, "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id,
             "actor": email or "system", "organization_id": r.organization_id, "metadata": r.event_metadata,
             "created_at": r.created_at} for r, email in rows]


@router.get("/audit-actions")
async def audit_actions(user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AuditEvent.action, func.count()).group_by(AuditEvent.action).order_by(AuditEvent.action))).all()
    return [{"action": a, "count": c} for a, c in rows]


# ---- AI providers & cost ------------------------------------------------------

@router.get("/ai/providers")
async def ai_providers(user: User = Depends(ADMIN)):
    """Provider health without secrets. Cloud checks hit the free /models
    endpoint only (no tokens spent)."""
    import httpx

    from app.core.config import get_settings
    from app.services.ai_gateway.budget import budget_state
    from app.services.ai_gateway.providers import TASK_POLICY, configured_providers, in_cooldown, route

    s = get_settings()
    avail = configured_providers()

    async def check(url, headers=None):
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                return (await c.get(url, headers=headers or {})).status_code == 200
        except httpx.HTTPError:
            return False

    ollama_loaded = False
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            ps = (await c.get(f"{s.OLLAMA_BASE_URL}/api/ps")).json()
            ollama_loaded = any(m.get("name", "").startswith(s.OLLAMA_MODEL) for m in ps.get("models", []))
    except (httpx.HTTPError, ValueError):
        pass
    b = await budget_state()
    return {
        "groq": {"configured": "groq" in avail, "model": s.GROQ_MODEL, "rate_limited": in_cooldown("groq"),
                 "healthy": await check(f"{s.GROQ_BASE_URL}/models", {"Authorization": f"Bearer {s.GROQ_API_KEY}"}) if "groq" in avail else False},
        "openai": {"configured": "luna" in avail, "cheap_model": s.OPENAI_CHEAP_MODEL, "escalation_model": s.OPENAI_ESCALATION_MODEL,
                   "healthy": await check(f"{s.OPENAI_BASE_URL}/models/{s.OPENAI_CHEAP_MODEL}", {"Authorization": f"Bearer {s.OPENAI_API_KEY}"}) if "luna" in avail else False},
        "ollama": {"configured": True, "model": s.OLLAMA_MODEL, "healthy": await check(f"{s.OLLAMA_BASE_URL}/api/version"),
                   "model_loaded_in_memory": ollama_loaded},
        "routing_mode": "local_only" if s.LOCAL_ONLY else "router",
        "routes": {t: (await route(t, budget=b)).names for t in TASK_POLICY},
        "budget": b.as_dict(),
    }


@router.get("/ai/usage")
async def ai_usage(days: int = 10, user: User = Depends(ADMIN), db: AsyncSession = Depends(get_db)):
    """All figures aggregated from ai_runs."""
    import datetime as dt

    from app.services.ai_gateway.budget import get_openai_spend_today

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    rows = (await db.execute(
        select(AIRun.provider, AIRun.model, func.count(), func.count().filter(AIRun.status == "FAILED"),
               func.count().filter(AIRun.fallback_used.is_(True)), func.avg(AIRun.latency_ms),
               func.coalesce(func.sum(AIRun.input_tokens), 0), func.coalesce(func.sum(AIRun.output_tokens), 0),
               func.coalesce(func.sum(AIRun.estimated_cost_usd), 0.0))
        .where(AIRun.created_at >= since).group_by(AIRun.provider, AIRun.model).order_by(func.count().desc())
    )).all()
    by_task = (await db.execute(
        select(AIRun.task_type, AIRun.provider, func.count()).where(AIRun.created_at >= since)
        .group_by(AIRun.task_type, AIRun.provider).order_by(AIRun.task_type)
    )).all()
    return {
        "openai_spend_today_usd": round(await get_openai_spend_today(), 6),
        f"openai_spend_{days}d_usd": round(sum(float(r[8]) for r in rows if r[0] == "openai"), 6),
        "label": "tracked estimate from ai_runs (not the OpenAI account balance)",
        "by_model": [{"provider": r[0], "model": r[1], "requests": r[2], "failures": r[3], "fallbacks": r[4],
                      "avg_latency_ms": round(float(r[5])) if r[5] else None, "input_tokens": int(r[6]),
                      "output_tokens": int(r[7]), "estimated_cost_usd": round(float(r[8]), 6)} for r in rows],
        "by_task": [{"task_type": t, "provider": p, "requests": n} for t, p, n in by_task],
    }
