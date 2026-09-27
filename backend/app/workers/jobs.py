"""Idempotent background-job bookkeeping.

Each logical job has a stable `job_key` (e.g. "jd:<job_id>"). Enqueueing
upserts one `processing_jobs` row; running it moves PENDING → RUNNING →
COMPLETED/FAILED. The work functions themselves are written to be safe to
re-run (upserts, idempotency keys, per-document replacement), so a retry —
automatic or from the Admin "Failed jobs" screen — converges to the same
rows instead of duplicating them.

Only transient failures (LLM timeouts, network errors, a lost DB
connection) are retried by Celery. Deterministic failures (validation,
missing records, a job whose requirements aren't confirmed) fail once and
stay FAILED for a human to look at.
"""

import datetime as dt
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.misc import ProcessingJob
from app.services.ai_gateway.gateway import AIGatewayError

TRANSIENT = (AIGatewayError, httpx.TransportError, httpx.TimeoutException, ConnectionError, TimeoutError, OSError)


class PermanentJobError(Exception):
    """A failure retrying won't fix."""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


async def upsert_job(job_key: str, job_type: str, payload: dict) -> ProcessingJob:
    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(ProcessingJob).where(ProcessingJob.job_key == job_key))
        if job is None:
            job = ProcessingJob(job_key=job_key, job_type=job_type, status="PENDING", payload=payload, attempts=0)
            db.add(job)
        else:
            job.status = "PENDING"
            job.payload = payload
            job.error = None
        await db.commit()
        await db.refresh(job)
        return job


async def run_tracked(
    job_key: str, job_type: str, payload: dict, celery_task_id: str | None, work: Callable[[], Awaitable[Any]]
) -> Any:
    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(ProcessingJob).where(ProcessingJob.job_key == job_key))
        if job is None:
            job = ProcessingJob(job_key=job_key, job_type=job_type, payload=payload, attempts=0)
            db.add(job)
        job.status = "RUNNING"
        job.attempts = (job.attempts or 0) + 1
        job.celery_task_id = celery_task_id
        job.error = None
        await db.commit()

    try:
        result = await work()
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            job = await db.scalar(select(ProcessingJob).where(ProcessingJob.job_key == job_key))
            job.status = "FAILED"
            job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"[:4000]
            await db.commit()
        raise

    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(ProcessingJob).where(ProcessingJob.job_key == job_key))
        job.status = "COMPLETED"
        job.result = result if isinstance(result, dict) else {"result": str(result)}
        await db.commit()
    return result
