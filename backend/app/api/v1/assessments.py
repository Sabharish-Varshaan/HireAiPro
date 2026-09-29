import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.tenancy import get_job_for_member, get_student_profile, member_org_ids
from app.core.database import get_db
from app.models.applications import Application
from app.models.coding import CodingSubmission
from app.models.evidence import SkillEvidence
from app.models.assessments import Assessment, AssessmentAnswer, AssessmentAttempt, AssessmentQuestion, AssessmentSection
from app.models.enums import QuestionSourceType, ApplicationStatus, AssessmentAttemptStatus, EvidenceSourceType, JobStatus, QuestionType, UserRole
from app.models.jobs import Job
from app.models.questions import Question
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
from app.schemas.questions import QuestionOut, QuestionStudentOut
from app.schemas.rubric import RubricEvaluation
from app.services.ai_gateway.gateway import AIGatewayError, get_ai_gateway
from app.services.applications.service import transition_application
from app.services.audit import audit
from app.services.evidence.estimator import recalculate_all_skills_for_student
from app.services.evidence.service import record_evidence
from app.workers.jobs import upsert_job

router = APIRouter(prefix="/assessments", tags=["assessments"])

RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)


async def _assessment_access(db: AsyncSession, user: User, assessment: Assessment | None) -> tuple[Assessment, bool]:
    """Returns (assessment, is_recruiter_view). Students only see a published
    assessment for a job they applied to, and never the answer key."""
    if assessment is None:
        raise HTTPException(404, "Assessment not found")
    job = await db.get(Job, assessment.job_id)
    if user.role == UserRole.PLATFORM_ADMIN or job.organization_id in await member_org_ids(db, user):
        return assessment, True
    if user.role == UserRole.STUDENT and assessment.status == "PUBLISHED":
        me = await get_student_profile(db, user)
        applied = me and await db.scalar(
            select(Application.id).where(Application.job_id == job.id, Application.student_id == me.id)
        )
        if applied:
            return assessment, False
    raise HTTPException(404, "Assessment not found")


@router.post("/jobs/{job_id}/generate", status_code=202)
async def generate_assessment(
    job_id: uuid.UUID, payload: GenerateAssessmentRequest,
    user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db),
):
    """Runs the Assessment Agent in the background (it can take minutes on a
    local model). Poll GET /jobs/{id}/processing for status."""
    job = await get_job_for_member(db, user, job_id)
    if JobStatus(job.status) not in (JobStatus.REQUIREMENTS_CONFIRMED, JobStatus.ASSESSMENT_READY):
        raise HTTPException(409, "Confirm the job requirements before generating an assessment")
    from app.workers.tasks_questions import generate_assessment_task

    await upsert_job(f"assessment:{job.id}", "assessment_generation", {"job_id": str(job.id), "title": payload.title})
    generate_assessment_task.delay(str(job.id), payload.title, str(user.id))
    return {"status": "PROCESSING", "job_key": f"assessment:{job.id}"}


@router.post("/{assessment_id}/publish", response_model=AssessmentOut)
async def publish_assessment(assessment_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)),
                             db: AsyncSession = Depends(get_db)):
    assessment = await db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(404, "Assessment not found")
    job = await get_job_for_member(db, user, assessment.job_id)
    n = len((await db.scalars(select(AssessmentQuestion.id).where(AssessmentQuestion.assessment_id == assessment.id))).all())
    if n == 0:
        raise HTTPException(409, "Assessment has no questions")
    assessment.status = "PUBLISHED"
    job.status = JobStatus.PUBLISHED
    await audit(db, user, "assessment_published", "assessment", assessment.id, organization_id=job.organization_id,
                metadata={"questions": n})
    await db.commit()
    await db.refresh(assessment)
    return assessment


@router.get("/by-job/{job_id}", response_model=AssessmentOut | None)
async def get_assessment_for_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    a = await db.scalar(select(Assessment).where(Assessment.job_id == job_id).order_by(Assessment.created_at))
    if a is None:
        return None
    try:
        await _assessment_access(db, user, a)
    except HTTPException:
        return None
    return a


@router.get("/{assessment_id}", response_model=AssessmentDetailOut)
async def get_assessment(assessment_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    assessment, recruiter_view = await _assessment_access(db, user, await db.get(Assessment, assessment_id))
    sections = (await db.scalars(select(AssessmentSection).where(AssessmentSection.assessment_id == assessment.id)
                                 .order_by(AssessmentSection.order_index))).all()
    section_outs = []
    for s in sections:
        aqs = (await db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.section_id == s.id)
                                .order_by(AssessmentQuestion.order_index))).all()
        items = []
        for aq in aqs:
            q = await db.get(Question, aq.question_id)
            view = QuestionOut.model_validate(q) if recruiter_view else QuestionStudentOut.model_validate(q)
            if not recruiter_view and QuestionSourceType(q.source_type) == QuestionSourceType.AI_GENERATED:
                view.starter_code = None  # generated starters may contain the solution; never show them
            items.append(AssessmentQuestionOut(id=aq.id, order_index=aq.order_index, question=view))
        section_outs.append(AssessmentSectionOut(id=s.id, title=s.title, order_index=s.order_index, questions=items))
    out = AssessmentDetailOut.model_validate(assessment)
    out.sections = section_outs
    out.plan = assessment.plan if recruiter_view else None
    return out


@router.post("/{assessment_id}/attempts", response_model=AttemptOut)
async def start_attempt(assessment_id: uuid.UUID, payload: StartAttemptRequest,
                        user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    assessment, _ = await _assessment_access(db, user, await db.get(Assessment, assessment_id))
    profile = await get_student_profile(db, user)
    application = await db.get(Application, payload.application_id)
    if profile is None or application is None or application.student_id != profile.id or application.job_id != assessment.job_id:
        raise HTTPException(403, "Not your application for this assessment")
    existing = await db.scalar(select(AssessmentAttempt).where(
        AssessmentAttempt.assessment_id == assessment_id, AssessmentAttempt.application_id == application.id))
    if existing:
        return existing
    attempt = AssessmentAttempt(assessment_id=assessment_id, application_id=application.id, student_id=profile.id,
                                status=AssessmentAttemptStatus.IN_PROGRESS)
    db.add(attempt)
    if ApplicationStatus(application.status) == ApplicationStatus.APPLIED:
        await transition_application(db, application, ApplicationStatus.ASSESSMENT_PENDING, user.id, "assessment started")
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def _own_attempt(db, user, attempt_id) -> AssessmentAttempt:
    attempt = await db.get(AssessmentAttempt, attempt_id)
    me = await get_student_profile(db, user)
    if attempt is None or me is None or attempt.student_id != me.id:
        raise HTTPException(404, "Attempt not found")
    return attempt


@router.get("/attempts/{attempt_id}")
async def get_attempt(attempt_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)),
                      db: AsyncSession = Depends(get_db)):
    attempt = await _own_attempt(db, user, attempt_id)
    answers = (await db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt.id))).all()
    return {
        "attempt": AttemptOut.model_validate(attempt),
        "answers": [{"id": a.id, "assessment_question_id": a.assessment_question_id, "answer_text": a.answer_text,
                     "selected_option_index": a.selected_option_index, "score": a.score} for a in answers],
    }


@router.put("/attempts/{attempt_id}/answers")
async def autosave_answer(attempt_id: uuid.UUID, payload: SubmitAnswerRequest,
                          user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    attempt = await _own_attempt(db, user, attempt_id)
    # Serialize upserts per attempt: two simultaneous saves for the same question
    # (e.g. autosave + "Run tests") used to both insert, creating duplicate answers.
    await db.execute(select(AssessmentAttempt.id).where(AssessmentAttempt.id == attempt.id).with_for_update())
    if attempt.status != AssessmentAttemptStatus.IN_PROGRESS:
        raise HTTPException(409, "Attempt already submitted")
    aq = await db.get(AssessmentQuestion, payload.assessment_question_id)
    if aq is None or aq.assessment_id != attempt.assessment_id:
        raise HTTPException(404, "Question not in this assessment")
    answer = await db.scalar(select(AssessmentAnswer).where(
        AssessmentAnswer.attempt_id == attempt_id, AssessmentAnswer.assessment_question_id == aq.id))
    if answer is None:
        answer = AssessmentAnswer(attempt_id=attempt_id, assessment_question_id=aq.id)
        db.add(answer)
    if payload.answer_text is not None:
        answer.answer_text = payload.answer_text
    if payload.selected_option_index is not None:
        answer.selected_option_index = payload.selected_option_index
    await db.commit()
    return {"status": "saved", "answer_id": answer.id}


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptOut)
async def submit_attempt(attempt_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)),
                         db: AsyncSession = Depends(get_db)):
    """Idempotent: re-submitting a scored attempt returns it unchanged; evidence
    rows are keyed per answer so nothing is double-counted."""
    attempt = await _own_attempt(db, user, attempt_id)
    if attempt.status == AssessmentAttemptStatus.SCORED:
        return attempt

    gateway = get_ai_gateway()
    all_aqs = (await db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.assessment_id == attempt.assessment_id))).all()
    all_answers = (await db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt_id)
                                    .order_by(AssessmentAnswer.updated_at))).all()
    answers, dup_answers = {}, {}
    for a in all_answers:  # legacy duplicates (pre-lock race): keep the most recently updated
        if a.assessment_question_id in answers:
            dup_answers.setdefault(a.assessment_question_id, []).append(answers[a.assessment_question_id])
        answers[a.assessment_question_id] = a
    total_points = earned = 0.0
    for aq in all_aqs:
        question = await db.get(Question, aq.question_id)
        answer = answers.get(aq.id)
        total_points += aq.points
        if answer is None:
            answer = AssessmentAnswer(attempt_id=attempt.id, assessment_question_id=aq.id, score=0.0)
            db.add(answer)
            await db.flush()
        qtype = QuestionType(question.question_type)
        if qtype == QuestionType.MCQ:
            correct = answer.selected_option_index is not None and answer.selected_option_index == question.correct_option_index
            answer.is_correct = correct
            answer.score = aq.points if correct else 0.0
            await record_evidence(db, attempt.student_id, question.skill_id, EvidenceSourceType.MCQ, 1.0 if correct else 0.0,
                                  source_id=answer.id, difficulty=question.difficulty, confidence=0.6, raw_score=answer.score,
                                  rubric_version="mcq_exact_match")
        elif qtype == QuestionType.TECHNICAL:
            if (answer.answer_text or "").strip():
                try:
                    ev: RubricEvaluation = await gateway.evaluate_rubric(
                        answer.answer_text,
                        {"question": question.question_text, "expected_concepts": question.expected_concepts or [],
                         **(question.rubric or {})},
                        RubricEvaluation, related_entity_type="assessment_answer", related_entity_id=answer.id,
                    )
                except AIGatewayError as exc:
                    raise HTTPException(503, f"Rubric evaluation is unavailable right now; your answers are saved. ({exc})")
                answer.rubric_evaluation = ev.model_dump()
                answer.score = ev.overall_score * aq.points
                norm, conf = ev.overall_score, ev.evaluator_confidence
            else:
                answer.score, norm, conf = 0.0, 0.0, 0.7
            await record_evidence(db, attempt.student_id, question.skill_id, EvidenceSourceType.TECHNICAL_ASSESSMENT, norm,
                                  source_id=answer.id, difficulty=question.difficulty, confidence=conf, model_id=gateway.model,
                                  prompt_version="rubric_eval_v1", rubric_version=(question.rubric or {}).get("version", "rubric_v1"))
        else:
            # CODING: score comes only from the latest Judge0 submission (POST /coding/submit),
            # across any duplicate answer rows; superseded coding evidence is retired.
            same_q = [answer, *dup_answers.get(aq.id, [])]
            latest = await db.scalar(select(CodingSubmission).where(
                CodingSubmission.assessment_answer_id.in_([a.id for a in same_q]), CodingSubmission.status == "COMPLETED")
                .order_by(CodingSubmission.created_at.desc()))
            if latest is not None:
                answer.score = (latest.score or 0.0) * aq.points
                answer.answer_text = latest.source_code
                stale = (await db.scalars(select(SkillEvidence).where(
                    SkillEvidence.student_id == attempt.student_id, SkillEvidence.source_type == EvidenceSourceType.CODING,
                    SkillEvidence.source_id.in_(select(CodingSubmission.id).where(
                        CodingSubmission.assessment_answer_id.in_([a.id for a in same_q]))),
                    SkillEvidence.source_id != latest.id, SkillEvidence.is_deleted.is_(False)))).all()
                for ev_row in stale:
                    ev_row.is_deleted = True
            if answer.score is None:
                answer.score = 0.0
                await record_evidence(db, attempt.student_id, question.skill_id, EvidenceSourceType.CODING, 0.0,
                                      source_id=answer.id, difficulty=question.difficulty, confidence=0.9,
                                      rubric_version="judge0_tests", idempotency_key=f"CODING:answer:{answer.id}")
        earned += answer.score or 0.0

    attempt.total_score = earned / total_points if total_points else 0.0
    attempt.status = AssessmentAttemptStatus.SCORED
    application = await db.get(Application, attempt.application_id)
    job = await db.get(Job, application.job_id)
    if ApplicationStatus(application.status) == ApplicationStatus.ASSESSMENT_PENDING:
        await transition_application(db, application, ApplicationStatus.ASSESSMENT_COMPLETED, user.id, "assessment submitted")
    await audit(db, user, "assessment_submitted", "assessment_attempt", attempt.id, organization_id=job.organization_id,
                metadata={"total_score": round(attempt.total_score, 4)})
    await db.commit()
    await recalculate_all_skills_for_student(db, attempt.student_id, user.id, "assessment_submitted")
    await db.refresh(attempt)
    return attempt


@router.get("/attempts/by-application/{application_id}")
async def attempt_for_application(application_id: uuid.UUID, user: User = Depends(get_current_user),
                                  db: AsyncSession = Depends(get_db)):
    """Student: their own attempt (to resume after refresh; no answer keys).
    Recruiter of the job's company: scored answers incl. rubric evaluations."""
    from app.api.tenancy import assert_can_view_student
    from app.models.coding import CodingSubmission, CodingTestResult

    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(404, "Application not found")
    await assert_can_view_student(db, user, application.student_id)
    recruiter = user.role != UserRole.STUDENT
    if recruiter and user.role != UserRole.PLATFORM_ADMIN:
        await get_job_for_member(db, user, application.job_id)
    attempt = await db.scalar(select(AssessmentAttempt).where(AssessmentAttempt.application_id == application_id))
    if attempt is None:
        return None
    answers = (await db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt.id))).all()
    out = []
    for a in answers:
        aq = await db.get(AssessmentQuestion, a.assessment_question_id)
        q = await db.get(Question, aq.question_id)
        sub = await db.scalar(select(CodingSubmission).where(CodingSubmission.assessment_answer_id == a.id)
                              .order_by(CodingSubmission.created_at.desc()))
        tests = (await db.scalars(select(CodingTestResult).where(CodingTestResult.submission_id == sub.id)
                                  .order_by(CodingTestResult.test_case_index))).all() if sub else []
        item = {"answer_id": a.id, "assessment_question_id": aq.id, "question_type": q.question_type,
                "answer_text": a.answer_text, "selected_option_index": a.selected_option_index,
                "coding": {"passed": sub.passed_count, "total": sub.total_count, "language": sub.language,
                           "judge0_language_id": sub.judge0_language_id,
                           "backends": sorted(set((sub.execution_backend or "").split(",")) - {""}) or sorted(
                               {"local_fallback" if "local fallback" in (t.judge0_status or "") else "judge0" for t in tests})}
                if sub else None}
        if recruiter or attempt.status == AssessmentAttemptStatus.SCORED:
            item.update({"question_text": q.question_text, "score": a.score, "is_correct": a.is_correct})
        if recruiter:
            item["rubric_evaluation"] = a.rubric_evaluation
        out.append(item)
    return {"attempt": AttemptOut.model_validate(attempt), "answers": out}
