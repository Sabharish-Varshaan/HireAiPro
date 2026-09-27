"""Every worker task run twice must converge to the same rows."""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.assessments import Assessment, AssessmentQuestion
from app.models.documents import Document
from app.models.enums import EvidenceSourceType, JobStatus, Visibility
from app.models.evidence import SkillEvidence
from app.models.jobs import Job, JobSkill
from app.models.knowledge import KnowledgeChunk, KnowledgeSource
from app.models.matching import Match
from app.models.questions import Question
from app.services.ai_gateway import vector_store
from app.services.ai_gateway.vector_store import TenantScope
from app.services.knowledge import service as ks
from app.services.storage.service import get_storage_service
from app.workers.jobs import PermanentJobError
from app.workers.tasks_jobs import process_jd
from app.workers.tasks_matching import recompute_job_matches
from app.workers.tasks_questions import generate_assessment
from app.workers.tasks_resumes import process_resume
from tests.factories import make_application, make_company, make_job, make_student, skill, uniq
from tests.fakes import FakeLLM, jd_skills


async def count(model, *where):
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(model).where(*where))


@pytest.mark.asyncio
async def test_jd_processing_retry_does_not_duplicate(monkeypatch):
    FakeLLM(monkeypatch, {"ExtractedJobSkills": jd_skills(
        ("Python", "required", 0.8, 1.0), ("python3", "required", 0.7, 0.9),  # same canonical skill twice
        ("FastAPI", "required", 0.7, 0.9), ("Postgres", "required", 0.6, 0.8), ("Quantum Basket Weaving", "preferred", 0.3, 0.2))})
    async with AsyncSessionLocal() as db:
        org, rec, _ = await make_company(db)
        job = Job(organization_id=org.id, created_by_user_id=rec.id, title="BE", description_raw="jd", status=JobStatus.DRAFT)
        db.add(job)
        await db.commit()
    await process_jd(job.id)
    first = await count(JobSkill, JobSkill.job_id == job.id)
    await process_jd(job.id)
    assert await count(JobSkill, JobSkill.job_id == job.id) == first == 4  # python merged; unmapped kept for review
    assert await count(JobSkill, JobSkill.job_id == job.id, JobSkill.skill_id.is_(None)) == 1
    async with AsyncSessionLocal() as db:
        (await db.get(Job, job.id)).status = JobStatus.REQUIREMENTS_CONFIRMED
        await db.commit()
    with pytest.raises(PermanentJobError):  # confirmed requirements are never overwritten by a retry
        await process_jd(job.id)


@pytest.mark.asyncio
async def test_resume_processing_retry_does_not_duplicate_claims(monkeypatch):
    FakeLLM(monkeypatch, {"ExtractedResume": {"summary": "s", "skills": [
        {"skill_name": "Python", "evidence_text": "x", "confidence": 0.9},
        {"skill_name": "py", "evidence_text": "x", "confidence": 0.8},
        {"skill_name": "Docker", "evidence_text": "x", "confidence": 0.7}]}})
    async with AsyncSessionLocal() as db:
        st, user, _ = await make_student(db)
        key, sha, size = get_storage_service().save("r.txt", b"Python and Docker developer")
        doc = Document(owner_user_id=user.id, storage_key=key, filename="r.txt", mime_type="text/plain", size_bytes=size,
                       sha256=sha, visibility=Visibility.COMPANY_PRIVATE, doc_type="RESUME")
        db.add(doc)
        await db.commit()
    await process_resume(st.id, doc.id)
    await process_resume(st.id, doc.id)
    claims = SkillEvidence.student_id == st.id, SkillEvidence.source_type == EvidenceSourceType.RESUME_CLAIM.value
    assert await count(SkillEvidence, *claims) == 2


@pytest.mark.asyncio
async def test_knowledge_ingestion_retry_does_not_duplicate_chunks_or_points():
    async with AsyncSessionLocal() as db:
        py = await skill(db, "Python")
        src = await ks.register_source(db, title="t", source_type="INLINE_TEXT", source_uri=f"inline:{uniq('k')}",
                                       skill_ids=[py.id], visibility="PLATFORM_PUBLIC",
                                       raw_text="Python generators yield values lazily.\n\n" * 40)
        await ks.ingest_source(db, src)
        await db.commit()
        src_id, v1 = src.id, src.document_version
    n1 = await count(KnowledgeChunk, KnowledgeChunk.document_id == src_id)
    async with AsyncSessionLocal() as db:
        src = await db.get(KnowledgeSource, src_id)
        again = await ks.ingest_source(db, src)  # unchanged content → skipped
        # a second registration of the same uri is the same source
        same = await ks.register_source(db, title="t", source_type="INLINE_TEXT", source_uri=src.source_uri,
                                        skill_ids=[py.id], visibility="PLATFORM_PUBLIC", raw_text=src.raw_text)
        await db.commit()
    assert again["skipped"] and same.id == src_id
    assert await count(KnowledgeChunk, KnowledgeChunk.document_id == src_id) == n1
    pts = vector_store.search("knowledge_chunks", [0.0] * 1023 + [1.0], TenantScope(), limit=500)
    assert len([p for p in pts if p.payload["document_id"] == str(src_id)]) == n1
    async with AsyncSessionLocal() as db:
        assert (await db.get(KnowledgeSource, src_id)).document_version == v1


def _question_fakes():
    counter = {"n": 0}

    def mcq(prompt):
        counter["n"] += 1
        return {"question_text": f"Which statement about container images is correct (variant {uuid.uuid4().hex})?",
                "options": ["Images are immutable layers", "Images are running processes", "Images store volumes"],
                "correct_option_index": 0, "explanation": "x"}

    def tech(prompt):
        counter["n"] += 1
        return {"question_text": f"Explain how you would design Docker image layering for fast rebuilds ({uuid.uuid4().hex[:6]}).",
                "expected_concepts": ["layer cache", "ordering"], "rubric_criteria": ["cache", "ordering"]}

    return counter, {"GeneratedMCQ": mcq, "GeneratedTechnicalQuestion": tech}


@pytest.mark.asyncio
async def test_assessment_generation_retry_does_not_duplicate(monkeypatch):
    counter, responses = _question_fakes()
    FakeLLM(monkeypatch, responses)
    async with AsyncSessionLocal() as db:
        org, rec, _ = await make_company(db)
        job = await make_job(db, org, rec, [("Docker", "required", 0.5, 1.0)], status=JobStatus.REQUIREMENTS_CONFIRMED)
        await db.commit()
    import app.agents.assessment_agent as aa

    orig = aa.run_assessment_agent
    monkeypatch.setattr(aa, "run_assessment_agent", lambda db, job, title, actor: orig(db, job, title, actor, use_llm=False))
    plan1 = await generate_assessment(job.id, "A", None)
    calls = counter["n"]
    q1 = await count(Question, Question.generation_key.like(f"{job.id}:%"))
    plan2 = await generate_assessment(job.id, "A", None)
    assert counter["n"] == calls  # retry reused the generated questions instead of calling the LLM again
    assert await count(Question, Question.generation_key.like(f"{job.id}:%")) == q1
    assert await count(Assessment, Assessment.job_id == job.id) == 1
    assert plan1["assessment_id"] == plan2["assessment_id"]
    assert await count(AssessmentQuestion, AssessmentQuestion.assessment_id == uuid.UUID(plan2["assessment_id"])) == plan2["total_questions"]


@pytest.mark.asyncio
async def test_bulk_matching_retry_does_not_duplicate():
    async with AsyncSessionLocal() as db:
        org, rec, _ = await make_company(db)
        job = await make_job(db, org, rec, [("Python", "required", 0.5, 1.0)])
        for _ in range(3):
            st, _, _ = await make_student(db)
            await make_application(db, job, st)
        await db.commit()
    await recompute_job_matches(job.id)
    await recompute_job_matches(job.id)
    assert await count(Match, Match.job_id == job.id) == 3
