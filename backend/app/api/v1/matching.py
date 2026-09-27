import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.tenancy import assert_can_view_student, get_job_for_member
from app.core.database import get_db
from app.models.applications import Application
from app.models.enums import UserRole
from app.models.matching import Match
from app.models.users import User
from app.schemas.matching import MatchOut
from app.services.matching.engine import WEIGHTS, compute_match_for_application

router = APIRouter(prefix="/matching", tags=["matching"])

RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)


def _out(m: Match) -> MatchOut:
    return MatchOut.model_validate(m).model_copy(update={"weights": WEIGHTS})


@router.post("/applications/{application_id}/compute", response_model=MatchOut)
async def compute_match(application_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)),
                        db: AsyncSession = Depends(get_db)):
    a = await db.get(Application, application_id)
    if a is None:
        raise HTTPException(404, "Application not found")
    await get_job_for_member(db, user, a.job_id)
    try:
        return _out(await compute_match_for_application(db, application_id))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/applications/{application_id}", response_model=MatchOut)
async def get_match(application_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    a = await db.get(Application, application_id)
    if a is None:
        raise HTTPException(404, "Application not found")
    await assert_can_view_student(db, user, a.student_id)
    if user.role in RECRUITER_ROLES:
        await get_job_for_member(db, user, a.job_id)
    m = await db.scalar(select(Match).where(Match.application_id == application_id))
    if m is None:
        raise HTTPException(404, "Match not computed yet")
    return _out(m)


@router.get("/jobs/{job_id}/ranked", response_model=list[MatchOut])
async def ranked_candidates_for_job(job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)),
                                    db: AsyncSession = Depends(get_db)):
    await get_job_for_member(db, user, job_id)
    rows = (await db.scalars(select(Match).where(Match.job_id == job_id).order_by(Match.match_score.desc()))).all()
    return [_out(m) for m in rows]


@router.post("/jobs/{job_id}/recompute", status_code=202)
async def recompute_job(job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    await get_job_for_member(db, user, job_id)
    from app.workers.jobs import upsert_job
    from app.workers.tasks_matching import recompute_job_matches_task

    await upsert_job(f"matching:{job_id}", "bulk_matching", {"job_id": str(job_id)})
    recompute_job_matches_task.delay(str(job_id))
    return {"status": "PROCESSING"}
