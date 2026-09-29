"""Proctoring: objective, human-reviewable session events (docs/PROCTORING.md).
No scores, no classification, no accusation — just what happened and when."""
import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk


class ProctoringSession(Base, UUIDPk, TimestampMixin):
    __tablename__ = "proctoring_sessions"

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("student_profiles.id"), index=True)
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("applications.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # ASSESSMENT | INTERVIEW
    assessment_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessment_attempts.id"), nullable=True, index=True)
    interview_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("interviews.id"), nullable=True, index=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    camera_required: Mapped[bool] = mapped_column(Boolean, default=True)
    microphone_required: Mapped[bool] = mapped_column(Boolean, default=True)
    fullscreen_required: Mapped[bool] = mapped_column(Boolean, default=True)
    preflight_status: Mapped[str] = mapped_column(String, default="NOT_RUN")  # NOT_RUN | PASSED | FAILED
    preflight_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    session_status: Mapped[str] = mapped_column(String, default="CREATED")  # CREATED | ACTIVE | COMPLETED
    last_heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_lost: Mapped[bool] = mapped_column(Boolean, default=False)


class ProctoringEvent(Base, UUIDPk, TimestampMixin):
    __tablename__ = "proctoring_events"

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("proctoring_sessions.id"), index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[str] = mapped_column(String, default="info")  # info | notice (never an accusation)
    source: Mapped[str] = mapped_column(String, default="client")  # client | server (heartbeat detection)
    event_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
