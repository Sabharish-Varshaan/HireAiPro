import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.tenancy import assert_can_view_student
from app.core.database import get_db
from app.models.evidence import SkillEvidence, StudentSkill
from app.models.skills import Skill
from app.models.users import User
from app.schemas.evidence import SkillEvidenceOut, StudentSkillOut

router = APIRouter(prefix="/evidence", tags=["evidence"])


async def _names(db, ids) -> dict:
    return {s.id: s.canonical_name for s in (await db.scalars(select(Skill).where(Skill.id.in_(set(ids))))).all()}


@router.get("/students/{student_id}/evidence", response_model=list[SkillEvidenceOut])
async def get_student_evidence(student_id: uuid.UUID, skill_id: uuid.UUID | None = None,
                               user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await assert_can_view_student(db, user, student_id)
    stmt = select(SkillEvidence).where(SkillEvidence.student_id == student_id, SkillEvidence.is_deleted.is_(False))
    if skill_id:
        stmt = stmt.where(SkillEvidence.skill_id == skill_id)
    rows = (await db.scalars(stmt.order_by(SkillEvidence.created_at.desc()))).all()
    names = await _names(db, [r.skill_id for r in rows])
    return [SkillEvidenceOut.model_validate(r).model_copy(update={"skill_name": names.get(r.skill_id)}) for r in rows]


@router.get("/students/{student_id}/skills", response_model=list[StudentSkillOut])
async def get_student_skills(student_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await assert_can_view_student(db, user, student_id)
    rows = (await db.scalars(select(StudentSkill).where(StudentSkill.student_id == student_id)
                             .order_by(StudentSkill.estimated_level.desc()))).all()
    names = await _names(db, [r.skill_id for r in rows])
    return [StudentSkillOut.model_validate(r).model_copy(update={"skill_name": names.get(r.skill_id)}) for r in rows]


@router.get("/students/{student_id}/skills/{skill_id}")
async def skill_detail(student_id: uuid.UUID, skill_id: uuid.UUID, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Explainability drilldown: the estimate and every evidence row behind it,
    including resume claims flagged as not counted."""
    await assert_can_view_student(db, user, student_id)
    skill = await db.get(Skill, skill_id)
    est = await db.scalar(select(StudentSkill).where(StudentSkill.student_id == student_id, StudentSkill.skill_id == skill_id))
    ev = (await db.scalars(select(SkillEvidence).where(SkillEvidence.student_id == student_id, SkillEvidence.skill_id == skill_id,
                                                      SkillEvidence.is_deleted.is_(False))
                           .order_by(SkillEvidence.created_at.desc()))).all()
    from app.services.evidence.estimator import BASE_WEIGHTS
    from app.models.enums import EvidenceSourceType

    return {
        "skill": {"id": skill_id, "canonical_name": skill.canonical_name if skill else None, "category": skill.category if skill else None},
        "estimate": StudentSkillOut.model_validate(est) if est else None,
        "weights": {k.value: v for k, v in BASE_WEIGHTS.items()},
        "evidence": [
            {**SkillEvidenceOut.model_validate(e).model_dump(), "source_id": e.source_id,
             "counts_toward_score": BASE_WEIGHTS.get(EvidenceSourceType(e.source_type), 0) > 0}
            for e in ev
        ],
    }


@router.post("/students/{student_id}/recalculate", response_model=list[StudentSkillOut])
async def recalculate_student_skills(student_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await assert_can_view_student(db, user, student_id)
    from app.services.evidence.estimator import recalculate_all_skills_for_student

    return await recalculate_all_skills_for_student(db, student_id, user.id, "manual")
