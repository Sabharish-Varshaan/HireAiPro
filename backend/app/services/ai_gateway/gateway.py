"""Single choke point for all LLM interaction.

Business services pass a `task_type`; the router (providers.route) decides
which provider/model handles it. Every call writes exactly one `ai_runs`
row with provider, model, token usage, estimated cost, retries and fallback
reason. Only SHA-256 hashes of prompts/outputs are stored, never raw text.

Cost safety:
- at most LLM_MAX_RETRIES schema-repair retries per provider (default 1),
- the chain advances only on provider/transient errors,
- a 429 puts that provider in cool-down and falls through immediately
  (interactive requests never sit in back-off),
- the budget governor removes OpenAI from the chain at the daily hard cap.
"""

import datetime as dt
import email.utils
import hashlib
import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.ai_gateway.pricing import estimate_cost_usd
from app.services.ai_gateway.providers import (
    Provider,
    ProviderHTTPError,
    ProviderUnavailable,
    in_cooldown,
    is_fallback_error,
    mark_rate_limited,
    route,
)

logger = logging.getLogger(__name__)

settings = get_settings()
T = TypeVar("T", bound=BaseModel)
_last_served: ContextVar[tuple[str, str]] = ContextVar("last_served", default=("router", "routed"))

PROMPT_VERSIONS = {
    "jd_extraction": "jd_extraction_v1",
    "resume_extraction": "resume_extraction_v1",
    "question_generation": "question_generation_v2_rag",
    "rubric_evaluation": "rubric_eval_v1",
    "interview_question": "interview_question_v1",
    "career_summary": "career_summary_v1",
    "rag_answer": "rag_answer_v1",
    "rubric_completion": "rubric_completion_v1",
    "analytics_summary": "analytics_summary_v1",
    "generic": "generic_v1",
}


class AIGatewayError(Exception):
    pass


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


async def _record_run(**fields: Any) -> None:
    # Own session: logging never rides on (or rolls back with) the caller's
    # transaction, and a logging failure never breaks the AI call itself.
    from app.core.database import AsyncSessionLocal
    from app.models.misc import AIRun

    try:
        async with AsyncSessionLocal() as db:
            db.add(AIRun(**fields))
            await db.commit()
    except Exception:  # noqa: BLE001
        # Never break the AI call itself, but never lose a cost row silently:
        # a missing ai_run means the budget governor under-counts spend.
        logger.exception("failed to record ai_run (task=%s provider=%s)", fields.get("task_type"), fields.get("provider"))


@dataclass
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.output_tokens += other.output_tokens


@dataclass
class CallOutcome:
    provider: Provider
    usage: Usage = field(default_factory=Usage)
    retries: int = 0
    raw: str = ""


def _retry_after(resp: httpx.Response) -> float | None:
    v = resp.headers.get("retry-after")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        parsed = email.utils.parsedate_to_datetime(v)
        return max(0.0, (parsed - dt.datetime.now(dt.timezone.utc)).total_seconds())


class AIGateway:
    @property
    def provider(self) -> str:
        """Vendor that served the most recent call in this context."""
        return _last_served.get()[0]

    @property
    def model(self) -> str:
        """Model that served the most recent call in this context (for evidence provenance)."""
        return _last_served.get()[1]

    async def _call(self, pv: Provider, prompt: str, system: str | None, temperature: float,
                    json_schema: dict | None) -> tuple[str, Usage]:
        if in_cooldown(pv.name):
            raise ProviderUnavailable(f"{pv.name} is in rate-limit cool-down")
        timeout = settings.LLM_OLLAMA_TIMEOUT_SECONDS if pv.is_local else settings.LLM_TIMEOUT_SECONDS
        async with httpx.AsyncClient(timeout=timeout) as client:
            if pv.vendor == "ollama":
                body: dict[str, Any] = {
                    "model": pv.model, "prompt": prompt, "system": system or "", "stream": False,
                    "think": settings.LLM_THINK, "keep_alive": "2m",  # unload soon after use to free RAM
                    "options": {"temperature": temperature, "num_predict": settings.LLM_MAX_OUTPUT_TOKENS, "num_ctx": 8192},
                }
                if json_schema is not None:
                    body["format"] = json_schema
                resp = await client.post(f"{pv.base_url}/api/generate", json=body)
                if resp.status_code >= 400:
                    raise ProviderHTTPError(pv.name, resp.status_code, resp.text)
                data = resp.json()
                return data.get("response", ""), Usage(data.get("prompt_eval_count", 0) or 0, 0, data.get("eval_count", 0) or 0)

            messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
            body = {"model": pv.model, "messages": messages, "stream": False}
            if pv.vendor == "openai":
                body["max_completion_tokens"] = settings.LLM_MAX_OUTPUT_TOKENS
                body["reasoning_effort"] = "low"
                if json_schema is not None:
                    body["response_format"] = {"type": "json_object"}
            else:  # groq gpt-oss
                body["max_tokens"] = settings.LLM_MAX_OUTPUT_TOKENS
                body["temperature"] = temperature
                body["reasoning_effort"] = "low"
                if json_schema is not None:
                    body["response_format"] = {"type": "json_object"}
            resp = await client.post(f"{pv.base_url}/chat/completions", json=body,
                                     headers={"Authorization": f"Bearer {pv.api_key}"})
            if resp.status_code == 429:
                ra = _retry_after(resp)
                mark_rate_limited(pv.name, ra)
                raise ProviderHTTPError(pv.name, 429, resp.text, ra)
            if resp.status_code >= 400:
                raise ProviderHTTPError(pv.name, resp.status_code, resp.text)
            data = resp.json()
            u = data.get("usage") or {}
            usage = Usage(u.get("prompt_tokens", 0) or 0,
                          ((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)) or 0,
                          u.get("completion_tokens", 0) or 0)
            return _strip_reasoning(data["choices"][0]["message"].get("content") or ""), usage

    async def _run(self, task_type: str, attempt, escalate: bool = False) -> tuple[Any, CallOutcome, list[str], Any]:
        r = await route(task_type, escalate=escalate)
        reasons = list(r.notes)
        last_exc: BaseException | None = None
        for i, pv in enumerate(r.chain):
            outcome = CallOutcome(provider=pv)
            try:
                return await attempt(pv, outcome), outcome, reasons, r
            except Exception as exc:  # noqa: BLE001
                if is_fallback_error(exc):
                    last_exc = exc
                    await self._log_failed_attempt(task_type, pv, outcome, exc)
                    reasons.append(f"{pv.name}: {type(exc).__name__} {str(exc)[:160]}")
                    continue
                if isinstance(exc, _SchemaInvalid):
                    # One provider couldn't produce valid output after its repair
                    # retry: that's a model-quality miss, so try the next tier once.
                    last_exc = exc
                    await self._log_failed_attempt(task_type, pv, outcome, exc, schema_valid=False)
                    reasons.append(f"{pv.name}: schema_invalid_after_retry")
                    continue
                if isinstance(exc, ProviderHTTPError):  # e.g. 400/401: our request/config, not an outage
                    await self._log_failed_attempt(task_type, pv, outcome, exc)
                    raise AIGatewayError(f"{pv.name} rejected the request: {exc}") from exc
                raise  # our own bug: never masked by switching models
        raise AIGatewayError(f"all providers failed for {task_type}: {'; '.join(reasons)}") from last_exc

    async def _log_failed_attempt(self, task_type, pv, outcome, exc, schema_valid=None):
        cost = estimate_cost_usd(pv.model, outcome.usage.input_tokens, outcome.usage.cached_input_tokens,
                                 outcome.usage.output_tokens) if pv.paid else 0.0
        await _record_run(
            task_type=task_type, provider=pv.vendor, model=pv.model,
            prompt_version=PROMPT_VERSIONS.get(task_type, "generic_v1"), status="FAILED",
            schema_valid=schema_valid, retry_count=outcome.retries, error=f"{type(exc).__name__}: {str(exc)[:500]}",
            input_tokens=outcome.usage.input_tokens, cached_input_tokens=outcome.usage.cached_input_tokens,
            output_tokens=outcome.usage.output_tokens, estimated_cost_usd=cost, started_at=_now(), ended_at=_now(),
        )

    async def _record_success(self, task_type, outcome: CallOutcome, reasons, t0, started_at, input_text,
                              schema_valid, related_entity_type, related_entity_id):
        pv, u = outcome.provider, outcome.usage
        _last_served.set((pv.vendor, pv.model))
        await _record_run(
            task_type=task_type, provider=pv.vendor, model=pv.model,
            prompt_version=PROMPT_VERSIONS.get(task_type, "generic_v1"), status="COMPLETED",
            latency_ms=(time.monotonic() - t0) * 1000, schema_valid=schema_valid, retry_count=outcome.retries,
            fallback_used=any(":" in r for r in reasons), fallback_reason="; ".join(reasons) or None,
            input_tokens=u.input_tokens, cached_input_tokens=u.cached_input_tokens, output_tokens=u.output_tokens,
            estimated_cost_usd=estimate_cost_usd(pv.model, u.input_tokens, u.cached_input_tokens, u.output_tokens) if pv.paid else 0.0,
            related_entity_type=related_entity_type, related_entity_id=related_entity_id,
            started_at=started_at, ended_at=_now(), input_hash=_sha(input_text), output_hash=_sha(outcome.raw),
        )

    async def generate(self, prompt: str, system: str | None = None, temperature: float = 0.2, *,
                       task_type: str = "generic", related_entity_type: str | None = None,
                       related_entity_id: uuid.UUID | None = None, escalate: bool = False) -> str:
        started_at, t0 = _now(), time.monotonic()

        async def attempt(pv: Provider, outcome: CallOutcome) -> str:
            text, usage = await self._call(pv, prompt, system, temperature, None)
            outcome.usage.add(usage)
            outcome.raw = text
            return text

        try:
            text, outcome, reasons, _ = await self._run(task_type, attempt, escalate)
        except AIGatewayError:
            raise
        await self._record_success(task_type, outcome, reasons, t0, started_at, (system or "") + prompt, None,
                                   related_entity_type, related_entity_id)
        return text

    async def generate_structured(self, prompt: str, schema: type[T], system: str | None = None,
                                  temperature: float = 0.1, max_retries: int | None = None, *,
                                  task_type: str = "generic", related_entity_type: str | None = None,
                                  related_entity_id: uuid.UUID | None = None, escalate: bool = False) -> T:
        """Stable rules/schema first (cache-friendly), dynamic data last."""
        retries = settings.LLM_MAX_RETRIES if max_retries is None else min(max_retries, settings.LLM_MAX_RETRIES)
        json_schema = schema.model_json_schema()
        full_system = ((system or "") + "\n\nRespond with ONLY a JSON object matching this JSON Schema, "
                       "no commentary, no markdown:\n" + json.dumps(json_schema))
        started_at, t0 = _now(), time.monotonic()

        async def attempt(pv: Provider, outcome: CallOutcome) -> T:
            current, err = prompt, None
            for n in range(retries + 1):
                outcome.retries = n
                raw, usage = await self._call(pv, current, full_system, temperature, json_schema)
                outcome.usage.add(usage)
                outcome.raw = raw
                try:
                    return schema.model_validate_json(_strip_code_fences(raw))
                except ValueError as exc:  # pydantic ValidationError / JSON decode only
                    err = exc
                    current = (f"{prompt}\n\nYour previous response was invalid ({str(exc)[:300]}). "
                               "Respond again with ONLY corrected JSON matching the schema.")
            raise _SchemaInvalid(str(err))

        result, outcome, reasons, _ = await self._run(task_type, attempt, escalate)
        await self._record_success(task_type, outcome, reasons, t0, started_at, full_system + prompt, True,
                                   related_entity_type, related_entity_id)
        return result

    async def extract_structured(self, text: str, schema: type[T], instruction: str, *,
                                 task_type: str = "generic", **kw: Any) -> T:
        prompt = f"{instruction}\n\n---\nSOURCE TEXT:\n{trim_text(text)}\n---"
        return await self.generate_structured(prompt, schema, task_type=task_type, **kw)

    async def evaluate_rubric(self, answer_text: str, rubric: dict[str, Any], schema: type[T], **kw: Any) -> T:
        system = ("Evaluate the candidate's answer strictly against the rubric. Do not invent correctness the "
                  "answer does not support. An empty, off-topic or nonsensical answer scores near 0 on every criterion.")
        prompt = f"RUBRIC:\n{json.dumps(rubric)}\n\nCANDIDATE ANSWER:\n{trim_text(answer_text, 6000)}"
        return await self.generate_structured(prompt, schema, system=system, temperature=0.0,
                                              task_type=kw.pop("task_type", "rubric_evaluation"), **kw)

    # Non-LLM local models, re-exported so the gateway stays the single entrypoint.
    def embed(self, texts: list[str]) -> list[list[float]]:
        from app.services.ai_gateway.embeddings import get_embedding_service

        return get_embedding_service().embed(texts)

    def rerank(self, query: str, candidates: list, top_n: int):
        from app.services.ai_gateway.embeddings import get_reranker_service

        return get_reranker_service().rerank(query, candidates, top_n)

    def transcribe(self, audio_path: str) -> dict:
        from app.services.ai_gateway.speech import get_speech_service

        return get_speech_service().transcribe(audio_path)


class _SchemaInvalid(Exception):
    pass


def trim_text(text: str, limit: int | None = None) -> str:
    """Head + tail of oversized inputs; keeps prompts small and cheap."""
    limit = limit or settings.LLM_CONTEXT_CHARS
    if len(text) <= limit:
        return text
    head = int(limit * 0.75)
    return text[:head] + "\n[... trimmed ...]\n" + text[-(limit - head):]


def _strip_reasoning(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```", 2)
        t = parts[1] if len(parts) > 1 else parts[0]
        if t.startswith("json"):
            t = t[4:]
    return t.strip()


_gateway: AIGateway | None = None


def get_ai_gateway() -> AIGateway:
    global _gateway
    if _gateway is None:
        _gateway = AIGateway()
    return _gateway
