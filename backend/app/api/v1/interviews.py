import tempfile
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
                                    answer_source=t.answer_source, answered=t.rubric_evaluation is not None)


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
    interview = Interview(application_id=application.id, student_id=me.id, job_id=application.job_id,
                          max_turns=settings.INTERVIEW_MAX_TURNS)
    db.add(interview)
    await db.flush()
    if session is not None:
        session.interview_id = interview.id
    await transition_application(db, application, ApplicationStatus.INTERVIEW_PENDING, user.id, "interview started")
    await db.commit()
    await db.refresh(interview)
    return interview


async def _complete(db, interview: Interview, actor_id) -> None:
    if interview.status == "COMPLETED":
        return
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
    interview = await _own_interview(db, user, interview_id)
    if interview.status == "COMPLETED":
        return None
    pending = await db.scalar(select(InterviewTurn).where(InterviewTurn.interview_id == interview.id,
                                                          InterviewTurn.student_answer_text.is_(None)))
    if pending:  # idempotent: don't generate a second question while one is unanswered
        return await _student_turn(db, pending)
    try:
        turn = await decide_next_turn(db, interview)
    except AIGatewayError as exc:
        raise HTTPException(503, f"The interviewer model is unavailable; try again shortly. ({exc})")
    if turn is None:
        await _complete(db, interview, user.id)
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
        try:
            result = get_ai_gateway().transcribe(tmp.name)
        except Exception as exc:  # noqa: BLE001 — the student can always type instead
            raise HTTPException(503, f"Transcription failed; please type your answer. ({type(exc).__name__}: {exc})")
    turn.audio_document_id = doc.id
    turn.transcript_meta = {**(turn.transcript_meta or {}), "transcription": result}
    await db.commit()
    return result


@router.post("/turns/{turn_id}/answer", response_model=StudentInterviewTurnView)
async def answer_turn(turn_id: uuid.UUID, payload: AnswerTurnRequest, user: User = Depends(require_roles(UserRole.STUDENT)),
                      db: AsyncSession = Depends(get_db)):
    turn, interview = await _own_turn(db, user, turn_id)
    if turn.rubric_evaluation is not None:
        return await _student_turn(db, turn)  # idempotent re-submit
    if not payload.answer_text.strip():
        raise HTTPException(422, "Answer is empty")
    turn.student_answer_text = payload.answer_text.strip()
    turn.answer_source = payload.answer_source if payload.answer_source in {"text", "voice"} else "text"
    try:
        ev = await evaluate_turn_answer(turn)
    except AIGatewayError as exc:
        await db.rollback()
        raise HTTPException(503, f"Scoring is unavailable right now; your answer was not lost, please resubmit. ({exc})")
    turn.rubric_evaluation = ev.model_dump()
    await record_evidence(db, interview.student_id, turn.target_skill_id, EvidenceSourceType.INTERVIEW, ev.overall_score,
                          source_id=turn.id, difficulty=turn.difficulty, confidence=ev.evaluator_confidence,
                          model_id=get_ai_gateway().model, prompt_version="rubric_eval_v1", rubric_version="interview_rubric_v1")
    await db.commit()
    await recalculate_all_skills_for_student(db, interview.student_id, user.id, "interview_turn")
    await db.refresh(turn)
    return await _student_turn(db, turn)


@router.post("/{interview_id}/finish")
async def finish_interview(interview_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)),
                           db: AsyncSession = Depends(get_db)):
    interview = await _own_interview(db, user, interview_id)
    answered = (await db.scalars(select(InterviewTurn.id).where(InterviewTurn.interview_id == interview.id,
                                                                InterviewTurn.rubric_evaluation.is_not(None)))).all()
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
