"""Direct-to-DB fixtures for tests that need realistic state without running
the (slow) LLM pipeline. Anything produced by AI in production is created
here explicitly and marked as such."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.applications import Application, ApplicationStatusHistory
from app.models.enums import ApplicationStatus, JobStatus, RequirementType, UserRole
from app.models.institutions import Cohort, Institution, InstitutionMember
from app.models.jobs import Job, JobSkill
from app.models.organizations import Organization, OrganizationMember
from app.models.skills import Skill
from app.models.students import StudentProfile
from app.models.users import User


def uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def make_user(db: AsyncSession, role: UserRole, name: str = "Test User") -> tuple[User, dict]:
    u = User(email=f"{uniq('u')}@example.com", password_hash=hash_password("pw12345!"), full_name=name, role=role)
    db.add(u)
    await db.flush()
    return u, {"Authorization": f"Bearer {create_access_token(u.id, role)}"}


async def make_company(db: AsyncSession, name: str = "Co") -> tuple[Organization, User, dict]:
    u, h = await make_user(db, UserRole.RECRUITER, f"{name} recruiter")
    org = Organization(name=uniq(name), created_by_user_id=u.id)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=u.id, role=UserRole.COMPANY_ADMIN))
    await db.flush()
    return org, u, h


async def skill(db: AsyncSession, name: str) -> Skill:
    return await db.scalar(select(Skill).where(Skill.canonical_name == name))


async def make_job(db: AsyncSession, org: Organization, owner: User, skills: list[tuple[str, str, float, float]],
                   status: JobStatus = JobStatus.PUBLISHED, title: str = "Backend Developer") -> Job:
    """skills: (canonical name, 'required'|'preferred', minimum_level, importance)"""
    job = Job(organization_id=org.id, created_by_user_id=owner.id, title=title, description_raw="test", status=status)
    db.add(job)
    await db.flush()
    for name, req, lvl, imp in skills:
        s = await skill(db, name)
        db.add(JobSkill(job_id=job.id, skill_id=s.id, raw_skill_name=name, requirement_type=RequirementType(req),
                        minimum_level=lvl, importance=imp, extraction_confidence=1.0, confirmed=True))
    await db.flush()
    return job


async def make_student(db: AsyncSession, name: str = "Student", institution: Institution | None = None,
                       cohort: Cohort | None = None) -> tuple[StudentProfile, User, dict]:
    u, h = await make_user(db, UserRole.STUDENT, name)
    p = StudentProfile(user_id=u.id, institution_id=institution.id if institution else None,
                       cohort_id=cohort.id if cohort else None)
    db.add(p)
    await db.flush()
    return p, u, h


async def make_application(db: AsyncSession, job: Job, student: StudentProfile,
                           status: ApplicationStatus = ApplicationStatus.APPLIED) -> Application:
    a = Application(job_id=job.id, student_id=student.id, status=status)
    db.add(a)
    await db.flush()
    db.add(ApplicationStatusHistory(application_id=a.id, from_status=None, to_status=status.value))
    await db.flush()
    return a


async def make_institution(db: AsyncSession, name: str = "Uni") -> tuple[Institution, User, dict]:
    u, h = await make_user(db, UserRole.INSTITUTION_ADMIN, f"{name} admin")
    inst = Institution(name=uniq(name), created_by_user_id=u.id)
    db.add(inst)
    await db.flush()
    db.add(InstitutionMember(institution_id=inst.id, user_id=u.id, role=UserRole.INSTITUTION_ADMIN))
    await db.flush()
    return inst, u, h
