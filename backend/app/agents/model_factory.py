"""PydanticAI model construction for the four agents.

Points at Ollama through its OpenAI-compatible `/v1` endpoint. Verified with
pydantic-ai 2.51: Qwen3.5 performs real tool calls in the default tool-output
mode once reasoning is disabled. `NativeOutput`/`PromptedOutput` were tried
and rejected — with them the model skipped tool calls and invented values.
"""

from functools import lru_cache

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import get_settings

AGENT_MODEL_SETTINGS = {
    "temperature": 0,
    # Ollama's OpenAI-compatible endpoint maps this to disabling Qwen's
    # thinking phase; without it each agent turn spends minutes reasoning.
    "extra_body": {"reasoning_effort": "none"},
    "timeout": 240,
}


@lru_cache
def get_agent_model() -> OpenAIChatModel:
    settings = get_settings()
    return OpenAIChatModel(
        settings.LLM_MODEL,
        provider=OpenAIProvider(base_url=f"{settings.LLM_BASE_URL}/v1", api_key="ollama"),
    )
