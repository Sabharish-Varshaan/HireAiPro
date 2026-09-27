"""Shared PydanticAI model construction, pointed at the AI Gateway's provider.

Only the four agents import this. All other business logic goes through
app.services.ai_gateway instead of touching PydanticAI/Ollama directly.
"""

from functools import lru_cache

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import get_settings


@lru_cache
def get_agent_model() -> OpenAIChatModel:
    settings = get_settings()
    return OpenAIChatModel(
        settings.LLM_MODEL,
        provider=OpenAIProvider(base_url=f"{settings.LLM_BASE_URL}/v1", api_key="ollama"),
    )
