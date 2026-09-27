import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.applications import Application
from app.services.matching.engine import compute_match_for_application
from app.workers.celery_app import celery_app
from app.workers.jobs import TRANSIENT, run_tracked
from app.workers.utils import run_async


async def recompute_job_matches(job_id: uuid.UUID) -> dict:
    """Matches upsert on application_id, so bulk recomputation never duplicates."""
    async with AsyncSessionLocal() as db:
        app_ids = (await db.scalars(select(Application.id).where(Application.job_id == job_id))).all()
        scores = {}
        for aid in app_ids:
            m = await compute_match_for_application(db, aid)
            scores[str(aid)] = m.match_score
        return {"job_id": str(job_id), "matches": len(scores)}


@celery_app.task(name="matching.recompute_job", bind=True, autoretry_for=TRANSIENT, retry_backoff=5, max_retries=3)
def recompute_job_matches_task(self, job_id: str) -> dict:
    return run_async(lambda: run_tracked(f"matching:{job_id}", "bulk_matching", {"job_id": job_id}, self.request.id,
                                         lambda: recompute_job_matches(uuid.UUID(job_id))))
