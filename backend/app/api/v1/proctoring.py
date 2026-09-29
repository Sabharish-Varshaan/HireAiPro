"""Proctoring API (docs/PROCTORING.md).

Students: create a session for their own application, consent, report the
system check, heartbeat, append objective events, complete. Reviewers (the
hiring company, the enrolled institution, platform admin): read the timeline
and objective counts. Nothing here scores, classifies or accuses anyone.
"""
import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.tenancy import assert_can_view_application, get_student_profile
from app.core.config import get_settings
from app.core.database import get_db
from app.models.applications import Application
from app.models.enums import UserRole
from app.models.proctoring import ProctoringEvent, ProctoringSession
from app.models.users import User
from app.services.proctoring import service as svc

router = APIRouter(prefix="/proctoring", tags=["proctoring"])
settings = get_settings()


class SessionCreate(BaseModel):
    application_id: uuid.UUID
    kind: str = Field(pattern="^(ASSESSMENT|INTERVIEW)$")


class PreflightReport(BaseModel):
    passed: bool
    checks: dict[str, bool | str | float | None]


class EventIn(BaseModel):
    event_type: str
    occurred_at: dt.datetime
    ended_at: dt.datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0, le=24 * 3600 * 1000)
    metadata: dict | None = None


class EventBatch(BaseModel):
    events: list[EventIn] = Field(max_length=50)


def _student_session_view(s: ProctoringSession) -> dict:
    return {"id": s.id, "kind": s.kind, "session_status": s.session_status, "consented": s.consent_at is not None,
            "preflight_status": s.preflight_status, "camera_required": s.camera_required,
            "microphone_required": s.microphone_required, "fullscreen_required": s.fullscreen_required,
            "heartbeat_seconds": settings.PROCTOR_HEARTBEAT_SECONDS}


async def _own_session(db, user, session_id) -> ProctoringSession:
    s = await db.get(ProctoringSession, session_id)
    me = await get_student_profile(db, user)
    if s is None or me is None or s.student_id != me.id:
        raise HTTPException(404, "Proctoring session not found")
    return s


@router.get("/policy")
async def policy(user: User = Depends(get_current_user)):
    return {"fullscreen_required": settings.PROCTOR_FULLSCREEN_REQUIRED, "camera_required": settings.PROCTOR_CAMERA_REQUIRED,
            "microphone_required": settings.PROCTOR_MICROPHONE_REQUIRED, "heartbeat_seconds": settings.PROCTOR_HEARTBEAT_SECONDS,
            "enforced": settings.PROCTOR_ENFORCE,
            "monitored": ["camera availability", "microphone availability and signal presence", "fullscreen exits",
                          "tab visibility changes", "window focus changes", "network interruptions", "session heartbeat"],
            "not_monitored": ["video or audio recording of the room", "screen recording", "face recognition",
                              "gaze or emotion analysis", "keystroke biometrics", "any automated cheating score"]}


@router.post("/sessions")
async def create_session(payload: SessionCreate, user: User = Depends(require_roles(UserRole.STUDENT)),
                         db: AsyncSession = Depends(get_db)):
    me = await get_student_profile(db, user)
    # row lock serializes concurrent creates for one application (double-mounted clients)
    app_ = await db.scalar(select(Application).where(Application.id == payload.application_id).with_for_update())
    if me is None or app_ is None or app_.student_id != me.id:
        raise HTTPException(404, "Application not found")
    existing = await db.scalar(select(ProctoringSession).where(
        ProctoringSession.application_id == app_.id, ProctoringSession.kind == payload.kind,
        ProctoringSession.session_status != "COMPLETED").order_by(ProctoringSession.created_at.desc()))
    if existing:  # resume after refresh; a new consent + system check is still required client-side
        return _student_session_view(existing)
    s = ProctoringSession(student_id=me.id, application_id=app_.id, kind=payload.kind,
                          camera_required=settings.PROCTOR_CAMERA_REQUIRED,
                          microphone_required=settings.PROCTOR_MICROPHONE_REQUIRED,
                          fullscreen_required=settings.PROCTOR_FULLSCREEN_REQUIRED)
    db.add(s)
    await db.commit()
    return _student_session_view(s)


@router.post("/sessions/{session_id}/consent")
async def consent(session_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    s = await _own_session(db, user, session_id)
    s.consent_at = s.consent_at or svc.now()
    await db.commit()
    return _student_session_view(s)


@router.post("/sessions/{session_id}/preflight")
async def preflight(session_id: uuid.UUID, payload: PreflightReport, user: User = Depends(require_roles(UserRole.STUDENT)),
                    db: AsyncSession = Depends(get_db)):
    s = await _own_session(db, user, session_id)
    if s.consent_at is None:
        raise HTTPException(409, "Consent is required before the system check")
    await svc.append_event(db, s, "SYSTEM_CHECK_STARTED", metadata=None)
    required = {"camera": s.camera_required, "microphone": s.microphone_required, "audio_signal": s.microphone_required,
                "network": True, "fullscreen_capable": s.fullscreen_required, "browser": True}
    missing = [k for k, need in required.items() if need and payload.checks.get(k) is not True]
    passed = payload.passed and not missing
    s.preflight_status = "PASSED" if passed else "FAILED"
    s.preflight_report = {"checks": payload.checks, "missing": missing}
    await svc.append_event(db, s, "SYSTEM_CHECK_PASSED" if passed else "SYSTEM_CHECK_FAILED",
                           metadata={"checks": payload.checks, "missing": missing})
    await db.commit()
    return {**_student_session_view(s), "missing": missing}


@router.post("/sessions/{session_id}/start")
async def start(session_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    s = await _own_session(db, user, session_id)
    if s.consent_at is None or s.preflight_status != "PASSED":
        raise HTTPException(409, "Complete the consent and system check first")
    if s.session_status != "ACTIVE":
        s.session_status, s.started_at, s.last_heartbeat_at = "ACTIVE", s.started_at or svc.now(), svc.now()
        await svc.append_event(db, s, "SESSION_STARTED")
    await db.commit()
    return _student_session_view(s)


@router.post("/sessions/{session_id}/heartbeat")
async def heartbeat(session_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    s = await _own_session(db, user, session_id)
    if s.session_status != "ACTIVE":
        raise HTTPException(409, "Session is not active")
    out = await svc.heartbeat(db, s)
    await db.commit()
    return out


@router.post("/sessions/{session_id}/events")
async def append_events(session_id: uuid.UUID, payload: EventBatch, user: User = Depends(require_roles(UserRole.STUDENT)),
                        db: AsyncSession = Depends(get_db)):
    s = await _own_session(db, user, session_id)
    if s.session_status == "COMPLETED":
        raise HTTPException(409, "Session already completed")
    stored = dropped = 0
    for e in sorted(payload.events, key=lambda e: e.occurred_at):
        if e.event_type not in svc.EVENT_TYPES or e.event_type.startswith(("HEARTBEAT_", "SYSTEM_CHECK_", "SESSION_")):
            raise HTTPException(422, f"Event type {e.event_type!r} cannot be reported by the client")
        ev = await svc.append_event(db, s, e.event_type, e.occurred_at, ended_at=e.ended_at, duration_ms=e.duration_ms,
                                    metadata=e.metadata)
        stored, dropped = stored + (ev is not None), dropped + (ev is None)
    await db.commit()
    return {"stored": stored, "deduplicated": dropped}


@router.post("/sessions/{session_id}/complete")
async def complete(session_id: uuid.UUID, user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    s = await _own_session(db, user, session_id)
    if s.session_status != "COMPLETED":
        s.session_status, s.ended_at = "COMPLETED", svc.now()
        await svc.append_event(db, s, "SESSION_COMPLETED")
        await db.commit()
    return _student_session_view(s)


@router.get("/review/by-application/{application_id}")
async def review(application_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Reviewer view: objective counts + full timeline. Students are refused: the
    review record is for the hiring company / enrolled institution / admins."""
    if user.role == UserRole.STUDENT:
        raise HTTPException(403, "Proctoring review is available to authorized reviewers only")
    app_ = await db.get(Application, application_id)
    if app_ is None:
        raise HTTPException(404, "Application not found")
    await assert_can_view_application(db, user, app_)
    sessions = (await db.scalars(select(ProctoringSession).where(ProctoringSession.application_id == application_id)
                                 .order_by(ProctoringSession.created_at))).all()
    out = []
    for s in sessions:
        events = (await db.scalars(select(ProctoringEvent).where(ProctoringEvent.session_id == s.id)
                                   .order_by(ProctoringEvent.occurred_at))).all()
        out.append({
            "session_id": s.id, "kind": s.kind, "session_status": s.session_status, "consent_at": s.consent_at,
            "started_at": s.started_at, "ended_at": s.ended_at, "preflight_report": s.preflight_report,
            "summary": svc.summarize(s, events),
            "timeline": [{"event_type": e.event_type, "occurred_at": e.occurred_at, "ended_at": e.ended_at,
                          "duration_ms": e.duration_ms, "severity": e.severity, "source": e.source,
                          "metadata": e.event_metadata} for e in events],
        })
    return {"application_id": application_id, "sessions": out,
            "note": "Objective events for human review. No automated judgement is made about the candidate."}


async def require_ready_session(db: AsyncSession, application_id: uuid.UUID, kind: str) -> ProctoringSession | None:
    """Gate used by attempt/interview start (server-side, so the check can't be skipped)."""
    if not settings.PROCTOR_ENFORCE:
        return None
    s = await db.scalar(select(ProctoringSession).where(
        ProctoringSession.application_id == application_id, ProctoringSession.kind == kind,
        ProctoringSession.session_status == "ACTIVE").order_by(ProctoringSession.created_at.desc()))
    if s is None:
        raise HTTPException(428, {"code": "PROCTORING_REQUIRED",
                                  "message": "Complete the system check and consent before starting."})
    return s
