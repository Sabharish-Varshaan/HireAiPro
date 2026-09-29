"""Tests and the development worker must never share Celery queues.

The test session uses its own Valkey database for broker and results
(tests/conftest.py); the dev worker consumes the dev database from backend/.env.
"""
import json
import os
import uuid

import pytest
import redis
from dotenv import dotenv_values

from app.workers.celery_app import celery_app

DEV_URL = dotenv_values(os.path.join(os.path.dirname(__file__), "..", "..", ".env")).get("VALKEY_URL") or "redis://localhost:6379/0"


def _ids_in(url: str, queue: str) -> list[str]:
    r = redis.Redis.from_url(url)
    return [json.loads(m)["headers"]["id"] for m in r.lrange(queue, 0, -1)]


def test_test_broker_and_backend_are_not_the_dev_ones():
    assert celery_app.conf.broker_url.rstrip("/") != DEV_URL.rstrip("/")
    assert str(celery_app.conf.result_backend).rstrip("/") != DEV_URL.rstrip("/")


def test_task_enqueued_by_tests_reaches_only_the_test_broker():
    marker = str(uuid.uuid4())
    res = celery_app.send_task("resumes.process", args=[marker, marker], queue="documents")
    assert res.id in _ids_in(celery_app.conf.broker_url, "documents")  # a test worker can receive it
    assert res.id not in _ids_in(DEV_URL, "documents")                 # the dev worker can never see it
    got = None
    with celery_app.connection_for_read() as conn:                     # a test-side consumer receives it
        q = conn.SimpleQueue("documents")
        for _ in range(20):
            msg = q.get(timeout=2)
            if msg.headers.get("id") == res.id:
                got = msg
                msg.ack()
                break
            msg.requeue()
        q.close()
    assert got is not None


def test_dev_broker_messages_are_invisible_to_the_test_broker():
    dev = redis.Redis.from_url(DEV_URL)
    probe_queue = f"isolation_probe_{uuid.uuid4().hex}"  # never consumed by any worker
    dev.lpush(probe_queue, json.dumps({"headers": {"id": "dev-only"}}))
    try:
        assert _ids_in(DEV_URL, probe_queue) == ["dev-only"]
        assert _ids_in(celery_app.conf.broker_url, probe_queue) == []
    finally:
        dev.delete(probe_queue)
