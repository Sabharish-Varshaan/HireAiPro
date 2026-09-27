"""Deterministic stand-ins for the LLM, used only where a test is about
something *other* than model quality (idempotency, tenancy, plumbing).
Every test that needs real model behaviour is marked `live` instead."""

import json
from typing import Any

from app.services.ai_gateway import gateway as gw


class FakeLLM:
    """Patches AIGateway.generate_structured. `responses` maps a schema
    class name to a dict or a callable(prompt) -> dict. Every prompt is
    recorded so tests can assert what was (not) sent to the model."""

    def __init__(self, monkeypatch, responses: dict[str, Any]):
        self.responses = responses
        self.prompts: list[str] = []
        fake = self

        async def generate_structured(self_, prompt, schema, system=None, temperature=0.1, max_retries=1, **kw):
            fake.prompts.append((system or "") + "\n" + prompt)
            r = fake.responses[schema.__name__]
            data = r(prompt) if callable(r) else r
            return schema.model_validate(data)

        monkeypatch.setattr(gw.AIGateway, "generate_structured", generate_structured)

    def all_text(self) -> str:
        return "\n".join(self.prompts)


def jd_skills(*items: tuple[str, str, float, float]) -> dict:
    return {"skills": [
        {"raw_skill_name": n, "requirement_type": r, "minimum_level": lvl, "importance": imp,
         "evidence_text": f"needs {n}", "extraction_confidence": 0.9} for n, r, lvl, imp in items]}


def rubric(score: float, conf: float = 0.8) -> dict:
    return {"concept_accuracy": score, "reasoning": score, "completeness": score, "communication": score,
            "demonstrated_concepts": [], "missing_concepts": [], "evaluator_confidence": conf}
