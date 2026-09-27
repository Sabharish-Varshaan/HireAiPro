import time

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.enums import JobStatus, ProcessingStatus, RequirementType
from app.models.jobs import Job, JobSkill
from app.models.misc import AIRun
from app.schemas.jobs import ExtractedJobSkills
from app.services.ai_gateway.gateway import AIGatewayError, get_ai_gateway
from app.services.skills.normalizer import normalize_skill_name
from app.workers.celery_app import celery_app
from app.workers.utils import run_async

JD_EXTRACTION_INSTRUCTION = """You are analyzing a job description to extract required and
preferred technical competencies. For each distinct skill/technology/competency mentioned or
clearly implied, output an entry with:
- raw_skill_name: the skill as named in the JD
- requirement_type: "required" or "preferred"
- minimum_level: a 0.0-1.0 proficiency bar implied by the JD wording (junior mention ~0.3,
  "strong"/"expert" ~0.8)
- importance: 0.0-1.0 relative importance of this skill to the role
- evidence_text: the exact phrase from the JD that justifies this
- extraction_confidence: 0.0-1.0 how confident you are this is a real distinct skill
Do not invent skills that are not supported by the text. Return 5-20 skills."""


async def _process(job_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None:
            return {"error": "job not found"}

        gateway = get_ai_gateway()
        run = AIRun(
            task_type="jd_extraction",
            provider=gateway.provider,
            model=gateway.model,
            status=ProcessingStatus.RUNNING,
            related_entity_type="job",
            related_entity_id=job.id,
        )
        db.add(run)
        await db.flush()

        started = time.monotonic()
        try:
            extracted = await gateway.extract_structured(
                text=job.description_raw or "",
                schema=ExtractedJobSkills,
                instruction=JD_EXTRACTION_INSTRUCTION,
            )
            run.status = ProcessingStatus.COMPLETED
            run.schema_valid = True
        except AIGatewayError as exc:
            run.status = ProcessingStatus.FAILED
            run.error = str(exc)
            run.schema_valid = False
            await db.commit()
            return {"error": str(exc)}
        finally:
            run.latency_ms = (time.monotonic() - started) * 1000

        # idempotency: clear any prior unconfirmed extraction before inserting
        existing = (
            await db.scalars(
                select(JobSkill).where(JobSkill.job_id == job.id, JobSkill.confirmed.is_(False))
            )
        ).all()
        for row in existing:
            await db.delete(row)
        await db.flush()

        for item in extracted.skills:
            skill_id, confidence = await normalize_skill_name(db, item.raw_skill_name)
            db.add(
                JobSkill(
                    job_id=job.id,
                    skill_id=skill_id,
                    raw_skill_name=item.raw_skill_name,
                    requirement_type=RequirementType(item.requirement_type),
                    minimum_level=item.minimum_level,
                    importance=item.importance,
                    evidence_text=item.evidence_text,
                    extraction_confidence=min(item.extraction_confidence, confidence or item.extraction_confidence),
                    confirmed=False,
                )
            )

        job.status = JobStatus.SKILLS_EXTRACTED
        await db.commit()
        return {"job_id": str(job.id), "skills_extracted": len(extracted.skills)}


@celery_app.task(name="jobs.process_jd", bind=True, max_retries=3)
def process_jd_task(self, job_id: str) -> dict:
    return run_async(lambda: _process(job_id))
