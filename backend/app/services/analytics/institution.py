import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import Application
from app.models.evidence import StudentSkill
from app.models.institutions import Cohort
from app.models.jobs import JobSkill
from app.models.skills import Skill
from app.models.students import StudentProfile


async def cohort_skill_heatmap(db: AsyncSession, institution_id: uuid.UUID) -> list[dict]:
    """Average estimated_level per (cohort, skill) — pure SQL aggregation."""
    stmt = (
        select(
            Cohort.id,
            Cohort.name,
            Skill.id,
            Skill.canonical_name,
            func.avg(StudentSkill.estimated_level),
            func.count(StudentSkill.id),
        )
        .select_from(StudentProfile)
        .join(Cohort, Cohort.id == StudentProfile.cohort_id)
        .join(StudentSkill, StudentSkill.student_id == StudentProfile.id)
        .join(Skill, Skill.id == StudentSkill.skill_id)
        .where(StudentProfile.institution_id == institution_id)
        .group_by(Cohort.id, Cohort.name, Skill.id, Skill.canonical_name)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "cohort_id": r[0],
            "cohort_name": r[1],
            "skill_id": r[2],
            "skill_name": r[3],
            "average_level": round(float(r[4]), 3),
            "student_count": r[5],
        }
        for r in rows
    ]


async def industry_demand_skills(db: AsyncSession, limit: int = 20) -> list[dict]:
    """How often each skill appears as required/preferred across all confirmed
    jobs platform-wide — pure SQL aggregation, no LLM."""
    stmt = (
        select(Skill.id, Skill.canonical_name, func.count(JobSkill.id), func.avg(JobSkill.importance))
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .where(JobSkill.confirmed.is_(True))
        .group_by(Skill.id, Skill.canonical_name)
        .order_by(func.count(JobSkill.id).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {"skill_id": r[0], "skill_name": r[1], "demand_count": r[2], "avg_importance": round(float(r[3]), 3)}
        for r in rows
    ]


async def placement_readiness(db: AsyncSession, institution_id: uuid.UUID) -> dict:
    total_students = await db.scalar(
        select(func.count(StudentProfile.id)).where(StudentProfile.institution_id == institution_id)
    )
    student_ids = (
        await db.scalars(select(StudentProfile.id).where(StudentProfile.institution_id == institution_id))
    ).all()
    if not student_ids:
        return {"total_students": 0, "students_with_applications": 0, "shortlisted": 0, "offers": 0}

    applications = (
        await db.scalars(select(Application).where(Application.student_id.in_(student_ids)))
    ).all()
    students_with_apps = len({a.student_id for a in applications})
    shortlisted = len([a for a in applications if a.status == "SHORTLISTED"])
    offers = len([a for a in applications if a.status == "OFFER"])

    return {
        "total_students": total_students,
        "students_with_applications": students_with_apps,
        "shortlisted": shortlisted,
        "offers": offers,
    }
