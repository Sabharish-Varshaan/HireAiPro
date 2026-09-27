from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.organizations import Organization, OrganizationMember
from app.models.users import User
from app.schemas.organizations import OrganizationCreate, OrganizationOut

router = APIRouter(prefix="/organizations", tags=["organizations"])

RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)


@router.post("", response_model=OrganizationOut)
async def create_organization(
    payload: OrganizationCreate,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    org = Organization(
        name=payload.name,
        website=payload.website,
        industry=payload.industry,
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=UserRole.COMPANY_ADMIN))
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/mine", response_model=list[OrganizationOut])
async def my_organizations(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user.id)
    )
    return (await db.scalars(stmt)).all()
