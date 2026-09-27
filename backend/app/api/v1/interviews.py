import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.interview_agent import decide_next_turn, evaluate_turn_answer
from app.api.deps import require_roles
from app.core.database import get_db
from app.models.applications import Application
from app.models.enums import ApplicationStatus, EvidenceSourceType, UserRole
from app.models.interviews import Interview, InterviewTurn
from app.models.students import StudentProfile
from app.models.users import User
from app.schemas.interviews_api import (
    AnswerTurnRequest,
    InterviewOut,
    InterviewTurnOut,
    StartInterviewRequest,
)
from app.services.evidence.estimator import recalculate_all_skills_for_student
from app.services.evidence.service import record_evidence

router = APIRouter(prefix="/interviews", tags=["interviews"])


@router.post("/start", response_model=InterviewOut)
async def start_interview(
    payload: StartInterviewRequest,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    application = await db.get(Application, payload.application_id)
    if profile is None or application is None or application.student_id != profile.id:
        raise HTTPException(403, "Not your application")

    existing = await db.scalar(
        select(Interview).where(Interview.application_id == application.id)
    )
    if existing:
        return existing

    interview = Interview(
        application_id=application.id, student_id=profile.id, job_id=application.job_id
    )
    db.add(interview)
    application.status = ApplicationStatus.INTERVIEW_PENDING
    await db.commit()
    await db.refresh(interview)
    return interview


@router.post("/{interview_id}/next-turn", response_model=InterviewTurnOut | None)
async def next_turn(
    interview_id: uuid.UUID,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    interview = await db.get(Interview, interview_id)
    if interview is None:
        raise HTTPException(404, "Interview not found")
    if interview.status == "COMPLETED":
        return None

    decision = await decide_next_turn(db, interview)
    if decision is None or not decision.should_continue:
        interview.status = "COMPLETED"
        application = await db.get(Application, interview.application_id)
        if application:
            application.status = ApplicationStatus.INTERVIEW_COMPLETED
        await db.commit()
        return None

    existing_count = len(
        (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == interview.id))).all()
    )
    turn = InterviewTurn(
        interview_id=interview.id,
        turn_index=existing_count,
        target_skill_id=decision.target_skill_id,
        question_text=decision.question_text,
        difficulty=decision.difficulty,
        reason_for_question=decision.reason_for_question,
    )
    db.add(turn)
    await db.commit()
    await db.refresh(turn)
    return turn


@router.post("/turns/{turn_id}/answer", response_model=InterviewTurnOut)
async def answer_turn(
    turn_id: uuid.UUID,
    payload: AnswerTurnRequest,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    turn = await db.get(InterviewTurn, turn_id)
    if turn is None:
        raise HTTPException(404, "Turn not found")

    turn.student_answer_text = payload.answer_text
    evaluation = await evaluate_turn_answer(turn.question_text, "", payload.answer_text)
    turn.rubric_evaluation = evaluation.model_dump()

    interview = await db.get(Interview, turn.interview_id)
    await record_evidence(
        db,
        student_id=interview.student_id,
        skill_id=turn.target_skill_id,
        source_type=EvidenceSourceType.INTERVIEW,
        normalized_score=evaluation.overall_score,
        source_id=turn.id,
        difficulty=turn.difficulty,
        confidence=evaluation.evaluator_confidence,
    )
    await db.commit()
    await recalculate_all_skills_for_student(db, interview.student_id)
    await db.refresh(turn)
    return turn


@router.get("/{interview_id}/turns", response_model=list[InterviewTurnOut])
async def list_turns(interview_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return (
        await db.scalars(
            select(InterviewTurn).where(InterviewTurn.interview_id == interview_id).order_by(InterviewTurn.turn_index)
        )
    ).all()


@router.get("/history/{student_id}", response_model=list[InterviewOut])
async def interview_history(student_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Interview).where(Interview.student_id == student_id))).all()
