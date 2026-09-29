import os

# Must run before any app import: tests get their own Postgres database and
# Qdrant collection prefix so they never read or write dev data.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://hireai:hireai@localhost:5435/hireai_test")
os.environ.setdefault("QDRANT_COLLECTION_PREFIX", "test_")
# Celery broker + result backend in their own Valkey database: a dev worker
# (db 0) can never consume a task enqueued by a test, and vice versa.
os.environ["VALKEY_URL"] = os.environ.get("TEST_VALKEY_URL", "redis://localhost:6380/10")
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine


def _assert_isolated_broker():
    """Refuse to run tests against the development broker."""
    from dotenv import dotenv_values
    from app.workers.celery_app import celery_app

    dev = (dotenv_values(os.path.join(os.path.dirname(__file__), "..", ".env")).get("VALKEY_URL") or "redis://localhost:6379/0")
    test = celery_app.conf.broker_url
    if test.rstrip("/") == dev.rstrip("/"):
        raise pytest.UsageError(f"test Celery broker must differ from dev broker ({dev})")
    import redis
    redis.Redis.from_url(test).flushdb()  # test-only database: drop tasks left by earlier sessions


def pytest_configure(config):
    _assert_isolated_broker()
    config.addinivalue_line("markers", "live: needs the local Ollama model (slow); run with -m live")
    config.addinivalue_line("markers", "judge0: needs the running cgroup-v2 Judge0 stack; run with -m judge0")


def pytest_collection_modifyitems(config, items):
    # Live-LLM tests are opt-in so the default suite stays fast and deterministic.
    if config.getoption("-m") or os.environ.get("RUN_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live LLM test; run with -m live")
    skip_j0 = pytest.mark.skip(reason="needs the Judge0 stack; run with -m judge0")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
        if "judge0" in item.keywords:
            item.add_marker(skip_j0)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    # pytest-asyncio gives each test its own event loop and asyncpg
    # connections are loop-bound, so dispose the pool after every test
    # (same reason as app/workers/utils.py::run_async).
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1", timeout=600) as c:
        yield c
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_each_test():
    yield
    await engine.dispose()
