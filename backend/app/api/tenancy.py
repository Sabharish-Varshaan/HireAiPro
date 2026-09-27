"""Tenant-scoping helpers shared by routes. Every org-scoped route resolves
the resource's owning organization and checks the caller is a member (or a
PLATFORM_ADMIN) before touching it."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import Application
from app.models.enums import UserRole
from app.models.institutions import InstitutionMember
from app.models.jobs import Job
from app.models.organizations import OrganizationMember
from app.models.students import StudentProfile
from app.models.users import User
from app.services.ai_gateway.vector_store import TenantScope


async def member_org_ids(db: AsyncSession, user: User) -> set[uuid.UUID]:
    rows = await db.scalars(select(OrganizationMember.organization_id).where(OrganizationMember.user_id == user.id))
    return set(rows.all())


async def member_institution_ids(db: AsyncSession, user: User) -> set[uuid.UUID]:
    rows = await db.scalars(select(InstitutionMember.institution_id).where(InstitutionMember.user_id == user.id))
    return set(rows.all())


async def require_org_member(db: AsyncSession, user: User, organization_id: uuid.UUID) -> None:
    if user.role == UserRole.PLATFORM_ADMIN:
        return
    if organization_id not in await member_org_ids(db, user):
        raise HTTPException(403, "Not a member of this organization")


async def get_job_for_member(db: AsyncSession, user: User, job_id: uuid.UUID) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    await require_org_member(db, user, job.organization_id)
    return job


async def get_student_profile(db: AsyncSession, user: User) -> StudentProfile | None:
    return await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))


async def assert_can_view_student(db: AsyncSession, user: User, student_id: uuid.UUID) -> None:
    """A student sees themselves. A recruiter sees a student only if that
    student applied to one of the recruiter's organization's jobs. Institution
    staff see students enrolled at their institution."""
    if user.role == UserRole.PLATFORM_ADMIN:
        return
    if user.role == UserRole.STUDENT:
        me = await get_student_profile(db, user)
        if me is None or me.id != student_id:
            raise HTTPException(403, "Not your profile")
        return
    orgs = await member_org_ids(db, user)
    if orgs:
        hit = await db.scalar(
            select(Application.id)
            .join(Job, Job.id == Application.job_id)
            .where(Application.student_id == student_id, Job.organization_id.in_(orgs))
            .limit(1)
        )
        if hit:
            return
    insts = await member_institution_ids(db, user)
    if insts:
        profile = await db.get(StudentProfile, student_id)
        if profile and profile.institution_id in insts:
            return
    raise HTTPException(403, "No access to this student")


async def scope_for(db: AsyncSession, user: User, organization_id: uuid.UUID | None = None) -> TenantScope:
    """Build the retrieval scope for this caller. An explicit organization_id
    must be one the caller belongs to."""
    if organization_id:
        await require_org_member(db, user, organization_id)
        return TenantScope(organization_id=organization_id)
    orgs = await member_org_ids(db, user)
    insts = await member_institution_ids(db, user)
    return TenantScope(
        organization_id=next(iter(orgs)) if len(orgs) == 1 else None,
        institution_id=next(iter(insts)) if len(insts) == 1 else None,
    )
