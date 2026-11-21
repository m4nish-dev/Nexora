"""Smoke test that runs INSIDE the production runtime image (no pytest there):

    make test-image
    # = docker run --rm -v ./backend/tests:/app/tests:ro -v ./backend/scripts:/app/scripts:ro \
    #       nexora-backend:latest python -m scripts.image_smoke

It proves the trimmed image still has everything the real code paths need: app startup, SQLite,
LiteLLM's Gemini handler (real HTTP to a local stub — see tests/gemini_stub.py), usage mapping,
the cache-hit import path, failover on genuine HTTP errors, and the simulation hook.
Not a real-provider test; that is tests/test_live_provider.py.
"""

from __future__ import annotations

import sys
import tempfile

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.gemini_stub import GeminiStub

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f"  ({detail})" if detail != "" else ""))
    if not condition:
        FAILURES.append(name)


def client_for(keys: str, stub: GeminiStub) -> TestClient:
    settings = Settings(
        llm_api_keys=keys,
        llm_api_base=stub.base_url,
        database_url=f"sqlite:///{tempfile.mkdtemp()}/smoke.db",
        enable_failure_simulation=True,
        log_level="WARNING",
        _env_file=None,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def chat(client: TestClient, session: str, message: str, header: str | None = None):
    headers = {"X-Simulate-Failure": header} if header else {}
    return client.post("/chat", json={"session_id": session, "message": message}, headers=headers)


NATIVE_MODULES = (
    "pydantic_core._pydantic_core",
    "orjson",
    "tiktoken._tiktoken",
    "tokenizers",
    "numpy",
    "soundfile",
    "yaml._yaml",
    "aiohttp._http_parser",
    "litellm.rust_bridge._native",
    "sqlite3",
)


def check_native_extensions() -> None:
    """Every native extension must still load after the image trimming (stripped .so files)."""
    import importlib

    for name in NATIVE_MODULES:
        try:
            importlib.import_module(name)
            ok, err = True, ""
        except Exception as exc:  # report and keep going
            ok, err = False, f"{type(exc).__name__}: {exc}"
        check(f"native extension loads: {name}", ok, err)


def main() -> int:
    print("Nexora runtime-image smoke test")
    check_native_extensions()
    stub = GeminiStub(delay_seconds=0.3).start()
    with client_for("stub-ok-1,stub-ok-2", stub) as client:
        health = client.get("/health")
        check("GET /health 200, 2 keys, cache on", health.status_code == 200 and health.json()["keys_configured"] == 2
              and health.json()["cache_enabled"] is True)

        live = chat(client, "img-a", "What is the capital of France?")
        lm = live.json().get("metadata", {})
        check("live inference via LiteLLM Gemini handler", live.status_code == 200 and lm.get("resolution_source") == "LIVE_INFERENCE"
              and lm.get("key_id") == "key_1", lm.get("latency_ms"))
        check("provider usage mapped (not estimated)", lm.get("usage_estimated") is False and lm.get("input_tokens", 0) > 0)

        cached = chat(client, "img-b", "What is the capital of France?")
        cm = cached.json().get("metadata", {})
        check("same first message in new session → LLM_CACHE", cm.get("resolution_source") == "LLM_CACHE")
        check("cache hit: identical reply, same tokens, key_id null",
              cached.json().get("reply") == live.json().get("reply")
              and (cm.get("input_tokens"), cm.get("output_tokens")) == (lm.get("input_tokens"), lm.get("output_tokens"))
              and cm.get("key_id") is None)
        check("cache hit faster than live", cm.get("latency_ms", 1e9) < lm.get("latency_ms", 0),
              f"{cm.get('latency_ms')} ms vs {lm.get('latency_ms')} ms")

        chat(client, "img-m", "My name is Ada.")
        second = chat(client, "img-m", "What is my name?")
        check("multi-turn history sent to provider", second.json().get("reply", "").endswith("(turn 2)"))
        history = client.get("/sessions/img-m/messages").json().get("messages", [])
        check("history oldest-first, 4 messages, assistant metadata", len(history) == 4
              and history[0]["content"] == "My name is Ada." and "metadata" in history[1])

        sim = chat(client, "img-s", "simulate", "key_1=429").json().get("metadata", {})
        check("X-Simulate-Failure key_1=429 → key_2", sim.get("key_id") == "key_2" and sim.get("fallback_attempts") == 1)
        down = chat(client, "img-d", "simulate", "*=429")
        check("X-Simulate-Failure *=429 → 503 exact body", down.status_code == 503
              and down.json() == {"detail": "all providers unavailable"})
        check("failed request not persisted", client.get("/sessions/img-d/messages").status_code == 404)
        check("422 on empty message", chat(client, "img-v", "  ").status_code == 422)

    with client_for("stub-quota-1,stub-ok-2", stub) as client:
        fo = chat(client, "img-q", "Real HTTP 429 on key_1")
        fm = fo.json().get("metadata", {})
        check("real HTTP 429 (quota) on key_1 → key_2", fo.status_code == 200 and fm.get("key_id") == "key_2"
              and fm.get("failed_attempts", [{}])[0].get("status") == 429)
        check("key material never returned", "stub-quota-1" not in fo.text)

    stub.stop()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
