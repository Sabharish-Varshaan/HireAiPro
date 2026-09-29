import tempfile
import asyncio
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.interview_agent import decide_next_turn, evaluate_turn_answer
from app.api.deps import get_current_user, require_roles
from app.api.tenancy import assert_can_view_application, assert_can_view_student, get_student_profile
from app.core.config import get_settings
from app.core.database import get_db
from app.models.applications import Application
from app.models.documents import Document
from app.models.enums import ApplicationStatus, EvidenceSourceType, UserRole, Visibility
from app.models.interviews import Interview, InterviewTurn
from app.models.jobs import Job
from app.models.skills import Skill
from app.models.users import User
from app.schemas.student_views import StudentInterviewTurnView, is_student
from app.schemas.interviews_api import InterviewOut, InterviewTurnOut, StartInterviewRequest
from app.services.ai_gateway.gateway import AIGatewayError, get_ai_gateway
from app.services.applications.service import transition_application
from app.services.audit import audit
from app.services.evidence.estimator import recalculate_all_skills_for_student
from app.services.evidence.service import record_evidence
from app.services.matching.engine import compute_match_for_application
from app.services.storage.service import get_storage_service

logger = logging.getLogger(__name__)
RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)

router = APIRouter(prefix="/interviews", tags=["interviews"])
settings = get_settings()
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/m4a", "video/webm"}


class AnswerTurnRequest(BaseModel):
    answer_text: str
    answer_source: str = "text"  # text | voice


async def _own_interview(db, user, interview_id) -> Interview:
    interview = await db.get(Interview, interview_id)
    me = await get_student_profile(db, user)
    if interview is None or me is None or interview.student_id != me.id:
        raise HTTPException(404, "Interview not found")
    return interview


async def _own_turn(db, user, turn_id) -> tuple[InterviewTurn, Interview]:
    turn = await db.get(InterviewTurn, turn_id)
    if turn is None:
        raise HTTPException(404, "Turn not found")
    return turn, await _own_interview(db, user, turn.interview_id)


async def _student_turn(db, t: InterviewTurn) -> StudentInterviewTurnView:
    """No rubric values, difficulty or selection reason (which embeds confidence numbers)."""
    skill = await db.get(Skill, t.target_skill_id)
    return StudentInterviewTurnView(id=t.id, turn_index=t.turn_index, skill_name=skill.canonical_name if skill else None,
                                    question_text=t.question_text, student_answer_text=t.student_answer_text,
                                    answer_source=t.answer_source, answered=t.student_answer_text is not None)


async def _turn_out(db, t: InterviewTurn) -> InterviewTurnOut:
    skill = await db.get(Skill, t.target_skill_id)
    return InterviewTurnOut.model_validate(t).model_copy(update={"skill_name": skill.canonical_name if skill else None})


@router.post("/start", response_model=InterviewOut)
async def start_interview(payload: StartInterviewRequest, user: User = Depends(require_roles(UserRole.STUDENT)),
                          db: AsyncSession = Depends(get_db)):
    me = await get_student_profile(db, user)
    application = await db.get(Application, payload.application_id)
    if me is None or application is None or application.student_id != me.id:
        raise HTTPException(404, "Application not found")
    from app.api.v1.proctoring import require_ready_session

    session = await require_ready_session(db, application.id, "INTERVIEW")
    existing = await db.scalar(select(Interview).where(Interview.application_id == application.id))
    if existing:
        if session is not None and session.interview_id is None:
            session.interview_id = existing.id
            await db.commit()
        return existing
    if ApplicationStatus(application.status) != ApplicationStatus.ASSESSMENT_COMPLETED:
        raise HTTPException(409, "Finish the assessment before starting the interview")
    from app.services.interviews.pool import pool_status
    from app.services.interviews.selector import rank_candidates

    interview = Interview(application_id=application.id, student_id=me.id, job_id=application.job_id,
                          max_turns=settings.INTERVIEW_MAX_TURNS)
    db.add(interview)
    await db.flush()
    # Session plan: the ranked competencies for THIS candidate at start (same blueprint, same rubric for everyone).
    ranked = await rank_candidates(db, application.job_id, me.id, interview.id)
    pool = await pool_status(db, application.job_id)
    interview.plan = {"competencies": [c.as_dict() for c in ranked[:settings.INTERVIEW_MAX_TURNS]], "pool": pool,
                      "rubric_version": "interview_rubric_v1"}
    if session is not None:
        session.interview_id = interview.id
    await transition_application(db, application, ApplicationStatus.INTERVIEW_PENDING, user.id, "interview started")
    await db.commit()
    await db.refresh(interview)
    return interview


async def _complete(db, interview: Interview, actor_id) -> None:
    if interview.status == "COMPLETED":
        return
    await _settle_pending(db, interview, actor_id, 60.0)  # the recruiter's evidence is complete before the match is computed
    interview = await db.get(Interview, interview.id)
    interview.status = "COMPLETED"
    application = await db.get(Application, interview.application_id)
    job = await db.get(Job, interview.job_id)
    await transition_application(db, application, ApplicationStatus.INTERVIEW_COMPLETED, actor_id, "interview completed")
    await transition_application(db, application, ApplicationStatus.UNDER_REVIEW, None, "ready for recruiter review")
    await audit(db, actor_id, "interview_completed", "interview", interview.id, organization_id=job.organization_id)
    await db.commit()
    await compute_match_for_application(db, application.id)


@router.post("/{interview_id}/next-turn", response_model=StudentInterviewTurnView | None)
async def next_turn(interview_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)),
                    db: AsyncSession = Depends(get_db)):
    actor_id = user.id  # read once: _settle_pending ends the read snapshot, which expires ORM objects loaded before it
    interview = await _own_interview(db, user, interview_id)
    if interview.status == "COMPLETED":
        return None
    pending = await db.scalar(select(InterviewTurn).where(InterviewTurn.interview_id == interview.id,
                                                          InterviewTurn.student_answer_text.is_(None)))
    if pending:  # idempotent: don't generate a second question while one is unanswered
        return await _student_turn(db, pending)
    await _settle_pending(db, interview, actor_id, settings.INTERVIEW_EVAL_CATCHUP_SECONDS)
    try:
        turn = await decide_next_turn(db, interview)
    except AIGatewayError as exc:
        raise HTTPException(503, f"The interviewer model is unavailable; try again shortly. ({exc})")
    if turn is None:
        await _complete(db, interview, actor_id)
        return None
    await db.commit()
    return await _student_turn(db, turn)


@router.post("/turns/{turn_id}/transcribe")
async def transcribe_answer(turn_id: uuid.UUID, audio: UploadFile, user: User = Depends(require_roles(UserRole.STUDENT)),
                            db: AsyncSession = Depends(get_db)):
    """Speech → text only. The transcript is returned for the student to
    review/edit, then submitted through the normal answer endpoint."""
    turn, interview = await _own_turn(db, user, turn_id)
    ctype = (audio.content_type or "").split(";")[0]
    if ctype and ctype not in AUDIO_TYPES:
        raise HTTPException(415, f"Unsupported audio type {ctype}")
    raw = await audio.read()
    if not raw:
        raise HTTPException(422, "Empty recording")
    if len(raw) > settings.MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording too large")
    key, sha, size = get_storage_service().save(audio.filename or "answer.webm", raw)
    doc = Document(owner_user_id=user.id, storage_key=key, filename=audio.filename or "answer.webm",
                   mime_type=ctype or "audio/webm", size_bytes=size, sha256=sha, visibility=Visibility.COMPANY_PRIVATE,
                   doc_type="INTERVIEW_AUDIO")
    db.add(doc)
    await db.flush()
    suffix = Path(audio.filename or "a.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(raw)
        tmp.flush()
        t_stt = time.perf_counter()
        try:  # CPU-bound: off the event loop so heartbeats and other candidates are not stalled while Whisper runs
            result = await asyncio.to_thread(get_ai_gateway().transcribe, tmp.name)
        except Exception as exc:  # noqa: BLE001 — the student can always type instead
            raise HTTPException(503, f"Transcription failed; please type your answer. ({type(exc).__name__}: {exc})")
    turn.audio_document_id = doc.id
    turn.transcript_meta = {**(turn.transcript_meta or {}), "transcription": result}
    turn.timing = {**(turn.timing or {}), "stt_ms": round((time.perf_counter() - t_stt) * 1000, 1)}
    await db.commit()
    return result


_EVALS: dict[uuid.UUID, "asyncio.Task[None]"] = {}  # in-flight scoring per turn (single API process); the DB row lock covers the rest


async def _evaluate_and_record(turn_id: uuid.UUID, student_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Scores one answered turn and records the evidence, in its own session. Safe to run twice: the row lock plus the
    `rubric_evaluation is None` check make the second run a no-op."""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        turn = await db.scalar(select(InterviewTurn).where(InterviewTurn.id == turn_id).with_for_update())
        if turn is None or turn.rubric_evaluation is not None or not turn.student_answer_text:
            return
        t_eval = time.perf_counter()
        ev = await evaluate_turn_answer(turn)  # AIGatewayError propagates; the answer itself is already saved
        eval_ms = (time.perf_counter() - t_eval) * 1000
        turn.rubric_evaluation = ev.model_dump()
        await record_evidence(db, student_id, turn.target_skill_id, EvidenceSourceType.INTERVIEW, ev.overall_score,
                              source_id=turn.id, difficulty=turn.difficulty, confidence=ev.evaluator_confidence,
                              model_id=get_ai_gateway().model, prompt_version="rubric_eval_v1", rubric_version="interview_rubric_v1")
        await db.commit()
        t_rc = time.perf_counter()
        await recalculate_all_skills_for_student(db, student_id, actor_id, "interview_turn")
        await db.refresh(turn)
        turn.timing = {**(turn.timing or {}), "answer": {"eval_ms": round(eval_ms, 1), "recalc_ms": round((time.perf_counter() - t_rc) * 1000, 1)}}
        await db.commit()


def _start_eval(turn_id, student_id, actor_id) -> "asyncio.Task[None]":
    existing = _EVALS.get(turn_id)
    if existing is not None and not existing.done():
        return existing
    task = asyncio.create_task(_evaluate_and_record(turn_id, student_id, actor_id))
    _EVALS[turn_id] = task
    task.add_done_callback(lambda t, tid=turn_id: (_EVALS.pop(tid, None), t.exception() and logger.warning("interview scoring failed for %s: %r", tid, t.exception())))
    return task


async def _settle_pending(db, interview: Interview, actor_id, timeout: float) -> None:
    """Give unscored answered turns of this interview up to `timeout` seconds to finish (restarting any that were lost)."""
    pending = (await db.scalars(select(InterviewTurn.id).where(
        InterviewTurn.interview_id == interview.id, InterviewTurn.student_answer_text.is_not(None), InterviewTurn.rubric_evaluation.is_(None)))).all()
    if not pending:
        return
    student_id = interview.student_id
    tasks = [_start_eval(tid, student_id, actor_id) for tid in pending]
    await asyncio.wait(tasks, timeout=timeout)
    await db.rollback()  # end the read snapshot so later queries see the background commits
    await db.refresh(interview)


@router.post("/turns/{turn_id}/answer", response_model=StudentInterviewTurnView)
async def answer_turn(turn_id: uuid.UUID, payload: AnswerTurnRequest, user: User = Depends(require_roles(UserRole.STUDENT)),
                      db: AsyncSession = Depends(get_db)):
    """Persists the answer first, then scores it. Scoring is awaited for at most INTERVIEW_EVAL_BUDGET_SECONDS: when the
    provider is slower, the answer is still saved, scoring finishes in the background, and the interview moves on."""
    turn, interview = await _own_turn(db, user, turn_id)
    if turn.rubric_evaluation is not None:
        return await _student_turn(db, turn)  # idempotent re-submit
    if turn.student_answer_text is None:
        if not payload.answer_text.strip():
            raise HTTPException(422, "Answer is empty")
        turn.student_answer_text = payload.answer_text.strip()
        turn.answer_source = payload.answer_source if payload.answer_source in {"text", "voice"} else "text"
        await db.commit()  # answer persisted before any model call
    task = _start_eval(turn.id, interview.student_id, user.id)
    await asyncio.wait({task}, timeout=settings.INTERVIEW_EVAL_BUDGET_SECONDS)
    if task.done() and task.exception() is not None:
        exc = task.exception()
        if isinstance(exc, AIGatewayError):  # answer is saved; scoring is retried on the next turn / at the end
            logger.warning("scoring deferred for turn %s: %s", turn.id, exc)
        else:
            raise exc
    await db.refresh(turn)
    return await _student_turn(db, turn)


@router.post("/{interview_id}/finish")
async def finish_interview(interview_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)),
                           db: AsyncSession = Depends(get_db)):
    interview = await _own_interview(db, user, interview_id)
    answered = (await db.scalars(select(InterviewTurn.id).where(InterviewTurn.interview_id == interview.id,
                                                                InterviewTurn.student_answer_text.is_not(None)))).all()
    if not answered:
        raise HTTPException(409, "Answer at least one question first")
    await _complete(db, interview, user.id)
    return {"status": "COMPLETED"}


@router.get("/{interview_id}/turns", response_model=None)
async def list_turns(interview_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    interview = await db.get(Interview, interview_id)
    if interview is None:
        raise HTTPException(404, "Interview not found")
    await assert_can_view_application(db, user, await db.get(Application, interview.application_id))
    turns = (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == interview_id)
                              .order_by(InterviewTurn.turn_index))).all()
    if is_student(user):
        return [await _student_turn(db, t) for t in turns]
    return [await _turn_out(db, t) for t in turns]


@router.get("/by-application/{application_id}", response_model=InterviewOut | None)
async def interview_for_application(application_id: uuid.UUID, user: User = Depends(get_current_user),
                                    db: AsyncSession = Depends(get_db)):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(404, "Application not found")
    await assert_can_view_application(db, user, application)
    return await db.scalar(select(Interview).where(Interview.application_id == application_id))


@router.get("/history/me", response_model=list[InterviewOut])
async def interview_history(user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    me = await get_student_profile(db, user)
    if me is None:
        return []
    return (await db.scalars(select(Interview).where(Interview.student_id == me.id).order_by(Interview.created_at.desc()))).all()


class PrepareRequest(BaseModel):
    application_id: uuid.UUID


@router.post("/prepare")
async def prepare_interview(payload: PrepareRequest, user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    """Interview setup step (runs during the system check): makes sure the job's question pool is ready so that question 1
    appears the instant the interview starts. Idempotent; returns readiness."""
    from app.services.interviews.pool import pool_status, upsert_template

    me = await get_student_profile(db, user)
    application = await db.get(Application, payload.application_id)
    if me is None or application is None or application.student_id != me.id:
        raise HTTPException(404, "Application not found")
    st = await pool_status(db, application.job_id)
    if st["status"] in ("MISSING", "FAILED"):  # legacy job or earlier failure: build it now, in the background
        job = await db.get(Job, application.job_id)
        await upsert_template(db, job, reset=st["status"] == "FAILED")
        await db.commit()
        _kick_prepare(application.job_id)
        st = await pool_status(db, application.job_id)
    return st


@router.get("/readiness/{application_id}")
async def interview_readiness(application_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    from app.services.interviews.pool import pool_status

    me = await get_student_profile(db, user)
    application = await db.get(Application, application_id)
    if me is None or application is None or application.student_id != me.id:
        raise HTTPException(404, "Application not found")
    st = await pool_status(db, application.job_id)
    return {"ready": st["ready"], "status": st["status"]}


def _kick_prepare(job_id: uuid.UUID) -> None:
    try:
        from app.workers.tasks_questions import prepare_interview_template_task

        prepare_interview_template_task.delay(str(job_id))
    except Exception:  # broker down: the live path still works, just slower
        logger.warning("could not enqueue interview pool preparation for %s", job_id, exc_info=True)


@router.get("/templates/by-job/{job_id}")
async def template_for_job(job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES, UserRole.PLATFORM_ADMIN)),
                           db: AsyncSession = Depends(get_db)):
    """The company reviews its interview configuration: competencies, rules, and the prepared questions per skill/difficulty."""
    from app.api.tenancy import get_job_for_member
    from app.models.interviews import InterviewPoolQuestion, InterviewTemplate
    from app.models.skills import Skill

    await get_job_for_member(db, user, job_id)
    t = await db.scalar(select(InterviewTemplate).where(InterviewTemplate.job_id == job_id))
    if t is None:
        return None
    rows = (await db.execute(select(InterviewPoolQuestion, Skill.canonical_name).join(Skill, Skill.id == InterviewPoolQuestion.skill_id)
                             .where(InterviewPoolQuestion.template_id == t.id).order_by(Skill.canonical_name, InterviewPoolQuestion.difficulty))).all()
    return {"status": t.status, "version": t.version, "error": t.error, "config": t.config,
            "questions": [{"id": q.id, "skill": n, "difficulty": q.difficulty, "question_text": q.question_text, "source": q.source} for q, n in rows]}


@router.post("/templates/by-job/{job_id}/rebuild", status_code=202)
async def rebuild_template(job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    from app.api.tenancy import get_job_for_member
    from app.services.interviews.pool import upsert_template

    job = await get_job_for_member(db, user, job_id)
    await upsert_template(db, job, reset=True)
    await db.commit()
    _kick_prepare(job_id)
    return {"status": "PREPARING"}
