"""Controlled provider-fallback probe (development tool).

Makes one tiny structured call through the real AI router and prints which
provider served it. Simulate outages with process-only env overrides, e.g.:

    OPENAI_BASE_URL=http://127.0.0.1:9/v1 GROQ_BASE_URL=http://127.0.0.1:9/v1 \
        PYTHONPATH=. .venv/bin/python scripts/fallback_probe.py

Each attempt is recorded in ai_runs (task_type=qa_fallback_probe). Unload the
local model afterwards:  curl localhost:11434/api/generate -d '{"model":"qwen3.5:4b","keep_alive":0}'
"""
import asyncio

from pydantic import BaseModel

from app.services.ai_gateway.gateway import get_ai_gateway


class Out(BaseModel):
    answer: str


async def main() -> None:
    r = await get_ai_gateway().generate_structured("Fallback probe: reply with answer='ok'.", Out, task_type="qa_fallback_probe")
    print("result:", r)


asyncio.run(main())
