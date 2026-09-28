"""PydanticAI models for the four agents, built from the gateway router.

The route is resolved per run (so the daily budget governor applies to
agents too) and becomes a `FallbackModel` that advances only on provider
failures (HTTP 404/429/5xx, connection/timeouts) — never on our own bugs.

Findings that shaped this (pydantic-ai 2.51):
- Default tool-output mode is used. NativeOutput/PromptedOutput were tried
  with Qwen and skipped tool calls while inventing values.
- Qwen's thinking must be off for tool workflows (`reasoning_effort=none` on
  Ollama's /v1 endpoint). gpt-oss / gpt-6 use low reasoning effort.
"""

from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from app.core.config import get_settings
from app.services.ai_gateway.providers import Provider, route

AGENT_MODEL_SETTINGS = {"timeout": 120}

# Model-request budget per agent run. Past it, the run stops and the
# deterministic fallback finishes from the state the tools already persisted.
# All four agents are the "complex agentic" class in the routing policy, so
# they get the complex budget (LLM_MAX_AGENT_TURNS, default 6). Measured on
# gpt-oss-120b: interview and career runs need 5–6 requests including the
# final answer; a budget of 4 cut both off just before they finished.
NORMAL_AGENT_REQUEST_LIMIT = 4
AGENT_REQUEST_LIMITS: dict[str, int | None] = {
    "interview_agent": None,
    "career_agent": None,
    "assessment_agent": None,
    "knowledge_agent": None,
}

_PER_VENDOR_SETTINGS = {
    "ollama": {"extra_body": {"reasoning_effort": "none"}, "temperature": 0},
    "groq": {"extra_body": {"reasoning_effort": "low"}, "temperature": 0},
    # gpt-6-* reject function tools combined with reasoning_effort on
    # /v1/chat/completions ("set reasoning_effort to 'none'"); measured 2026-09-27.
    "openai": {"openai_reasoning_effort": "none"},
}


def _should_fallback(exc: Exception) -> bool:
    if isinstance(exc, ModelHTTPError):
        return exc.status_code in (404, 413, 429) or exc.status_code >= 500
    return isinstance(exc, ModelAPIError)  # connection errors / timeouts


def _model(pv: Provider) -> OpenAIChatModel:
    base = f"{pv.base_url}/v1" if pv.vendor == "ollama" else pv.base_url
    return OpenAIChatModel(pv.model, provider=OpenAIProvider(base_url=base, api_key=pv.api_key or "local"),
                           settings=_PER_VENDOR_SETTINGS.get(pv.vendor, {}))


async def agent_run_kwargs(agent_type: str) -> tuple[dict, list[Provider], list[str]]:
    r = await route(f"agent:{agent_type}")
    models = [_model(pv) for pv in r.chain]
    model: Model = models[0] if len(models) == 1 else FallbackModel(models[0], *models[1:], fallback_on=_should_fallback)
    limit = AGENT_REQUEST_LIMITS.get(agent_type) or get_settings().LLM_MAX_AGENT_TURNS
    return {"model": model, "usage_limits": UsageLimits(request_limit=limit)}, r.chain, r.notes
