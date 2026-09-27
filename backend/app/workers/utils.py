import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


def run_async(coro_fn: Callable[[], Awaitable[T]]) -> T:
    """Runs a coroutine in a fresh event loop and disposes the shared async
    engine's connection pool afterwards.

    Celery (prefork/solo) tasks each get their own asyncio.run() call, i.e. a
    brand new event loop per task. asyncpg connections are bound to the loop
    that created them, so without disposing the pool here, a connection
    checked out on a previous task's now-closed loop can be handed back out
    on the next task and blow up with "cannot rollback; the transaction is
    in error state". Disposing after every task keeps the pool loop-safe at
    the cost of reconnecting each time, which is fine for background jobs.
    """

    async def _wrapped() -> T:
        from app.core.database import engine

        try:
            return await coro_fn()
        finally:
            await engine.dispose()

    return asyncio.run(_wrapped())
