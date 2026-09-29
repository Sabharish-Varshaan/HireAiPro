"""Deterministic assessment-building services. The Assessment Agent calls
these as tools; none of them decide *what* the blueprint is (that's the
blueprint engine) or whether a question is valid (that's the validator).

Idempotency: one Assessment per job (regeneration replaces its questions in
place), and every generated question carries a `generation_key` of
(job, skill, type, slot) so a retry reuses the question it already made.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessments import Assessment, AssessmentQuestion, AssessmentSection
from app.models.enums import JobStatus, QuestionSourceType, QuestionStatus as QS, QuestionType, Visibility
from app.models.jobs import Job, JobSkill
from app.models.questions import Question
from app.models.skills import Skill
from app.schemas.assessment_generation import (
    GeneratedCodingQuestion,
    GeneratedMCQ,
    GeneratedTechnicalQuestion,
)
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.ai_gateway.vector_store import TenantScope
from app.services.assessments.blueprint import Blueprint, build_blueprint
from app.services.knowledge.rag import format_context, select_refs
from app.services.knowledge.service import retrieve
from app.services.questions.governance import USABLE_OWN_COMPANY, USABLE_PLATFORM
from app.services.questions.validator import (
    ValidationResult,
    content_hash,
    index_question,
    validate_semantics,
    validate_structure,
)


class GenerationError(Exception):
    pass


async def get_confirmed_job_skills(db: AsyncSession, job_id: uuid.UUID) -> list[dict]:
    job = await db.get(Job, job_id)
    if job is None or JobStatus(job.status) not in (
        JobStatus.REQUIREMENTS_CONFIRMED, JobStatus.ASSESSMENT_READY, JobStatus.PUBLISHED,
    ):
        raise ValueError("Job requirements are not confirmed yet")
    rows = (
        await db.scalars(select(JobSkill).where(JobSkill.job_id == job_id, JobSkill.confirmed.is_(True)))
    ).all()
    out = []
    for r in rows:
        if r.skill_id is None:
            continue
        skill = await db.get(Skill, r.skill_id)
        out.append(
            {
                "skill_id": r.skill_id,
                "skill_name": skill.canonical_name if skill else r.raw_skill_name,
                "requirement_type": r.requirement_type,
                "importance": r.importance,
                "minimum_level": r.minimum_level,
            }
        )
    return out


async def search_company_questions(
    db: AsyncSession, organization_id: uuid.UUID, skill_id: uuid.UUID, qtype: QuestionType, limit: int,
    exclude: set[uuid.UUID] | None = None,
) -> list[Question]:
    stmt = (
        select(Question)
        .where(
            Question.skill_id == skill_id,
            Question.question_type == qtype,
            Question.organization_id == organization_id,
            Question.visibility == Visibility.COMPANY_PRIVATE,
            Question.status.in_([s.value for s in USABLE_OWN_COMPANY]),
            Question.source_type == QuestionSourceType.COMPANY_PRIVATE,
        )
        .order_by(Question.created_at)
    )
    rows = [q for q in (await db.scalars(stmt)).all() if q.id not in (exclude or set())
            and not (q.question_type == QuestionType.CODING and q.source_type == QuestionSourceType.AI_GENERATED
                     and not _tests_verified(q))]
    return rows[:limit]


def _tests_verified(q: Question) -> bool:
    """An AI-generated coding question is reusable only if its tests were execution-verified AND are deep enough.
    (Earlier generations shipped only 2-3 tests.)"""
    from app.services.coding.test_model import MIN_TOTAL

    ok = bool(((q.validation_report or {}).get("checks") or {}).get("tests_verified_by_execution"))
    return ok and len(q.test_cases or []) >= MIN_TOTAL


async def _reverify_coding(q: Question, job_id: uuid.UUID) -> None:
    """Coding questions generated before execution verification existed are checked
    now; a failure demotes them to DRAFT so no assessment uses their tests."""
    from app.services.questions.coding_verification import verify_test_cases

    ok, why = await verify_test_cases(q.question_text, q.test_cases or [], related_entity_id=job_id)
    report = dict(q.validation_report or {})
    report["checks"] = {**(report.get("checks") or {}), "tests_verified_by_execution": ok}
    if not ok:
        report["reasons"] = [*(report.get("reasons") or []), why]
        q.status = QS.DRAFT
    report["ok"] = ok and report.get("ok", True)
    q.validation_report = report


async def search_platform_questions(
    db: AsyncSession, skill_id: uuid.UUID, qtype: QuestionType, limit: int, exclude: set[uuid.UUID] | None = None
) -> list[Question]:
    stmt = (
        select(Question)
        .where(
            Question.skill_id == skill_id,
            Question.question_type == qtype,
            Question.visibility == Visibility.PLATFORM_PUBLIC,
            Question.status.in_([s.value for s in USABLE_PLATFORM]),
        )
        .order_by(Question.created_at)
    )
    rows = [q for q in (await db.scalars(stmt)).all() if q.id not in (exclude or set())
            and not (q.question_type == QuestionType.CODING and q.source_type == QuestionSourceType.AI_GENERATED
                     and not _tests_verified(q))]
    return rows[:limit]


def retrieve_knowledge(skill_name: str, skill_id: uuid.UUID, organization_id: uuid.UUID, qtype: QuestionType):
    query = f"{skill_name} key concepts" if qtype != QuestionType.CODING else f"{skill_name} example code"
    return retrieve(query, TenantScope(organization_id=organization_id), skill_ids=[skill_id], top_k=30, top_n=3)


GEN_SYSTEM = (
    "You write assessment questions for a hiring platform. When CONTEXT blocks are given, the question "
    "must be answerable from them; list the block numbers you relied on in used_context."
)


async def generate_missing_question(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    organization_id: uuid.UUID,
    skill_id: uuid.UUID,
    skill_name: str,
    qtype: QuestionType,
    difficulty: str,
    slot: int,
    avoid: list[str] | None = None,
    rejected_hashes: set[str] | None = None,
) -> Question:
    """Generates (or returns the previously generated) question for this slot.
    Result is VALIDATED only if every validator check passes; otherwise it is
    kept as DRAFT with the failing checks recorded.

    avoid: compact reasons earlier candidates for the same slot were rejected
    (fed to the model so a replacement fixes them, not the whole old prompt).
    rejected_hashes: content hashes of those candidates; an identical repeat is
    rejected without further validation."""
    gkey = f"{job_id}:{skill_id}:{qtype.value}:{slot}"
    existing = await db.scalar(select(Question).where(Question.generation_key == gkey))
    if existing:
        if qtype == QuestionType.CODING and not _tests_verified(existing):
            await _reverify_coding(existing, job_id)
        return existing

    docs = retrieve_knowledge(skill_name, skill_id, organization_id, qtype)
    context = f"CONTEXT:\n{format_context(docs)}\n\n" if docs else ""
    if avoid:
        context += ("A previous candidate for this slot was rejected: " + "; ".join(a[:160] for a in avoid[-3:])
                    + ". Write a DIFFERENT question that avoids these problems.\n\n")
    gateway = get_ai_gateway()
    common = dict(system=GEN_SYSTEM, task_type="question_generation", related_entity_type="job", related_entity_id=job_id)
    fields: dict = {}
    if qtype == QuestionType.MCQ:
        g = await gateway.generate_structured(
            f"{context}Write one {difficulty} multiple-choice question testing '{skill_name}'. "
            "Give 4 distinct options, exactly one correct; never use 'all/none of the above'.",
            GeneratedMCQ, **common,
        )
        fields = dict(options=g.options, correct_option_index=g.correct_option_index)
    elif qtype == QuestionType.TECHNICAL:
        g = await gateway.generate_structured(
            f"{context}Write one {difficulty} open-ended technical question testing '{skill_name}', "
            "plus 3-5 expected_concepts a strong answer covers and 3-4 rubric_criteria.",
            GeneratedTechnicalQuestion, **common,
        )
        fields = dict(expected_concepts=g.expected_concepts, rubric={"criteria": g.rubric_criteria, "version": "rubric_v1"})
    else:
        g = await gateway.generate_structured(
            f"{context}Write one {difficulty} language-neutral coding problem testing '{skill_name}' that can be solved in "
            "Python, JavaScript or C++. The program reads ONE line of stdin containing a JSON value (e.g. [1,2,3]) "
            "and prints the answer. Do NOT include starter code or any part of a solution. Give 11 to 14 test_cases as "
            '{"input": "<exact stdin text>", "expected_output": "<exact stdout text>", "visible": <true|false>, "category": "<category>"}. '
            "Exactly 2 or 3 have visible=true: simple, illustrative samples. The rest are hidden. Every test must be a DIFFERENT case; "
            "use categories such as normal, boundary_minimum, empty, single_element, maximum_size, duplicates, ordering, "
            "negative_values, all_equal, special_case, performance (only where the problem makes them meaningful). "
            "Include at least 4 distinct categories. Compute every expected_output exactly; inputs stay under 1500 characters.",
            GeneratedCodingQuestion, **common,
        )
        # LLM-written starter code is never shipped: in QA it contained the complete
        # solution (2026-09-29). Students get neutral per-language stdin templates.
        fields = dict(starter_code=None, test_cases=g.test_cases)

    refs = select_refs(docs, getattr(g, "used_context", []) or []) if docs else []
    if rejected_hashes and content_hash(g.question_text) in rejected_hashes:
        result = ValidationResult(ok=False, checks={"not_repeat_of_rejected": False},
                                  reasons=["repeat of a candidate already rejected for this slot"])
    else:
        result = validate_structure(
            qtype, g.question_text, difficulty, fields.get("expected_concepts"), fields.get("rubric"),
            fields.get("options"), fields.get("correct_option_index"), fields.get("test_cases"), strict_tests=True,
        )
    if result.ok:
        result = validate_semantics(
            result, g.question_text, skill_name, skill_id, TenantScope(organization_id=organization_id),
            context_texts=[d.text for d in docs] if docs else None,
        )
    if result.ok and qtype == QuestionType.CODING:
        from app.services.questions.coding_verification import verify_test_cases

        from app.services.questions.coding_verification import verify_and_prune

        verified, why, kept = await verify_and_prune(g.question_text, fields["test_cases"], related_entity_id=job_id)
        if kept:
            fields["test_cases"] = kept  # only tests confirmed by two independent sources are stored
        result.checks["tests_verified_by_execution"] = verified
        if not verified:
            result.reasons.append(why)
        result.ok = all(result.checks.values())

    q = Question(
        question_text=g.question_text,
        question_type=qtype,
        skill_id=skill_id,
        difficulty=difficulty,
        source_type=QuestionSourceType.AI_GENERATED,
        organization_id=organization_id,
        visibility=Visibility.COMPANY_PRIVATE,
        status=QS.VALIDATED if result.ok else QS.DRAFT,
        model_version=gateway.model,
        content_hash=content_hash(g.question_text),
        source_refs=refs,
        knowledge_source_ids=sorted({r["document_id"] for r in refs if r.get("document_id")}),
        validation_report=result.report(),
        generation_key=gkey,
        provenance="AI_GENERATED_COMPANY_PRIVATE",  # generated for this company's JD/context: private to it, never auto-shared
        **fields,
    )
    db.add(q)
    await db.flush()
    index_question(q, result.embedding)
    return q


async def get_or_create_assessment(db: AsyncSession, job_id: uuid.UUID, title: str, bp: Blueprint) -> Assessment:
    """One assessment per job. Regenerating an unpublished assessment clears
    its sections and rebuilds; a published one is never rebuilt."""
    assessment = await db.scalar(select(Assessment).where(Assessment.job_id == job_id).order_by(Assessment.created_at))
    blueprint_json = {
        "allocations": [
            {"skill_id": str(a.skill_id), "skill_name": a.skill_name, "weight": round(a.weight, 4),
             "mcq_count": a.mcq_count, "technical_count": a.technical_count, "coding_count": a.coding_count}
            for a in bp.allocations
        ],
        "total_questions": bp.total_questions,
    }
    if assessment and assessment.status == "PUBLISHED":
        raise GenerationError("Assessment is already published; it cannot be regenerated")
    if assessment is None:
        assessment = Assessment(job_id=job_id, title=title, status="DRAFT")
        db.add(assessment)
        await db.flush()
    else:
        await db.execute(delete(AssessmentQuestion).where(AssessmentQuestion.assessment_id == assessment.id))
        await db.execute(delete(AssessmentSection).where(AssessmentSection.assessment_id == assessment.id))
    assessment.title = title
    assessment.blueprint = blueprint_json
    assessment.total_duration_minutes = bp.estimated_duration_minutes
    await db.flush()
    return assessment


async def add_section(db: AsyncSession, assessment: Assessment, title: str, order: int, question_ids: list[uuid.UUID]) -> None:
    section = AssessmentSection(assessment_id=assessment.id, title=title, order_index=order)
    db.add(section)
    await db.flush()
    for i, qid in enumerate(question_ids):
        db.add(AssessmentQuestion(assessment_id=assessment.id, section_id=section.id, question_id=qid, order_index=i))
    await db.flush()


def blueprint_for(job_skills: list[dict], target_total: int | None = None) -> Blueprint:
    return build_blueprint(job_skills, target_total or 12)
