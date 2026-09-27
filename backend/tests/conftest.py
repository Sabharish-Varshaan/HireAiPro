import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    # Each test function gets its own event loop under pytest-asyncio's
    # default function-scoped loop, but asyncpg connections are bound to the
    # loop that created them. Disposing the shared engine's pool after every
    # test (same fix as app/workers/utils.py::run_async) keeps it loop-safe.
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()
    await engine.dispose()
