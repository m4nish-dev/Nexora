"""Application configuration.

Every setting comes from environment variables (optionally a local ``.env`` file),
so the same image runs unchanged in Docker, on Render, or on a laptop.
"""

from __future__ import annotations

from functools import cached_property

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = (
    "You are Nexora, a precise and helpful AI assistant. "
    "Answer clearly and concisely, use Markdown when it improves readability, "
    "and say so when you are unsure."
)


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    # --- LLM gateway -------------------------------------------------------
    llm_api_keys: str = Field(default="", description="Comma-separated key pool; ids are key_1..key_n in order")
    llm_model: str = Field(default="gemini/gemini-2.5-flash", description="LiteLLM model used by every key")
    llm_key_models: str = Field(
        default="",
        description="Optional comma-separated per-key models aligned with LLM_API_KEYS (blank entries fall back to LLM_MODEL)",
    )
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    llm_max_output_tokens: int | None = Field(default=None, gt=0)

    # --- cache ---------------------------------------------------------------
    cache_enabled: bool = True
    cache_ttl_seconds: int = Field(default=86_400, gt=0)
    cache_max_items: int = Field(default=1_000, gt=0)

    # --- storage / http --------------------------------------------------------
    database_url: str = "sqlite:///./data/app.db"
    allowed_origins: str = "http://localhost:3000"
    enable_failure_simulation: bool = False

    # --- behaviour -------------------------------------------------------------
    default_system_prompt: str = DEFAULT_SYSTEM_PROMPT
    log_level: str = "INFO"

    @field_validator("llm_model")
    @classmethod
    def _model_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LLM_MODEL must not be empty")
        return value.strip()

    @field_validator("default_system_prompt")
    @classmethod
    def _prompt_not_blank(cls, value: str) -> str:
        return value.strip() or DEFAULT_SYSTEM_PROMPT

    @cached_property
    def api_keys(self) -> list[str]:
        return _split_csv(self.llm_api_keys)

    @cached_property
    def key_models(self) -> list[str]:
        """Model per key, aligned with ``api_keys``."""
        overrides = [item.strip() for item in self.llm_key_models.split(",")] if self.llm_key_models else []
        return [
            (overrides[i] if i < len(overrides) and overrides[i] else self.llm_model)
            for i in range(len(self.api_keys))
        ]

    @cached_property
    def cors_origins(self) -> list[str]:
        return _split_csv(self.allowed_origins)

    @cached_property
    def sqlite_path(self) -> str:
        return sqlite_path_from_url(self.database_url)


def sqlite_path_from_url(url: str) -> str:
    """Translate a SQLAlchemy-style SQLite URL into a filesystem path.

    ``sqlite:////data/app.db`` -> ``/data/app.db`` (absolute)
    ``sqlite:///./data/app.db`` -> ``./data/app.db`` (relative)
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError("DATABASE_URL must start with 'sqlite:///' (only SQLite is supported)")
    path = url[len(prefix) :]
    if not path or path == ":memory:":
        raise ValueError("DATABASE_URL must point to a database file (in-memory SQLite is not persistent)")
    return path
