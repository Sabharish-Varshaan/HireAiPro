"""Audit events for important mutations. Metadata is kept to ids, statuses
and counts — never resume text, answers, or transcripts."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.misc import AuditEvent


async def audit(
    db: AsyncSession,
    actor,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    *,
    organization_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_user_id=getattr(actor, "id", actor),
            organization_id=organization_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            event_metadata=metadata,
        )
    )
