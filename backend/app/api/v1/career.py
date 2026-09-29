import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.career_agent import build_career_roadmap
from app.api.deps import get_current_user, require_roles
from app.api.tenancy import get_student_profile
from app.core.database import get_db
from app.models.career import LearningPath, LearningPathStep, LearningResource
from app.models.enums import JobStatus, UserRole
from app.models.jobs import Job
from app.models.skills import Skill
from app.models.users import User
from app.schemas.student_views import StudentGapView
from app.schemas.career import CareerRoadmap, CareerStep, ResourceRef
from app.services.career.gaps import calculate_skill_gaps

router = APIRouter(prefix="/career", tags=["career"])


async def _target_job(db, job_id) -> Job:
    job = await db.get(Job, job_id)
    if job is None or JobStatus(job.status) != JobStatus.PUBLISHED:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/gaps/{target_job_id}")
async def gaps(target_job_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    await _target_job(db, target_job_id)
    me = await get_student_profile(db, user)
    if me is None:
        return []
    # gaps are computed deterministically (already ordered by gap x importance) but the
    # student gets priority order and status only - no levels, required levels or gap sizes
    return [StudentGapView(skill_id=g["skill_id"], skill_name=g["skill_name"], priority=i + 1,
                           status="not_yet_demonstrated" if not g["current_level"] else "below_requirement")
            for i, g in enumerate(await calculate_skill_gaps(db, me.id, target_job_id))]


@router.post("/roadmap/{target_job_id}", response_model=CareerRoadmap)
async def generate_roadmap(target_job_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)),
                           db: AsyncSession = Depends(get_db)):
    await _target_job(db, target_job_id)
    me = await get_student_profile(db, user)
    if me is None:
        raise HTTPException(409, "Create your profile first")
    return await build_career_roadmap(db, me.id, target_job_id)


async def _load(db, path: LearningPath) -> CareerRoadmap:
    steps = (await db.scalars(select(LearningPathStep).where(LearningPathStep.learning_path_id == path.id)
                              .order_by(LearningPathStep.order_index))).all()
    out = []
    for st in steps:
        skill = await db.get(Skill, st.skill_id)
        ids = [uuid.UUID(i) for i in (st.resource_ids or ([str(st.resource_id)] if st.resource_id else []))]
        res = (await db.scalars(select(LearningResource).where(LearningResource.id.in_(ids)))).all() if ids else []
        out.append(CareerStep(
            skill_id=st.skill_id, skill_name=skill.canonical_name if skill else str(st.skill_id), rationale=st.rationale or "",
            is_prerequisite=str(st.skill_id) not in path.gap_skill_ids,
            resources=[ResourceRef(resource_id=r.id, title=r.title, provider=r.provider, url=r.url, resource_type=r.resource_type) for r in res],
        ))
    return CareerRoadmap(learning_path_id=path.id, target_job_id=path.target_job_id,
                         gap_skill_ids=[uuid.UUID(g) for g in path.gap_skill_ids], steps=out, summary=path.summary or "")


@router.get("/roadmap/history")
async def roadmap_history(user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    me = await get_student_profile(db, user)
    if me is None:
        return []
    paths = (await db.scalars(select(LearningPath).where(LearningPath.student_id == me.id).order_by(LearningPath.created_at.desc()))).all()
    out = []
    for p in paths:
        job = await db.get(Job, p.target_job_id) if p.target_job_id else None
        out.append({"id": p.id, "target_job_id": p.target_job_id, "job_title": job.title if job else None,
                    "summary": p.summary, "gaps": len(p.gap_skill_ids), "created_at": p.created_at})
    return out


@router.get("/roadmap/{path_id}", response_model=CareerRoadmap)
async def get_roadmap(path_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    me = await get_student_profile(db, user)
    path = await db.get(LearningPath, path_id)
    if path is None or me is None or path.student_id != me.id:
        raise HTTPException(404, "Roadmap not found")
    return await _load(db, path)


@router.get("/resources")
async def resources(skill: str | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(LearningResource, Skill.canonical_name).join(Skill, Skill.id == LearningResource.skill_id).where(
        LearningResource.status == "ACTIVE")
    if skill:
        stmt = stmt.where(Skill.canonical_name.ilike(skill))
    rows = (await db.execute(stmt.order_by(Skill.canonical_name, LearningResource.difficulty))).all()
    return [{"id": r.id, "skill": name, "title": r.title, "url": r.url, "provider": r.provider,
             "resource_type": r.resource_type, "difficulty": r.difficulty, "is_free": r.is_free} for r, name in rows]
