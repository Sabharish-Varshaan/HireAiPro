"""In-app notifications. `dedupe_key` is unique, so the same event (e.g. a
retried task, a double-clicked submit) never produces two notifications."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.misc import Notification


async def notify(
    db: AsyncSession,
    user_id: uuid.UUID,
    event_type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    dedupe_key: str | None = None,
) -> None:
    key = dedupe_key or f"{event_type}:{user_id}:{link}"
    exists = await db.scalar(select(Notification.id).where(Notification.dedupe_key == key))
    if exists:
        return
    db.add(Notification(user_id=user_id, event_type=event_type, title=title, body=body, link=link, dedupe_key=key))


APPLICATION_STATUS_MESSAGES = {
    "APPLIED": ("application_submitted", "Application submitted"),
    "ASSESSMENT_PENDING": ("assessment_assigned", "Assessment ready to take"),
    "ASSESSMENT_COMPLETED": ("assessment_completed", "Assessment completed"),
    "INTERVIEW_PENDING": ("interview_ready", "Interview ready"),
    "INTERVIEW_COMPLETED": ("interview_completed", "Interview completed"),
    "UNDER_REVIEW": ("under_review", "Your application is under review"),
    "SHORTLISTED": ("shortlisted", "You've been shortlisted"),
    "REJECTED": ("rejected", "Application update"),
    "OFFER": ("offer", "You received an offer"),
}
