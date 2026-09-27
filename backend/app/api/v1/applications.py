import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.applications import Application, ApplicationStatusHistory
from app.models.enums import ApplicationStatus, UserRole
from app.models.students import StudentProfile
from app.models.users import User
from app.schemas.applications import ApplicationCreate, ApplicationOut, ApplicationStatusUpdate
from app.services.applications.state_machine import can_transition

router = APIRouter(prefix="/applications", tags=["applications"])

RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)


@router.post("", response_model=ApplicationOut)
async def apply_to_job(
    payload: ApplicationCreate,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(400, "Complete your student profile first")

    existing = await db.scalar(
        select(Application).where(
            Application.job_id == payload.job_id, Application.student_id == profile.id
        )
    )
    if existing:
        return existing

    application = Application(job_id=payload.job_id, student_id=profile.id, status=ApplicationStatus.APPLIED)
    db.add(application)
    await db.flush()
    db.add(
        ApplicationStatusHistory(
            application_id=application.id,
            from_status=None,
            to_status=ApplicationStatus.APPLIED.value,
            changed_by_user_id=user.id,
        )
    )
    await db.commit()
    await db.refresh(application)
    return application


@router.get("/mine", response_model=list[ApplicationOut])
async def my_applications(
    user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)
):
    profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    if profile is None:
        return []
    return (await db.scalars(select(Application).where(Application.student_id == profile.id))).all()


@router.get("/job/{job_id}", response_model=list[ApplicationOut])
async def applications_for_job(
    job_id: uuid.UUID,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    return (await db.scalars(select(Application).where(Application.job_id == job_id))).all()


@router.put("/{application_id}/status", response_model=ApplicationOut)
async def update_application_status(
    application_id: uuid.UUID,
    payload: ApplicationStatusUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(404, "Application not found")
    if not can_transition(ApplicationStatus(application.status), payload.status):
        raise HTTPException(
            400, f"Cannot transition from {application.status} to {payload.status}"
        )
    db.add(
        ApplicationStatusHistory(
            application_id=application.id,
            from_status=application.status.value,
            to_status=payload.status.value,
            changed_by_user_id=user.id,
            note=payload.note,
        )
    )
    application.status = payload.status
    await db.commit()
    await db.refresh(application)
    return application
