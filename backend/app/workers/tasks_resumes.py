from app.core.database import AsyncSessionLocal
from app.models.documents import Document
from app.models.enums import EvidenceSourceType
from app.models.students import StudentProfile
from app.schemas.resume import ExtractedResume
from app.services.ai_gateway.gateway import AIGatewayError, get_ai_gateway
from app.services.documents.extraction import extract_text
from app.services.evidence.service import record_evidence
from app.services.skills.normalizer import normalize_skill_name
from app.services.storage.service import get_storage_service
from app.workers.celery_app import celery_app
from app.workers.utils import run_async

RESUME_EXTRACTION_INSTRUCTION = """Extract technical skills claimed in this resume. For each
skill, give: skill_name, evidence_text (the sentence/line it came from), confidence (0-1).
Also give a 1-2 sentence summary. Only extract skills that are actually named or clearly
demonstrated (e.g. via a named project/technology), not generic soft skills."""


async def _process(student_id: str, document_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        profile = await db.get(StudentProfile, student_id)
        document = await db.get(Document, document_id)
        if profile is None or document is None:
            return {"error": "not found"}

        try:
            content = get_storage_service().read(document.storage_key)
            text = extract_text(content, document.mime_type, document.filename)

            gateway = get_ai_gateway()
            extracted = await gateway.extract_structured(
                text=text, schema=ExtractedResume, instruction=RESUME_EXTRACTION_INSTRUCTION
            )

            for item in extracted.skills:
                skill_id, _confidence = await normalize_skill_name(db, item.skill_name)
                if skill_id is None:
                    continue
                # RESUME_CLAIM evidence always normalized_score=0 contribution is
                # enforced in the estimator (BASE_WEIGHTS[RESUME_CLAIM] == 0); we
                # still store the claim itself for transparency in the UI.
                await record_evidence(
                    db,
                    student_id=profile.id,
                    skill_id=skill_id,
                    source_type=EvidenceSourceType.RESUME_CLAIM,
                    normalized_score=item.confidence,
                    source_id=document.id,
                    confidence=item.confidence,
                    model_id=gateway.model,
                    model_version=gateway.model,
                )

            profile.resume_parse_status = "READY"
            await db.commit()
            return {"skills_extracted": len(extracted.skills)}
        except AIGatewayError as exc:
            profile.resume_parse_status = "FAILED"
            await db.commit()
            return {"error": str(exc)}


@celery_app.task(name="resumes.process", bind=True, max_retries=3)
def process_resume_task(self, student_id: str, document_id: str) -> dict:
    return run_async(lambda: _process(student_id, document_id))
