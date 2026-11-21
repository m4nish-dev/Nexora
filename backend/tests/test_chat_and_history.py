from __future__ import annotations

import sqlite3
import threading

from app.config import DEFAULT_SYSTEM_PROMPT
from tests.conftest import KEY_1, KEY_2, MODEL, chat, fake_token_count


def test_chat_success_matches_contract(client):
    response = chat(client, "s-7f3a", "What is the capital of France?")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "s-7f3a"
    assert body["reply"] == "Echo: What is the capital of France?"
    meta = body["metadata"]
    assert set(meta) >= {
        "resolution_source",
        "model",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "key_id",
        "fallback_attempts",
    }
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == MODEL
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] >= 0
    assert isinstance(meta["input_tokens"], int) and meta["input_tokens"] > 0
    assert isinstance(meta["output_tokens"], int) and meta["output_tokens"] > 0
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0


def test_response_never_contains_key_material(client):
    text = chat(client, "s-secret", "hello").text
    assert KEY_1 not in text and KEY_2 not in text


def test_message_is_trimmed_before_sending(client, provider):
    chat(client, "s-trim", "   hello world   ")
    assert provider.calls[0]["messages"][-1] == {"role": "user", "content": "hello world"}


def test_multi_turn_sends_full_history(client, provider):
    chat(client, "s-multi", "My name is Ada.")
    chat(client, "s-multi", "What is my name?")
    sent = provider.calls[-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "My name is Ada."
    assert sent[2]["content"] == "Echo: My name is Ada."
    assert sent[3]["content"] == "What is my name?"


def test_tokens_are_per_request_not_running_totals(client, provider):
    first = chat(client, "s-tok", "one two three").json()["metadata"]
    second = chat(client, "s-tok", "four five six").json()["metadata"]
    # Input tokens equal exactly what this request sent (system + history + new message)...
    assert second["input_tokens"] == fake_token_count(provider.calls[-1]["messages"])
    # ...and output tokens are this reply only, not accumulated.
    assert second["output_tokens"] == len("Echo: four five six".split())
    assert second["input_tokens"] != first["input_tokens"] + second["output_tokens"] + first["output_tokens"]


def test_equal_length_first_messages_report_same_input_tokens(client):
    a = chat(client, "s-a", "alpha beta gamma").json()["metadata"]["input_tokens"]
    b = chat(client, "s-b", "delta omega sigma").json()["metadata"]["input_tokens"]
    assert a == b


def test_default_system_prompt_is_used(client, provider):
    chat(client, "s-sys", "hi")
    assert provider.calls[0]["messages"][0] == {"role": "system", "content": DEFAULT_SYSTEM_PROMPT}


def test_custom_system_prompt_overrides_and_persists_for_session(client, provider):
    chat(client, "s-pirate", "hi", system_prompt="Talk like a pirate.")
    chat(client, "s-pirate", "and again")  # no system_prompt: session keeps the custom one
    assert provider.calls[0]["messages"][0]["content"] == "Talk like a pirate."
    assert provider.calls[1]["messages"][0]["content"] == "Talk like a pirate."


def test_blank_system_prompt_falls_back_to_default(client, provider):
    chat(client, "s-blank", "hi", system_prompt="   ")
    assert provider.calls[0]["messages"][0]["content"] == DEFAULT_SYSTEM_PROMPT


def test_history_endpoint_shape_order_and_metadata(client):
    chat(client, "s-hist", "first")
    chat(client, "s-hist", "second")
    response = client.get("/sessions/s-hist/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "s-hist"
    msgs = body["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "first"),
        ("assistant", "Echo: first"),
        ("user", "second"),
        ("assistant", "Echo: second"),
    ]
    assert "metadata" not in msgs[0]
    meta = msgs[1]["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert isinstance(meta["input_tokens"], int) and isinstance(meta["output_tokens"], int)


def test_history_excludes_system_prompt(client):
    chat(client, "s-nosys", "hi", system_prompt="SECRET INSTRUCTIONS")
    body = client.get("/sessions/s-nosys/messages").text
    assert "SECRET INSTRUCTIONS" not in body
    assert '"system"' not in body


def test_unknown_session_returns_404(client):
    response = client.get("/sessions/never-seen/messages")
    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


def test_sessions_are_isolated(client, provider):
    chat(client, "s-one", "I like tea")
    chat(client, "s-two", "I like coffee")
    chat(client, "s-two", "What do I like?")
    sent = provider.calls[-1]["messages"]
    assert all("tea" not in m["content"] for m in sent)
    one = client.get("/sessions/s-one/messages").json()["messages"]
    assert [m["content"] for m in one] == ["I like tea", "Echo: I like tea"]


def test_history_survives_app_restart(client_factory):
    first = client_factory()
    chat(first, "s-persist", "remember me")
    first.__exit__(None, None, None)
    second = client_factory()  # same tmp_path → same SQLite file
    msgs = second.get("/sessions/s-persist/messages").json()["messages"]
    assert [m["content"] for m in msgs] == ["remember me", "Echo: remember me"]


def test_stored_rows_match_schema(client):
    chat(client, "s-schema", "hello")
    conn = sqlite3.connect(client.app.state.database.path)
    rows = conn.execute("SELECT session_id, role, content, metadata, created_at FROM messages ORDER BY id").fetchall()
    conn.close()
    assert [r[1] for r in rows] == ["user", "assistant"]
    assert rows[0][3] is None  # metadata only on assistant rows
    assert rows[1][3] is not None and '"resolution_source"' in rows[1][3]
    assert all("T" in r[4] for r in rows)  # ISO-8601


def test_concurrent_requests_same_session_do_not_interleave(client, provider):
    provider.async_delay_seconds = 0.05
    errors: list[int] = []

    def send(i: int) -> None:
        r = chat(client, "s-race", f"message {i}")
        if r.status_code != 200:
            errors.append(r.status_code)

    threads = [threading.Thread(target=send, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # Each turn must be built on every previous turn: system + 2k history + new user message.
    assert sorted(len(c["messages"]) for c in provider.calls) == [2, 4, 6, 8, 10]
    msgs = client.get("/sessions/s-race/messages").json()["messages"]
    assert len(msgs) == 10
    # Strict user/assistant alternation and each reply answers the user turn right before it.
    for user, assistant in zip(msgs[::2], msgs[1::2], strict=True):
        assert user["role"] == "user" and assistant["role"] == "assistant"
        assert assistant["content"] == f"Echo: {user['content']}"
