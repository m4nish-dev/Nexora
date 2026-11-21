"""Test fixtures.

LLM calls are made deterministic with LiteLLM's own ``mock_response`` hook rather than by
patching LiteLLM out. That means the real LiteLLM cache, exception mapping and response
objects are exercised in every test — only the network hop to the provider is replaced.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

KEY_1 = "test-secret-key-one"
KEY_2 = "test-secret-key-two"
MODEL = "gemini/gemini-2.5-flash"


def fake_token_count(messages: list[dict[str, str]]) -> int:
    """Deterministic stand-in for a tokenizer: grows with every message sent."""
    return sum(4 + len(m["content"].split()) for m in messages)


@dataclass
class FakeProvider:
    """Wraps ``litellm.acompletion``; decides per api_key whether the 'provider' answers or fails."""

    failures: dict[str, Exception] = field(default_factory=dict)
    reply_fn: Callable[[list[dict[str, str]]], str] = lambda msgs: f"Echo: {msgs[-1]['content']}"
    delay_seconds: float = 0.0
    async_delay_seconds: float = 0.0  # awaits, so concurrent requests genuinely interleave
    calls: list[dict[str, Any]] = field(default_factory=list)
    live_calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.async_delay_seconds:
            await asyncio.sleep(self.async_delay_seconds)
        if "mock_response" not in kwargs:  # not a simulated failure: act as the provider
            failure = self.failures.get(kwargs["api_key"])
            if failure is not None:
                kwargs["mock_response"] = failure
            else:
                text = self.reply_fn(kwargs["messages"])
                kwargs["mock_response"] = litellm.ModelResponse(
                    model=kwargs["model"],
                    choices=[{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
                    usage={
                        "prompt_tokens": fake_token_count(kwargs["messages"]),
                        "completion_tokens": len(text.split()),
                        "total_tokens": fake_token_count(kwargs["messages"]) + len(text.split()),
                    },
                )
                if self.delay_seconds:
                    kwargs["mock_delay"] = self.delay_seconds
        response = await litellm.acompletion(**kwargs)
        if not response._hidden_params.get("cache_hit"):
            self.live_calls.append(kwargs)
        return response


def make_settings(tmp_path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "llm_api_keys": f"{KEY_1},{KEY_2}",
        "llm_model": MODEL,
        "database_url": f"sqlite:///{tmp_path / 'test.db'}",
        "allowed_origins": "http://localhost:3000",
        "enable_failure_simulation": True,
        "cache_enabled": True,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client_factory(tmp_path, provider) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def factory(**overrides: Any) -> TestClient:
        app = create_app(make_settings(tmp_path, **overrides), completion_fn=provider)
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(client_factory) -> TestClient:
    return client_factory()


def chat(client: TestClient, session_id: str, message: str, headers: dict[str, str] | None = None, **extra: Any):
    return client.post("/chat", json={"session_id": session_id, "message": message, **extra}, headers=headers or {})
