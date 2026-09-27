"""Knowledge sources: registration, ingestion (Knowledge Agent via Celery),
status, retry, tenant-scoped search and grounded Q&A.

Who may register what:
- PLATFORM_ADMIN: PLATFORM_PUBLIC sources (or on behalf of a tenant),
- company members: COMPANY_PRIVATE sources for their own organization,
- institution members: INSTITUTION_PRIVATE sources for their institution.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.tenancy import member_institution_ids, member_org_ids, require_org_member, scope_for
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.knowledge import KnowledgeSource
from app.models.skills import Skill
from app.models.users import User
from app.services.audit import audit
from app.services.knowledge import service as ks
from app.services.knowledge.rag import grounded_answer
from app.workers.jobs import upsert_job

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

STAFF = (UserRole.PLATFORM_ADMIN, UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER,
         UserRole.INSTITUTION_ADMIN, UserRole.PLACEMENT_OFFICER, UserRole.FACULTY, UserRole.DEPARTMENT_HEAD)


class RegisterSource(BaseModel):
    title: str
    source_type: str = Field(pattern="^(INLINE_TEXT|APPROVED_URL|LOCAL_FILE)$")
    source_uri: str | None = None
    text: str | None = None
    skills: list[str]
    visibility: str = Field(pattern="^(PLATFORM_PUBLIC|COMPANY_PRIVATE|INSTITUTION_PRIVATE)$")
    organization_id: uuid.UUID | None = None
    institution_id: uuid.UUID | None = None
    ingest: bool = True


class AskRequest(BaseModel):
    question: str
    skills: list[str] | None = None
    organization_id: uuid.UUID | None = None


def _out(s: KnowledgeSource, names: dict) -> dict:
    return {
        "id": s.id, "title": s.title, "source_type": s.source_type, "source_uri": s.source_uri,
        "visibility": s.visibility, "organization_id": s.organization_id, "institution_id": s.institution_id,
        "skills": [names.get(uuid.UUID(i), i) for i in s.skill_ids], "status": s.status, "chunk_count": s.chunk_count,
        "document_version": s.document_version, "content_hash": s.content_hash, "embedding_model": s.embedding_model,
        "last_ingested_at": s.last_ingested_at, "error": s.error, "created_at": s.created_at,
    }


async def _skill_ids(db, names: list[str]) -> list[uuid.UUID]:
    from app.services.skills.normalizer import normalize_skill_name

    out = []
    for n in names:
        sid, _ = await normalize_skill_name(db, n)
        if sid is None:
            raise HTTPException(422, f"Unknown skill '{n}'")
        out.append(sid)
    return out


async def _authorize_register(db, user: User, p: RegisterSource) -> None:
    if p.visibility == "PLATFORM_PUBLIC" and user.role != UserRole.PLATFORM_ADMIN:
        raise HTTPException(403, "Only a Platform Admin can add platform-wide knowledge")
    if p.visibility == "COMPANY_PRIVATE":
        if not p.organization_id:
            raise HTTPException(422, "organization_id required")
        await require_org_member(db, user, p.organization_id)
    if p.visibility == "INSTITUTION_PRIVATE":
        if not p.institution_id:
            raise HTTPException(422, "institution_id required")
        if user.role != UserRole.PLATFORM_ADMIN and p.institution_id not in await member_institution_ids(db, user):
            raise HTTPException(403, "Not a member of this institution")


async def _visible_sources_stmt(db, user: User):
    stmt = select(KnowledgeSource)
    if user.role != UserRole.PLATFORM_ADMIN:
        orgs, insts = await member_org_ids(db, user), await member_institution_ids(db, user)
        stmt = stmt.where(or_(KnowledgeSource.visibility == "PLATFORM_PUBLIC", KnowledgeSource.organization_id.in_(orgs),
                              KnowledgeSource.institution_id.in_(insts)))
    return stmt


@router.post("/sources")
async def register(p: RegisterSource, user: User = Depends(require_roles(*STAFF)), db: AsyncSession = Depends(get_db)):
    await _authorize_register(db, user, p)
    skill_ids = await _skill_ids(db, p.skills)
    if p.source_type == "INLINE_TEXT":
        if not (p.text or "").strip():
            raise HTTPException(422, "text is required for INLINE_TEXT sources")
        uri = p.source_uri or f"inline:{ks.content_hash(p.text)[:16]}"
    else:
        if not p.source_uri:
            raise HTTPException(422, "source_uri required")
        uri = p.source_uri
    try:
        src = await ks.register_source(
            db, title=p.title, source_type=p.source_type, source_uri=uri, skill_ids=skill_ids, visibility=p.visibility,
            organization_id=p.organization_id if p.visibility == "COMPANY_PRIVATE" else None,
            institution_id=p.institution_id if p.visibility == "INSTITUTION_PRIVATE" else None,
            owner_user_id=user.id, raw_text=p.text,
        )
    except ks.KnowledgeError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit(db, user, "knowledge_source_registered", "knowledge_source", src.id, organization_id=src.organization_id,
                metadata={"visibility": src.visibility, "source_type": src.source_type})
    await db.commit()
    if p.ingest:
        await _enqueue(src.id, user.id)
    names = {s.id: s.canonical_name for s in (await db.scalars(select(Skill).where(Skill.id.in_(skill_ids)))).all()}
    return _out(src, names)


async def _enqueue(source_id: uuid.UUID, actor: uuid.UUID) -> None:
    from app.workers.tasks_knowledge import ingest_task

    await upsert_job(f"knowledge:{source_id}", "knowledge_ingestion", {"source_id": str(source_id)})
    ingest_task.delay(str(source_id), str(actor))


@router.post("/sources/{source_id}/ingest", status_code=202)
async def reingest(source_id: uuid.UUID, user: User = Depends(require_roles(*STAFF)), db: AsyncSession = Depends(get_db)):
    src = (await db.scalars((await _visible_sources_stmt(db, user)).where(KnowledgeSource.id == source_id))).first()
    if src is None:
        raise HTTPException(404, "Source not found")
    if src.visibility == "PLATFORM_PUBLIC" and user.role != UserRole.PLATFORM_ADMIN:
        raise HTTPException(403, "Only a Platform Admin can re-ingest platform knowledge")
    await _enqueue(src.id, user.id)
    return {"status": "PROCESSING"}


@router.get("/sources")
async def list_sources(skill: str | None = None, status: str | None = None, user: User = Depends(require_roles(*STAFF)),
                       db: AsyncSession = Depends(get_db)):
    stmt = await _visible_sources_stmt(db, user)
    if skill:
        stmt = stmt.where(KnowledgeSource.skill_ids.any(str((await _skill_ids(db, [skill]))[0])))
    if status:
        stmt = stmt.where(KnowledgeSource.status == status)
    rows = (await db.scalars(stmt.order_by(KnowledgeSource.created_at.desc()))).all()
    ids = {uuid.UUID(i) for r in rows for i in r.skill_ids}
    names = {s.id: s.canonical_name for s in (await db.scalars(select(Skill).where(Skill.id.in_(ids)))).all()}
    return [_out(r, names) for r in rows]


@router.get("/search")
async def search(q: str, skill: str | None = None, organization_id: uuid.UUID | None = None, top_n: int = 5,
                 user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Tenant-scoped retrieve → rerank. Scope comes from the caller's
    memberships, never from a client-supplied visibility."""
    scope = await scope_for(db, user, organization_id)
    skill_ids = await _skill_ids(db, [skill]) if skill else None
    docs = ks.retrieve(q, scope, skill_ids=skill_ids, top_k=30, top_n=min(top_n, 8))
    return [{"text": d.text, "vector_score": round(d.score, 4), **ref} for d, ref in zip(docs, ks.to_source_refs(docs))]


@router.post("/ask")
async def ask(p: AskRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    scope = await scope_for(db, user, p.organization_id)
    skill_ids = await _skill_ids(db, p.skills) if p.skills else None
    return (await grounded_answer(p.question, scope, skill_ids)).model_dump()
