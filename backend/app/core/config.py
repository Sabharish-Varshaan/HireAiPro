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

    LLM_PROVIDER: str = "ollama"
    LLM_BASE_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "qwen3.5:4b"
    LLM_THINK: bool = False

    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    WHISPER_MODEL: str = "small.en"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"
    MAX_AUDIO_BYTES: int = 15 * 1024 * 1024
    INTERVIEW_MAX_TURNS: int = 5

    JUDGE0_URL: str = "http://localhost:2358"

    SCORING_VERSION: str = "skill_scoring_v1"
    MATCHING_VERSION: str = "matching_v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
