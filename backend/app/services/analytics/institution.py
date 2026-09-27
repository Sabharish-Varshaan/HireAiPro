"""Institution analytics. Every number here comes from a SQL aggregate over
authoritative Postgres rows. The optional LLM summary is generated *from*
these numbers and is labelled as such; it never produces a value."""

import json
import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import Application
from app.models.assessments import AssessmentAttempt
from app.models.evidence import StudentSkill
from app.models.institutions import Cohort, Department
from app.models.jobs import JobSkill
from app.models.matching import Match
from app.models.skills import Skill
from app.models.students import StudentProfile
from app.models.users import User

READINESS_THRESHOLD = 0.7


def _student_filter(institution_id, department_id=None, cohort_id=None):
    conds = [StudentProfile.institution_id == institution_id]
    if cohort_id:
        conds.append(StudentProfile.cohort_id == cohort_id)
    if department_id:
        conds.append(StudentProfile.cohort_id.in_(select(Cohort.id).where(Cohort.department_id == department_id)))
    return and_(*conds)


async def roster(db: AsyncSession, institution_id, department_id=None, cohort_id=None) -> list[dict]:
    stmt = (
        select(StudentProfile.id, User.full_name, User.email, Cohort.name, Department.name,
               func.count(func.distinct(StudentSkill.id)), func.avg(StudentSkill.estimated_level),
               func.count(func.distinct(Application.id)))
        .join(User, User.id == StudentProfile.user_id)
        .outerjoin(Cohort, Cohort.id == StudentProfile.cohort_id)
        .outerjoin(Department, Department.id == Cohort.department_id)
        .outerjoin(StudentSkill, StudentSkill.student_id == StudentProfile.id)
        .outerjoin(Application, Application.student_id == StudentProfile.id)
        .where(_student_filter(institution_id, department_id, cohort_id))
        .group_by(StudentProfile.id, User.full_name, User.email, Cohort.name, Department.name)
        .order_by(User.full_name)
    )
    return [
        {"student_id": r[0], "name": r[1], "email": r[2], "cohort": r[3], "department": r[4],
         "verified_skills": r[5], "avg_level": round(float(r[6]), 3) if r[6] is not None else None, "applications": r[7]}
        for r in (await db.execute(stmt)).all()
    ]


async def cohort_skill_heatmap(db: AsyncSession, institution_id, department_id=None, cohort_id=None) -> list[dict]:
    stmt = (
        select(Cohort.id, Cohort.name, Skill.id, Skill.canonical_name,
               func.avg(StudentSkill.estimated_level), func.count(StudentSkill.id))
        .select_from(StudentProfile)
        .join(Cohort, Cohort.id == StudentProfile.cohort_id)
        .join(StudentSkill, StudentSkill.student_id == StudentProfile.id)
        .join(Skill, Skill.id == StudentSkill.skill_id)
        .where(_student_filter(institution_id, department_id, cohort_id))
        .group_by(Cohort.id, Cohort.name, Skill.id, Skill.canonical_name)
    )
    return [
        {"cohort_id": r[0], "cohort_name": r[1], "skill_id": r[2], "skill_name": r[3],
         "average_level": round(float(r[4]), 3), "student_count": r[5]}
        for r in (await db.execute(stmt)).all()
    ]


async def industry_demand_skills(db: AsyncSession, limit: int = 20) -> list[dict]:
    stmt = (
        select(Skill.id, Skill.canonical_name, func.count(JobSkill.id), func.avg(JobSkill.importance),
               func.avg(JobSkill.minimum_level))
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .where(JobSkill.confirmed.is_(True))
        .group_by(Skill.id, Skill.canonical_name)
        .order_by(func.count(JobSkill.id).desc(), func.avg(JobSkill.importance).desc())
        .limit(limit)
    )
    return [
        {"skill_id": r[0], "skill_name": r[1], "demand_count": r[2], "avg_importance": round(float(r[3]), 3),
         "avg_required_level": round(float(r[4]), 3)}
        for r in (await db.execute(stmt)).all()
    ]


async def strengths_and_gaps(db: AsyncSession, institution_id, department_id=None, cohort_id=None, limit: int = 8) -> dict:
    """Gap = industry avg required level − cohort avg level (students with no
    evidence count as 0 for that skill, so unassessed skills show as gaps)."""
    n_students = await db.scalar(select(func.count(StudentProfile.id)).where(_student_filter(institution_id, department_id, cohort_id))) or 0
    demand = await industry_demand_skills(db, limit=50)
    if not demand or not n_students:
        return {"students": n_students, "strengths": [], "gaps": []}
    sums = dict(
        (r[0], float(r[1]))
        for r in (
            await db.execute(
                select(StudentSkill.skill_id, func.sum(StudentSkill.estimated_level))
                .join(StudentProfile, StudentProfile.id == StudentSkill.student_id)
                .where(_student_filter(institution_id, department_id, cohort_id))
                .group_by(StudentSkill.skill_id)
            )
        ).all()
    )
    rows = []
    for d in demand:
        cohort_avg = sums.get(d["skill_id"], 0.0) / n_students
        rows.append({**d, "cohort_avg_level": round(cohort_avg, 3), "gap": round(d["avg_required_level"] - cohort_avg, 3)})
    return {
        "students": n_students,
        "gaps": sorted(rows, key=lambda r: r["gap"] * r["avg_importance"], reverse=True)[:limit],
        "strengths": sorted([r for r in rows if r["cohort_avg_level"] > 0], key=lambda r: r["gap"])[:limit],
    }


async def assessment_performance(db: AsyncSession, institution_id, department_id=None, cohort_id=None) -> dict:
    row = (
        await db.execute(
            select(func.count(AssessmentAttempt.id), func.avg(AssessmentAttempt.total_score),
                   func.min(AssessmentAttempt.total_score), func.max(AssessmentAttempt.total_score))
            .join(StudentProfile, StudentProfile.id == AssessmentAttempt.student_id)
            .where(_student_filter(institution_id, department_id, cohort_id), AssessmentAttempt.status == "SCORED")
        )
    ).one()
    return {"attempts": row[0], "avg_score": round(float(row[1]), 3) if row[1] is not None else None,
            "min_score": row[2], "max_score": row[3]}


async def application_funnel(db: AsyncSession, institution_id, department_id=None, cohort_id=None) -> list[dict]:
    rows = (
        await db.execute(
            select(Application.status, func.count(Application.id))
            .join(StudentProfile, StudentProfile.id == Application.student_id)
            .where(_student_filter(institution_id, department_id, cohort_id))
            .group_by(Application.status)
        )
    ).all()
    order = ["APPLIED", "ASSESSMENT_PENDING", "ASSESSMENT_COMPLETED", "INTERVIEW_PENDING", "INTERVIEW_COMPLETED",
             "UNDER_REVIEW", "SHORTLISTED", "OFFER", "REJECTED"]
    counts = {str(r[0]): r[1] for r in rows}
    return [{"status": s, "count": counts.get(s, 0)} for s in order]


async def role_readiness(db: AsyncSession, institution_id, department_id=None, cohort_id=None) -> dict:
    """Readiness uses the deterministic matching_v1 scores already stored."""
    row = (
        await db.execute(
            select(func.count(func.distinct(Match.student_id)),
                   func.count(func.distinct(Match.student_id)).filter(Match.required_skill_fit >= READINESS_THRESHOLD),
                   func.avg(Match.match_score))
            .join(StudentProfile, StudentProfile.id == Match.student_id)
            .where(_student_filter(institution_id, department_id, cohort_id))
        )
    ).one()
    return {"students_matched": row[0], "students_ready": row[1], "readiness_threshold": READINESS_THRESHOLD,
            "avg_match_score": round(float(row[2]), 3) if row[2] is not None else None}


async def placement_readiness(db: AsyncSession, institution_id) -> dict:
    funnel = {f["status"]: f["count"] for f in await application_funnel(db, institution_id)}
    total = await db.scalar(select(func.count(StudentProfile.id)).where(StudentProfile.institution_id == institution_id))
    with_apps = await db.scalar(
        select(func.count(func.distinct(Application.student_id)))
        .join(StudentProfile, StudentProfile.id == Application.student_id)
        .where(StudentProfile.institution_id == institution_id)
    )
    return {"total_students": total or 0, "students_with_applications": with_apps or 0,
            "shortlisted": funnel.get("SHORTLISTED", 0), "offers": funnel.get("OFFER", 0)}


async def institution_report(db: AsyncSession, institution_id, department_id=None, cohort_id=None, with_summary=False) -> dict:
    report = {
        "placement": await placement_readiness(db, institution_id),
        "readiness": await role_readiness(db, institution_id, department_id, cohort_id),
        "assessment_performance": await assessment_performance(db, institution_id, department_id, cohort_id),
        "funnel": await application_funnel(db, institution_id, department_id, cohort_id),
        "strengths_and_gaps": await strengths_and_gaps(db, institution_id, department_id, cohort_id),
    }
    if with_summary:
        report["summary"] = await summarize(report)
    return json.loads(json.dumps(report, default=str))


async def summarize(report: dict) -> dict:
    from pydantic import BaseModel

    from app.services.ai_gateway.gateway import AIGatewayError, get_ai_gateway

    class _S(BaseModel):
        summary: str

    try:
        s = await get_ai_gateway().generate_structured(
            "Write a 3-4 sentence summary for a placement officer of these analytics. Use ONLY numbers that "
            "appear in the data; do not estimate or invent any figure.\n\nDATA:\n" + json.dumps(report, default=str)[:6000],
            _S, task_type="analytics_summary",
        )
        return {"text": s.summary, "generated_by": "LLM from the SQL figures above"}
    except AIGatewayError as exc:
        return {"text": None, "error": str(exc)}
