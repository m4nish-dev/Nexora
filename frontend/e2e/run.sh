#!/usr/bin/env bash
# Builds the frontend, starts the test-only backend (backend/tests/e2e_server.py) and a static
# preview server on dedicated ports (8100/3100, so a running `make up` stack is untouched), then
# runs the browser suite. Requires backend/.venv (see README) and `npx playwright install chromium`.
set -euo pipefail
cd "$(dirname "$0")/.."
FRONTEND_DIR=$(pwd)
BACKEND_DIR="$FRONTEND_DIR/../backend"
PY="$BACKEND_DIR/.venv/bin/python"
[ -x "$PY" ] || PY=python3

cleanup() { kill "${BACKEND_PID:-}" "${PREVIEW_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT

VITE_API_BASE_URL=http://localhost:8100 npx vite build --logLevel warn
(cd "$BACKEND_DIR" && exec "$PY" -m tests.e2e_server --port 8100 --origin http://localhost:3100) &
BACKEND_PID=$!
npx vite preview --port 3100 --strictPort >/dev/null 2>&1 &
PREVIEW_PID=$!

for _ in $(seq 1 60); do
  curl -sf http://localhost:8100/health >/dev/null && curl -sf http://localhost:3100 >/dev/null && break
  sleep 0.5
done

E2E_URL=http://localhost:3100 E2E_MODE=fake node e2e/contract.e2e.mjs
