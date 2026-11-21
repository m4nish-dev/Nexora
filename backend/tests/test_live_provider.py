"""Real-provider integration tests: genuine LiteLLM calls with real API keys. No mocks.

Opt-in only (they cost tokens and need network):

    NEXORA_LIVE=1 LLM_API_KEYS="real-key-1,real-key-2" LLM_MODEL=gemini/gemini-3.5-flash-lite \
        .venv/bin/python -m pytest -m live -v
    # or: make test-live   (reads the repo-root .env)

They are skipped otherwise — and skipped, never passed, when the keys look like placeholders.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.live

_KEYS = [k.strip() for k in os.environ.get("LLM_API_KEYS", "").split(",") if k.strip()]
_MODEL = os.environ.get("LLM_MODEL", "gemini/gemini-3.5-flash-lite")
_PLACEHOLDER = any(k.startswith("your-") for k in _KEYS)

if os.environ.get("NEXORA_LIVE") != "1":
    pytest.skip("live provider tests are opt-in: set NEXORA_LIVE=1", allow_module_level=True)
if len(_KEYS) < 2 or _PLACEHOLDER:
    pytest.skip("live provider tests need 2 real keys in LLM_API_KEYS", allow_module_level=True)


def _client(tmp_path, keys: list[str]) -> TestClient:
    settings = Settings(
        llm_api_keys=",".join(keys),
        llm_model=_MODEL,
        database_url=f"sqlite:///{tmp_path / 'live.db'}",
        enable_failure_simulation=True,
        _env_file=None,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)  # real litellm.acompletion


def _unique(text: str) -> str:
    # A run-unique suffix guarantees the first call is a genuine provider call, not a cache hit.
    return f"{text} (ref {uuid.uuid4().hex[:8]})"


def _chat(client, session, message, headers=None):
    return client.post("/chat", json={"session_id": session, "message": message}, headers=headers or {})


def test_live_inference_then_cache_hit(tmp_path):
    with _client(tmp_path, _KEYS) as client:
        question = _unique("In one short sentence, what is the capital of France?")
        live = _chat(client, "live-a", question)
        assert live.status_code == 200, live.text
        live_body = live.json()
        meta = live_body["metadata"]
        assert meta["resolution_source"] == "LIVE_INFERENCE"
        assert meta["key_id"] == "key_1" and meta["fallback_attempts"] == 0
        assert meta["model"] == _MODEL
        assert live_body["reply"].strip()
        assert meta["input_tokens"] > 0 and meta["output_tokens"] > 0
        assert meta["usage_estimated"] is False, "provider did not report usage"

        cached = _chat(client, "live-b", question)
        assert cached.status_code == 200, cached.text
        cmeta = cached.json()["metadata"]
        assert cmeta["resolution_source"] == "LLM_CACHE"
        assert cached.json()["reply"] == live_body["reply"]
        assert (cmeta["input_tokens"], cmeta["output_tokens"]) == (meta["input_tokens"], meta["output_tokens"])
        assert cmeta["key_id"] is None and cmeta["fallback_attempts"] == 0
        assert cmeta["latency_ms"] < meta["latency_ms"]


def test_live_multi_turn_memory(tmp_path):
    with _client(tmp_path, _KEYS) as client:
        session = f"live-mem-{uuid.uuid4().hex[:6]}"
        assert _chat(client, session, "My favourite colour is teal. Reply with just OK.").status_code == 200
        second = _chat(client, session, "What is my favourite colour? Answer with one word.")
        assert second.status_code == 200, second.text
        assert "teal" in second.json()["reply"].lower()
        history = client.get(f"/sessions/{session}/messages").json()["messages"]
        assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]


@pytest.mark.parametrize("status", [429, 500])
def test_live_simulated_failover_returns_real_answer(tmp_path, status):
    with _client(tmp_path, _KEYS) as client:
        response = _chat(client, "live-fo", _unique("Say hello in French."), {"X-Simulate-Failure": f"key_1={status}"})
        assert response.status_code == 200, response.text
        meta = response.json()["metadata"]
        assert meta["key_id"] == "key_2" and meta["fallback_attempts"] == 1
        assert meta["resolution_source"] == "LIVE_INFERENCE"
        assert meta["output_tokens"] > 0 and response.json()["reply"].strip()


def test_live_all_keys_failing_returns_503_and_persists_nothing(tmp_path):
    with _client(tmp_path, _KEYS) as client:
        response = _chat(client, "live-down", _unique("hello"), {"X-Simulate-Failure": "key_1=429,key_2=500"})
        assert response.status_code == 503
        assert response.json() == {"detail": "all providers unavailable"}
        assert client.get("/sessions/live-down/messages").status_code == 404


def test_live_real_provider_error_triggers_failover(tmp_path):
    """A genuinely invalid key_1 is rejected by the provider itself; key_2 (real) must answer."""
    with _client(tmp_path, ["invalid-key-for-failover-test", _KEYS[0]]) as client:
        response = _chat(client, "live-real-err", _unique("Reply with the word ready."))
        assert response.status_code == 200, response.text
        meta = response.json()["metadata"]
        assert meta["key_id"] == "key_2" and meta["fallback_attempts"] == 1
        assert meta["failed_attempts"][0]["key_id"] == "key_1"
        assert "invalid-key-for-failover-test" not in response.text
