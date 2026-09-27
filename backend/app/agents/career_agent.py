"""Career Agent: turns deterministically-calculated skill gaps + the
prerequisite graph into a persisted, explained learning roadmap. The gap
values themselves are never touched by the LLM — only the explanatory text
and step ordering rationale are AI-generated, and only over resources that
actually exist in the database (no hallucinated links).
"""

import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.career import LearningPath, LearningPathStep, LearningResource
from app.schemas.career import CareerRoadmap, CareerStep
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.career.gaps import calculate_skill_gaps, get_prerequisites


class _RoadmapSummary(BaseModel):
    summary: str
    step_rationales: dict[str, str]


async def _find_resource(db: AsyncSession, skill_id: uuid.UUID) -> LearningResource | None:
    return await db.scalar(select(LearningResource).where(LearningResource.skill_id == skill_id))


async def build_career_roadmap(
    db: AsyncSession, student_id: uuid.UUID, target_job_id: uuid.UUID
) -> CareerRoadmap:
    gaps = await calculate_skill_gaps(db, student_id, target_job_id)

    ordered_skill_names: list[str] = []
    step_skill_ids: list[uuid.UUID] = []
    for gap in gaps:
        prereqs = await get_prerequisites(db, gap["skill_id"])
        for p in prereqs:
            if p.id not in step_skill_ids:
                step_skill_ids.append(p.id)
                ordered_skill_names.append(p.canonical_name)
        if gap["skill_id"] not in step_skill_ids:
            step_skill_ids.append(gap["skill_id"])
            ordered_skill_names.append(gap["skill_name"])

    gateway = get_ai_gateway()
    try:
        ai_summary = await gateway.generate_structured(
            "Student has these skill gaps for the target role, in priority order: "
            + ", ".join(ordered_skill_names)
            + ". Write a short encouraging summary (2-3 sentences) and one short "
            "rationale sentence per skill (keyed by skill name) explaining why it's "
            "next.",
            _RoadmapSummary,
        )
    except Exception:  # noqa: BLE001 — interview must degrade gracefully without AI
        ai_summary = _RoadmapSummary(
            summary="Roadmap generated from your current skill gaps.",
            step_rationales={name: f"Builds toward role requirements." for name in ordered_skill_names},
        )

    steps: list[CareerStep] = []
    for skill_id, skill_name in zip(step_skill_ids, ordered_skill_names):
        resource = await _find_resource(db, skill_id)
        steps.append(
            CareerStep(
                skill_id=skill_id,
                skill_name=skill_name,
                rationale=ai_summary.step_rationales.get(skill_name, "Needed to close a gap for this role."),
                resource_id=resource.id if resource else None,
                resource_title=resource.title if resource else None,
            )
        )

    learning_path = LearningPath(
        student_id=student_id,
        target_job_id=target_job_id,
        gap_skill_ids=[str(g["skill_id"]) for g in gaps],
        summary=ai_summary.summary,
    )
    db.add(learning_path)
    await db.flush()

    for idx, step in enumerate(steps):
        db.add(
            LearningPathStep(
                learning_path_id=learning_path.id,
                order_index=idx,
                skill_id=step.skill_id,
                resource_id=step.resource_id,
                rationale=step.rationale,
            )
        )
    await db.commit()

    return CareerRoadmap(
        target_job_id=target_job_id,
        gap_skill_ids=[g["skill_id"] for g in gaps],
        steps=steps,
        summary=ai_summary.summary,
    )
