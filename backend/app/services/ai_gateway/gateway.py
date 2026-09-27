"""Single choke point for all model interaction.

Business services and agents must call through this gateway, never Ollama
(or any provider) directly. Swapping the backing provider (e.g. to vLLM in
production) means changing this module only.
"""

import json
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.core.config import get_settings

settings = get_settings()

T = TypeVar("T", bound=BaseModel)


class AIGatewayError(Exception):
    pass


class AIGateway:
    def __init__(self) -> None:
        self.provider = settings.LLM_PROVIDER
        self.base_url = settings.LLM_BASE_URL
        self.model = settings.LLM_MODEL

    async def generate(
        self, prompt: str, system: str | None = None, temperature: float = 0.2
    ) -> str:
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "system": system or "",
                        "stream": False,
                        "think": settings.LLM_THINK,
                        "options": {"temperature": temperature, "num_predict": 1024, "num_ctx": 8192},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "")
        except httpx.HTTPError as exc:
            raise AIGatewayError(f"LLM generate failed: {exc}") from exc
        finally:
            self._latency_ms = (time.monotonic() - started) * 1000

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system: str | None = None,
        temperature: float = 0.1,
        max_retries: int = 1,
    ) -> T:
        """Generate JSON constrained to a Pydantic schema, with repair retries."""
        schema_json = json.dumps(schema.model_json_schema())
        full_system = (
            (system or "")
            + "\n\nYou must respond with ONLY valid JSON matching this JSON Schema, "
            "no markdown fences, no commentary:\n"
            + schema_json
        )
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            raw = await self.generate(prompt, system=full_system, temperature=temperature)
            cleaned = _strip_code_fences(raw)
            try:
                return schema.model_validate_json(cleaned)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                prompt = (
                    f"Your previous response was invalid: {exc}\n"
                    f"Previous response was:\n{raw}\n\n"
                    "Respond again with ONLY corrected valid JSON matching the schema."
                )
        raise AIGatewayError(f"generate_structured failed after retries: {last_error}")

    async def extract_structured(self, text: str, schema: type[T], instruction: str) -> T:
        prompt = f"{instruction}\n\n---\nSOURCE TEXT:\n{text}\n---"
        return await self.generate_structured(prompt, schema)

    async def evaluate_rubric(
        self, answer_text: str, rubric: dict[str, Any], schema: type[T]
    ) -> T:
        prompt = (
            "Evaluate the candidate's answer strictly against the rubric below. "
            "Do not invent correctness that is not supported by the answer text.\n\n"
            f"RUBRIC:\n{json.dumps(rubric)}\n\nCANDIDATE ANSWER:\n{answer_text}"
        )
        return await self.generate_structured(prompt, schema, temperature=0.0)


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)
        t = t[1] if len(t) > 1 else t[0]
        if t.startswith("json"):
            t = t[4:]
    return t.strip()


_gateway: AIGateway | None = None


def get_ai_gateway() -> AIGateway:
    global _gateway
    if _gateway is None:
        _gateway = AIGateway()
    return _gateway
