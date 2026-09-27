import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import StudentSkill
from app.models.jobs import JobSkill
from app.models.skills import Skill, SkillRelationship
from app.models.enums import SkillRelationType


async def calculate_skill_gaps(
    db: AsyncSession, student_id: uuid.UUID, target_job_id: uuid.UUID
) -> list[dict]:
    """Deterministic: required job skills where student level < minimum_level."""
    job_skills = (
        await db.scalars(
            select(JobSkill).where(JobSkill.job_id == target_job_id, JobSkill.confirmed.is_(True), JobSkill.skill_id.is_not(None))
        )
    ).all()
    student_skills = {
        s.skill_id: s
        for s in (await db.scalars(select(StudentSkill).where(StudentSkill.student_id == student_id))).all()
    }

    gaps = []
    for js in job_skills:
        current = student_skills.get(js.skill_id)
        level = current.estimated_level if current else 0.0
        if level < js.minimum_level:
            skill = await db.get(Skill, js.skill_id)
            gaps.append(
                {
                    "skill_id": js.skill_id,
                    "skill_name": skill.canonical_name if skill else js.raw_skill_name,
                    "current_level": level,
                    "required_level": js.minimum_level,
                    "gap": js.minimum_level - level,
                    "importance": js.importance,
                }
            )
    gaps.sort(key=lambda g: g["gap"] * g["importance"], reverse=True)
    return gaps


async def get_prerequisites(db: AsyncSession, skill_id: uuid.UUID) -> list[Skill]:
    rel_rows = (
        await db.scalars(
            select(SkillRelationship).where(
                SkillRelationship.to_skill_id == skill_id,
                SkillRelationship.relation_type == SkillRelationType.PREREQUISITE_OF,
            )
        )
    ).all()
    prereqs = []
    for r in rel_rows:
        skill = await db.get(Skill, r.from_skill_id)
        if skill:
            prereqs.append(skill)
    return prereqs
