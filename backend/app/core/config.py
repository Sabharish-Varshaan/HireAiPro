from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "HireAiPro"
    ENV: str = "development"

    DATABASE_URL: str = "postgresql+asyncpg://hireai:hireai@localhost:5432/hireai"
    VALKEY_URL: str = "redis://localhost:6379/0"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION_PREFIX: str = ""
    UPLOAD_DIR: str = "data/uploads"

    JWT_SECRET: str = "dev-only-insecure-secret-change-me-0000000000"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7

    # ---- LLM routing (see docs/AI_ROUTING_AND_COST.md) ------------------
    # "router" = task-aware routing across groq/openai/ollama. LOCAL_ONLY forces Ollama.
    LLM_PROVIDER: str = "router"
    LOCAL_ONLY: bool = False
    LLM_PRIMARY_PROVIDER: str = "groq"          # complex/agentic tasks
    LLM_CHEAP_PROVIDER: str = "openai"          # simple structured tasks
    LLM_LOCAL_FALLBACK_PROVIDER: str = "ollama"  # offline / emergency
    LLM_THINK: bool = False

    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_CHEAP_MODEL: str = "gpt-6-luna"
    OPENAI_ESCALATION_MODEL: str = "gpt-6-sol"

    OLLAMA_BASE_URL: str = "http://localhost:11435"
    OLLAMA_MODEL: str = "qwen3.5:4b"

    # Cost governor. Spend is the application's own tracked estimate from
    # ai_runs, not the authoritative OpenAI account balance.
    OPENAI_DAILY_SOFT_LIMIT_USD: float = 0.25
    OPENAI_DAILY_HARD_LIMIT_USD: float = 0.35
    OPENAI_STARTING_BUDGET_USD: float = 6.50
    OPENAI_RESERVE_USD: float = 3.00

    LLM_MAX_RETRIES: int = 1
    LLM_MAX_AGENT_TURNS: int = 6
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_OLLAMA_TIMEOUT_SECONDS: int = 300
    LLM_MAX_OUTPUT_TOKENS: int = 1536
    LLM_CONTEXT_CHARS: int = 12000

    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    EMBEDDING_FP16: bool = True
    MODEL_IDLE_UNLOAD_SECONDS: int = 300  # free local models after 5 idle minutes; 0 keeps them resident

    WHISPER_MODEL: str = "small.en"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"
    MAX_AUDIO_BYTES: int = 15 * 1024 * 1024
    INTERVIEW_MAX_TURNS: int = 5

    JUDGE0_URL: str = "http://localhost:2358"
    JUDGE0_POLL_TIMEOUT_SECONDS: int = 30  # per test case; past it the run fails closed (never re-run unsandboxed)

    SCORING_VERSION: str = "skill_scoring_v1"
    MATCHING_VERSION: str = "matching_v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
