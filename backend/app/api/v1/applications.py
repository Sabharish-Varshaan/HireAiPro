import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.tenancy import assert_can_view_student, get_job_for_member, get_student_profile, require_org_member
from app.core.database import get_db
from app.models.applications import Application, ApplicationStatusHistory
from app.models.enums import ApplicationStatus, JobStatus, UserRole
from app.models.jobs import Job
from app.models.matching import Match
from app.models.organizations import Organization
from app.models.students import StudentProfile
from app.models.users import User
from app.schemas.applications import ApplicationCreate, ApplicationOut, ApplicationStatusUpdate
from app.services.applications.service import RECRUITER_DECISIONS, InvalidTransition, transition_application
from app.services.audit import audit
from app.services.notifications import notify

router = APIRouter(prefix="/applications", tags=["applications"])

RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)


async def _enrich(db, a: Application) -> ApplicationOut:
    job = await db.get(Job, a.job_id)
    org = await db.get(Organization, job.organization_id) if job else None
    profile = await db.get(StudentProfile, a.student_id)
    student = await db.get(User, profile.user_id) if profile else None
    match = await db.scalar(select(Match).where(Match.application_id == a.id))
    return ApplicationOut.model_validate(a).model_copy(update={
        "job_title": job.title if job else None, "organization_name": org.name if org else None,
        "student_name": student.full_name if student else None,
        "match_score": match.match_score if match else None, "applied_at": a.created_at,
    })


@router.post("", response_model=ApplicationOut)
async def apply_to_job(payload: ApplicationCreate, user: User = Depends(require_roles(UserRole.STUDENT)),
                       db: AsyncSession = Depends(get_db)):
    me = await get_student_profile(db, user)
    if me is None:
        me = StudentProfile(user_id=user.id)
        db.add(me)
        await db.flush()
    job = await db.get(Job, payload.job_id)
    if job is None or JobStatus(job.status) != JobStatus.PUBLISHED:
        raise HTTPException(404, "Job not found or not open for applications")
    existing = await db.scalar(select(Application).where(Application.job_id == job.id, Application.student_id == me.id))
    if existing:
        return await _enrich(db, existing)
    application = Application(job_id=job.id, student_id=me.id, status=ApplicationStatus.APPLIED)
    db.add(application)
    await db.flush()
    db.add(ApplicationStatusHistory(application_id=application.id, from_status=None,
                                    to_status=ApplicationStatus.APPLIED.value, changed_by_user_id=user.id))
    await audit(db, user, "application_submitted", "application", application.id, organization_id=job.organization_id)
    await notify(db, user.id, "application_submitted", "Application submitted", body=job.title,
                 link=f"/student/applications/{application.id}", dedupe_key=f"app:{application.id}:APPLIED")
    await notify(db, user.id, "assessment_assigned", "Assessment ready to take", body=job.title,
                 link=f"/student/applications/{application.id}", dedupe_key=f"app:{application.id}:assessment_assigned")
    await db.commit()
    return await _enrich(db, application)


@router.get("/mine", response_model=list[ApplicationOut])
async def my_applications(user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    me = await get_student_profile(db, user)
    if me is None:
        return []
    rows = (await db.scalars(select(Application).where(Application.student_id == me.id).order_by(Application.created_at.desc()))).all()
    return [await _enrich(db, a) for a in rows]


@router.get("/job/{job_id}", response_model=list[ApplicationOut])
async def applications_for_job(job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES, UserRole.PLATFORM_ADMIN)),
                               db: AsyncSession = Depends(get_db)):
    await get_job_for_member(db, user, job_id)
    rows = (await db.scalars(select(Application).where(Application.job_id == job_id))).all()
    out = [await _enrich(db, a) for a in rows]
    return sorted(out, key=lambda a: a.match_score or -1, reverse=True)


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(application_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    a = await db.get(Application, application_id)
    if a is None:
        raise HTTPException(404, "Application not found")
    await assert_can_view_student(db, user, a.student_id)
    if user.role != UserRole.STUDENT and user.role != UserRole.PLATFORM_ADMIN:
        job = await db.get(Job, a.job_id)
        if user.role in RECRUITER_ROLES:
            await require_org_member(db, user, job.organization_id)
    return await _enrich(db, a)


@router.get("/{application_id}/history")
async def application_history(application_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    a = await db.get(Application, application_id)
    if a is None:
        raise HTTPException(404, "Application not found")
    await assert_can_view_student(db, user, a.student_id)
    rows = (await db.scalars(select(ApplicationStatusHistory).where(ApplicationStatusHistory.application_id == a.id)
                             .order_by(ApplicationStatusHistory.created_at))).all()
    return [{"from": r.from_status, "to": r.to_status, "at": r.created_at, "note": r.note,
             "by_system": r.changed_by_user_id is None} for r in rows]


@router.put("/{application_id}/status", response_model=ApplicationOut)
async def update_application_status(application_id: uuid.UUID, payload: ApplicationStatusUpdate,
                                    user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    """Recruiter decisions only. Student-driven steps (assessment/interview)
    advance automatically through their own endpoints."""
    a = await db.get(Application, application_id)
    if a is None:
        raise HTTPException(404, "Application not found")
    await get_job_for_member(db, user, a.job_id)
    if payload.status not in RECRUITER_DECISIONS:
        raise HTTPException(403, f"Recruiters may only set {sorted(s.value for s in RECRUITER_DECISIONS)}")
    try:
        await transition_application(db, a, payload.status, user.id, payload.note)
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    return await _enrich(db, a)
