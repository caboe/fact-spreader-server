"""Application configuration (PURPOSE §3.15, IMPLEMENT §3).

Every secret is a ``SecretStr`` so that an accidental ``repr(settings)`` or a structured
log line cannot leak it. Provider keys reach the database only through the bootstrap CLI,
where they are encrypted before the row is written.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- runtime ---------------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    public_base_url: str = "http://127.0.0.1:8000"
    app_secret_key: SecretStr = SecretStr("dev-only-change-me-please-32-bytes-min")

    # --- storage ---------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://factspreader:factspreader@localhost:5432/app"
    redis_url: str = "redis://localhost:6379/0"

    # --- stock LightRAG ---------------------------------------------------------
    lightrag_base_url: str = "http://localhost:9621"
    lightrag_api_key: SecretStr = SecretStr("")
    lightrag_timeout_seconds: float = 180.0
    lightrag_top_k: int = 40
    lightrag_chunk_top_k: int = 20

    # --- internal LLM gateway ---------------------------------------------------
    internal_llm_key: SecretStr = SecretStr("")
    lightrag_internal_key: SecretStr = SecretStr("")
    internal_gateway_url: str = "http://127.0.0.1:8000/internal/llm/v1"
    llm_input_cost_per_mtok: float = 0.30
    llm_output_cost_per_mtok: float = 0.50
    monthly_budget_usd: float = 15.0
    user_budget_usd: float = 15.0
    provider_timeout_seconds: float = 120.0
    research_summary_timeout_seconds: float = 60.0
    cache_similarity_threshold: float = 0.93

    # --- bootstrap providers (Phase 1 only) ------------------------------------
    deepseek_api_key: SecretStr = SecretStr("")
    provider_chat_base_url: str = "https://api.deepseek.com/v1"
    provider_chat_model: str = "deepseek-flash"
    provider_embedding_base_url: str = "http://host.docker.internal:11434/v1"
    provider_embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    openrouter_api_key: SecretStr = SecretStr("")
    provider_vision_base_url: str = "https://openrouter.ai/api/v1"
    provider_vision_model: str = ""
    vision_enabled: bool = False

    # --- bootstrap admin (Phase 1; the setup wizard replaces it) ---------------
    bootstrap_admin_email: str = "admin@example.org"
    bootstrap_admin_password: SecretStr = SecretStr("change-me-now")

    # --- behaviour -------------------------------------------------------------
    supported_languages: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["en", "de", "fr", "es"]
    )
    default_response_language: str = "en"
    max_text_chars: int = 20_000
    url_fetch_timeout_seconds: float = 10.0
    url_fetch_max_bytes: int = 20_000_000
    upload_max_bytes: int = 20_000_000
    image_max_bytes: int = 15_000_000
    image_max_pixels: int = 20_000_000
    rate_limit_per_minute: int = 60
    cors_extension_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    publisher_list_path: str = "../methodology/publishers.json"
    personas_path: str = "../PERSONAS.md"
    checklist_dir: str = "../methodology/checklists"
    pattern_list_path: str = "../methodology/patterns.json"
    fixture_corpus_dir: str = "../tests/fixtures/corpus"
    docs_openapi_path: str = "../docs/openapi.json"

    @field_validator("supported_languages", "cors_extension_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def secret_material(self) -> bytes:
        """Derive Fernet/session material from the deployment secret."""
        return self.app_secret_key.get_secret_value().encode("utf-8")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
