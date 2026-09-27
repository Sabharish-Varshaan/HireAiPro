"""Assessment Agent: orchestrates blueprint -> retrieval -> generation ->
validation -> persistence. Deterministic logic lives in
app.services.assessments; this agent's job is to decide *when* generation
is needed and record the run for admin visibility.
"""

import datetime as dt
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProcessingStatus
from app.models.misc import AgentRun
from app.schemas.assessment_generation import AssessmentPlan, AssessmentSectionPlan
from app.services.assessments.generator import build_assessment_for_job


async def run_assessment_agent(
    db: AsyncSession, job_id: uuid.UUID, organization_id: uuid.UUID, title: str
) -> AssessmentPlan:
    run = AgentRun(agent_type="assessment_agent", task=f"build_assessment:{job_id}", status=ProcessingStatus.RUNNING)
    db.add(run)
    await db.flush()

    tool_calls = []
    try:
        tool_calls.append({"tool": "get_job_competencies", "job_id": str(job_id)})
        assessment, covered, missing = await build_assessment_for_job(
            db, job_id, organization_id, title
        )
        tool_calls.append({"tool": "create_assessment", "assessment_id": str(assessment.id)})

        from sqlalchemy import select

        from app.models.assessments import AssessmentQuestion, AssessmentSection

        sections = (
            await db.scalars(
                select(AssessmentSection).where(AssessmentSection.assessment_id == assessment.id)
            )
        ).all()
        section_plans = []
        total_questions = 0
        for s in sections:
            qs = (
                await db.scalars(
                    select(AssessmentQuestion).where(AssessmentQuestion.section_id == s.id)
                )
            ).all()
            total_questions += len(qs)
            section_plans.append(
                AssessmentSectionPlan(
                    skill_id=covered[0] if covered else uuid.uuid4(),
                    skill_name=s.title,
                    question_ids=[q.question_id for q in qs],
                )
            )

        plan = AssessmentPlan(
            job_id=job_id,
            sections=section_plans,
            total_questions=total_questions,
            covered_skills=covered,
            missing_coverage=missing,
            estimated_duration_minutes=assessment.total_duration_minutes,
        )

        run.status = ProcessingStatus.COMPLETED
        run.tool_calls = tool_calls
        run.ended_at = dt.datetime.now(dt.timezone.utc).isoformat()
        await db.commit()
        return plan
    except Exception as exc:  # noqa: BLE001
        run.status = ProcessingStatus.FAILED
        run.error = str(exc)
        run.tool_calls = tool_calls
        run.ended_at = dt.datetime.now(dt.timezone.utc).isoformat()
        await db.commit()
        raise
