import uuid

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.enums import JobStatus, RequirementType
from app.models.jobs import Job, JobSkill
from app.schemas.jobs import ExtractedJobSkills
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.audit import audit
from app.services.skills.normalizer import normalize_skill_name
from app.workers.celery_app import celery_app
from app.workers.jobs import TRANSIENT, PermanentJobError, run_tracked
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


async def process_jd(job_id: uuid.UUID) -> dict:
    """Idempotent: replaces this job's *unconfirmed* suggestions; refuses to
    touch a job whose requirements a recruiter already confirmed."""
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None:
            raise PermanentJobError("job not found")
        if JobStatus(job.status) not in (JobStatus.DRAFT, JobStatus.SKILLS_EXTRACTED):
            raise PermanentJobError(f"job is {job.status}; confirmed requirements are never overwritten")
        if not (job.description_raw or "").strip():
            raise PermanentJobError("job has no JD text")

        extracted = await get_ai_gateway().extract_structured(
            text=job.description_raw, schema=ExtractedJobSkills, instruction=JD_EXTRACTION_INSTRUCTION,
            task_type="jd_extraction", related_entity_type="job", related_entity_id=job.id,
        )

        await db.execute(delete(JobSkill).where(JobSkill.job_id == job.id, JobSkill.confirmed.is_(False)))
        merged: dict[str, JobSkill] = {}
        for item in extracted.skills:
            skill_id, norm_conf = await normalize_skill_name(db, item.raw_skill_name)
            key = str(skill_id) if skill_id else f"raw:{item.raw_skill_name.strip().lower()}"
            prev = merged.get(key)
            if prev is not None:  # the model listed the same canonical skill twice
                prev.importance = max(prev.importance, item.importance)
                prev.minimum_level = max(prev.minimum_level, item.minimum_level)
                if item.requirement_type == "required":
                    prev.requirement_type = RequirementType.REQUIRED
                continue
            merged[key] = JobSkill(
                job_id=job.id, skill_id=skill_id, raw_skill_name=item.raw_skill_name,
                requirement_type=RequirementType(item.requirement_type), minimum_level=item.minimum_level,
                importance=item.importance, evidence_text=item.evidence_text,
                extraction_confidence=min(item.extraction_confidence, norm_conf if skill_id else item.extraction_confidence),
                confirmed=False,
            )
        db.add_all(merged.values())
        job.status = JobStatus.SKILLS_EXTRACTED
        await audit(db, None, "job_skills_extracted", "job", job.id, organization_id=job.organization_id,
                    metadata={"extracted": len(extracted.skills), "stored": len(merged),
                              "unmapped": sum(1 for s in merged.values() if s.skill_id is None)})
        await db.commit()
        return {"job_id": str(job.id), "skills_extracted": len(merged)}


@celery_app.task(name="jobs.process_jd", bind=True, autoretry_for=TRANSIENT, retry_backoff=10, max_retries=3)
def process_jd_task(self, job_id: str) -> dict:
    return run_async(lambda: run_tracked(f"jd:{job_id}", "jd_processing", {"job_id": job_id}, self.request.id,
                                         lambda: process_jd(uuid.UUID(job_id))))
