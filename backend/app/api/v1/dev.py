"""Development/demo mail outbox. Returns 404 (as if the route did not exist) outside development/demo."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.accounts import EmailOutbox
from app.services.accounts.service import outbox_enabled

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/email-outbox")
async def email_outbox(to: str | None = None, limit: int = 50, db: AsyncSession = Depends(get_db)):
    if not outbox_enabled():
        raise HTTPException(404, "Not found")
    stmt = select(EmailOutbox).order_by(EmailOutbox.created_at.desc()).limit(min(limit, 200))
    if to:
        stmt = stmt.where(EmailOutbox.to_email == to)
    return [{"id": e.id, "to": e.to_email, "subject": e.subject, "link": e.link, "created_at": e.created_at}
            for e in (await db.scalars(stmt)).all()]
