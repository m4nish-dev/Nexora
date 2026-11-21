from __future__ import annotations

import litellm
import pytest

from app.services.failure_simulation import parse_simulation_header
from app.services.llm_gateway import classify_provider_error
from tests.conftest import KEY_1, KEY_2, MODEL, chat

ALL_UNAVAILABLE = {"detail": "all providers unavailable"}


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_simulated_failure_on_key_1_fails_over_to_key_2(client, provider, status):
    response = chat(client, "s-fo", "hello failover", headers={"X-Simulate-Failure": f"key_1={status}"})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Echo: hello failover"  # a real (provider) answer, not an error in a 200
    meta = body["metadata"]
    assert meta["key_id"] == "key_2"
    assert meta["fallback_attempts"] == 1
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["failed_attempts"][0]["key_id"] == "key_1"
    assert meta["failed_attempts"][0]["status"] == status
    # key_1's attempt went through LiteLLM with the simulated exception; key_2 really answered.
    assert [c["api_key"] for c in provider.calls] == [KEY_1, KEY_2]
    assert [c["api_key"] for c in provider.live_calls] == [KEY_2]


@pytest.mark.parametrize("header", ["*=429", "key_1=429,key_2=500", "key_1=503,key_2=502"])
def test_all_keys_failing_returns_503(client, header):
    response = chat(client, "s-down", "hello", headers={"X-Simulate-Failure": header})
    assert response.status_code == 503
    assert response.json() == ALL_UNAVAILABLE


def test_failed_request_is_not_persisted(client):
    chat(client, "s-nopersist", "hello", headers={"X-Simulate-Failure": "*=429"})
    assert client.get("/sessions/s-nopersist/messages").status_code == 404


def test_failed_turn_does_not_pollute_existing_history(client):
    chat(client, "s-mixed", "turn one")
    chat(client, "s-mixed", "turn two", headers={"X-Simulate-Failure": "*=500"})
    msgs = client.get("/sessions/s-mixed/messages").json()["messages"]
    assert [m["content"] for m in msgs] == ["turn one", "Echo: turn one"]


def test_simulation_is_scoped_to_one_request(client):
    chat(client, "s-scope", "first", headers={"X-Simulate-Failure": "key_1=429"})
    meta = chat(client, "s-scope", "second").json()["metadata"]
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0


def test_simulation_bypasses_cache_reads(client):
    chat(client, "s-a", "cached question")
    meta = chat(client, "s-b", "cached question", headers={"X-Simulate-Failure": "key_1=429"}).json()["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["key_id"] == "key_2"


def test_explicit_key_overrides_wildcard(client):
    meta = chat(client, "s-w", "hi", headers={"X-Simulate-Failure": "*=429,key_2=500"})
    assert meta.status_code == 503
    client2_meta = chat(client, "s-w2", "hi", headers={"X-Simulate-Failure": "key_2=500"}).json()["metadata"]
    assert client2_meta["key_id"] == "key_1"


def test_simulation_ignored_when_disabled(client_factory, provider):
    client = client_factory(enable_failure_simulation=False)
    response = chat(client, "s-off", "hello", headers={"X-Simulate-Failure": "*=429"})
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_1"


@pytest.mark.parametrize("header", ["key_1", "key_1=404", "key_1=abc", "bogus=429", "=429"])
def test_malformed_simulation_header_returns_422(client, provider, header):
    response = chat(client, "s-bad", "hello", headers={"X-Simulate-Failure": header})
    assert response.status_code == 422
    assert "detail" in response.json()
    assert provider.calls == []


def test_three_key_pool_counts_attempts(client_factory):
    client = client_factory(llm_api_keys=f"{KEY_1},{KEY_2},third-secret")
    meta = chat(client, "s-3", "hi", headers={"X-Simulate-Failure": "key_1=429,key_2=503"}).json()["metadata"]
    assert meta["key_id"] == "key_3"
    assert meta["fallback_attempts"] == 2


# --- genuine provider errors (not the header) -------------------------------------------------


def _err(cls, **kw):
    return cls(message="boom", llm_provider="gemini", model=MODEL, **kw)


@pytest.mark.parametrize(
    "error",
    [
        _err(litellm.RateLimitError),
        _err(litellm.InternalServerError),
        _err(litellm.ServiceUnavailableError),
        _err(litellm.BadGatewayError),
        _err(litellm.Timeout),
        _err(litellm.AuthenticationError),
        litellm.BadRequestError(message="Quota exceeded for this project", llm_provider="gemini", model=MODEL),
        litellm.BadRequestError(message="API key not valid. Please pass a valid API key.", llm_provider="gemini", model=MODEL),
    ],
    ids=lambda e: type(e).__name__,
)
def test_real_key_level_errors_fail_over(client, provider, error):
    provider.failures[KEY_1] = error
    response = chat(client, "s-real", "hello")
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_2"
    assert response.json()["metadata"]["fallback_attempts"] == 1


def test_real_failures_on_every_key_return_503(client, provider):
    provider.failures[KEY_1] = _err(litellm.RateLimitError)
    provider.failures[KEY_2] = _err(litellm.ServiceUnavailableError)
    response = chat(client, "s-real-down", "hello")
    assert response.status_code == 503
    assert response.json() == ALL_UNAVAILABLE


def test_request_level_error_is_not_retried_on_other_keys(client, provider):
    provider.failures[KEY_1] = litellm.ContextWindowExceededError(
        message="prompt too long", llm_provider="gemini", model=MODEL
    )
    response = chat(client, "s-ctx", "hello")
    assert response.status_code == 502
    assert response.json() == {"detail": "upstream provider rejected the request"}
    assert len(provider.calls) == 1
    assert client.get("/sessions/s-ctx/messages").status_code == 404


def test_provider_error_text_with_key_is_never_returned(client, provider):
    leaky = f"403 Forbidden for url https://generativelanguage.googleapis.com/v1?key={KEY_1}"
    provider.failures[KEY_1] = litellm.InternalServerError(message=leaky, llm_provider="gemini", model=MODEL)
    provider.failures[KEY_2] = litellm.InternalServerError(message=leaky, llm_provider="gemini", model=MODEL)
    response = chat(client, "s-leak", "hello")
    assert response.status_code == 503
    assert KEY_1 not in response.text


def test_empty_completion_is_not_reported_as_success(client, provider):
    provider.reply_fn = lambda msgs: "   "
    response = chat(client, "s-empty", "hello")
    assert response.status_code == 502
    assert client.get("/sessions/s-empty/messages").status_code == 404


# --- unit: header parsing and classification ------------------------------------------------


def test_parse_header_examples():
    assert parse_simulation_header("key_1=429", enabled=True).status_for("key_1") == 429
    plan = parse_simulation_header("key_1=429, key_2=500", enabled=True)
    assert (plan.status_for("key_1"), plan.status_for("key_2"), plan.status_for("key_3")) == (429, 500, None)
    star = parse_simulation_header("*=429", enabled=True)
    assert star.status_for("key_1") == star.status_for("key_9") == 429
    assert parse_simulation_header("*=429", enabled=False) is None
    assert parse_simulation_header(None, enabled=True) is None


def test_classifier_does_not_retry_plain_bad_requests():
    verdict = classify_provider_error(litellm.BadRequestError(message="invalid role", llm_provider="gemini", model=MODEL))
    assert verdict.retryable is False
