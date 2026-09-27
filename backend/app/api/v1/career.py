import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.career_agent import build_career_roadmap
from app.api.deps import require_roles
from app.core.database import get_db
from app.models.career import LearningPath
from app.models.enums import UserRole
from app.models.students import StudentProfile
from app.models.users import User
from app.schemas.career import CareerRoadmap

router = APIRouter(prefix="/career", tags=["career"])


@router.post("/roadmap/{target_job_id}", response_model=CareerRoadmap)
async def generate_roadmap(
    target_job_id: uuid.UUID,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    return await build_career_roadmap(db, profile.id, target_job_id)


@router.get("/roadmap/history", response_model=list[dict])
async def roadmap_history(
    user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)
):
    profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    paths = (
        await db.scalars(select(LearningPath).where(LearningPath.student_id == profile.id))
    ).all()
    return [
        {"id": p.id, "target_job_id": p.target_job_id, "summary": p.summary, "created_at": p.created_at}
        for p in paths
    ]
