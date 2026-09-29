"""Proctoring service: append objective events, detect heartbeat gaps on the
server, and summarize for human reviewers. Never scores or classifies."""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.proctoring import ProctoringEvent, ProctoringSession

settings = get_settings()

EVENT_TYPES = {
    "SYSTEM_CHECK_STARTED", "SYSTEM_CHECK_PASSED", "SYSTEM_CHECK_FAILED",
    "FULLSCREEN_ENTERED", "FULLSCREEN_EXITED",
    "TAB_HIDDEN", "TAB_VISIBLE",
    "WINDOW_BLUR", "WINDOW_FOCUS",
    "CAMERA_STARTED", "CAMERA_TRACK_ENDED", "CAMERA_MUTED", "CAMERA_UNMUTED",
    "MIC_STARTED", "MIC_TRACK_ENDED", "MIC_MUTED", "MIC_UNMUTED", "MIC_NO_SIGNAL",
    "NETWORK_OFFLINE", "NETWORK_ONLINE",
    "HEARTBEAT_LOST", "HEARTBEAT_RESTORED",
    "SESSION_STARTED", "SESSION_COMPLETED",
}
# "notice" = worth a reviewer's attention; it is NOT a judgement about the student.
NOTICE = {"FULLSCREEN_EXITED", "TAB_HIDDEN", "CAMERA_TRACK_ENDED", "CAMERA_MUTED", "MIC_TRACK_ENDED", "MIC_MUTED",
          "MIC_NO_SIGNAL", "NETWORK_OFFLINE", "HEARTBEAT_LOST", "SYSTEM_CHECK_FAILED"}
# Counts shown to reviewers (objective tallies, no weighting, no total "risk").
SUMMARY_COUNTS = {
    "fullscreen_exits": {"FULLSCREEN_EXITED"},
    "tab_switches": {"TAB_HIDDEN"},
    "window_blurs": {"WINDOW_BLUR"},
    "camera_interruptions": {"CAMERA_TRACK_ENDED", "CAMERA_MUTED"},
    "microphone_interruptions": {"MIC_TRACK_ENDED", "MIC_MUTED", "MIC_NO_SIGNAL"},
    "network_outages": {"NETWORK_OFFLINE"},
    "heartbeat_interruptions": {"HEARTBEAT_LOST"},
}


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


async def _last_of_type(db: AsyncSession, session_id, event_type: str) -> ProctoringEvent | None:
    return await db.scalar(select(ProctoringEvent).where(ProctoringEvent.session_id == session_id,
                                                         ProctoringEvent.event_type == event_type)
                           .order_by(ProctoringEvent.occurred_at.desc()).limit(1))


async def append_event(db: AsyncSession, session: ProctoringSession, event_type: str, occurred_at: dt.datetime | None = None,
                       *, ended_at=None, duration_ms=None, metadata=None, source: str = "client") -> ProctoringEvent | None:
    """Append one event; identical consecutive events inside the dedupe window are dropped
    (browser focus/visibility/online events can fire in bursts)."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown proctoring event type {event_type!r}")
    occurred_at = occurred_at or now()
    prev = await _last_of_type(db, session.id, event_type)
    if prev is not None and abs((occurred_at - prev.occurred_at).total_seconds() * 1000) < settings.PROCTOR_DEDUPE_WINDOW_MS:
        return None
    ev = ProctoringEvent(session_id=session.id, event_type=event_type, occurred_at=occurred_at, ended_at=ended_at,
                         duration_ms=duration_ms, severity="notice" if event_type in NOTICE else "info",
                         source=source, event_metadata=metadata)
    db.add(ev)
    await db.flush()
    return ev


async def heartbeat(db: AsyncSession, session: ProctoringSession) -> dict:
    """Server-side gap detection: the server, not the browser, decides that the
    heartbeat was lost (a paused or disconnected client cannot report that)."""
    t = now()
    gap = (t - session.last_heartbeat_at).total_seconds() if session.last_heartbeat_at else 0.0
    restored = None
    if session.last_heartbeat_at and gap > settings.PROCTOR_HEARTBEAT_LOST_AFTER_SECONDS:
        lost_at = session.last_heartbeat_at
        await append_event(db, session, "HEARTBEAT_LOST", lost_at, source="server",
                           metadata={"last_heartbeat_at": lost_at.isoformat()})
        restored = await append_event(db, session, "HEARTBEAT_RESTORED", t, source="server",
                                      duration_ms=int(gap * 1000), metadata={"gap_seconds": round(gap, 1)})
    session.last_heartbeat_at = t
    session.heartbeat_lost = False
    return {"ok": True, "server_time": t.isoformat(), "gap_seconds": round(gap, 1), "restored_after_gap": restored is not None,
            "interval_seconds": settings.PROCTOR_HEARTBEAT_SECONDS}


def summarize(session: ProctoringSession, events: list[ProctoringEvent]) -> dict:
    counts = {k: sum(1 for e in events if e.event_type in types) for k, types in SUMMARY_COUNTS.items()}
    hidden_ms = sum(e.duration_ms or 0 for e in events if e.event_type == "TAB_VISIBLE")
    offline_ms = sum(e.duration_ms or 0 for e in events if e.event_type in {"NETWORK_ONLINE", "HEARTBEAT_RESTORED"})
    end = session.ended_at or (events[-1].occurred_at if events else None)
    duration = int((end - session.started_at).total_seconds()) if (end and session.started_at) else None
    return {"session_duration_seconds": duration, **counts, "time_tab_hidden_ms": hidden_ms,
            "time_disconnected_ms": offline_ms, "preflight_status": session.preflight_status}
