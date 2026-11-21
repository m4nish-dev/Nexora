# Nexora — Project Plan & Progress Tracker

LLM chatbot with key failover and response caching (Lyftr AI full-stack assignment).
Stack (mandated): React (Vite) · FastAPI · LiteLLM · SQLite · Docker.

---

## 1. Assignment compliance audit (source of truth: the PDF, re-read 2026-11-21)

Statuses: **PASS** = implemented and verified by running it · **PARTIAL** = implemented but incomplete or not fully verifiable · **FAIL** = missing or broken · **BLOCKED** = needs an external credential or service.
"Fake provider" means the real app, real LiteLLM cache and real failover code, with only the provider network hop replaced by LiteLLM's `mock_response`.

**Phase scope:** GitHub publishing, deployment, live URLs and the demo video are **POSTPONED** for this phase (local completion only).

### §2 Frontend (UI)
| Requirement | Status | Evidence |
|---|---|---|
| Clean UI to send messages and view a multi-turn conversation | PASS | e2e: send, multi-turn, history; screenshots desktop / tablet / mobile / dark |
| Per-reply source, model, latency (ms), input/output tokens for that request only | PASS | e2e checks every reply has its own `meta-*`; input tokens grow per turn (not totals) |
| Optional system-prompt field | PASS | e2e: Apply changes the reply; Reset restores the default in the same session (bug fixed this phase) |

### §2 Backend & LiteLLM gateway
| Requirement | Status | Evidence |
|---|---|---|
| Multi-turn state stored per session; bot remembers earlier messages | PASS (fake provider) / BLOCKED (real model) | pytest `test_multi_turn_sends_full_history`; e2e "turn 2"; live memory test needs keys |
| ≥2 keys through LiteLLM; fail over on 429 / quota / 5xx | PASS (simulated + real 401) / BLOCKED (real successful key_2) | pytest 429/500/502/503, quota-400, invalid-key-400, timeout; live Gemini 401s failed over to 503 in Docker |
| User never sees a broken screen or unhandled exception | PASS | JSON 500 with CORS (fixed this phase); ErrorBoundary; e2e 503 / 422 cards |
| LiteLLM built-in cache; LLM_CACHE / LIVE_INFERENCE from LiteLLM's own cache-hit flag | PASS (fake provider) / BLOCKED (after a real response) | pytest cache suite; e2e reload → LLM_CACHE at 3 ms |
| Per-request token tracking | PASS (fake provider) / BLOCKED (real usage values) | pytest per-request tokens; live test asserts `usage_estimated == false` |

### §2 Storage
| Requirement | Status | Evidence |
|---|---|---|
| SQLite only (no Redis / Postgres) | PASS | Only `sqlite3`; LiteLLM cache is `type="local"` |
| DB under a Docker volume via `DATABASE_URL`; survives restarts | PASS | Docker: `/data/app.db` on `nexora_nexora-data`; rows survived several `make down` / `make up` cycles |
| Schema created automatically | PASS | `Database.initialize()` in lifespan; fresh-volume start verified |
| `messages` table matches the minimal model | PASS | `test_stored_rows_match_schema` |

### §3 API contract
| Requirement | Status | Evidence |
|---|---|---|
| `GET /health` → `{status, keys_configured, cache_enabled}`; 200 only when DB and key pool are OK | PASS | pytest (ok, DB down 503, no keys 503); Docker curl 200 |
| `POST /chat` validation (session_id 1–128, message 1–4000 after trim, optional system_prompt) | PASS | pytest 11 cases + boundaries; Docker curl 422s (empty, missing, 4001, malformed JSON) |
| `session_id` echoed verbatim | PASS | Was trimmed before (contract deviation); fixed and tested this phase |
| Response fields `reply, resolution_source, model, latency_ms, input_tokens, output_tokens, key_id, fallback_attempts` | PASS | `test_chat_success_matches_contract` |
| `GET /sessions/{id}/messages`: oldest first, no system prompt, assistant metadata; 404 for unknown | PASS | pytest history tests; e2e history check; Docker curl 404 |
| Every error is JSON `detail`, no traceback / HTML; failed requests not stored | PASS | pytest 404 / 405 / 500 / 502 / 503; nothing persisted on 422 / 502 / 503 |
| Cache key = model + full message list; same first message in a new session hits; different message never does | PASS | pytest: different message / history / system prompt → LIVE |
| Cache hit: identical reply, stored tokens, `key_id` null | PASS (fake provider) / BLOCKED (real) | pytest + e2e |
| Tokens per request; equal-length first messages ≈ same input_tokens | PASS (fake provider) / BLOCKED (real) | `test_equal_length_first_messages_report_same_input_tokens` |
| Integer `latency_ms`; cache hit faster than live | PASS | pytest controlled-delay test; uvicorn 945 ms live vs 2–3 ms cached |

### §4 Failover test hook
| Requirement | Status | Evidence |
|---|---|---|
| Header format, `*`, statuses 429/500/502/503 | PASS | pytest parser tests; malformed → 422 |
| Failure raised inside LiteLLM's call path, this request only, keys not disabled | PASS | `mock_response=<LiteLLM exception>`; `test_simulation_is_scoped_to_one_request` |
| `key_1=429` / `key_1=500` → 200, key_2 | PASS (fake provider) / BLOCKED (real key_2 answer) | pytest + e2e UI; `test_live_simulated_failover_returns_real_answer` ready |
| `key_1=429,key_2=500` and `*=429` → 503, nothing added to history | PASS | pytest; Docker curl (exact body), history 404 |
| Honoured only when `ENABLE_FAILURE_SIMULATION=true` | PASS | `test_simulation_ignored_when_disabled` |

### §5 Frontend contract
| Requirement | Status | Evidence |
|---|---|---|
| `chat-input`, `send-button`, `assistant-message`, `meta-source`, `meta-model`, `meta-latency`, `meta-input-tokens`, `meta-output-tokens`, `system-prompt-input` | PASS | e2e presence and exact-content checks (`^\d+ ms$`, integers, exact source strings) |
| Input empty after sending; Enter sends; Shift+Enter newline | PASS | e2e |
| New session on each page load | PASS | e2e: session id changes, messages cleared |
| 422 / 503 readable in chat, never blank | PASS | e2e (fake backend) and Docker browser check (real 503) |
| Deployed frontend ↔ backend, CORS | PASS locally (Docker, CORS verified) / POSTPONED (deployment) | |

### §6 Docker
| Requirement | Status | Evidence |
|---|---|---|
| `make up` → backend :8000, frontend :3000 | PASS | `make up` (with `--wait`): both containers healthy |
| Multi-stage Dockerfiles | PASS | backend builder → runtime (+ separate test stage); frontend node build → nginx |
| Small runtime images | PARTIAL | frontend 91 MB; backend 597 MB (trimmed from 820 MB). The floor is LiteLLM's dependency tree; numpy is required by soundfile on LiteLLM's cache-hit path |
| Root compose, named volume at `/data` | PASS | `nexora-data:/data` |
| Makefile `up`, `down` (+ `test`) | PASS | All run; `make test` works with or without a local venv |
| All configuration via env vars | PASS | pydantic-settings; empty values fall back to defaults |

### §7 Repository / env / docs
| Requirement | Status | Evidence |
|---|---|---|
| Layout `/backend /frontend docker-compose.yml Makefile .env.example README.md` | PASS | |
| Backend tests included | PASS | 89 + opt-in live suite |
| `LLM_API_KEYS`, `DATABASE_URL`, `ALLOWED_ORIGINS`, `ENABLE_FAILURE_SIMULATION` (+ extras) in `.env.example`, placeholders only | PASS | Every Settings field listed; secret scan clean |
| README with the six required headings | PASS (Live URLs pending) | |
| Public repo, live URLs, demo video, submission form | POSTPONED | Out of scope this phase (repo already exists at m4nish-dev/Nexora from the earlier push) |

### Real-provider verification
| Check | Status |
|---|---|
| Successful real inference, real cache hit after it, real token usage | **BLOCKED**: `.env` still has placeholder keys |
| Simulated failover answered by a real key_2; invalid real key_1 → real key_2 | **BLOCKED**: same |
| Real provider *error* path (Gemini 401 → failover → 503, no key leakage) | PASS (local uvicorn and Docker) |

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
- **Backend (`make test`, 89 tests):** pytest + TestClient. Each test gets a temporary SQLite file and a fresh LiteLLM cache. Provider calls are faked with LiteLLM's own `mock_response`, so the real cache and exception mapping run.
- **Browser (`make test-e2e`, 14 tests):** Playwright against the production build and `backend/tests/e2e_server.py` (test-only), on ports 8100/3100.
- **Real provider (`make test-live`):** genuine LiteLLM calls with `.env` keys. Opt-in, and skipped (never passed) without real keys.
- **Smoke (`make smoke`):** curl checks against any running backend.
- **Mutation checks** confirm the concurrency and system-prompt tests actually detect regressions.

## 8. Docker architecture
- **backend:** `python:3.12-slim` builder (wheels into a venv) → slim runtime copying the venv; non-root user; `/data` volume; healthcheck on `/health`.
- **frontend:** `node:22-alpine` build → `nginx:alpine` serving static files on :3000. An entrypoint writes `config.js` from `API_BASE_URL` at container start, so the same image works in any environment.
- **compose:** `backend` (8000), `frontend` (3000), named volume `nexora-data:/data`, env from `.env`.

## 9. Deployment plan: POSTPONED this phase
Prepared but not executed: `render.yaml` (backend, Docker) and `frontend/vercel.json`. Do not deploy or push until the user says so.

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

## 11. Progress log, test results & known issues

### Final audit run (2026-11-21, after this phase's fixes)
| Check | Result |
|---|---|
| `make test` (local venv) | **89 passed, 1 skipped** (live suite, opt-in) |
| `make test-docker` (Dockerfile test stage) | **89 passed, 1 skipped** |
| Live suite with placeholder keys | Skipped ("need 2 real keys"); it never passes on mocks |
| `make test-e2e` (Playwright) | **14 passed, 0 failed** |
| Mutation checks | Removing the session lock fails the concurrency test; reverting the system-prompt fix fails the Reset e2e test |
| `npm run build` | OK |
| `docker compose config -q` | Valid |
| `make up` | Both containers healthy (`--wait`); backend runs as uid 10001 |
| Docker endpoint checks | /health 200; real-key 503 exact body; `*=429` and `key_1=429,key_2=500` → 503; 422 (empty / missing / 4001 / malformed JSON / bad header); 404; JSON 405; CORS preflight OK; no key text in logs |
| Persistence | Rows written before `make down` present after `make up` |
| Docker browser check | UI → backend over CORS; readable 503; input cleared |
| ruff (E, F, W, B, UP, SIM, RUF) | Only cosmetic findings; fixed (zip strict, stale noqa) |

### Bugs / gaps found and fixed this phase
1. `session_id` was trimmed before being echoed (contract: echo of the request value). Now verbatim; blank ids still give 422.
2. Unexpected 500s lacked CORS headers, so the browser reported a network error instead of the JSON. Added an inner `UnhandledErrorMiddleware`.
3. System prompt **Reset** had no effect within a session (the backend kept the stored custom prompt when the field was omitted). The UI now always sends the effective prompt.
4. Browser tests existed only outside the repo. Added `frontend/e2e` (Playwright) and a test-only `backend/tests/e2e_server.py`.
5. No real-provider test suite. Added `backend/tests/test_live_provider.py` (opt-in, never passes on placeholders).
6. `make test` required a local venv. It now falls back to a Docker test stage; added `test-e2e`, `test-live`, `smoke`.
7. `make up` didn't confirm health. It now uses `--wait`.
8. Lint: `zip(..., strict=True)`, stale `noqa` and `eslint` comments.

### Known issues / limitations
- **Real successful inference is unverified (BLOCKED):** add two real keys to `.env`, then run `make test-live` and `make up && make smoke`.
- `gemini/gemini-2.5-flash` availability must be confirmed for the keys used (`LLM_MODEL` is configurable).
- The in-memory cache resets on restart (LiteLLM 1.110 has no disk backend) and needs a single worker.
- Backend image 597 MB (see §6 PARTIAL).
- A `session_id` containing `/` can be chatted with but not fetched via the history path (path routing); the UI never generates one.

### Demo video script (2–3 min, POSTPONED)
1. (15 s) Repo layout + `make up`; open `/health`.
2. (30 s) Ask a question; show the metadata (LIVE_INFERENCE, model, latency, tokens, key_1).
3. (25 s) Multi-turn memory; `GET /sessions/{id}/messages`.
4. (25 s) New chat → same first question → LLM_CACHE, identical text, ms latency.
5. (35 s) Failover lab `key_1 → 429` → key_2; curl `key_1=500`; `*=429` → 503 and history 404.
6. (15 s) 422 via curl; close on README §3.
