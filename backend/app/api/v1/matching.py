import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.matching import Match
from app.models.users import User
from app.schemas.matching import MatchOut
from app.services.matching.engine import compute_match_for_application

router = APIRouter(prefix="/matching", tags=["matching"])

RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)


@router.post("/applications/{application_id}/compute", response_model=MatchOut)
async def compute_match(
    application_id: uuid.UUID,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await compute_match_for_application(db, application_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/applications/{application_id}", response_model=MatchOut)
async def get_match(
    application_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    match = await db.scalar(select(Match).where(Match.application_id == application_id))
    if match is None:
        raise HTTPException(404, "Match not computed yet")
    return match


@router.get("/jobs/{job_id}/ranked", response_model=list[MatchOut])
async def ranked_candidates_for_job(
    job_id: uuid.UUID,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    return (
        await db.scalars(
            select(Match).where(Match.job_id == job_id).order_by(Match.match_score.desc())
        )
    ).all()
