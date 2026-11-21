from __future__ import annotations

from tests.conftest import chat


def test_first_live_then_cache_hit_in_new_session(client, provider):
    first = chat(client, "s-c1", "What is the capital of France?").json()
    second = chat(client, "s-c2", "What is the capital of France?").json()
    assert first["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert len(provider.live_calls) == 1  # the provider was only hit once


def test_cache_hit_returns_identical_reply_and_stored_usage(client):
    provider_reply = chat(client, "s-c1", "Tell me a fact").json()
    cached = chat(client, "s-c2", "Tell me a fact").json()
    assert cached["reply"] == provider_reply["reply"]
    assert cached["metadata"]["input_tokens"] == provider_reply["metadata"]["input_tokens"]
    assert cached["metadata"]["output_tokens"] == provider_reply["metadata"]["output_tokens"]


def test_cache_hit_has_null_key_and_zero_fallbacks(client):
    chat(client, "s-c1", "hello cache")
    meta = chat(client, "s-c2", "hello cache").json()["metadata"]
    assert meta["key_id"] is None
    assert meta["fallback_attempts"] == 0
    assert meta["model"] == "gemini/gemini-2.5-flash"


def test_different_message_never_served_from_cache(client):
    chat(client, "s-c1", "What is the capital of France?")
    other = chat(client, "s-c2", "What is the capital of Spain?").json()
    assert other["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert other["reply"] == "Echo: What is the capital of Spain?"


def test_different_history_never_served_from_cache(client):
    chat(client, "s-h1", "context A")
    chat(client, "s-h1", "follow up")
    chat(client, "s-h2", "context B")
    meta = chat(client, "s-h2", "follow up").json()["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"


def test_different_system_prompt_never_served_from_cache(client):
    chat(client, "s-p1", "hi there", system_prompt="Be formal.")
    meta = chat(client, "s-p2", "hi there", system_prompt="Be casual.").json()["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"


def test_cache_hit_is_faster_than_live_call(client, provider):
    provider.delay_seconds = 0.25  # simulated provider latency; cache hits never reach the provider
    live = chat(client, "s-l1", "timed question").json()["metadata"]
    cached = chat(client, "s-l2", "timed question").json()["metadata"]
    assert cached["resolution_source"] == "LLM_CACHE"
    assert live["latency_ms"] >= 250
    assert cached["latency_ms"] < live["latency_ms"]


def test_cache_hit_is_persisted_with_its_metadata(client):
    chat(client, "s-p1", "persist cache")
    chat(client, "s-p2", "persist cache")
    msgs = client.get("/sessions/s-p2/messages").json()["messages"]
    assert msgs[1]["metadata"]["resolution_source"] == "LLM_CACHE"


def test_cache_disabled_always_live(client_factory, provider):
    client = client_factory(cache_enabled=False)
    chat(client, "s-1", "same")
    meta = chat(client, "s-2", "same").json()["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert len(provider.live_calls) == 2


def test_reply_from_fallback_key_is_cached_for_any_key(client):
    chat(client, "s-f1", "shared answer", headers={"X-Simulate-Failure": "key_1=429"})
    meta = chat(client, "s-f2", "shared answer").json()["metadata"]
    assert meta["resolution_source"] == "LLM_CACHE"
