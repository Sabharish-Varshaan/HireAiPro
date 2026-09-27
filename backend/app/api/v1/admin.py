import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.enums import ProcessingStatus, UserRole
from app.models.misc import AgentRun, AIRun, AuditEvent
from app.models.organizations import Organization
from app.models.institutions import Institution
from app.models.questions import Question
from app.models.skills import Skill, SkillAlias, SkillRelationship
from app.models.users import User

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_ONLY = (UserRole.PLATFORM_ADMIN,)


@router.get("/users", response_model=list[dict])
async def list_users(user: User = Depends(require_roles(*ADMIN_ONLY)), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(User))).all()
    return [{"id": u.id, "email": u.email, "role": u.role, "full_name": u.full_name, "is_active": u.is_active} for u in rows]


@router.get("/organizations", response_model=list[dict])
async def list_organizations(user: User = Depends(require_roles(*ADMIN_ONLY)), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Organization))).all()
    return [{"id": o.id, "name": o.name} for o in rows]


@router.get("/institutions", response_model=list[dict])
async def list_institutions(user: User = Depends(require_roles(*ADMIN_ONLY)), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Institution))).all()
    return [{"id": i.id, "name": i.name} for i in rows]


@router.post("/knowledge/ingest")
async def ingest_knowledge(
    skill_id: uuid.UUID,
    source_name: str,
    text: str,
    user: User = Depends(require_roles(*ADMIN_ONLY)),
    db: AsyncSession = Depends(get_db),
):
    """Admin-approved knowledge ingestion — never autonomous crawling."""
    from app.agents.knowledge_agent import ingest_knowledge_source

    package = await ingest_knowledge_source(db, skill_id, source_name, text)
    return {
        "skill_id": package.skill_id,
        "source_id": package.source_id,
        "chunks_created": package.chunks_created,
        "status": package.status,
    }


@router.get("/skills", response_model=list[dict])
async def list_skills(user: User = Depends(require_roles(*ADMIN_ONLY)), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Skill))).all()
    return [{"id": s.id, "canonical_name": s.canonical_name, "category": s.category} for s in rows]


@router.post("/skills")
async def create_skill(
    canonical_name: str,
    category: str,
    user: User = Depends(require_roles(*ADMIN_ONLY)),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only permanent taxonomy mutation — the one path the AI is never
    allowed to reach directly."""
    skill = Skill(canonical_name=canonical_name, category=category)
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return {"id": skill.id}


@router.post("/skills/{skill_id}/aliases")
async def add_alias(
    skill_id: uuid.UUID,
    alias: str,
    user: User = Depends(require_roles(*ADMIN_ONLY)),
    db: AsyncSession = Depends(get_db),
):
    import re

    row = SkillAlias(skill_id=skill_id, alias=alias, alias_normalized=re.sub(r"[^a-z0-9]+", "", alias.lower()))
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.get("/questions/ai-generated", response_model=list[dict])
async def ai_generated_questions(user: User = Depends(require_roles(*ADMIN_ONLY)), db: AsyncSession = Depends(get_db)):
    from app.models.enums import QuestionSourceType

    rows = (
        await db.scalars(select(Question).where(Question.source_type == QuestionSourceType.AI_GENERATED))
    ).all()
    return [{"id": q.id, "question_text": q.question_text, "status": q.status, "skill_id": q.skill_id} for q in rows]


@router.get("/ai-runs", response_model=list[dict])
async def list_ai_runs(
    status: ProcessingStatus | None = None,
    user: User = Depends(require_roles(*ADMIN_ONLY)),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AIRun).order_by(AIRun.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(AIRun.status == status)
    rows = (await db.scalars(stmt)).all()
    return [
        {
            "id": r.id,
            "task_type": r.task_type,
            "model": r.model,
            "status": r.status,
            "latency_ms": r.latency_ms,
            "error": r.error,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/agent-runs", response_model=list[dict])
async def list_agent_runs(user: User = Depends(require_roles(*ADMIN_ONLY)), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(200))).all()
    return [
        {"id": r.id, "agent_type": r.agent_type, "task": r.task, "status": r.status, "error": r.error}
        for r in rows
    ]


@router.get("/audit-logs", response_model=list[dict])
async def list_audit_logs(user: User = Depends(require_roles(*ADMIN_ONLY)), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(200))).all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "actor_user_id": r.actor_user_id,
            "created_at": r.created_at,
        }
        for r in rows
    ]
