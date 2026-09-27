"""Shared plumbing for the four PydanticAI agents.

Each agent is a real `pydantic_ai.Agent` with typed deps, a typed output
and registered tools that call deterministic services. This module adds:

- `agent_runs` logging (start/end, status, every tool call with args),
- a guard so a small local model that misbehaves (never calls a required
  tool, exceeds output retries, times out) doesn't take the product down:
  the run is logged FAILED with the model error, and the caller's
  deterministic fallback — the same tools called in a fixed order — runs
  instead, with `used_fallback=True` recorded so it's visible in Admin.
"""

import datetime as dt
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic_ai import Agent

from app.agents.model_factory import AGENT_MODEL_SETTINGS, get_agent_model
from app.core.database import AsyncSessionLocal
from app.models.misc import AgentRun

T = TypeVar("T")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


@dataclass
class ToolLog:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, tool: str, **args: Any) -> None:
        self.calls.append({"tool": tool, "at": _now(), **{k: _jsonable(v) for k, v in args.items()}})


def _jsonable(v: Any) -> Any:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v][:20]
    if isinstance(v, str) and len(v) > 200:
        return v[:200] + "…"
    return v


def build_agent(output_type: type, deps_type: type, instructions: str) -> Agent:
    return Agent(
        get_agent_model(),
        deps_type=deps_type,
        output_type=output_type,
        instructions=instructions,
        retries=3,
        model_settings=AGENT_MODEL_SETTINGS,
    )


async def _write_run(**fields: Any) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        run = AgentRun(**fields)
        db.add(run)
        await db.commit()
        return run.id


async def _update_run(run_id: uuid.UUID, **fields: Any) -> None:
    async with AsyncSessionLocal() as db:
        run = await db.get(AgentRun, run_id)
        for k, v in fields.items():
            setattr(run, k, v)
        await db.commit()


async def run_agent(
    *,
    agent_type: str,
    task: str,
    context_type: str | None,
    context_id: uuid.UUID | None,
    tool_log: ToolLog,
    run_llm: Callable[[], Awaitable[T]],
    fallback: Callable[[], Awaitable[T]] | None,
    required_tools: set[str] = frozenset(),
) -> T:
    run_id = await _write_run(
        agent_type=agent_type, task=task, status="RUNNING", context_type=context_type,
        context_id=context_id, started_at=_now(),
    )
    llm_error: str | None = None
    llm_started, t0 = _now(), time.monotonic()
    try:
        output = await run_llm()
        called = {c["tool"] for c in tool_log.calls}
        missing = required_tools - called
        if missing:
            raise RuntimeError(f"agent finished without calling required tools: {sorted(missing)}")
        await _update_run(run_id, status="COMPLETED", tool_calls=tool_log.calls, ended_at=_now())
        await _log_llm(agent_type, context_type, context_id, llm_started, t0, None)
        return output
    except Exception as exc:  # noqa: BLE001
        llm_error = f"{type(exc).__name__}: {exc}"
        if "disabled" not in llm_error:
            await _log_llm(agent_type, context_type, context_id, llm_started, t0, llm_error)
        if fallback is None:
            await _update_run(run_id, status="FAILED", tool_calls=tool_log.calls, error=llm_error, ended_at=_now())
            raise

    try:
        output = await fallback()
        await _update_run(
            run_id, status="COMPLETED", used_fallback=True, tool_calls=tool_log.calls,
            error=f"LLM orchestration failed, deterministic fallback used: {llm_error}", ended_at=_now(),
        )
        return output
    except Exception as exc:  # noqa: BLE001
        await _update_run(
            run_id, status="FAILED", used_fallback=True, tool_calls=tool_log.calls,
            error=f"LLM: {llm_error} | fallback: {type(exc).__name__}: {exc}", ended_at=_now(),
        )
        raise


async def _log_llm(agent_type, context_type, context_id, started_at, t0, error) -> None:
    from app.core.config import get_settings
    from app.services.ai_gateway.gateway import _record_run

    await _record_run(
        task_type=f"agent:{agent_type}", provider="ollama-openai-compat", model=get_settings().LLM_MODEL,
        prompt_version=f"{agent_type}_v1", status="FAILED" if error else "COMPLETED",
        latency_ms=(time.monotonic() - t0) * 1000, schema_valid=error is None, error=error,
        related_entity_type=context_type, related_entity_id=context_id, started_at=started_at, ended_at=_now(),
    )
