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

from app.agents.model_factory import AGENT_MODEL_SETTINGS, agent_run_kwargs
from app.core.database import AsyncSessionLocal
from app.models.misc import AgentRun

T = TypeVar("T")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


@dataclass
class ToolLog:
    calls: list[dict[str, Any]] = field(default_factory=list)
    llm: dict[str, Any] = field(default_factory=dict)  # served model + usage of the agent's own LLM calls

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


def build_agent(output_type: type, deps_type: type, instructions: str, agent_type: str) -> Agent:
    # No default model: `run_llm_agent` always supplies the routed one, and a
    # run without a model fails loudly instead of using a stand-in.
    return Agent(
        None,
        name=agent_type,
        deps_type=deps_type,
        # Typed output OR a short text reply. Allowing text keeps tool_choice
        # "auto": with a required output tool, gpt-oss-120b sometimes writes the
        # final JSON as text and Groq rejects the turn (400 tool_use_failed)
        # after all tool work is done. The public agent functions rebuild the
        # typed result from tool-persisted state either way.
        output_type=[output_type, str],
        instructions=instructions,
        retries=2,
        model_settings=AGENT_MODEL_SETTINGS,
        defer_model_check=True,
    )


async def run_llm_agent(agent: Agent, agent_type: str, prompt: str, deps, log: ToolLog):
    """Runs a PydanticAI agent on the routed model with a hard request limit,
    capturing the served model and token usage for ai_runs/cost tracking."""
    from pydantic_ai.usage import RunUsage

    kwargs, chain, notes = await agent_run_kwargs(agent_type)
    usage = RunUsage()  # caller-owned: token usage survives even if the run raises
    log.llm = {"route": [p.name for p in chain], "notes": notes, "chain": chain}

    def capture(served=None):
        log.llm.update({"served_model": served, "input_tokens": usage.input_tokens or 0,
                        "cached_input_tokens": usage.cache_read_tokens or 0,
                        "output_tokens": usage.output_tokens or 0, "requests": usage.requests})

    from pydantic_ai.exceptions import UsageLimitExceeded

    try:
        # Tools share one AsyncSession, which isn't safe for concurrent use:
        # batched tool calls in a single model response run one at a time.
        with Agent.parallel_tool_call_execution_mode("sequential"):
            result = await agent.run(prompt, deps=deps, usage=usage, **kwargs)
    except UsageLimitExceeded:
        # The request budget stopped the conversation. Whether the *work* is
        # done is decided by the caller's checks on tool-persisted state
        # (e.g. every source READY, turn saved, assessment created); if it
        # isn't, those checks raise and the deterministic fallback runs.
        capture()
        log.llm["notes"] = list(log.llm.get("notes") or []) + ["stopped_at_request_budget"]
        return None
    except Exception:
        capture()
        raise
    capture(next((m.model_name for m in reversed(result.all_messages()) if getattr(m, "model_name", None)), None))
    return result


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
        await _log_llm(agent_type, context_type, context_id, llm_started, t0, None, tool_log, tool_ok=True)
        return output
    except Exception as exc:  # noqa: BLE001
        llm_error = f"{type(exc).__name__}: {exc}"
        if "disabled" not in llm_error:
            await _log_llm(agent_type, context_type, context_id, llm_started, t0, llm_error, tool_log, tool_ok=False)
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


async def _log_llm(agent_type, context_type, context_id, started_at, t0, error, tool_log: ToolLog, tool_ok=None) -> None:
    from app.services.ai_gateway.gateway import _record_run
    from app.services.ai_gateway.pricing import estimate_cost_usd

    meta = tool_log.llm
    chain = meta.get("chain") or []
    served = meta.get("served_model")
    pv = next((p for p in chain if p.model == served), None)
    if pv is None and served is None and chain:
        pv = chain[0]  # run errored before a response named its model: attribute to the route head
    if pv is None and not chain:
        return
    i, c, o = meta.get("input_tokens", 0), meta.get("cached_input_tokens", 0), meta.get("output_tokens", 0)
    await _record_run(
        # If the served model isn't one of the routed providers (e.g. a scripted test model), say so.
        task_type=f"agent:{agent_type}", provider=pv.vendor if pv else "unrouted",
        model=served or (chain[0].model if error else "unknown"), tool_call_success=tool_ok,
        prompt_version=f"{agent_type}_v1", status="FAILED" if error else "COMPLETED",
        latency_ms=(time.monotonic() - t0) * 1000, schema_valid=error is None, error=error,
        retry_count=max(0, (meta.get("requests") or 1) - 1),
        fallback_used=bool(pv and served and served != chain[0].model),
        fallback_reason="; ".join(meta.get("notes") or []) or None,
        input_tokens=i, cached_input_tokens=c, output_tokens=o,
        estimated_cost_usd=estimate_cost_usd(served, i, c, o) if (pv and pv.paid) else 0.0,
        related_entity_type=context_type, related_entity_id=context_id, started_at=started_at, ended_at=_now(),
    )


def tool_uuid(value: str, what: str = "id") -> uuid.UUID:
    """Parse an id the model passed to a tool; a malformed id becomes a
    correction for the model (ModelRetry), not a crashed run."""
    from pydantic_ai import ModelRetry

    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise ModelRetry(f"'{value}' is not a valid {what}; use the exact id returned by a previous tool") from None
