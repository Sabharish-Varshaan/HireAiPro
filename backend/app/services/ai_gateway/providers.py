"""Providers and the task-aware router.

Roles:
- luna  (OpenAI cheap model)  — simple structured tasks, most-used paid model
- groq  (gpt-oss-120b, free)  — agentic / complex tasks
- sol   (OpenAI escalation)   — never a default; only on explicit escalation
- ollama (local qwen3.5:4b)   — offline / emergency fallback, not the demo engine

`route(task_type, escalate=False)` returns an ordered provider chain plus the
reasons it was shaped that way (budget state, missing keys, LOCAL_ONLY).
Business code never picks a provider; it passes a task_type.

The chain advances only on provider/transient failures (see
`is_fallback_error`). Our own bugs (AttributeError, integrity errors,
pydantic programming mismatches, authorization) propagate untouched.
"""

import time
from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class Provider:
    name: str      # luna | groq | sol | ollama
    vendor: str    # openai | groq | ollama
    base_url: str
    model: str
    api_key: str = field(default="", repr=False)

    @property
    def paid(self) -> bool:
        return self.vendor == "openai"

    @property
    def is_local(self) -> bool:
        return self.vendor == "ollama"


class ProviderHTTPError(Exception):
    def __init__(self, provider: str, status: int, body: str, retry_after: float | None = None):
        super().__init__(f"{provider} HTTP {status}: {body[:300]}")
        self.provider, self.status, self.retry_after = provider, status, retry_after


class ProviderUnavailable(Exception):
    """Raised before a call when a provider is in rate-limit cool-down."""


# Configuration-driven policy. Tiers not configured/allowed are skipped.
CHEAP = ["luna", "groq", "ollama"]
AGENT = ["groq", "luna", "ollama"]
CRITICAL = ["groq", "luna", "sol", "ollama"]

TASK_POLICY: dict[str, list[str]] = {
    "jd_extraction": CHEAP,
    "resume_extraction": CHEAP,
    "question_validation": CHEAP,
    "rubric_completion": CHEAP,
    "rag_answer": CHEAP,
    "analytics_summary": CHEAP,
    "rubric_evaluation": CHEAP,
    # candidate is waiting on this call between interview turns: Groq first (measured p50 1.1 s vs 3.9 s for luna), luna fallback
    "interview_rubric_evaluation": AGENT,
    "career_summary": CHEAP,
    "interview_question": CHEAP,
    # authoring-time batches and the candidate-facing HR observation (a person waits on it between turns)
    "interview_pool_batch": AGENT,
    "hr_observation": AGENT,
    "aptitude_generation": AGENT,
    "aptitude_verification": AGENT,
    "metadata_extraction": CHEAP,
    "ambiguous_skill_resolution": CHEAP,
    "generic": CHEAP,
    "question_generation": AGENT,
    "agent:assessment_agent": AGENT,
    "agent:interview_agent": AGENT,
    "agent:career_agent": AGENT,
    "agent:knowledge_agent": AGENT,
    "critical_complex_failure": CRITICAL,
}

# Groq 429 cool-down (in-process): don't hammer a rate-limited provider.
_cooldown_until: dict[str, float] = {}
DEFAULT_COOLDOWN_S = 20.0


def mark_rate_limited(name: str, retry_after: float | None) -> None:
    _cooldown_until[name] = time.monotonic() + min(retry_after or DEFAULT_COOLDOWN_S, 120.0)


def in_cooldown(name: str) -> bool:
    return _cooldown_until.get(name, 0.0) > time.monotonic()


def is_fallback_error(exc: BaseException) -> bool:
    if isinstance(exc, ProviderUnavailable):
        return True
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError)):
        return True
    if isinstance(exc, ProviderHTTPError):
        # 404 model unavailable; 413 provider request-size/TPM cap (Groq free tier); 429 rate limit; 5xx outage
        return exc.status in (404, 413, 429) or exc.status >= 500
    return False


def configured_providers() -> dict[str, Provider]:
    s = get_settings()
    out = {"ollama": Provider("ollama", "ollama", s.OLLAMA_BASE_URL.rstrip("/"), s.OLLAMA_MODEL)}
    if s.GROQ_API_KEY.strip():
        out["groq"] = Provider("groq", "groq", s.GROQ_BASE_URL.rstrip("/"), s.GROQ_MODEL, s.GROQ_API_KEY.strip())
    if s.OPENAI_API_KEY.strip():
        base = s.OPENAI_BASE_URL.rstrip("/")
        out["luna"] = Provider("luna", "openai", base, s.OPENAI_CHEAP_MODEL, s.OPENAI_API_KEY.strip())
        out["sol"] = Provider("sol", "openai", base, s.OPENAI_ESCALATION_MODEL, s.OPENAI_API_KEY.strip())
    return out


@dataclass
class Route:
    chain: list[Provider]
    notes: list[str]
    budget_state: str

    @property
    def names(self) -> list[str]:
        return [p.name for p in self.chain]


async def route(task_type: str, escalate: bool = False, budget=None) -> Route:
    from app.services.ai_gateway.budget import HARD, SOFT, budget_state

    s = get_settings()
    avail = configured_providers()
    if s.LOCAL_ONLY:
        return Route([avail["ollama"]], ["LOCAL_ONLY"], "local_only")

    b = budget or await budget_state()
    policy = list(TASK_POLICY.get(task_type, CHEAP))
    notes: list[str] = []

    if b.state == HARD:
        notes.append(b.reason)
        policy = [p for p in policy if p not in ("luna", "sol")]
    elif b.state == SOFT:
        notes.append(b.reason)
        policy = [p for p in policy if p != "sol"]
        if "groq" in policy:  # prefer the free path; keep Luna as a later fallback
            policy.remove("groq")
            policy.insert(0, "groq")
    if "sol" in policy and not escalate:
        policy.remove("sol")

    chain = []
    for name in policy:
        if name not in avail:
            notes.append(f"{name}_not_configured")
        elif in_cooldown(name):
            notes.append(f"{name}_rate_limited_cooldown")
        else:
            chain.append(avail[name])
    if not chain:
        chain = [avail["ollama"]]
    return Route(chain, notes, b.state)
