"""Single choke point for all model interaction.

Business services and agents must call through this gateway, never Ollama
(or any provider) directly. Swapping the backing provider (e.g. to vLLM in
production) means changing this module only.

Every LLM call writes one `ai_runs` row (retries of the same structured call
share it). Only SHA-256 hashes of the prompt/output are stored, never the
raw text, because prompts routinely contain resume and interview content.
"""

import datetime as dt
import hashlib
import json
import time
import uuid
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.core.config import get_settings

settings = get_settings()

T = TypeVar("T", bound=BaseModel)

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
    # Own session so AI-run logging never rides on (or rolls back with) the
    # caller's business transaction. Logging failures must not break the call.
    from app.core.database import AsyncSessionLocal
    from app.models.misc import AIRun

    try:
        async with AsyncSessionLocal() as db:
            db.add(AIRun(**fields))
            await db.commit()
    except Exception:  # noqa: BLE001
        pass


class AIGateway:
    def __init__(self) -> None:
        self.provider = settings.LLM_PROVIDER
        self.base_url = settings.LLM_BASE_URL
        self.model = settings.LLM_MODEL

    async def _raw_generate(
        self, prompt: str, system: str | None, temperature: float, json_schema: dict | None = None
    ) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "system": system or "",
            "stream": False,
            "think": settings.LLM_THINK,
            "options": {"temperature": temperature, "num_predict": 1536, "num_ctx": 8192},
        }
        if json_schema is not None:
            body["format"] = json_schema
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=body)
                resp.raise_for_status()
                return resp.json().get("response", "")
        except httpx.TimeoutException as exc:
            raise AIGatewayError("LLM call timed out after 300s") from exc
        except httpx.HTTPError as exc:
            raise AIGatewayError(f"LLM call failed: {exc!r}") from exc

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.2,
        *,
        task_type: str = "generic",
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
    ) -> str:
        started_at, t0 = _now(), time.monotonic()
        status, error, output = "COMPLETED", None, ""
        try:
            output = await self._raw_generate(prompt, system, temperature)
            return output
        except AIGatewayError as exc:
            status, error = "FAILED", str(exc)
            raise
        finally:
            await _record_run(
                task_type=task_type,
                provider=self.provider,
                model=self.model,
                prompt_version=PROMPT_VERSIONS.get(task_type, PROMPT_VERSIONS["generic"]),
                status=status,
                latency_ms=(time.monotonic() - t0) * 1000,
                schema_valid=None,
                error=error,
                related_entity_type=related_entity_type,
                related_entity_id=related_entity_id,
                started_at=started_at,
                ended_at=_now(),
                input_hash=_sha((system or "") + prompt),
                output_hash=_sha(output) if output else None,
            )

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system: str | None = None,
        temperature: float = 0.1,
        max_retries: int = 1,
        *,
        task_type: str = "generic",
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
    ) -> T:
        """JSON constrained to a Pydantic schema. The schema is sent both in
        the prompt and as Ollama's `format` so the decoder is constrained;
        invalid output gets one repair retry."""
        json_schema = schema.model_json_schema()
        full_system = (
            (system or "")
            + "\n\nRespond with ONLY valid JSON matching this JSON Schema, no commentary:\n"
            + json.dumps(json_schema)
        )
        started_at, t0 = _now(), time.monotonic()
        last_error: Exception | None = None
        raw = ""
        current_prompt = prompt
        try:
            for _attempt in range(max_retries + 1):
                raw = await self._raw_generate(current_prompt, full_system, temperature, json_schema)
                try:
                    result = schema.model_validate_json(_strip_code_fences(raw))
                    await _record_run(
                        task_type=task_type, provider=self.provider, model=self.model,
                        prompt_version=PROMPT_VERSIONS.get(task_type, PROMPT_VERSIONS["generic"]),
                        status="COMPLETED", latency_ms=(time.monotonic() - t0) * 1000, schema_valid=True,
                        related_entity_type=related_entity_type, related_entity_id=related_entity_id,
                        started_at=started_at, ended_at=_now(),
                        input_hash=_sha(full_system + prompt), output_hash=_sha(raw),
                    )
                    return result
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    current_prompt = (
                        f"{prompt}\n\nYour previous response was invalid ({exc}). "
                        "Respond again with ONLY corrected valid JSON matching the schema."
                    )
            error = f"schema validation failed after retries: {last_error}"
            schema_valid = False
        except AIGatewayError as exc:
            error, schema_valid = str(exc), None
        await _record_run(
            task_type=task_type, provider=self.provider, model=self.model,
            prompt_version=PROMPT_VERSIONS.get(task_type, PROMPT_VERSIONS["generic"]),
            status="FAILED", latency_ms=(time.monotonic() - t0) * 1000, schema_valid=schema_valid,
            error=error, related_entity_type=related_entity_type, related_entity_id=related_entity_id,
            started_at=started_at, ended_at=_now(),
            input_hash=_sha(full_system + prompt), output_hash=_sha(raw) if raw else None,
        )
        raise AIGatewayError(error)

    async def extract_structured(
        self, text: str, schema: type[T], instruction: str, *, task_type: str = "generic", **kw: Any
    ) -> T:
        prompt = f"{instruction}\n\n---\nSOURCE TEXT:\n{text}\n---"
        return await self.generate_structured(prompt, schema, task_type=task_type, **kw)

    async def evaluate_rubric(
        self, answer_text: str, rubric: dict[str, Any], schema: type[T], **kw: Any
    ) -> T:
        prompt = (
            "Evaluate the candidate's answer strictly against the rubric below. "
            "Do not invent correctness that is not supported by the answer text. "
            "An empty, off-topic or nonsensical answer scores near 0 on every criterion.\n\n"
            f"RUBRIC:\n{json.dumps(rubric)}\n\nCANDIDATE ANSWER:\n{answer_text}"
        )
        return await self.generate_structured(
            prompt, schema, temperature=0.0, task_type="rubric_evaluation", **kw
        )

    # Non-LLM model calls live in sibling modules but are re-exported here so
    # the gateway stays the single entrypoint callers depend on.
    def embed(self, texts: list[str]) -> list[list[float]]:
        from app.services.ai_gateway.embeddings import get_embedding_service

        return get_embedding_service().embed(texts)

    def rerank(self, query: str, candidates: list, top_n: int):
        from app.services.ai_gateway.embeddings import get_reranker_service

        return get_reranker_service().rerank(query, candidates, top_n)

    def transcribe(self, audio_path: str) -> dict:
        from app.services.ai_gateway.speech import get_speech_service

        return get_speech_service().transcribe(audio_path)


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
