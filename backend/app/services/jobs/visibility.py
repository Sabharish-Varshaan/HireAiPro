"""Deterministic job visibility and eligibility. No model is involved in any decision here."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import InstitutionStudent
from app.models.enums import JobStatus
from app.models.jobs import Job
from app.models.students import StudentProfile
from app.models.users import User


def _allows(rule: list | None, value) -> bool:
    return not rule or (value is not None and str(value) in {str(x) for x in rule})


async def student_can_access_job(db: AsyncSession, user: User, job: Job) -> bool:
    if JobStatus(job.status) != JobStatus.PUBLISHED:
        return False
    if job.distribution_type != "INSTITUTION":
        return True
    if job.institution_approval != "APPROVED" or job.target_institution_id is None:
        return False
    profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    if profile is None or profile.institution_id != job.target_institution_id:
        return False
    rec = await db.scalar(select(InstitutionStudent).where(
        InstitutionStudent.institution_id == job.target_institution_id, InstitutionStudent.user_id == user.id,
        InstitutionStudent.status == "ACTIVE"))
    if rec is None:
        return False
    rules = job.eligibility or {}
    return (_allows(rules.get("department_ids"), rec.department_id) and _allows(rules.get("cohort_ids"), rec.cohort_id)
            and _allows(rules.get("graduation_years"), rec.graduation_year))


def normalize_rules(department_ids: list[uuid.UUID], cohort_ids: list[uuid.UUID], graduation_years: list[int]) -> dict:
    return {"department_ids": [str(x) for x in department_ids], "cohort_ids": [str(x) for x in cohort_ids],
            "graduation_years": sorted(set(graduation_years))}
