# Nexora — Project Plan & Progress Tracker

LLM chatbot with key failover and response caching (Lyftr AI full-stack assignment).
Stack (mandated): React (Vite) · FastAPI · LiteLLM · SQLite · Docker.

---

## 1. Requirement checklist (source of truth: assignment PDF, pp. 1–6)

Legend: ✅ done & verified · 🟡 in progress · ⬜ pending · 🔒 needs user action

### Frontend (UI) — §2, §5
| # | Requirement | Status |
|---|---|---|
| F1 | Clean UI to send messages and view a multi-turn conversation | ✅ |
| F2 | Per-reply metadata: resolution source, model, latency (ms), input/output tokens (per request, never totals) | ✅ |
| F3 | Optional system-prompt field (`system-prompt-input`) | ✅ |
| F4 | `data-testid`s: chat-input, send-button, assistant-message, meta-source, meta-model, meta-latency, meta-input-tokens, meta-output-tokens, system-prompt-input | ✅ |
| F5 | chat-input empty after sending; Enter sends; Shift+Enter newline | ✅ |
| F6 | New session on every page load | ✅ |
| F7 | 422 / 503 / network errors shown as readable chat messages, never a blank screen | ✅ |
| F8 | Deployed frontend talks to deployed backend; backend allows that origin (CORS) | 🔒 |

### Backend & LiteLLM — §2, §3, §4
| # | Requirement | Status |
|---|---|---|
| B1 | `GET /health` → `{status, keys_configured, cache_enabled}`; 200 only when DB reachable and key pool loaded | ✅ |
| B2 | `POST /chat` request validation: session_id 1–128, message 1–4000 after trim, optional system_prompt | ✅ |
| B3 | `POST /chat` response: `session_id`, `reply`, `metadata{resolution_source, model, latency_ms, input_tokens, output_tokens, key_id, fallback_attempts}` | ✅ |
| B4 | `GET /sessions/{id}/messages` oldest-first, no system prompt, assistant metadata; 404 `session not found` | ✅ |
| B5 | Multi-turn: history per session in SQLite; client sends only the new message | ✅ |
| B6 | Key pool from `LLM_API_KEYS` (≥2), ids `key_1..key_n`; never expose raw keys | ✅ |
| B7 | Failover on 429 / quota / 5xx to next key; 503 `all providers unavailable` when all fail | ✅ |
| B8 | LiteLLM built-in cache; `LLM_CACHE` vs `LIVE_INFERENCE` from LiteLLM's own cache-hit flag | ✅ |
| B9 | Cache key = model + full message list; same first message in new session → `LLM_CACHE`; different message never cached | ✅ |
| B10 | Cache hit: identical reply, stored usage, `key_id=null`, `fallback_attempts=0`, faster than live | ✅ |
| B11 | Per-request tokens (system + history + new message), never running totals | ✅ |
| B12 | Server-measured integer `latency_ms` | ✅ |
| B13 | Errors are JSON with `detail`; never stack traces/HTML; 422 / 503 / 404 exact | ✅ |
| B14 | Failed requests (422/503) not added to history | ✅ |
| B15 | `X-Simulate-Failure` (`key_1=429`, `key_1=429,key_2=500`, `*=429`; 429/500/502/503), per-request only, gated by `ENABLE_FAILURE_SIMULATION=true` | ✅ |
| B16 | Simulated request still returns a real LLM answer from the surviving key | ✅ (mocked) / 🔒 (live needs keys) |

### Storage — §2
| # | Requirement | Status |
|---|---|---|
| S1 | SQLite only (no Redis/Postgres) | ✅ |
| S2 | DB path from `DATABASE_URL` (e.g. `sqlite:////data/app.db`) on a Docker volume | ✅ |
| S3 | Schema auto-created on startup; `messages` table matches the minimal model | ✅ |

### Docker / repo / docs — §6, §7
| # | Requirement | Status |
|---|---|---|
| D1 | `make up` → backend :8000, frontend :3000 | ✅ |
| D2 | Multi-stage Dockerfiles (backend + frontend), small runtime images | ✅ |
| D3 | Root `docker-compose.yml`, named volume at `/data` | ✅ |
| D4 | Makefile with `up`, `down` | ✅ |
| D5 | All config via env vars; `.env.example` lists every variable | ✅ |
| D6 | Repo layout `/backend /frontend docker-compose.yml Makefile .env.example README.md` | ✅ |
| D7 | Backend tests | ✅ |
| D8 | README with the six required headings | ✅ |

### Deployment & submission — §2, §7
| # | Requirement | Status |
|---|---|---|
| X1 | Public frontend URL | 🔒 |
| X2 | Public backend URL with `ENABLE_FAILURE_SIMULATION=true` | 🔒 |
| X3 | Public GitHub repo | 🔒 (on hold until user approves) |
| X4 | 2–3 min demo video (cache hit + failover) | 🔒 |
| X5 | Submission form | 🔒 |

---

## 2. Architecture

```
┌──────────────────────────┐        HTTPS/JSON        ┌───────────────────────────────────────────────┐
│  React SPA (Vite)        │  POST /chat              │  FastAPI                                      │
│  - session id per load   │ ───────────────────────► │  routers/   → thin HTTP layer                 │
│  - only sends new msg    │  GET /health             │  services/chat_service  (orchestration)       │
│  - renders metadata      │  GET /sessions/{id}/...  │     ├─ repositories/messages (SQLite)         │
└──────────────────────────┘                          │     └─ services/llm_gateway                   │
                                                      │           ├─ KeyPool (key_1..key_n)           │
                                                      │           ├─ FailureSimulator (header)        │
                                                      │           └─ litellm.acompletion ─┐           │
                                                      │                                   ▼           │
                                                      │                LiteLLM in-memory Cache        │
                                                      │                (model + messages key)         │
                                                      └──────────────────────────────┬────────────────┘
                                                                                     ▼
                                                          SQLite file on /data volume (DATABASE_URL)
```

### Request flow — `POST /chat`
1. Pydantic validates the body (trims `message`; 422 on violations, including malformed JSON).
2. Acquire a **per-session asyncio lock**, so concurrent requests on the same session can't interleave history.
3. Load history from SQLite and resolve the system prompt (request > stored session prompt > default).
4. Build `messages = [system, ...history, user]`.
5. `LLMGateway.complete(messages, simulation)`: walk the key pool in order. Each attempt is a real `litellm.acompletion` call with that key, through LiteLLM's cache.
   - Cache hit (`_hidden_params["cache_hit"]`) → `LLM_CACHE`, `key_id=null`, `fallback_attempts=0`.
   - Retryable failure (429, quota, 5xx, timeout, connection, auth/permission on that key) → log the key id and status, then try the next key.
   - Non-retryable request error (400 / context window / content policy) → stop (502, no history write).
   - All keys failed → `AllProvidersUnavailable` → 503 `all providers unavailable`.
6. On success, persist the user and assistant messages (plus the session's system prompt) **in one transaction**. Nothing is written on failure.
7. Return the response with server-measured `latency_ms`, captured from request start to just before the response is sent.

## 3. Folder structure

```
backend/
  app/
    main.py                 # app factory, lifespan (schema init, cache init), CORS, error handlers
    config.py               # pydantic-settings; parses LLM_API_KEYS, DATABASE_URL, etc.
    database.py             # sqlite connection mgmt + schema migration
    schemas/chat.py         # request/response Pydantic models (exact contract)
    routers/                # health.py, chat.py, sessions.py
    services/
      key_pool.py           # ApiKey(id, model, secret), KeyPool
      failure_simulation.py # X-Simulate-Failure parser → per-request plan
      llm_gateway.py        # LiteLLM cache setup, failover loop, error classification
      chat_service.py       # orchestration: history → LLM → persist
    repositories/messages.py
    errors.py               # domain exceptions + JSON handlers
  tests/                    # pytest, deterministic (LiteLLM mock_response — no network)
  requirements.txt, Dockerfile
frontend/
  src/
    api/client.js           # fetch wrapper, typed errors (422/503/404/network)
    hooks/useChat.js, useHealth.js
    components/             # Sidebar, ChatView, MessageList, AssistantMessage, MetaBar, Composer, SystemPromptPanel, WelcomeScreen, ...
    lib/                    # session id, formatting
  Dockerfile (node build → nginx runtime, runtime-injected API URL), nginx.conf
docker-compose.yml, Makefile, .env.example, README.md
```

## 4. Database design

```sql
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content TEXT NOT NULL,
  metadata TEXT,              -- JSON, assistant rows only
  created_at TEXT NOT NULL    -- server UTC ISO-8601
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS sessions (      -- extra table: per-session system prompt (never exposed by history endpoint)
  session_id TEXT PRIMARY KEY,
  system_prompt TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```
- WAL journal mode, `busy_timeout`, and one connection per operation via `asyncio.to_thread`, so the event loop is never blocked.
- Chronological order uses `id` (monotonic AUTOINCREMENT), not `created_at`, so it stays stable when timestamps tie.

## 5. LLM integration, failover & caching

**Why a LiteLLM-driven ordered key loop rather than `litellm.Router`:**
- The contract needs **deterministic key order** (`key_1` first), **exact `fallback_attempts`**, and **per-request, per-key failure injection**.
- Router cooldowns would carry a *simulated* 429 on `key_1` into later real requests, breaking the "this request only" rule. Within one model group the Router also retries randomly, so attempt counts can't be guaranteed.
- Every provider call is still `litellm.acompletion` (LiteLLM does provider translation, exception mapping, usage accounting and caching). The loop only decides which credential comes next.

**Failure simulation:**
- The header is parsed into `{key_id: status}`.
- For a targeted key, the attempt calls `litellm.acompletion(..., mock_response=<LiteLLM exception for that status>)`. The failure is raised **inside LiteLLM's own call path** and caught by the same classifier that handles real provider errors.
- Requests that carry an active simulation skip cache **reads** (`cache={"no-cache": True}`), so a cached answer can't bypass the failover being demonstrated. Writes stay enabled.

**Cache:**
- `litellm.cache = Cache(type="local")`, an in-memory cache.
  - LiteLLM 1.110 removed the disk backend. The PDF allows in-memory, and Redis is forbidden.
- Key = LiteLLM's own hash of the model, the messages and the sampling params. `api_key` is excluded (verified), so an answer from `key_2` serves later requests on any key.
- Cache-hit detection uses LiteLLM's `_hidden_params["cache_hit"]`, never timing.
- TTL is configurable (`CACHE_TTL_SECONDS`, default 24h) with LiteLLM's built-in size bound.
- LiteLLM writes the cache in a background task. After a live call the gateway awaits pending cache writes, so an immediate identical request reliably hits.

**Tokens:**
- Taken from `response.usage.prompt_tokens` / `completion_tokens`, which are the provider-reported values.
- If usage is missing, fall back to `litellm.token_counter` and flag `usage_estimated: true`, an extra field the contract allows.

**Model compatibility:**
- At startup, `litellm.get_llm_provider(model)` validates each configured model.
- Optional `LLM_KEY_MODELS` assigns a model per key, for multi-provider pools.

## 6. Error-handling strategy
| Situation | Status | Body |
|---|---|---|
| Validation / malformed JSON | 422 | FastAPI default `{"detail":[...]}` |
| All keys failed | 503 | `{"detail":"all providers unavailable"}` |
| Provider rejected request (non-retryable 4xx) | 502 | `{"detail":"upstream provider rejected the request"}` |
| Unknown session | 404 | `{"detail":"session not found"}` |
| DB error / unexpected | 500 / 503 | `{"detail":"internal server error"}` — logged server-side, never a traceback |

Starlette's 404/405 responses are also JSON.

## 7. Testing strategy
- **pytest + TestClient** with a temporary SQLite file per test and a fresh LiteLLM cache per test.
- LLM calls are deterministic through LiteLLM's own `mock_response` (and mocked exceptions), so the **real** LiteLLM cache and exception-mapping code runs with no network.
- Areas covered: health (ok, DB down, key count), validation (empty, whitespace, >4000, session id bounds, malformed JSON), multi-turn context, system prompt, cache (hit/miss, identical reply, preserved usage, different messages, latency), failover (429, 500, 502, 503, all-fail, `*`, disabled flag, unknown key, malformed header), persistence (isolation, order, metadata, nothing persisted on failure), and real-error classification.
- A separate `scripts/smoke_test.sh` runs against a live backend with real keys.

## 8. Docker architecture
- **backend:** `python:3.12-slim` builder (wheels into a venv) → slim runtime copying the venv; non-root user; `/data` volume; healthcheck on `/health`.
- **frontend:** `node:22-alpine` build → `nginx:alpine` serving static files on :3000. An entrypoint writes `config.js` from `API_BASE_URL` at container start, so the same image works in any environment.
- **compose:** `backend` (8000), `frontend` (3000), named volume `nexora-data:/data`, env from `.env`.

## 9. Deployment plan
- **Backend → Render (Docker)** with `render.yaml`. Set env vars in the dashboard: `LLM_API_KEYS`, `ENABLE_FAILURE_SIMULATION=true`, `ALLOWED_ORIGINS=<frontend URL>`, `DATABASE_URL=sqlite:////data/app.db`. Attaching a persistent disk at `/data` needs a paid plan; without it SQLite works but resets on redeploy (documented).
- **Frontend → Vercel** (Vite preset, root `frontend/`, `VITE_API_BASE_URL=<backend URL>`).
- Deployment and GitHub publishing are **on hold until the user explicitly approves.**

## 10. Security considerations
- Keys only ever come from env vars. They're held in memory, never logged (logs show `key_1`, …), and never returned.
- The frontend has no secrets.
- `.env` is gitignored; `.env.example` has placeholders only.
- CORS is restricted to `ALLOWED_ORIGINS`.
- Strict input limits (message 4000, session_id 128, system_prompt 4000). Request bodies are size-bounded by validation.
- Parameterized SQL only.
- Generic error bodies. Provider error text is never forwarded to clients.
- Bounded failover (at most one attempt per key). Per-call timeout `LLM_TIMEOUT_SECONDS`, and `num_retries=0` inside LiteLLM so retries happen only at the key level.
- The simulation hook is off unless `ENABLE_FAILURE_SIMULATION=true`.
- Containers run as a non-root user.

## 11. Implementation phases
1. ✅ Analysis & plan
2. ✅ Foundation (venv, deps, structure)
3. ✅ Backend core (DB, schemas, routes)
4. ✅ AI gateway (LiteLLM, key pool, failover, cache, simulation)
5. ✅ Frontend
6. 🟡 Integration (local + Docker with LiteLLM-mocked provider ✅; real Gemini error path ✅; real successful completions 🔒 need keys)
7. ✅ Tests
8. ✅ Docker (`make up` / `make down` / volume persistence verified)
9. 🔒 Deployment
10. 🟡 Final QA ✅, README ✅, demo script ✅ (below); live-URL QA 🔒

---

## 12. Progress log, test results & known issues

### Verified (2026-11-21)
| Check | Result |
|---|---|
| Backend unit/integration tests (`pytest -q`) | **86 passed** |
| Concurrency test is meaningful | Fails with the session lock removed, passes with it in place (mutation check) |
| LiteLLM behaviour probes (v1.110.2) | `api_key` excluded from cache key ✓ · `_hidden_params["cache_hit"]` ✓ · usage preserved on hit ✓ · mock exceptions raise typed errors with status ✓ · cache write is a background task, so the gateway awaits it ✓ |
| Real Gemini error path | Invalid keys → live 401 from Google → classified key-level → failover → 503 JSON; no key text in logs ✓ |
| Cache-hit latency (uvicorn) | Live ≈ 945 ms vs cache 2–3 ms, identical reply and usage ✓ |
| Browser e2e (Playwright, Chromium) | All `data-testid`s present; input clears; Enter / Shift+Enter; per-message metadata; LIVE → LLM_CACHE after reload; failover via lab (key_2 + chip); 503 and 422 readable cards; Retry; new session per load; no horizontal overflow at 390 px ✓ |
| Docker | `make up` builds both images; both containers healthy; frontend ↔ backend via CORS in a real browser; history survives `make down` → `make up` on the `nexora-data` volume ✓ |
| Image sizes | backend 597 MB (from 820 MB after trimming; the remainder is LiteLLM's dependency tree), frontend 91 MB |

### Known issues / limitations
- **No real successful completion has run yet**: it needs two real provider keys. Run `backend/scripts/smoke_test.sh` once keys are set.
- The default model `gemini/gemini-2.5-flash` must be confirmed available for the keys used (`LLM_MODEL` is configurable).
- The cache is in-memory (LiteLLM 1.110 removed the disk backend), so it resets on restart; it requires a single worker.
- Render free tier has no persistent disk, so deployed history resets on redeploy (a paid disk at `/data` fixes this).
- LiteLLM 1.110's cache-hit path imports proxy modules that need `orjson` + `soundfile` (pinned; checked at startup).

### Demo video script (2–3 min)
1. (15 s) Repo layout + `make up`; open `/health` on the live backend.
2. (30 s) Live UI: ask a question, then point at the metadata (LIVE_INFERENCE, model, latency, in/out tokens, key_1).
3. (25 s) Multi-turn: "My name is Ada" → "What's my name?"; show `GET /sessions/{id}/messages`.
4. (25 s) Cache: New chat → same first question → LLM_CACHE, identical text, ~ms latency, key_id null.
5. (35 s) Failover: Failover lab `key_1 → 429` → key_2 + "1 failover"; curl `X-Simulate-Failure: key_1=500` → key_2; `*=429` → 503 card and curl 503, history 404.
6. (15 s) 422 via curl (empty message); close on the design decisions (README §3).
