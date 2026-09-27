import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.institutions import Institution
from app.models.users import User
from app.services.analytics.institution import (
    cohort_skill_heatmap,
    industry_demand_skills,
    placement_readiness,
)

router = APIRouter(prefix="/institutions", tags=["institutions"])

INSTITUTION_ROLES = (
    UserRole.INSTITUTION_ADMIN,
    UserRole.PLACEMENT_OFFICER,
    UserRole.FACULTY,
    UserRole.DEPARTMENT_HEAD,
)


@router.post("")
async def create_institution(
    name: str,
    user: User = Depends(require_roles(*INSTITUTION_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    from app.models.institutions import InstitutionMember

    inst = Institution(name=name, created_by_user_id=user.id)
    db.add(inst)
    await db.flush()
    db.add(InstitutionMember(institution_id=inst.id, user_id=user.id, role=UserRole.INSTITUTION_ADMIN))
    await db.commit()
    await db.refresh(inst)
    return inst


@router.get("/{institution_id}/analytics/cohort-heatmap")
async def cohort_heatmap(
    institution_id: uuid.UUID,
    user: User = Depends(require_roles(*INSTITUTION_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    return await cohort_skill_heatmap(db, institution_id)


@router.get("/analytics/industry-demand")
async def industry_demand(
    user: User = Depends(require_roles(*INSTITUTION_ROLES)), db: AsyncSession = Depends(get_db)
):
    return await industry_demand_skills(db)


@router.get("/{institution_id}/analytics/placement-readiness")
async def placement_readiness_route(
    institution_id: uuid.UUID,
    user: User = Depends(require_roles(*INSTITUTION_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    return await placement_readiness(db, institution_id)
