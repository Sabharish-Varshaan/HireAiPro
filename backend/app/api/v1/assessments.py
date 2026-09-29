import asyncio
import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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
    AssessmentConfigIn,
    StartAttemptRequest,
    SubmitAnswerRequest,
)
from app.schemas.student_views import StudentAnswerView, StudentAttemptView, coding_status, is_student
from app.schemas.questions import QuestionOut, QuestionStudentOut
from app.schemas.rubric import RubricEvaluation
from app.services.ai_gateway.gateway import AIGatewayError, get_ai_gateway
from app.services.applications.service import transition_application
from app.services.assessments import versioning as ver
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

    job.assessment_target_questions = payload.total_questions
    await db.commit()

    await upsert_job(f"assessment:{job.id}", "assessment_generation", {"job_id": str(job.id), "title": payload.title})
    generate_assessment_task.delay(str(job.id), payload.title, str(user.id))
    return {"status": "PROCESSING", "job_key": f"assessment:{job.id}"}


@router.put("/{assessment_id}/config", response_model=AssessmentOut)
async def set_config(assessment_id: uuid.UUID, payload: AssessmentConfigIn, user: User = Depends(require_roles(*RECRUITER_ROLES)),
                     db: AsyncSession = Depends(get_db)):
    """Delivery options. Locked once published: the published version is immutable."""
    assessment = await db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(404, "Assessment not found")
    await get_job_for_member(db, user, assessment.job_id)
    if assessment.status == "PUBLISHED":
        raise HTTPException(409, "A published assessment is frozen and its options can no longer change")
    assessment.config = {**(assessment.config or {}), **payload.model_dump(exclude_none=True)}
    await db.commit()
    await db.refresh(assessment)
    return assessment


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
    from app.services.jobs.posting import missing_for_publish

    missing = missing_for_publish(job)
    if missing:
        raise HTTPException(409, {"code": "POSTING_INCOMPLETE", "missing": missing,
                                  "message": "Complete the posting details (employment type, work mode, location) before publishing."})
    await ver.ensure_version(db, assessment, user.id)  # freeze content, answer keys and hidden tests
    assessment.status = "PUBLISHED"
    job.status = JobStatus.PUBLISHED
    if job.distribution_type == "INSTITUTION" and job.institution_approval in ("NOT_REQUIRED", "REJECTED"):
        job.institution_approval = "PENDING"  # goes to the placement officer's queue; students cannot see it yet
    await audit(db, user, "assessment_published", "assessment", assessment.id, organization_id=job.organization_id,
                metadata={"questions": n})
    await db.commit()
    await db.refresh(assessment)
    await _prepare_interview(db, job)
    return assessment


async def _prepare_interview(db: AsyncSession, job: Job) -> None:
    """Publishing also prepares the interview template and question pool in the background."""
    from app.api.v1.interviews import _kick_prepare
    from app.services.interviews.pool import upsert_template

    await upsert_template(db, job)
    await db.commit()
    _kick_prepare(job.id)


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
    for s in sections if recruiter_view else []:  # candidates receive questions only through their attempt session
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


def _student_attempt(a: AssessmentAttempt) -> StudentAttemptView:
    return StudentAttemptView(id=a.id, assessment_id=a.assessment_id, status=a.status,
                              completed=AssessmentAttemptStatus(a.status) == AssessmentAttemptStatus.SCORED)


@router.post("/{assessment_id}/attempts", response_model=StudentAttemptView)
async def start_attempt(assessment_id: uuid.UUID, payload: StartAttemptRequest,
                        user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    assessment, _ = await _assessment_access(db, user, await db.get(Assessment, assessment_id))
    profile = await get_student_profile(db, user)
    # row lock: two tabs starting at once must not create two attempts (and two clocks)
    application = await db.scalar(select(Application).where(Application.id == payload.application_id).with_for_update())
    if profile is None or application is None or application.student_id != profile.id or application.job_id != assessment.job_id:
        raise HTTPException(403, "Not your application for this assessment")
    from app.api.v1.proctoring import require_ready_session

    session = await require_ready_session(db, application.id, "ASSESSMENT")
    existing = await db.scalar(select(AssessmentAttempt).where(
        AssessmentAttempt.assessment_id == assessment_id, AssessmentAttempt.application_id == application.id))
    if existing:
        if session is not None and session.assessment_attempt_id is None:
            session.assessment_attempt_id = existing.id
            await db.commit()
        return _student_attempt(existing)
    version = await ver.ensure_version(db, assessment)
    cfg = version.config
    qorder, oorder = ver.new_layout(ver._from_content(version.content), cfg)
    started = ver.now()
    attempt = AssessmentAttempt(assessment_id=assessment_id, application_id=application.id, student_id=profile.id,
                                status=AssessmentAttemptStatus.IN_PROGRESS, version_id=version.id, started_at=started,
                                expires_at=started + dt.timedelta(minutes=version.duration_minutes),
                                question_order=qorder, option_orders=oorder)
    db.add(attempt)
    if ApplicationStatus(application.status) == ApplicationStatus.APPLIED:
        await transition_application(db, application, ApplicationStatus.ASSESSMENT_PENDING, user.id, "assessment started")
    await db.flush()
    if session is not None:
        session.assessment_attempt_id = attempt.id
    await db.commit()
    await db.refresh(attempt)
    return _student_attempt(attempt)


async def _own_attempt(db, user, attempt_id) -> AssessmentAttempt:
    attempt = await db.get(AssessmentAttempt, attempt_id)
    me = await get_student_profile(db, user)
    if attempt is None or me is None or attempt.student_id != me.id:
        raise HTTPException(404, "Attempt not found")
    return attempt


@router.get("/{assessment_id}/overview")
async def overview(assessment_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """What a candidate may know before starting: size and time limit, never the questions."""
    assessment, _ = await _assessment_access(db, user, await db.get(Assessment, assessment_id))
    version = await ver.ensure_version(db, assessment)
    fz = ver._from_content(version.content)
    await db.commit()
    return {"id": assessment.id, "title": assessment.title, "question_count": len(fz.by_aq),
            "duration_minutes": version.duration_minutes, "sections": [{"title": x["title"], "count": len(x["aq_ids"])} for x in fz.sections],
            "types": {t: sum(1 for q in fz.by_aq.values() if q.question_type == t) for t in ("MCQ", "TECHNICAL", "CODING")}}


@router.get("/attempts/{attempt_id}")
async def get_attempt(attempt_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)),
                      db: AsyncSession = Depends(get_db)):
    """The candidate's session: frozen questions in this attempt's persisted order, saved answers, and the server clock.
    An attempt found past its deadline is finalized here, so abandoning the tab cannot extend the time."""
    attempt = await _own_attempt(db, user, attempt_id)
    if attempt.status == AssessmentAttemptStatus.IN_PROGRESS and ver.expired(attempt):
        await _finalize(db, attempt, user)
        await db.refresh(attempt)
    fz = await ver.load_frozen(db, attempt)
    answers = {a.assessment_question_id: a for a in (await db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt.id))).all()}
    sec_title = {aq: sec["title"] for sec in fz.sections for aq in sec["aq_ids"]}
    items = []
    for n, aq_id in enumerate(ver.ordered_ids(attempt, fz), start=1):
        q = fz.by_aq[aq_id]
        a = answers.get(q.aq_id)
        items.append({"id": q.aq_id, "number": n, "section": sec_title.get(q.aq_id), "question": ver.student_question(attempt, q),
                      "answer": {"answer_id": a.id if a else None, "answer_text": a.answer_text if a else None,
                                 "selected_option_index": ver.to_displayed(attempt, q.aq_id, a.selected_option_index) if a else None,
                                 "marked_for_review": bool(a.marked_for_review) if a else False}})
    sections = [{"id": "attempt", "title": "Assessment", "questions": items}]
    return {"attempt": _student_attempt(attempt), "started_at": attempt.started_at, "expires_at": attempt.expires_at,
            "server_time": ver.now(), "sections": sections}


@router.put("/attempts/{attempt_id}/answers")
async def autosave_answer(attempt_id: uuid.UUID, payload: SubmitAnswerRequest,
                          user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    attempt = await _own_attempt(db, user, attempt_id)
    # Serialize upserts per attempt: two simultaneous saves for the same question
    # (e.g. autosave + "Run tests") used to both insert, creating duplicate answers.
    await db.execute(select(AssessmentAttempt.id).where(AssessmentAttempt.id == attempt.id).with_for_update())
    if attempt.status != AssessmentAttemptStatus.IN_PROGRESS:
        raise HTTPException(409, "Attempt already submitted")
    if ver.expired(attempt, grace=True):
        raise HTTPException(409, {"code": "ATTEMPT_EXPIRED", "message": "Time is up; your saved answers will be submitted."})
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
        try:  # the client speaks in displayed positions; storage is the original option index
            answer.selected_option_index = ver.to_original(attempt, aq.id, payload.selected_option_index)
        except ValueError:
            raise HTTPException(422, "Option index out of range")
    if payload.marked_for_review is not None:
        answer.marked_for_review = payload.marked_for_review
    await db.commit()
    return {"status": "saved", "answer_id": answer.id}


@router.post("/attempts/{attempt_id}/submit", response_model=StudentAttemptView)
async def submit_attempt(attempt_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)),
                         db: AsyncSession = Depends(get_db)):
    """Idempotent: re-submitting a scored attempt returns it unchanged; evidence
    rows are keyed per answer so nothing is double-counted. Concurrent submits serialize on the attempt row."""
    attempt = await _own_attempt(db, user, attempt_id)
    await db.execute(select(AssessmentAttempt.id).where(AssessmentAttempt.id == attempt.id).with_for_update())
    await db.refresh(attempt)
    if attempt.status == AssessmentAttemptStatus.SCORED:
        return _student_attempt(attempt)
    return await _finalize(db, attempt, user)


async def _finalize(db: AsyncSession, attempt: AssessmentAttempt, user: User) -> StudentAttemptView:
    """Grades from the frozen version (never the live question rows)."""
    attempt_id = attempt.id
    if attempt.status == AssessmentAttemptStatus.SCORED:
        return _student_attempt(attempt)
    gateway = get_ai_gateway()
    fz = await ver.load_frozen(db, attempt)
    all_answers = (await db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt_id)
                                    .order_by(AssessmentAnswer.updated_at))).all()
    answers, dup_answers = {}, {}
    for a in all_answers:  # legacy duplicates (pre-lock race): keep the most recently updated
        if a.assessment_question_id in answers:
            dup_answers.setdefault(a.assessment_question_id, []).append(answers[a.assessment_question_id])
        answers[a.assessment_question_id] = a
    # Written answers are scored concurrently (bounded): sequential scoring made submit take ~4 s per written question.
    sem = asyncio.Semaphore(4)

    async def _score(q, a):
        async with sem:
            return a.id, await gateway.evaluate_rubric(
                a.answer_text, {"question": q.question_text, "expected_concepts": q.expected_concepts or [], **(q.rubric or {})},
                RubricEvaluation, related_entity_type="assessment_answer", related_entity_id=a.id)

    to_score = [(q, answers[q.aq_id]) for q in fz.by_aq.values()
                if q.question_type == QuestionType.TECHNICAL.value and q.aq_id in answers and (answers[q.aq_id].answer_text or "").strip()]
    try:
        tech_evals = dict(await asyncio.gather(*(_score(q, a) for q, a in to_score)))
    except AIGatewayError as exc:
        raise HTTPException(503, f"Rubric evaluation is unavailable right now; your answers are saved. ({exc})")
    total_points = earned = 0.0
    for question in fz.by_aq.values():
        aq = SimpleNamespace(id=question.aq_id, points=question.points)
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
                ev = tech_evals[answer.id]  # scored concurrently above
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
    attempt.submitted_at = ver.now()
    application = await db.get(Application, attempt.application_id)
    job = await db.get(Job, application.job_id)
    if ApplicationStatus(application.status) == ApplicationStatus.ASSESSMENT_PENDING:
        await transition_application(db, application, ApplicationStatus.ASSESSMENT_COMPLETED, user.id, "assessment submitted")
    await audit(db, user, "assessment_submitted", "assessment_attempt", attempt.id, organization_id=job.organization_id,
                metadata={"total_score": round(attempt.total_score, 4)})
    await db.commit()
    await recalculate_all_skills_for_student(db, attempt.student_id, user.id, "assessment_submitted")
    await db.refresh(attempt)
    return _student_attempt(attempt)


@router.get("/attempts/by-application/{application_id}")
async def attempt_for_application(application_id: uuid.UUID, user: User = Depends(get_current_user),
                                  db: AsyncSession = Depends(get_db)):
    """Student: their own attempt (to resume after refresh; no answer keys).
    Recruiter of the job's company: scored answers incl. rubric evaluations."""
    from app.api.tenancy import assert_can_view_application
    from app.models.coding import CodingSubmission, CodingTestResult

    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(404, "Application not found")
    await assert_can_view_application(db, user, application)  # own / company's own job / enrolled institution
    student = is_student(user)
    attempt = await db.scalar(select(AssessmentAttempt).where(AssessmentAttempt.application_id == application_id))
    if attempt is None:
        return None
    if student and attempt.status == AssessmentAttemptStatus.IN_PROGRESS and ver.expired(attempt):
        await _finalize(db, attempt, user)
        await db.refresh(attempt)
    fz = await ver.load_frozen(db, attempt)
    answers = (await db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt.id))).all()
    out = []
    for a in answers:
        aq = SimpleNamespace(id=a.assessment_question_id)
        q = fz.by_aq[a.assessment_question_id]
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
        if student:
            coding = None
            if sub:
                coding = {"language": sub.language, "backend": item["coding"]["backends"],
                          "status": coding_status(sub.passed_count, sub.total_count, [t.judge0_status for t in tests])}
            out.append(StudentAnswerView(
                answer_id=a.id, assessment_question_id=aq.id, question_type=q.question_type, answer_text=a.answer_text,
                selected_option_index=ver.to_displayed(attempt, aq.id, a.selected_option_index),
                completed=bool(a.answer_text or a.selected_option_index is not None),
                question_text=q.question_text if attempt.status == AssessmentAttemptStatus.SCORED else None, coding=coding))
            continue
        item.update({"question_text": q.question_text, "score": a.score, "is_correct": a.is_correct,
                     "rubric_evaluation": a.rubric_evaluation})
        out.append(item)
    if student:
        return {"attempt": _student_attempt(attempt), "answers": out}
    return {"attempt": AttemptOut.model_validate(attempt), "answers": out}


class AttachQuestion(BaseModel):
    question_id: uuid.UUID


async def _attach(db: AsyncSession, user: User, assessment: Assessment, job: Job, question_id: uuid.UUID) -> dict:
    """Reuse one of the company's own (or an approved platform) questions in a DRAFT assessment. The question stays owned by its company;
    this only creates the usage row. Published assessments are frozen and cannot change."""
    if assessment.status == "PUBLISHED":
        raise HTTPException(409, "A published assessment is frozen; questions can no longer be added")
    assessment_id = assessment.id
    q = await db.get(Question, question_id)
    from app.models.enums import QuestionStatus, Visibility

    own = q is not None and q.organization_id == job.organization_id
    platform = q is not None and q.visibility == Visibility.PLATFORM_PUBLIC and QuestionStatus(q.status) in (QuestionStatus.APPROVED, QuestionStatus.ACTIVE)
    if q is None or not (own or platform):
        raise HTTPException(404, "Question not found")  # another company's private question is indistinguishable from a missing one
    if own and QuestionStatus(q.status) not in (QuestionStatus.VALIDATED, QuestionStatus.APPROVED, QuestionStatus.ACTIVE):
        raise HTTPException(409, "This question is not validated yet")
    if await db.scalar(select(AssessmentQuestion.id).where(AssessmentQuestion.assessment_id == assessment_id, AssessmentQuestion.question_id == q.id)):
        raise HTTPException(409, "Already in this assessment")
    from app.models.skills import Skill

    skill = await db.get(Skill, q.skill_id)
    sec = await db.scalar(select(AssessmentSection).where(AssessmentSection.assessment_id == assessment_id, AssessmentSection.title == skill.canonical_name))
    if sec is None:
        n = len((await db.scalars(select(AssessmentSection.id).where(AssessmentSection.assessment_id == assessment_id))).all())
        sec = AssessmentSection(assessment_id=assessment_id, title=skill.canonical_name, order_index=n)
        db.add(sec)
        await db.flush()
    order = len((await db.scalars(select(AssessmentQuestion.id).where(AssessmentQuestion.assessment_id == assessment_id))).all())
    aq = AssessmentQuestion(assessment_id=assessment_id, section_id=sec.id, question_id=q.id, order_index=order, points=(q.import_meta or {}).get("max_score") or 1.0)
    db.add(aq)
    await audit(db, user, "assessment_question_attached", "assessment", assessment_id, organization_id=job.organization_id, metadata={"question_id": str(q.id)})
    await db.commit()
    return {"assessment_question_id": aq.id, "question_id": q.id, "assessment_id": assessment_id}


@router.post("/{assessment_id}/questions")
async def attach_question(assessment_id: uuid.UUID, payload: AttachQuestion, user: User = Depends(require_roles(*RECRUITER_ROLES)),
                          db: AsyncSession = Depends(get_db)):
    assessment = await db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(404, "Assessment not found")
    job = await get_job_for_member(db, user, assessment.job_id)
    return await _attach(db, user, assessment, job, payload.question_id)


@router.post("/jobs/{job_id}/questions")
async def attach_question_to_job(job_id: uuid.UUID, payload: AttachQuestion, user: User = Depends(require_roles(*RECRUITER_ROLES)),
                                 db: AsyncSession = Depends(get_db)):
    """Same as above, creating the job's draft assessment first if it has none (so questions can be reused before any generation)."""
    job = await get_job_for_member(db, user, job_id)
    assessment = await db.scalar(select(Assessment).where(Assessment.job_id == job_id).order_by(Assessment.created_at.desc()))
    if assessment is None:
        assessment = Assessment(job_id=job_id, title=f"{job.title} Assessment", status="DRAFT")
        db.add(assessment)
        await db.flush()
    return await _attach(db, user, assessment, job, payload.question_id)


@router.delete("/{assessment_id}/questions/{question_id}")
async def detach_question(assessment_id: uuid.UUID, question_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)),
                          db: AsyncSession = Depends(get_db)):
    assessment = await db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(404, "Assessment not found")
    await get_job_for_member(db, user, assessment.job_id)
    if assessment.status == "PUBLISHED":
        raise HTTPException(409, "A published assessment is frozen")
    aq = await db.scalar(select(AssessmentQuestion).where(AssessmentQuestion.assessment_id == assessment_id, AssessmentQuestion.question_id == question_id))
    if aq is None:
        raise HTTPException(404, "Question is not in this assessment")
    await db.delete(aq)
    await db.commit()
    return {"removed": True}
