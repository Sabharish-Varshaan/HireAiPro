from app.core.database import AsyncSessionLocal
from app.models.applications import Application
from app.services.matching.engine import compute_match_for_application
from app.workers.celery_app import celery_app
from app.workers.utils import run_async


async def _recompute(application_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        app_row = await db.get(Application, application_id)
        if app_row is None:
            return {"error": "application not found"}
        match = await compute_match_for_application(db, app_row.id)
        return {"application_id": application_id, "match_score": match.match_score}


@celery_app.task(name="matching.recompute", bind=True, max_retries=3)
def recompute_match_task(self, application_id: str) -> dict:
    return run_async(lambda: _recompute(application_id))
