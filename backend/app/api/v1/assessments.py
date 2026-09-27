import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.applications import Application
from app.models.assessments import (
    Assessment,
    AssessmentAnswer,
    AssessmentAttempt,
    AssessmentQuestion,
    AssessmentSection,
)
from app.models.enums import (
    ApplicationStatus,
    AssessmentAttemptStatus,
    EvidenceSourceType,
    JobStatus,
    QuestionType,
    UserRole,
)
from app.models.jobs import Job
from app.models.questions import Question
from app.models.students import StudentProfile
from app.models.users import User
from app.schemas.assessments import (
    AssessmentDetailOut,
    AssessmentOut,
    AssessmentQuestionOut,
    AssessmentSectionOut,
    AttemptOut,
    GenerateAssessmentRequest,
    StartAttemptRequest,
    SubmitAnswerRequest,
)
from app.schemas.rubric import RubricEvaluation
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.evidence.estimator import recalculate_all_skills_for_student
from app.services.evidence.service import record_evidence

router = APIRouter(prefix="/assessments", tags=["assessments"])

RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)


@router.post("/jobs/{job_id}/generate", response_model=AssessmentOut)
async def generate_assessment(
    job_id: uuid.UUID,
    payload: GenerateAssessmentRequest,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")

    from app.agents.assessment_agent import run_assessment_agent

    try:
        plan = await run_assessment_agent(db, job_id, job.organization_id, payload.title)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    assessment = await db.scalar(select(Assessment).where(Assessment.job_id == job_id).order_by(Assessment.created_at.desc()))
    job.status = JobStatus.ASSESSMENT_READY
    await db.commit()
    await db.refresh(assessment)
    return assessment


@router.post("/{assessment_id}/publish", response_model=AssessmentOut)
async def publish_assessment(
    assessment_id: uuid.UUID,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    assessment = await db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(404, "Assessment not found")
    assessment.status = "PUBLISHED"
    job = await db.get(Job, assessment.job_id)
    if job:
        job.status = JobStatus.PUBLISHED
    await db.commit()
    await db.refresh(assessment)
    return assessment


@router.get("/by-job/{job_id}", response_model=AssessmentOut | None)
async def get_assessment_for_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await db.scalar(
        select(Assessment).where(Assessment.job_id == job_id).order_by(Assessment.created_at.desc())
    )


@router.get("/{assessment_id}", response_model=AssessmentDetailOut)
async def get_assessment(assessment_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    assessment = await db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(404, "Assessment not found")
    sections = (
        await db.scalars(
            select(AssessmentSection)
            .where(AssessmentSection.assessment_id == assessment.id)
            .order_by(AssessmentSection.order_index)
        )
    ).all()
    section_outs = []
    for s in sections:
        aqs = (
            await db.scalars(
                select(AssessmentQuestion)
                .where(AssessmentQuestion.section_id == s.id)
                .order_by(AssessmentQuestion.order_index)
            )
        ).all()
        q_outs = []
        for aq in aqs:
            question = await db.get(Question, aq.question_id)
            q_outs.append(AssessmentQuestionOut(id=aq.id, order_index=aq.order_index, question=question))
        section_outs.append(
            AssessmentSectionOut(id=s.id, title=s.title, order_index=s.order_index, questions=q_outs)
        )
    out = AssessmentDetailOut.model_validate(assessment)
    out.sections = section_outs
    return out


@router.post("/{assessment_id}/attempts", response_model=AttemptOut)
async def start_attempt(
    assessment_id: uuid.UUID,
    payload: StartAttemptRequest,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    application = await db.get(Application, payload.application_id)
    if profile is None or application is None or application.student_id != profile.id:
        raise HTTPException(403, "Not your application")

    existing = await db.scalar(
        select(AssessmentAttempt).where(
            AssessmentAttempt.assessment_id == assessment_id,
            AssessmentAttempt.application_id == application.id,
        )
    )
    if existing:
        return existing

    attempt = AssessmentAttempt(
        assessment_id=assessment_id,
        application_id=application.id,
        student_id=profile.id,
        status=AssessmentAttemptStatus.IN_PROGRESS,
    )
    db.add(attempt)
    application.status = ApplicationStatus.ASSESSMENT_PENDING
    await db.commit()
    await db.refresh(attempt)
    return attempt


@router.put("/attempts/{attempt_id}/answers")
async def autosave_answer(
    attempt_id: uuid.UUID,
    payload: SubmitAnswerRequest,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    attempt = await db.get(AssessmentAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(404, "Attempt not found")

    answer = await db.scalar(
        select(AssessmentAnswer).where(
            AssessmentAnswer.attempt_id == attempt_id,
            AssessmentAnswer.assessment_question_id == payload.assessment_question_id,
        )
    )
    if answer is None:
        answer = AssessmentAnswer(
            attempt_id=attempt_id, assessment_question_id=payload.assessment_question_id
        )
        db.add(answer)
    answer.answer_text = payload.answer_text
    answer.selected_option_index = payload.selected_option_index
    await db.commit()
    return {"status": "saved"}


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptOut)
async def submit_attempt(
    attempt_id: uuid.UUID,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    attempt = await db.get(AssessmentAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(404, "Attempt not found")

    answers = (
        await db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt_id))
    ).all()

    gateway = get_ai_gateway()
    total_points = 0.0
    earned_points = 0.0

    for answer in answers:
        aq = await db.get(AssessmentQuestion, answer.assessment_question_id)
        question = await db.get(Question, aq.question_id)
        total_points += aq.points

        if question.question_type == QuestionType.MCQ:
            is_correct = answer.selected_option_index == question.correct_option_index
            answer.is_correct = is_correct
            answer.score = aq.points if is_correct else 0.0
            earned_points += answer.score
            await record_evidence(
                db,
                student_id=attempt.student_id,
                skill_id=question.skill_id,
                source_type=EvidenceSourceType.MCQ,
                normalized_score=1.0 if is_correct else 0.0,
                source_id=answer.id,
                difficulty=question.difficulty,
                confidence=0.6,
            )
        elif question.question_type == QuestionType.TECHNICAL:
            if answer.answer_text:
                evaluation: RubricEvaluation = await gateway.evaluate_rubric(
                    answer.answer_text, question.rubric or {}, RubricEvaluation
                )
                answer.rubric_evaluation = evaluation.model_dump()
                answer.score = evaluation.overall_score * aq.points
                earned_points += answer.score
                await record_evidence(
                    db,
                    student_id=attempt.student_id,
                    skill_id=question.skill_id,
                    source_type=EvidenceSourceType.TECHNICAL_ASSESSMENT,
                    normalized_score=evaluation.overall_score,
                    source_id=answer.id,
                    difficulty=question.difficulty,
                    confidence=evaluation.evaluator_confidence,
                    model_id=gateway.model,
                    rubric_version="rubric_v1",
                )
            else:
                answer.score = 0.0
        # CODING is scored separately via /coding submissions -> Judge0

    attempt.total_score = earned_points / total_points if total_points else 0.0
    attempt.status = AssessmentAttemptStatus.SCORED

    application = await db.get(Application, attempt.application_id)
    if application:
        application.status = ApplicationStatus.ASSESSMENT_COMPLETED

    await db.commit()
    await recalculate_all_skills_for_student(db, attempt.student_id)
    await db.refresh(attempt)
    return attempt
