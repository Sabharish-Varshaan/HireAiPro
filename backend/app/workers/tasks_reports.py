import uuid

from app.core.database import AsyncSessionLocal
from app.services.analytics.institution import institution_report
from app.workers.celery_app import celery_app
from app.workers.jobs import TRANSIENT, run_tracked
from app.workers.utils import run_async


async def build_report(institution_id: uuid.UUID, with_summary: bool = True) -> dict:
    async with AsyncSessionLocal() as db:
        return await institution_report(db, institution_id, with_summary=with_summary)


@celery_app.task(name="reports.institution", bind=True, autoretry_for=TRANSIENT, retry_backoff=5, max_retries=2)
def institution_report_task(self, institution_id: str) -> dict:
    return run_async(lambda: run_tracked(f"report:{institution_id}", "report_generation", {"institution_id": institution_id},
                                         self.request.id, lambda: build_report(uuid.UUID(institution_id))))
