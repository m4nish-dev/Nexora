"""TEST-ONLY server for the frontend browser suite (frontend/e2e). Never used in production.

Runs the real Nexora app: real routes, SQLite, LiteLLM cache and failover gateway. The only
stand-in is the provider network hop, replaced by the same LiteLLM ``mock_response`` fake the
pytest suite uses, so UI tests are deterministic and need no API keys. Every simulated live call
takes ~0.6 s; cache hits never reach the provider, so their latency stays in milliseconds.

    python -m tests.e2e_server --port 8100 --origin http://localhost:3100
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import uvicorn

from app.main import create_app
from tests.conftest import FakeProvider, make_settings


def reply_for(messages: list[dict[str, str]]) -> str:
    system, last = messages[0]["content"], messages[-1]["content"]
    prefix = "Arr! " if "pirate" in system.lower() else ""
    if "caching" in last.lower():
        return (
            f"{prefix}Response caching stores the model's answer keyed by the **exact prompt**.\n\n"
            "1. **Lower latency** - a memory lookup takes milliseconds.\n"
            "2. **Lower cost** - cached replies consume no provider tokens.\n\n"
            "```python\nlitellm.cache = Cache(type=\"local\")\n```"
        )
    turns = sum(1 for m in messages if m["role"] == "user")
    return f"{prefix}You said: *{last}* (turn {turns} of this session)."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--origin", default="http://localhost:3100")
    args = parser.parse_args()
    data_dir = Path(tempfile.mkdtemp(prefix="nexora-e2e-"))
    provider = FakeProvider(reply_fn=reply_for, delay_seconds=0.6)
    app = create_app(make_settings(data_dir, allowed_origins=args.origin, log_level="WARNING"), completion_fn=provider)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
