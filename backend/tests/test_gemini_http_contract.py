"""HTTP-level integration tests: real ``litellm.acompletion`` (no ``mock_response``, no injected
completion function) talking real HTTP to a local Gemini REST stub.

Unlike the mocked suites, these exercise LiteLLM's actual Gemini handler: request building,
response parsing, usage mapping, and HTTP status → exception mapping for genuine 429 / 500 / 503 /
invalid-key responses. Real-provider behaviour is covered separately by test_live_provider.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import MODEL, make_settings
from tests.gemini_stub import GeminiStub

ALL_DOWN = {"detail": "all providers unavailable"}


@pytest.fixture
def stub():
    server = GeminiStub().start()
    yield server
    server.stop()


@pytest.fixture
def http_client_factory(tmp_path, stub):
    clients = []

    def factory(keys: str) -> TestClient:
        settings = make_settings(tmp_path, llm_api_keys=keys, llm_api_base=stub.base_url)
        client = TestClient(create_app(settings), raise_server_exceptions=False)  # production completion path
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


def chat(client, session, message, headers=None):
    return client.post("/chat", json={"session_id": session, "message": message}, headers=headers or {})


def test_live_reply_parsed_from_gemini_response(http_client_factory, stub):
    client = http_client_factory("stub-ok-1,stub-ok-2")
    body = chat(client, "h-1", "What is the capital of France?").json()
    assert body["reply"] == "Stub reply to: What is the capital of France? (turn 1)"
    meta = body["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["key_id"] == "key_1" and meta["fallback_attempts"] == 0
    # Tokens are the provider's usageMetadata, mapped by LiteLLM — not estimated.
    assert meta["usage_estimated"] is False
    assert meta["output_tokens"] == len(body["reply"].split())
    assert stub.requests[0]["path"].endswith(f"/models/{MODEL.split('/', 1)[1]}:generateContent")


def test_cache_hit_never_reaches_the_provider(http_client_factory, stub):
    client = http_client_factory("stub-ok-1,stub-ok-2")
    live = chat(client, "h-a", "Cache me").json()
    cached = chat(client, "h-b", "Cache me").json()
    assert cached["metadata"]["resolution_source"] == "LLM_CACHE"
    assert cached["reply"] == live["reply"]
    assert cached["metadata"]["input_tokens"] == live["metadata"]["input_tokens"]
    assert cached["metadata"]["output_tokens"] == live["metadata"]["output_tokens"]
    assert cached["metadata"]["key_id"] is None
    assert cached["metadata"]["latency_ms"] < live["metadata"]["latency_ms"]
    assert len(stub.requests) == 1


def test_history_and_system_prompt_reach_the_provider(http_client_factory, stub):
    client = http_client_factory("stub-ok-1,stub-ok-2")
    chat(client, "h-mt", "My name is Ada.")
    second = chat(client, "h-mt", "What is my name?").json()
    assert second["reply"].endswith("(turn 2)")
    contents = stub.requests[-1]["body"]["contents"]
    texts = [" ".join(p["text"] for p in c["parts"]) for c in contents]
    assert texts[0] == "My name is Ada." and texts[-1] == "What is my name?"
    assert "Stub reply to: My name is Ada." in texts[1]
    assert second["metadata"]["input_tokens"] > chat(client, "h-x", "What is my name?").json()["metadata"]["input_tokens"]


# `status` is LiteLLM's normalised status for the provider's HTTP response (LiteLLM 1.110 maps Gemini's
# 503 UNAVAILABLE to InternalServerError/500 and its 400 "API key not valid" to AuthenticationError/401).
@pytest.mark.parametrize(
    ("first_key", "status"),
    [("stub-quota-1", 429), ("stub-server-error-1", 500), ("stub-unavailable-1", 500), ("stub-invalid-1", 401)],
)
def test_real_http_errors_fail_over_to_key_2(http_client_factory, stub, first_key, status):
    client = http_client_factory(f"{first_key},stub-ok-2")
    response = chat(client, "h-fo", "Fail over please")
    assert response.status_code == 200, response.text
    meta = response.json()["metadata"]
    assert meta["key_id"] == "key_2" and meta["fallback_attempts"] == 1
    assert meta["failed_attempts"][0]["key_id"] == "key_1"
    assert meta["failed_attempts"][0]["status"] == status
    assert stub.keys_called() == [first_key, "stub-ok-2"]
    assert first_key not in response.text


def test_every_key_failing_over_http_returns_503(http_client_factory, stub):
    client = http_client_factory("stub-quota-1,stub-unavailable-2")
    response = chat(client, "h-down", "hello")
    assert response.status_code == 503
    assert response.json() == ALL_DOWN
    assert client.get("/sessions/h-down/messages").status_code == 404
    assert "stub-quota-1" not in response.text


def test_simulated_failure_header_with_real_http_provider(http_client_factory, stub):
    client = http_client_factory("stub-ok-1,stub-ok-2")
    meta = chat(client, "h-sim", "simulated", {"X-Simulate-Failure": "key_1=429"}).json()["metadata"]
    assert meta["key_id"] == "key_2" and meta["fallback_attempts"] == 1
    # The simulated failure never left the process: only key_2 hit the provider.
    assert stub.keys_called() == ["stub-ok-2"]
    both = chat(client, "h-sim2", "simulated", {"X-Simulate-Failure": "key_1=429,key_2=500"})
    assert both.status_code == 503 and both.json() == ALL_DOWN
