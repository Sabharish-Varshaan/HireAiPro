import uuid

from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.documents import Document
from app.models.enums import EvidenceSourceType
from app.models.evidence import SkillEvidence
from app.models.students import StudentProfile
from app.schemas.resume import ExtractedResume
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.documents.extraction import extract_text
from app.services.evidence.service import evidence_key, record_evidence
from app.services.notifications import notify
from app.services.skills.normalizer import normalize_skill_name
from app.services.storage.service import get_storage_service
from app.workers.celery_app import celery_app
from app.workers.jobs import TRANSIENT, PermanentJobError, run_tracked
from app.workers.utils import run_async

RESUME_EXTRACTION_INSTRUCTION = """Extract technical skills claimed in this resume. For each
skill, give: skill_name, evidence_text (the sentence/line it came from), confidence (0-1).
Also give a 1-2 sentence summary. Only extract skills that are actually named or clearly
demonstrated (e.g. via a named project/technology), not generic soft skills."""


async def process_resume(student_id: uuid.UUID, document_id: uuid.UUID) -> dict:
    """Idempotent: one RESUME_CLAIM row per (document, skill). Claims from an
    older resume are soft-deleted so only the current resume's claims show."""
    async with AsyncSessionLocal() as db:
        profile = await db.get(StudentProfile, student_id)
        document = await db.get(Document, document_id)
        if profile is None or document is None:
            raise PermanentJobError("student or document not found")
        profile.resume_parse_status = "PROCESSING"
        await db.commit()
        try:
            text = extract_text(get_storage_service().read(document.storage_key), document.mime_type, document.filename)
            if not text.strip():
                raise PermanentJobError("no extractable text in resume")
            gateway = get_ai_gateway()
            extracted = await gateway.extract_structured(
                text=text, schema=ExtractedResume, instruction=RESUME_EXTRACTION_INSTRUCTION,
                task_type="resume_extraction", related_entity_type="document", related_entity_id=document.id,
            )
        except Exception:
            profile.resume_parse_status = "FAILED"
            await db.commit()
            raise

        stored = set()
        for item in extracted.skills:
            skill_id, _ = await normalize_skill_name(db, item.skill_name)
            if skill_id is None or skill_id in stored:
                continue
            stored.add(skill_id)
            await record_evidence(
                db, student_id=profile.id, skill_id=skill_id, source_type=EvidenceSourceType.RESUME_CLAIM,
                normalized_score=item.confidence, source_id=document.id, confidence=item.confidence,
                model_id=gateway.model, prompt_version="resume_extraction_v1",
                idempotency_key=evidence_key(EvidenceSourceType.RESUME_CLAIM, document.id, skill_id),
            )
        await db.execute(
            update(SkillEvidence)
            .where(SkillEvidence.student_id == profile.id, SkillEvidence.source_type == EvidenceSourceType.RESUME_CLAIM.value,
                   SkillEvidence.source_id != document.id)
            .values(is_deleted=True)
        )
        profile.resume_parse_status = "READY"
        await notify(db, profile.user_id, "resume_parsed", "Resume processed",
                     body=f"{len(stored)} claimed skills found. Claims are unverified until assessed.",
                     link="/student/profile", dedupe_key=f"resume:{document.id}")
        await db.commit()
        return {"claims": len(stored)}


@celery_app.task(name="resumes.process", bind=True, autoretry_for=TRANSIENT, retry_backoff=10, max_retries=3)
def process_resume_task(self, student_id: str, document_id: str) -> dict:
    return run_async(lambda: run_tracked(
        f"resume:{document_id}", "resume_processing", {"student_id": student_id, "document_id": document_id},
        self.request.id, lambda: process_resume(uuid.UUID(student_id), uuid.UUID(document_id)),
    ))
