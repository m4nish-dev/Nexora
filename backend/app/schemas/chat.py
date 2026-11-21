"""Request/response models. Field names mirror the assignment contract exactly."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ResolutionSource = Literal["LIVE_INFERENCE", "LLM_CACHE"]

SessionId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]

SYSTEM_PROMPT_MAX_CHARS = 8000


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strict=True)

    session_id: SessionId
    message: MessageText
    system_prompt: str | None = Field(default=None, max_length=SYSTEM_PROMPT_MAX_CHARS)

    @field_validator("system_prompt")
    @classmethod
    def _blank_prompt_means_default(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class FailedAttempt(BaseModel):
    key_id: str
    status: int | None
    reason: str


class ChatMetadata(BaseModel):
    resolution_source: ResolutionSource
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int
    # Extra fields (allowed by the contract) that make the UI and debugging more informative.
    usage_estimated: bool = False
    failed_attempts: list[FailedAttempt] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    metadata: dict[str, Any] | None = None
    created_at: str | None = None


class SessionHistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    keys_configured: int
    cache_enabled: bool
    models: list[str]
    failure_simulation_enabled: bool
    default_system_prompt: str
