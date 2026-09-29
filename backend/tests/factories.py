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


async def configure_pipeline(db: AsyncSession, job: Job, enabled: list[str], durations: dict[str, int] | None = None):
    """Sets which stages of the job's hiring process are enabled (in the given order); everything else is disabled."""
    from app.services.pipeline import service as pl
    from app.services.pipeline import stages as S

    rows = {r.stage_type: r for r in await pl.ensure_pipeline(db, job)}
    order = list(enabled) + [t for t in S.ALL_STAGES if t not in enabled]
    for i, t in enumerate(order):
        rows[t].order_index = i
        rows[t].enabled = t in enabled
        if durations and t in durations:
            rows[t].duration_minutes = durations[t]
    await db.flush()
    return rows


async def make_stage_assessment(db: AsyncSession, org: Organization, job: Job, stage_type: str, *, duration: int = 30,
                                published: bool = True, n: int = 3, token: str = ""):
    """A stage-linked assessment whose questions belong to the stage's own domain: aptitude MCQs (no skill), technical MCQ + written, or coding."""
    from app.models.assessments import Assessment, AssessmentQuestion, AssessmentSection
    from app.models.enums import QuestionSourceType, QuestionStatus, QuestionType, Visibility
    from app.models.questions import Question
    from app.services.assessments import versioning as ver
    from app.services.pipeline import service as pl
    from app.services.pipeline import stages as S

    rows = {r.stage_type: r for r in await pl.ensure_pipeline(db, job)}
    st = rows[stage_type]
    st.enabled, st.duration_minutes = True, duration
    py = await skill(db, "Python")
    qs = []
    if stage_type == S.APTITUDE:
        for i in range(n):
            qs.append(Question(question_text=f"{token} Aptitude question {i}: what is {i + 2} multiplied by 6?", question_type=QuestionType.MCQ, skill_id=None,
                               domain="APTITUDE", category="Quantitative Aptitude", options=["10", str((i + 2) * 6), "30", "41"], correct_option_index=1))
    elif stage_type == S.CODING:
        for i in range(max(1, n - 1)):
            qs.append(Question(question_text=f"{token} Coding problem {i}: read integers from stdin and print their sum.", question_type=QuestionType.CODING,
                               skill_id=py.id, domain="CODING", starter_code="import sys\n",
                               test_cases=[{"input": "[1, 2, 3]", "expected_output": "6"}, {"input": "[10, -4]", "expected_output": "6"}, {"input": "[0]", "expected_output": "0"}]))
    else:
        for i in range(n):
            if i % 2 == 0:
                qs.append(Question(question_text=f"{token} Technical MCQ {i}: which keyword defines a generator?", question_type=QuestionType.MCQ, skill_id=py.id,
                                   options=["return", "yield", "emit"], correct_option_index=1))
            else:
                qs.append(Question(question_text=f"{token} Technical written {i}: explain Python's method resolution order.", question_type=QuestionType.TECHNICAL,
                                   skill_id=py.id, expected_concepts=["C3", "mro"], rubric={"criteria": ["mro"]}))
    for q in qs:
        q.difficulty, q.source_type, q.organization_id = "medium", QuestionSourceType.COMPANY_PRIVATE, org.id
        q.visibility, q.status = Visibility.COMPANY_PRIVATE, QuestionStatus.APPROVED
        db.add(q)
    a = Assessment(job_id=job.id, title=S.label(stage_type), status="PUBLISHED" if published else "DRAFT", stage_type=stage_type,
                   total_duration_minutes=duration, config={"duration_minutes": duration, "randomize_questions": False, "randomize_options": False})
    db.add(a)
    await db.flush()
    sec = AssessmentSection(assessment_id=a.id, title="all", order_index=0)
    db.add(sec)
    await db.flush()
    aqs = []
    for i, q in enumerate(qs):
        aq = AssessmentQuestion(assessment_id=a.id, section_id=sec.id, question_id=q.id, order_index=i)
        db.add(aq)
        aqs.append(aq)
    st.assessment_id, st.status = a.id, "PUBLISHED" if published else "READY"
    await db.flush()
    if published:
        await ver.ensure_version(db, a)
    return st, a, aqs, qs
