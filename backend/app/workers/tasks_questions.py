import uuid

from app.core.database import AsyncSessionLocal
from app.models.jobs import Job
from app.models.enums import JobStatus
from app.services.audit import audit
from app.workers.celery_app import celery_app
from app.workers.jobs import TRANSIENT, PermanentJobError, run_tracked
from app.workers.utils import run_async


async def generate_assessment(job_id: uuid.UUID, title: str, actor_user_id: uuid.UUID | None) -> dict:
    """Idempotent: one assessment per job, rebuilt in place; generated
    questions are keyed by (job, skill, type, slot) and reused on retry."""
    from app.agents.assessment_agent import run_assessment_agent
    from app.services.assessments.generator import GenerationError

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None:
            raise PermanentJobError("job not found")
        try:
            plan = await run_assessment_agent(db, job, title, actor_user_id)
        except (ValueError, GenerationError) as exc:
            raise PermanentJobError(str(exc)) from exc
        job = await db.get(Job, job_id)
        if JobStatus(job.status) == JobStatus.REQUIREMENTS_CONFIRMED:
            job.status = JobStatus.ASSESSMENT_READY
        await audit(db, actor_user_id, "assessment_generated", "assessment", plan.assessment_id,
                    organization_id=job.organization_id,
                    metadata={"questions": plan.total_questions, "missing": len(plan.missing_coverage)})
        await db.commit()
        return plan.model_dump(mode="json")


@celery_app.task(name="assessments.generate", bind=True, autoretry_for=TRANSIENT, retry_backoff=10, max_retries=2)
def generate_assessment_task(self, job_id: str, title: str, actor_user_id: str | None = None) -> dict:
    return run_async(lambda: run_tracked(
        f"assessment:{job_id}", "assessment_generation", {"job_id": job_id, "title": title}, self.request.id,
        lambda: generate_assessment(uuid.UUID(job_id), title, uuid.UUID(actor_user_id) if actor_user_id else None),
    ))


@celery_app.task(name="assessments.prepare_interview", bind=True, autoretry_for=TRANSIENT, retry_backoff=10, max_retries=2)
def prepare_interview_template_task(self, job_id: str, stage_type: str = "TECHNICAL_INTERVIEW") -> dict:
    """Authoring-time preparation of an interview stage's template and question pool (docs/INTERVIEW_LATENCY.md)."""
    from app.services.interviews.pool import fill_pool

    key = f"interview_template:{job_id}" + ("" if stage_type == "TECHNICAL_INTERVIEW" else f":{stage_type}")
    return run_async(lambda: run_tracked(key, "interview_template", {"job_id": job_id, "stage_type": stage_type}, self.request.id,
                                         lambda: fill_pool(uuid.UUID(job_id), stage_type)))


@celery_app.task(name="pipeline.generate_stage", bind=True, autoretry_for=TRANSIENT, retry_backoff=10, max_retries=2)
def generate_stage_task(self, job_id: str, stage_type: str, actor_user_id: str | None = None) -> dict:
    """Builds one stage of a job's hiring process (aptitude / technical / coding assessment, or an interview template and pool)."""
    from app.services.pipeline.stage_content import StageContentError, generate_stage

    async def work():
        try:
            return await generate_stage(uuid.UUID(job_id), stage_type, uuid.UUID(actor_user_id) if actor_user_id else None)
        except StageContentError as exc:
            raise PermanentJobError(str(exc)) from exc

    return run_async(lambda: run_tracked(f"stage:{job_id}:{stage_type}", "stage_generation", {"job_id": job_id, "stage_type": stage_type},
                                         self.request.id, work))
