"""Campus opportunities: a company targets an institution; its placement officer approves or rejects and sets eligibility."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.tenancy import member_institution_ids
from app.core.database import get_db
from app.models.assessments import Assessment, AssessmentVersion
from app.models.enums import JobStatus, UserRole
from app.models.institutions import Cohort, Department, Institution
from app.models.jobs import Job, JobSkill
from app.models.organizations import Organization
from app.models.skills import Skill
from app.models.users import User
from app.services.audit import audit
from app.services.jobs.visibility import normalize_rules

router = APIRouter(prefix="/institutions", tags=["opportunities"])
OFFICER = (UserRole.PLACEMENT_OFFICER, UserRole.INSTITUTION_ADMIN)
RECRUITERS = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)


class ApproveIn(BaseModel):
    department_ids: list[uuid.UUID] = Field(default_factory=list)
    cohort_ids: list[uuid.UUID] = Field(default_factory=list)
    graduation_years: list[int] = Field(default_factory=list)


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=1000)


@router.get("/directory")
async def directory(user: User = Depends(require_roles(*RECRUITERS)), db: AsyncSession = Depends(get_db)):
    """Institution names a company may target (name only)."""
    return [{"id": i.id, "name": i.name} for i in (await db.scalars(select(Institution).order_by(Institution.name))).all()]


async def _own(db, user, institution_id):
    if institution_id not in await member_institution_ids(db, user):
        raise HTTPException(404, "Institution not found")


async def _job_for(db, institution_id, job_id) -> Job:
    job = await db.get(Job, job_id)
    if job is None or job.target_institution_id != institution_id or job.distribution_type != "INSTITUTION":
        raise HTTPException(404, "Opportunity not found")
    return job


@router.get("/{institution_id}/opportunities")
async def list_opportunities(institution_id: uuid.UUID, status: str | None = None, user: User = Depends(require_roles(*OFFICER)),
                             db: AsyncSession = Depends(get_db)):
    await _own(db, user, institution_id)
    stmt = (select(Job, Organization.name).join(Organization, Organization.id == Job.organization_id)
            .where(Job.target_institution_id == institution_id, Job.distribution_type == "INSTITUTION",
                   Job.status == JobStatus.PUBLISHED.value, Job.institution_approval != "NOT_REQUIRED")
            .order_by(Job.created_at.desc()))
    if status:
        stmt = stmt.where(Job.institution_approval == status)
    out = []
    for job, org in (await db.execute(stmt)).all():
        skills = (await db.execute(select(Skill.canonical_name, JobSkill.requirement_type).join(JobSkill, JobSkill.skill_id == Skill.id)
                                   .where(JobSkill.job_id == job.id, JobSkill.confirmed.is_(True)))).all()
        version = await db.scalar(select(AssessmentVersion).join(Assessment, Assessment.id == AssessmentVersion.assessment_id)
                                  .where(Assessment.job_id == job.id).order_by(AssessmentVersion.version_no.desc()))
        assessment = None
        if version is not None:  # what the assessment is, never its questions
            types: dict[str, int] = {}
            for sec in version.content["sections"]:
                for item in sec["questions"]:
                    t = item["question"]["question_type"]
                    types[t] = types.get(t, 0) + 1
            assessment = {"question_count": sum(types.values()), "duration_minutes": version.duration_minutes, "types": types}
        out.append({"job_id": job.id, "title": job.title, "company": org, "location": job.location, "employment_type": job.employment_type,
                    "work_mode": job.work_mode, "display": job.display, "number_of_openings": job.number_of_openings,
                    "description": job.description_raw, "status": job.institution_approval, "note": job.approval_note,
                    "eligibility": job.eligibility, "assessment": assessment,
                    "skills": [{"name": n, "type": str(t)} for n, t in skills], "submitted_at": job.updated_at})
    return out


@router.post("/{institution_id}/opportunities/{job_id}/approve")
async def approve(institution_id: uuid.UUID, job_id: uuid.UUID, payload: ApproveIn, user: User = Depends(require_roles(*OFFICER)),
                  db: AsyncSession = Depends(get_db)):
    await _own(db, user, institution_id)
    job = await _job_for(db, institution_id, job_id)
    if job.institution_approval != "PENDING":
        raise HTTPException(409, f"Opportunity is {job.institution_approval}, not pending")
    for did in payload.department_ids:
        d = await db.get(Department, did)
        if d is None or d.institution_id != institution_id:
            raise HTTPException(422, "Department is not part of this institution")
    for cid in payload.cohort_ids:
        c = await db.get(Cohort, cid)
        if c is None or c.institution_id != institution_id:
            raise HTTPException(422, "Cohort is not part of this institution")
    job.institution_approval, job.approved_by_user_id, job.approval_note = "APPROVED", user.id, None
    job.eligibility = normalize_rules(payload.department_ids, payload.cohort_ids, payload.graduation_years)
    await audit(db, user, "opportunity_approved", "job", job.id, organization_id=job.organization_id,
                metadata={"institution_id": str(institution_id), "eligibility": job.eligibility})
    await db.commit()
    return {"status": job.institution_approval, "eligibility": job.eligibility}


@router.post("/{institution_id}/opportunities/{job_id}/reject")
async def reject(institution_id: uuid.UUID, job_id: uuid.UUID, payload: RejectIn, user: User = Depends(require_roles(*OFFICER)),
                 db: AsyncSession = Depends(get_db)):
    await _own(db, user, institution_id)
    job = await _job_for(db, institution_id, job_id)
    if job.institution_approval != "PENDING":
        raise HTTPException(409, f"Opportunity is {job.institution_approval}, not pending")
    job.institution_approval, job.approved_by_user_id, job.approval_note = "REJECTED", user.id, payload.note.strip()
    await audit(db, user, "opportunity_rejected", "job", job.id, organization_id=job.organization_id,
                metadata={"institution_id": str(institution_id)})
    await db.commit()
    return {"status": job.institution_approval}
