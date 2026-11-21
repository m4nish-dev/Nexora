"""TEST-ONLY local stand-in for the Google AI Studio (Gemini) REST API.

LiteLLM is pointed at it with ``api_base`` and speaks real HTTP to it, so these code paths run
exactly as in production: request building, response parsing, ``usageMetadata`` → usage mapping,
and HTTP status → LiteLLM exception mapping. It is NOT a substitute for real-provider tests
(tests/test_live_provider.py); it validates our integration with LiteLLM's Gemini handler.

Behaviour is chosen per API key (sent by LiteLLM in the ``x-goog-api-key`` header):
    "ok"           → 200 with a deterministic reply and usage
    "quota"        → 429 RESOURCE_EXHAUSTED (Gemini's quota/rate-limit error)
    "server-error" → 500 INTERNAL
    "unavailable"  → 503 UNAVAILABLE
    "invalid"      → 400 INVALID_ARGUMENT "API key not valid" (what Gemini returns for bad keys)
Keys are matched by prefix, e.g. "stub-ok-1" behaves as "ok".
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_ERRORS = {
    "quota": (429, "RESOURCE_EXHAUSTED", "Resource has been exhausted (e.g. check quota)."),
    "server-error": (500, "INTERNAL", "An internal error has occurred."),
    "unavailable": (503, "UNAVAILABLE", "The model is overloaded. Please try again later."),
    "invalid": (400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."),
}


def _behaviour(api_key: str) -> str:
    key = api_key.removeprefix("stub-")
    for name in ("quota", "server-error", "unavailable", "invalid"):
        if key.startswith(name):
            return name
    return "ok"


def _text_of(content: dict) -> str:
    return " ".join(part.get("text", "") for part in content.get("parts", []))


@dataclass
class GeminiStub:
    delay_seconds: float = 0.25
    requests: list[dict] = field(default_factory=list)  # (api_key, body) of every request received
    _server: ThreadingHTTPServer | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> GeminiStub:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # keep test output clean
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                api_key = self.headers.get("x-goog-api-key", "")
                stub.requests.append({"api_key": api_key, "path": self.path.split("?")[0], "body": body})
                time.sleep(stub.delay_seconds)
                behaviour = _behaviour(api_key)
                if behaviour in _ERRORS:
                    code, status, message = _ERRORS[behaviour]
                    self._json(code, {"error": {"code": code, "message": message, "status": status}})
                    return
                contents = body.get("contents", [])
                last = _text_of(contents[-1]) if contents else ""
                system = _text_of(body.get("system_instruction") or body.get("systemInstruction") or {})
                turns = sum(1 for c in contents if c.get("role") == "user")
                reply = f"Stub reply to: {last} (turn {turns})"
                prompt_tokens = len((system + " " + " ".join(_text_of(c) for c in contents)).split()) + 3 * len(contents)
                self._json(
                    200,
                    {
                        "candidates": [
                            {"content": {"parts": [{"text": reply}], "role": "model"}, "finishReason": "STOP", "index": 0}
                        ],
                        "usageMetadata": {
                            "promptTokenCount": prompt_tokens,
                            "candidatesTokenCount": len(reply.split()),
                            "totalTokenCount": prompt_tokens + len(reply.split()),
                        },
                        "modelVersion": "gemini-3.5-flash-lite",
                    },
                )

            def _json(self, code: int, payload: dict) -> None:
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def keys_called(self) -> list[str]:
        return [r["api_key"] for r in self.requests]
