import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.tenancy import member_institution_ids
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.applications import Application
from app.models.jobs import Job
from app.models.organizations import Organization
from app.models.institutions import Cohort, Department, Institution, InstitutionMember
from app.models.students import StudentProfile
from app.models.users import User
from app.services.analytics import institution as ia
from app.services.audit import audit

router = APIRouter(prefix="/institutions", tags=["institutions"])

STAFF = (UserRole.INSTITUTION_ADMIN, UserRole.PLACEMENT_OFFICER, UserRole.FACULTY, UserRole.DEPARTMENT_HEAD)
MANAGERS = (UserRole.INSTITUTION_ADMIN, UserRole.PLACEMENT_OFFICER)


class NameIn(BaseModel):
    name: str


class CohortIn(BaseModel):
    name: str
    department_id: uuid.UUID | None = None
    graduation_year: int | None = None


class EnrollIn(BaseModel):
    student_email: str
    cohort_id: uuid.UUID | None = None


async def _member(db, user: User, institution_id: uuid.UUID) -> None:
    if user.role != UserRole.PLATFORM_ADMIN and institution_id not in await member_institution_ids(db, user):
        raise HTTPException(404, "Institution not found")


@router.post("")
async def create_institution(payload: NameIn, user: User = Depends(require_roles(UserRole.PLACEMENT_OFFICER, UserRole.INSTITUTION_ADMIN)),
                             db: AsyncSession = Depends(get_db)):
    inst = Institution(name=payload.name, created_by_user_id=user.id)
    db.add(inst)
    await db.flush()
    db.add(InstitutionMember(institution_id=inst.id, user_id=user.id, role=UserRole.INSTITUTION_ADMIN))
    await audit(db, user, "institution_created", "institution", inst.id)
    await db.commit()
    return {"id": inst.id, "name": inst.name}


@router.get("/mine")
async def my_institutions(user: User = Depends(require_roles(*STAFF, UserRole.PLATFORM_ADMIN)), db: AsyncSession = Depends(get_db)):
    ids = await member_institution_ids(db, user)
    rows = (await db.scalars(select(Institution).where(Institution.id.in_(ids)))).all()
    return [{"id": i.id, "name": i.name} for i in rows]


@router.get("/{institution_id}/structure")
async def structure(institution_id: uuid.UUID, user: User = Depends(require_roles(*STAFF, UserRole.PLATFORM_ADMIN)),
                    db: AsyncSession = Depends(get_db)):
    await _member(db, user, institution_id)
    deps = (await db.scalars(select(Department).where(Department.institution_id == institution_id))).all()
    cohorts = (await db.scalars(select(Cohort).where(Cohort.institution_id == institution_id))).all()
    return {"departments": [{"id": d.id, "name": d.name} for d in deps],
            "cohorts": [{"id": c.id, "name": c.name, "department_id": c.department_id, "graduation_year": c.graduation_year}
                        for c in cohorts]}


@router.post("/{institution_id}/departments")
async def add_department(institution_id: uuid.UUID, payload: NameIn, user: User = Depends(require_roles(*MANAGERS)),
                         db: AsyncSession = Depends(get_db)):
    await _member(db, user, institution_id)
    d = Department(institution_id=institution_id, name=payload.name)
    db.add(d)
    await db.commit()
    return {"id": d.id, "name": d.name}


@router.post("/{institution_id}/cohorts")
async def add_cohort(institution_id: uuid.UUID, payload: CohortIn, user: User = Depends(require_roles(*MANAGERS)),
                     db: AsyncSession = Depends(get_db)):
    await _member(db, user, institution_id)
    if payload.department_id:
        dep = await db.get(Department, payload.department_id)
        if dep is None or dep.institution_id != institution_id:
            raise HTTPException(422, "Department not in this institution")
    c = Cohort(institution_id=institution_id, **payload.model_dump())
    db.add(c)
    await db.commit()
    return {"id": c.id, "name": c.name}


@router.get("/{institution_id}/roster")
async def roster(institution_id: uuid.UUID, department_id: uuid.UUID | None = None, cohort_id: uuid.UUID | None = None,
                 user: User = Depends(require_roles(*STAFF, UserRole.PLATFORM_ADMIN)), db: AsyncSession = Depends(get_db)):
    await _member(db, user, institution_id)
    return await ia.roster(db, institution_id, department_id, cohort_id)


@router.get("/{institution_id}/students/{student_id}/applications")
async def student_applications(institution_id: uuid.UUID, student_id: uuid.UUID,
                               user: User = Depends(require_roles(*STAFF, UserRole.PLATFORM_ADMIN)),
                               db: AsyncSession = Depends(get_db)):
    """Applications of ONE enrolled student, so staff can open the per-application
    evaluation and proctoring record (docs/SCORE_VISIBILITY.md)."""
    await _member(db, user, institution_id)
    profile = await db.get(StudentProfile, student_id)
    if profile is None or profile.institution_id != institution_id:
        raise HTTPException(404, "Student not enrolled at this institution")
    owner = await db.get(User, profile.user_id)
    rows = (await db.execute(select(Application, Job, Organization).join(Job, Job.id == Application.job_id)
                             .join(Organization, Organization.id == Job.organization_id)
                             .where(Application.student_id == student_id).order_by(Application.created_at.desc()))).all()
    return {"student_id": student_id, "name": owner.full_name if owner else None,
            "applications": [{"id": a.id, "job_title": j.title, "organization_name": o.name, "status": a.status,
                              "applied_at": a.created_at} for a, j, o in rows]}


@router.get("/{institution_id}/analytics")
async def analytics_bundle(institution_id: uuid.UUID, department_id: uuid.UUID | None = None, cohort_id: uuid.UUID | None = None,
                           user: User = Depends(require_roles(*STAFF, UserRole.PLATFORM_ADMIN)), db: AsyncSession = Depends(get_db)):
    await _member(db, user, institution_id)
    report = await ia.institution_report(db, institution_id, department_id, cohort_id)
    report["heatmap"] = await ia.cohort_skill_heatmap(db, institution_id, department_id, cohort_id)
    report["industry_demand"] = await ia.industry_demand_skills(db)
    return report


@router.post("/{institution_id}/analytics/summary")
async def analytics_summary(institution_id: uuid.UUID, department_id: uuid.UUID | None = None, cohort_id: uuid.UUID | None = None,
                            user: User = Depends(require_roles(*STAFF, UserRole.PLATFORM_ADMIN)), db: AsyncSession = Depends(get_db)):
    await _member(db, user, institution_id)
    report = await ia.institution_report(db, institution_id, department_id, cohort_id)
    return await ia.summarize(report)


@router.get("/{institution_id}/analytics/cohort-heatmap")
async def cohort_heatmap(institution_id: uuid.UUID, user: User = Depends(require_roles(*STAFF)), db: AsyncSession = Depends(get_db)):
    await _member(db, user, institution_id)
    return await ia.cohort_skill_heatmap(db, institution_id)


@router.get("/analytics/industry-demand")
async def industry_demand(user: User = Depends(require_roles(*STAFF, UserRole.PLATFORM_ADMIN)), db: AsyncSession = Depends(get_db)):
    return await ia.industry_demand_skills(db)


@router.get("/{institution_id}/analytics/placement-readiness")
async def placement_readiness_route(institution_id: uuid.UUID, user: User = Depends(require_roles(*STAFF)),
                                    db: AsyncSession = Depends(get_db)):
    await _member(db, user, institution_id)
    return await ia.placement_readiness(db, institution_id)
