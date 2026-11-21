# Nexora: LLM chat with key failover and response caching

Nexora is a full-stack chatbot. A **React** UI talks to a **FastAPI** backend, which sends every model call through **LiteLLM**:
- **Key failover:** an ordered pool of API keys. A 429, quota error or 5xx on one key moves the request to the next key automatically.
- **Response cache:** LiteLLM's built-in cache. Every reply is labelled `LLM_CACHE` or `LIVE_INFERENCE`.
- **Persistent history:** conversations are stored per session in **SQLite** on a Docker volume.

Each reply in the UI carries its own metadata: resolution source, model, server-measured latency, and input/output tokens for that request only.

```
React (Vite, Tailwind)  ──HTTP/JSON──►  FastAPI
  new session per load                    routers → ChatService (per-session lock)
  sends only the new message                 ├─ MessageRepository ──► SQLite (/data/app.db)
  renders per-reply metadata                 └─ LLMGateway
                                                  ├─ KeyPool  key_1 … key_n (ordered)
                                                  ├─ X-Simulate-Failure plan (per request)
                                                  └─ litellm.acompletion ◄─► LiteLLM in-memory Cache
```

---

## 1. Live URLs

| Tier | URL |
|---|---|
| Frontend | _to be added after deployment_ |
| Backend | _to be added after deployment_ (health: `/health`) |
| Repository | _to be added_ |

The deployed backend runs with `ENABLE_FAILURE_SIMULATION=true`, so the failover hook can be tried on the live URL.

---

## 2. Run locally

### With Docker (recommended)

```bash
cp .env.example .env        # then put two real keys in LLM_API_KEYS
make up                     # builds and starts both services
```

- Frontend: <http://localhost:3000>
- Backend: <http://localhost:8000> (`GET /health`, OpenAPI docs at `/docs`)
- `make down` stops the stack. The SQLite file stays on the named volume `nexora-data` (mounted at `/data`), so history survives restarts.
- `make clean` also deletes that volume.
- Other targets: `make logs`, `make ps`, `make test`.

If `.env` is missing, `make up` creates it from `.env.example`. The stack still starts, but chat returns 503 until real keys are configured.

### Without Docker

Backend (Python 3.12):

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export LLM_API_KEYS="key-one,key-two" DATABASE_URL="sqlite:///./data/app.db" ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --port 8000
pytest -q                   # 86 tests, no network needed
```

Frontend (Node 20+):

```bash
cd frontend
npm install
VITE_API_BASE_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `LLM_API_KEYS` | (none) | **Required.** Comma-separated key pool; ids are `key_1`, `key_2`, … in order |
| `LLM_MODEL` | `gemini/gemini-2.5-flash` | LiteLLM model used by every key |
| `LLM_KEY_MODELS` | (empty) | Optional per-key models aligned with the keys (multi-provider pools); blanks fall back to `LLM_MODEL` |
| `DATABASE_URL` | `sqlite:////data/app.db` (Docker) | SQLite location |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins (`*` allowed) |
| `ENABLE_FAILURE_SIMULATION` | `false` (compose sets `true`) | Enables the `X-Simulate-Failure` hook |
| `LLM_TIMEOUT_SECONDS` | `30` | Per-attempt provider timeout |
| `LLM_MAX_OUTPUT_TOKENS` | provider default | Optional output cap |
| `CACHE_ENABLED` / `CACHE_TTL_SECONDS` / `CACHE_MAX_ITEMS` | `true` / `86400` / `1000` | LiteLLM cache settings |
| `DEFAULT_SYSTEM_PROMPT` | built-in | Default system prompt |
| `LOG_LEVEL` | `INFO` | Backend log level |
| `API_BASE_URL` | `http://localhost:8000` | Frontend container: backend URL the browser uses (injected at runtime) |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Same, at build time (Vercel / `npm run dev`) |

---

## 3. Design decisions

### Key fallback

`LLMGateway.complete()` ([backend/app/services/llm_gateway.py](backend/app/services/llm_gateway.py)) walks the key pool **in order**. Each attempt is a real `litellm.acompletion(model, messages, api_key=…)` call.

LiteLLM handles provider translation, maps provider errors to typed exceptions, and reports usage. Every exception is classified:

| Outcome | Examples | Action |
|---|---|---|
| Key/provider-level failure | `RateLimitError` (429, quota / `RESOURCE_EXHAUSTED`), 500/502/503, timeouts, connection errors, 401/403 (revoked or invalid key) | Log `key_id` + status, **try the next key** |
| Request-level failure | `ContextWindowExceeded`, content policy, plain 400 | Stop. Another key would fail the same way. Return 502 |
| Every key failed | | **503 `{"detail": "all providers unavailable"}`** |

- Attempts are bounded: at most one per key. `num_retries=0` inside LiteLLM, so no retries are hidden.
- `key_id` and `fallback_attempts` come straight from the loop. `metadata.failed_attempts` (an extra field) lists which keys failed and with what status.
- Raw keys are never returned or logged. Provider error text is redacted before logging, because Gemini puts the key in its URL. Clients only see generic error bodies.

**Why not `litellm.Router`?** The contract needs three things Router doesn't give reliably:
- deterministic order (`key_1` first)
- an exact attempt count
- failures injected *for one request only*

Router cooldowns are process-wide, so a simulated 429 on `key_1` would bench that key for later real traffic. Router also picks deployments within a model group at random. The ordered loop is about 60 lines, uses LiteLLM for every call, and is fully testable.

**Failover test hook.** `X-Simulate-Failure: key_1=429,key_2=500` (or `*=429`) is parsed into a per-request plan. Supported statuses are 429, 500, 502 and 503. A malformed header returns 422. When `ENABLE_FAILURE_SIMULATION` is off, the header is ignored.

For a targeted key, the gateway passes the matching **LiteLLM exception as `mock_response`** (`RateLimitError`, `InternalServerError`, `BadGatewayError`, `ServiceUnavailableError`):
- The failure is raised inside LiteLLM's own call path and handled by the same classifier as a real provider error.
- The surviving key makes a **real** provider call, so the answer is genuine.
- Simulated requests skip cache *reads*, so a cached answer can't bypass the failover being demonstrated. Writes stay enabled.

### Caching

- **Engine:** LiteLLM's built-in cache, `litellm.cache = Cache(type="local")`, which is in-memory with a TTL and a size bound.
  - LiteLLM 1.110 removed its disk backend.
  - The assignment allows in-memory and rules out Redis.
  - Trade-off: the cache resets on restart, and it is per-process, so the server runs one uvicorn worker.
- **Key:** LiteLLM's hash of `model + messages + sampling params`. `messages` is the full list sent to the model (system prompt + stored history + new message).
  - The same first message in a new session therefore produces the same key, and any difference in message, history, system prompt or model produces a different key.
  - LiteLLM leaves `api_key` out of the hash (verified), so an answer from `key_2` serves later requests on any key.
- **Detection:** `response._hidden_params["cache_hit"]`, LiteLLM's own flag, never timing. A cache hit returns:
  - the identical reply text
  - the token usage stored with the cached response
  - `key_id: null` and `fallback_attempts: 0`
- **Deterministic writes:** LiteLLM writes cache entries in a background task. After a live call, the gateway awaits the pending write, so sending the same message immediately afterwards reliably hits.
- **Warm-up:** at startup the gateway preloads the modules LiteLLM imports lazily on the first hit. This keeps the first hit fast and fails fast if a dependency is missing.
- **Measured:** a cache hit takes about 2–3 ms versus about 1 s for a live call.

### SQLite session storage

- **Schema:** the `messages` table matches the assignment's model, plus a `CHECK` on `role` and an index on `(session_id, id)`.
  - A small `sessions` table holds each session's system prompt. It is never returned by the history endpoint.
  - The schema is created idempotently at startup. The database runs in WAL mode.
- **Atomic turns:** the user and assistant messages are written in **one transaction, after** the model succeeds. A 422, 502 or 503 never touches history, and a turn can't be half-written.
- **Concurrency:** a per-session `asyncio.Lock` serialises turns of the *same* session, so two concurrent requests can't both build on stale history. A test proves this by removing the lock and watching it fail. Different sessions never block each other.
  - Locks are held weakly so idle sessions don't leak memory.
- **Non-blocking:** each DB call is a short-lived connection run via `asyncio.to_thread`, so the event loop never blocks on disk.
- **Ordering:** history is ordered by the monotonic `id`, oldest first. `created_at` is server UTC ISO-8601.
- **System prompt precedence:** the request's `system_prompt`, then the session's stored prompt, then the default. The prompt is part of the cache key.

### Other decisions

- **Tokens:** `usage.prompt_tokens` / `completion_tokens` as reported by the provider for that one request.
  - If a provider ever omits usage, LiteLLM's tokenizer estimates it and `usage_estimated: true` is returned. Values are never invented.
- **Latency:** `time.perf_counter()` from the start of the handler to just before persistence. It is an integer in milliseconds.
- **Errors:** every error is JSON with `detail`. Custom handlers cover domain errors, Starlette 404/405, SQLite errors (503) and anything unexpected (500, logged server-side, no traceback).
- **Frontend runtime config:** the nginx container writes `config.js` from `API_BASE_URL` at start, so one image works anywhere. Vercel uses `VITE_API_BASE_URL` at build time.
- **Images:**
  - Backend: multi-stage, a slim runtime with only the venv and app, a non-root user, and no bytecode, pip, or LiteLLM proxy UI assets (820 MB → about 600 MB). The rest is LiteLLM's own dependency tree.
  - Frontend: multi-stage, unprivileged nginx at about 90 MB.

---

## 4. Verification

### In the UI

1. **Cache hit:** send *"What is the capital of France?"* and note `LIVE_INFERENCE`. Click **New chat** (or reload, which starts a new session) and send the same text. The reply is identical and tagged `LLM_CACHE`, with a few ms of latency, the same tokens, and no key chip.
2. **Failover:** in the sidebar's **Failover lab**, pick `key_1 → 429` and send any message.
   - The reply is a real answer tagged `key_2` with an amber **1 failover** chip; hover it to see `key_1 → 429`.
   - Pick `All keys → 429` to see the readable **All providers unavailable (HTTP 503)** card, with Retry.
3. **Tokens:** every reply shows `in N · out M` for that request alone. In a multi-turn chat, `in` grows with history while `out` reflects only that reply.
4. **Memory:** say *"My name is Ada"*, then ask *"What's my name?"*.

### With curl

```bash
B=http://localhost:8000
curl -s $B/health
# {"status":"ok","keys_configured":2,"cache_enabled":true,...}

curl -s -X POST $B/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"s-1","message":"What is the capital of France?"}'
# metadata.resolution_source = LIVE_INFERENCE, key_id = key_1

curl -s -X POST $B/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"s-2","message":"What is the capital of France?"}'
# metadata.resolution_source = LLM_CACHE, key_id = null, same reply, lower latency_ms

curl -s -X POST $B/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"s-3","message":"Say hi"}'
# 200, key_id = key_2, fallback_attempts = 1

curl -s -i -X POST $B/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"s-4","message":"Say hi"}'
# 503 {"detail":"all providers unavailable"}, and GET /sessions/s-4/messages → 404 (nothing stored)

curl -s $B/sessions/s-1/messages
# oldest-first history with assistant metadata; unknown id → 404 {"detail":"session not found"}
```

`backend/scripts/smoke_test.sh <base-url>` runs all of the above, plus multi-turn memory, 404 and 422, against a live backend with real keys.

### Automated tests

`make test` (or `cd backend && pytest -q`) runs **86 tests** with no network:
- **Health:** ok, DB down, no keys, key count, cache flag.
- **Validation:** empty or whitespace message, more than 4000 characters (counted after trimming), session id bounds, wrong types, malformed JSON.
- **Chat:** contract shape, multi-turn context, per-request tokens, system prompt handling.
- **Cache:** live → cached across sessions, identical reply and usage, different message, history or system prompt never cached, cache hit faster than live.
- **Failover:** 429, 500, 502 and 503 on `key_1`; all-fail 503; `*`; precedence; three-key pools; real (non-simulated) provider errors including invalid-key and quota 400s; non-retryable 400s; key redaction; disabled hook; malformed header.
- **Persistence:** isolation, ordering, restart survival, schema, nothing persisted on failure, concurrent same-session turns.

Provider responses are injected through LiteLLM's own `mock_response`, so the real LiteLLM cache and exception code runs in every test.

---

## 5. Setup Used

- **Editor:** Visual Studio Code
- **AI tools:** Claude Code (Anthropic) as a pair-programming agent for architecture, implementation, tests and documentation. LiteLLM behaviour (cache key, cache-hit flag, background cache writes, mock exceptions) was verified empirically against the installed version, not assumed.
- **Local runtime:** macOS, Python 3.12 (uv), Node 22, Docker via Colima.

---

## 6. Bonus features (if any)

- **Failover lab in the UI:** one-click `X-Simulate-Failure` presets that apply to the next message only, so failover can be demonstrated without curl.
- **Failover transparency:** `key_id`, a failover chip, and `failed_attempts` (which keys failed and with what status) on every reply. These are extra response fields, which the contract allows.
- **System status panel:** live backend health and latency, model, key-pool size and cache state, polled from `/health`.
- **Session panel:** session id with copy, plus turn, cache-hit and failover counts (never token totals).
- **System-prompt editor** with apply and reset, per session. The prompt persists server-side for the session and is part of the cache key.
- **Error UX:** readable error cards per failure type (503, 422, network, timeout) with **Retry** that re-sends without duplicating the message.
- **Markdown replies** (GFM tables, code blocks), copy-reply, light and dark themes, a mobile drawer, reduced-motion support, and keyboard-friendly controls.
- **Hardening:** per-session locking, atomic turn writes, key redaction in logs, fail-fast model validation, a non-root container, and nginx security headers.

---

## API reference

| Method & path | Success | Errors |
|---|---|---|
| `GET /health` | `200 {"status":"ok","keys_configured":2,"cache_enabled":true, …}` | `503` if the DB is unreachable or no keys are configured |
| `POST /chat` | `200 {"session_id","reply","metadata":{resolution_source, model, latency_ms, input_tokens, output_tokens, key_id, fallback_attempts, …}}` | `422` validation or malformed header · `502` provider rejected the request · `503 {"detail":"all providers unavailable"}` |
| `GET /sessions/{id}/messages` | `200 {"session_id","messages":[{role, content, metadata?}]}` | `404 {"detail":"session not found"}` |

Interactive docs are at `/docs` (FastAPI OpenAPI).

## Project structure

```
backend/
  app/
    main.py                  app factory, lifespan wiring, CORS
    config.py                env-driven settings
    database.py              SQLite connection, schema
    errors.py                domain errors → JSON
    schemas/chat.py          request/response contract
    repositories/messages.py history persistence (atomic turns)
    services/
      key_pool.py            key ids, model validation, redaction
      failure_simulation.py  X-Simulate-Failure parsing → LiteLLM exceptions
      llm_gateway.py         LiteLLM cache + ordered failover + classification
      chat_service.py        orchestration, per-session locks
    routers/                 health, chat, sessions
  tests/                     pytest suite (86 tests)
  scripts/smoke_test.sh      live end-to-end check
  Dockerfile
frontend/
  src/
    components/              Sidebar, Composer, Messages, MetaBar, WelcomeScreen, ui/
    hooks/                   useChat, useHealth, useTheme, useAutoScroll
    lib/                     api client, session ids, formatting
  docker/                    nginx.conf, runtime config entrypoint
  Dockerfile
docker-compose.yml  Makefile  .env.example  render.yaml
```

## Deployment

- **Backend → Render:** New Blueprint → this repo (`render.yaml`, Docker, root `backend/`). Set `LLM_API_KEYS` and `ALLOWED_ORIGINS=<frontend URL>`. The blueprint sets `ENABLE_FAILURE_SIMULATION=true`.
  - Render's free plan has no persistent disk, so `/data` resets on redeploy. A paid plan can mount a disk at `/data` (commented in `render.yaml`).
- **Frontend → Vercel:** import the repo, set root directory `frontend/` (Vite preset) and `VITE_API_BASE_URL=<backend URL>`.
- Then add the Vercel URL to the backend's `ALLOWED_ORIGINS`.
