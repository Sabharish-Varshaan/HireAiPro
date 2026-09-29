from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "hireai",
    broker=settings.VALKEY_URL,
    backend=settings.VALKEY_URL,
    include=[
        "app.workers.tasks_jobs",
        "app.workers.tasks_resumes",
        "app.workers.tasks_questions",
        "app.workers.tasks_matching",
        "app.workers.tasks_knowledge",
        "app.workers.tasks_reports",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_routes={
        "jobs.*": {"queue": "documents"},
        "resumes.*": {"queue": "documents"},
        "assessments.*": {"queue": "assessments"},
        "pipeline.*": {"queue": "assessments"},
        "matching.*": {"queue": "matching"},
        "knowledge.*": {"queue": "knowledge"},
        "reports.*": {"queue": "reports"},
        "app.workers.tasks_jobs.*": {"queue": "documents"},
        "app.workers.tasks_resumes.*": {"queue": "documents"},
        "app.workers.tasks_questions.*": {"queue": "assessments"},
        "app.workers.tasks_matching.*": {"queue": "matching"},
        "app.workers.tasks_knowledge.*": {"queue": "knowledge"},
        "app.workers.tasks_reports.*": {"queue": "reports"},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)
