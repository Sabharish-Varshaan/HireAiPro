import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    JobStatus,
    QuestionSourceType,
    QuestionStatus,
    QuestionType,
    Visibility,
)
from app.models.jobs import Job, JobSkill
from app.models.questions import Question
from app.models.skills import Skill
from app.schemas.assessment_generation import (
    GeneratedCodingQuestion,
    GeneratedMCQ,
    GeneratedTechnicalQuestion,
)
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.assessments.blueprint import build_blueprint

QUESTIONS_PER_SKILL_TYPE = 2


async def get_confirmed_job_skills(db: AsyncSession, job_id: uuid.UUID) -> list[dict]:
    job = await db.get(Job, job_id)
    if job is None or job.status not in (
        JobStatus.REQUIREMENTS_CONFIRMED,
        JobStatus.ASSESSMENT_READY,
        JobStatus.PUBLISHED,
    ):
        raise ValueError("Job requirements are not confirmed yet")

    rows = (
        await db.scalars(
            select(JobSkill).where(JobSkill.job_id == job_id, JobSkill.confirmed.is_(True))
        )
    ).all()

    out = []
    for r in rows:
        skill = await db.get(Skill, r.skill_id) if r.skill_id else None
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


async def search_existing_questions(
    db: AsyncSession,
    skill_id: uuid.UUID,
    question_type: QuestionType,
    organization_id: uuid.UUID | None,
    limit: int = QUESTIONS_PER_SKILL_TYPE,
) -> list[Question]:
    """Company-private questions first, then platform questions — never another
    organization's private bank."""
    company: list[Question] = []
    if organization_id:
        company = (
            await db.scalars(
                select(Question)
                .where(
                    Question.skill_id == skill_id,
                    Question.question_type == question_type,
                    Question.organization_id == organization_id,
                    Question.status.in_([QuestionStatus.APPROVED, QuestionStatus.ACTIVE, QuestionStatus.VALIDATED]),
                )
                .limit(limit)
            )
        ).all()
    if len(company) >= limit:
        return company[:limit]

    platform = (
        await db.scalars(
            select(Question)
            .where(
                Question.skill_id == skill_id,
                Question.question_type == question_type,
                Question.visibility == Visibility.PLATFORM_PUBLIC,
                Question.status.in_([QuestionStatus.APPROVED, QuestionStatus.ACTIVE]),
            )
            .limit(limit - len(company))
        )
    ).all()
    return company + platform


def validate_question_payload(
    question_type: QuestionType,
    expected_concepts: list[str] | None,
    rubric: dict | None,
    options: list | None,
    correct_option_index: int | None,
    test_cases: list | None,
) -> tuple[bool, list[str]]:
    reasons = []
    if question_type == QuestionType.MCQ:
        if not options or len(options) < 3:
            reasons.append("MCQ requires at least 3 options")
        if correct_option_index is None or (options and not (0 <= correct_option_index < len(options))):
            reasons.append("MCQ correct_option_index out of range")
    elif question_type == QuestionType.TECHNICAL:
        if not expected_concepts:
            reasons.append("Technical question missing expected_concepts")
        if not rubric:
            reasons.append("Technical question missing rubric")
    elif question_type == QuestionType.CODING:
        if not test_cases or len(test_cases) < 2:
            reasons.append("Coding question requires at least 2 test cases")
    return len(reasons) == 0, reasons


async def generate_missing_question(
    db: AsyncSession,
    skill_name: str,
    question_type: QuestionType,
    difficulty: str,
    skill_id: uuid.UUID,
) -> Question:
    gateway = get_ai_gateway()

    if question_type == QuestionType.MCQ:
        gen = await gateway.generate_structured(
            f"Write one {difficulty}-difficulty multiple-choice question testing '{skill_name}'.",
            GeneratedMCQ,
        )
        ok, reasons = validate_question_payload(
            question_type, None, None, gen.options, gen.correct_option_index, None
        )
        status = QuestionStatus.VALIDATED if ok else QuestionStatus.DRAFT
        q = Question(
            question_text=gen.question_text,
            question_type=question_type,
            skill_id=skill_id,
            difficulty=difficulty,
            options=gen.options,
            correct_option_index=gen.correct_option_index,
            source_type=QuestionSourceType.AI_GENERATED,
            visibility=Visibility.COMPANY_PRIVATE,
            status=status,
            model_version=gateway.model,
        )
    elif question_type == QuestionType.TECHNICAL:
        gen = await gateway.generate_structured(
            f"Write one {difficulty}-difficulty open-ended technical interview question testing "
            f"'{skill_name}'. Provide expected_concepts a strong answer must cover and rubric_criteria.",
            GeneratedTechnicalQuestion,
        )
        rubric = {"criteria": gen.rubric_criteria}
        ok, reasons = validate_question_payload(
            question_type, gen.expected_concepts, rubric, None, None, None
        )
        status = QuestionStatus.VALIDATED if ok else QuestionStatus.DRAFT
        q = Question(
            question_text=gen.question_text,
            question_type=question_type,
            skill_id=skill_id,
            difficulty=difficulty,
            expected_concepts=gen.expected_concepts,
            rubric=rubric,
            source_type=QuestionSourceType.AI_GENERATED,
            visibility=Visibility.COMPANY_PRIVATE,
            status=status,
            model_version=gateway.model,
        )
    else:  # CODING
        gen = await gateway.generate_structured(
            f"Write one {difficulty}-difficulty coding problem testing '{skill_name}' solvable in "
            "Python. Provide starter_code (a function stub) and test_cases as a list of "
            '{"input": ..., "expected_output": ...} objects.',
            GeneratedCodingQuestion,
        )
        ok, reasons = validate_question_payload(
            question_type, None, None, None, None, gen.test_cases
        )
        status = QuestionStatus.VALIDATED if ok else QuestionStatus.DRAFT
        q = Question(
            question_text=gen.question_text,
            question_type=question_type,
            skill_id=skill_id,
            difficulty=difficulty,
            starter_code=gen.starter_code,
            test_cases=gen.test_cases,
            source_type=QuestionSourceType.AI_GENERATED,
            visibility=Visibility.COMPANY_PRIVATE,
            status=status,
            model_version=gateway.model,
        )

    db.add(q)
    await db.flush()
    return q


async def build_assessment_for_job(
    db: AsyncSession, job_id: uuid.UUID, organization_id: uuid.UUID, title: str
):
    from app.models.assessments import Assessment, AssessmentQuestion, AssessmentSection

    job_skills = await get_confirmed_job_skills(db, job_id)
    job_skills_with_id = [s for s in job_skills if s["skill_id"] is not None]

    bp = build_blueprint(job_skills_with_id)

    assessment = Assessment(
        job_id=job_id,
        title=title,
        status="DRAFT",
        total_duration_minutes=bp.estimated_duration_minutes,
        blueprint={
            "allocations": [
                {
                    "skill_id": str(a.skill_id),
                    "skill_name": a.skill_name,
                    "mcq_count": a.mcq_count,
                    "technical_count": a.technical_count,
                    "coding_count": a.coding_count,
                }
                for a in bp.allocations
            ]
        },
    )
    db.add(assessment)
    await db.flush()

    covered_skills: list[uuid.UUID] = []
    missing_coverage: list[uuid.UUID] = []
    order_index = 0

    for alloc in bp.allocations:
        section = AssessmentSection(
            assessment_id=assessment.id, title=alloc.skill_name, order_index=order_index
        )
        db.add(section)
        await db.flush()
        order_index += 1

        wanted: list[tuple[QuestionType, int]] = [
            (QuestionType.MCQ, alloc.mcq_count),
            (QuestionType.TECHNICAL, alloc.technical_count),
            (QuestionType.CODING, alloc.coding_count),
        ]
        section_had_question = False
        q_order = 0
        for qtype, count in wanted:
            if count <= 0:
                continue
            existing = await search_existing_questions(db, alloc.skill_id, qtype, organization_id, count)
            questions = list(existing)
            while len(questions) < count:
                new_q = await generate_missing_question(
                    db, alloc.skill_name, qtype, "medium", alloc.skill_id
                )
                questions.append(new_q)

            for q in questions[:count]:
                db.add(
                    AssessmentQuestion(
                        assessment_id=assessment.id,
                        section_id=section.id,
                        question_id=q.id,
                        order_index=q_order,
                    )
                )
                q_order += 1
                section_had_question = True

        if section_had_question:
            covered_skills.append(alloc.skill_id)
        else:
            missing_coverage.append(alloc.skill_id)

    await db.commit()
    await db.refresh(assessment)
    return assessment, covered_skills, missing_coverage
