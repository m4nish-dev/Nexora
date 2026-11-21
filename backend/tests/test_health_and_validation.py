from __future__ import annotations

import pytest

from tests.conftest import chat


def test_health_ok_reports_key_pool_and_cache(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["keys_configured"] == 2
    assert body["cache_enabled"] is True


def test_health_counts_actual_keys(client_factory):
    client = client_factory(llm_api_keys="a,b,c")
    assert client.get("/health").json()["keys_configured"] == 3


def test_health_reports_cache_disabled(client_factory):
    client = client_factory(cache_enabled=False)
    assert client.get("/health").json()["cache_enabled"] is False


def test_health_503_when_database_unreachable(client):
    client.app.state.database.path = "/nonexistent-dir/definitely/missing.db"
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["detail"] == "database unavailable"


def test_health_503_when_no_keys(client_factory):
    client = client_factory(llm_api_keys="")
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["detail"] == "no API keys configured"


def test_health_never_exposes_secrets(client):
    from tests.conftest import KEY_1, KEY_2

    text = client.get("/health").text
    assert KEY_1 not in text and KEY_2 not in text


@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "s1", "message": ""},
        {"session_id": "s1", "message": "   \n\t "},
        {"session_id": "s1", "message": "x" * 4001},
        {"session_id": "s1"},
        {"message": "hello"},
        {"session_id": "", "message": "hello"},
        {"session_id": "   ", "message": "hello"},
        {"session_id": "s" * 129, "message": "hello"},
        {"session_id": "s1", "message": 123},
        {"session_id": "s1", "message": None},
        {"session_id": "s1", "message": "hi", "system_prompt": "p" * 8001},
    ],
)
def test_chat_validation_returns_422(client, provider, payload):
    response = client.post("/chat", json=payload)
    assert response.status_code == 422
    assert "detail" in response.json()
    assert provider.calls == []


def test_malformed_json_returns_422(client, provider):
    response = client.post("/chat", content=b'{"session_id": "s1", "message": ', headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert "detail" in response.json()
    assert provider.calls == []


def test_message_limit_counts_after_trimming(client):
    padded = "  " + "x" * 4000 + "  \n"
    assert chat(client, "s-trim", padded).status_code == 200


def test_session_id_boundaries_accepted(client):
    assert chat(client, "a", "hello").status_code == 200
    assert chat(client, "s" * 128, "hello").status_code == 200


def test_validation_failure_is_not_persisted(client):
    client.post("/chat", json={"session_id": "s-val", "message": ""})
    assert client.get("/sessions/s-val/messages").status_code == 404


def test_unknown_route_is_json(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_cors_allows_configured_origin_and_simulation_header(client):
    response = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_unknown_origin(client):
    response = client.options(
        "/chat", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in response.headers


def test_empty_env_values_fall_back_to_defaults(monkeypatch, tmp_path):
    from app.config import DEFAULT_SYSTEM_PROMPT, Settings

    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "")
    monkeypatch.setenv("DEFAULT_SYSTEM_PROMPT", "")
    monkeypatch.setenv("LLM_API_KEYS", " k1 , k2 ,, ")
    settings = Settings(_env_file=None)
    assert settings.llm_max_output_tokens is None
    assert settings.default_system_prompt == DEFAULT_SYSTEM_PROMPT
    assert settings.api_keys == ["k1", "k2"]


def test_database_url_parsing():
    from app.config import sqlite_path_from_url

    assert sqlite_path_from_url("sqlite:////data/app.db") == "/data/app.db"
    assert sqlite_path_from_url("sqlite:///./app.db") == "./app.db"
    for bad in ("postgres://x/y", "sqlite:///:memory:", "sqlite:///"):
        with pytest.raises(ValueError):
            sqlite_path_from_url(bad)


def test_per_key_models(client_factory):
    client = client_factory(llm_api_keys="a,b", llm_key_models=",openai/gpt-4o-mini")
    assert client.get("/health").json()["models"] == ["gemini/gemini-2.5-flash", "openai/gpt-4o-mini"]
