import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.evidence import SkillEvidence, StudentSkill
from app.models.users import User
from app.schemas.evidence import SkillEvidenceOut, StudentSkillOut
from app.services.evidence.estimator import recalculate_all_skills_for_student

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/students/{student_id}/evidence", response_model=list[SkillEvidenceOut])
async def get_student_evidence(
    student_id: uuid.UUID,
    skill_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stmt = select(SkillEvidence).where(SkillEvidence.student_id == student_id)
    if skill_id:
        stmt = stmt.where(SkillEvidence.skill_id == skill_id)
    return (await db.scalars(stmt.order_by(SkillEvidence.created_at.desc()))).all()


@router.get("/students/{student_id}/skills", response_model=list[StudentSkillOut])
async def get_student_skills(
    student_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return (
        await db.scalars(select(StudentSkill).where(StudentSkill.student_id == student_id))
    ).all()


@router.post("/students/{student_id}/recalculate", response_model=list[StudentSkillOut])
async def recalculate_student_skills(
    student_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return await recalculate_all_skills_for_student(db, student_id)
