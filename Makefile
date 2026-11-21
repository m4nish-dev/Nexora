.DEFAULT_GOAL := help
COMPOSE ?= docker compose
VENV_PY := backend/.venv/bin/python

.PHONY: help up down logs ps restart test test-local test-docker test-image test-live test-e2e smoke clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

up: .env ## Build and start the stack; waits until both containers are healthy
	$(COMPOSE) up -d --build --wait --wait-timeout 180
	@echo ""
	@echo "  Frontend  http://localhost:3000"
	@echo "  Backend   http://localhost:8000  (health: http://localhost:8000/health)"

down: ## Stop the stack (the SQLite volume is kept)
	$(COMPOSE) down

logs: ## Follow logs
	$(COMPOSE) logs -f

ps: ## Show container status
	$(COMPOSE) ps

restart: down up ## Restart the stack

test: ## Backend test suite (local venv if present, otherwise inside Docker)
	@if [ -x $(VENV_PY) ]; then $(MAKE) --no-print-directory test-local; else $(MAKE) --no-print-directory test-docker; fi

test-local: ## Backend tests with backend/.venv
	cd backend && .venv/bin/python -m pytest -q -rs

test-docker: ## Backend tests in a throwaway container (Dockerfile "test" stage)
	docker build --target test -t nexora-backend-test ./backend
	docker run --rm nexora-backend-test

test-image: ## Smoke-test the production backend image (real LiteLLM Gemini handler vs a local HTTP stub)
	$(COMPOSE) build backend
	docker run --rm -v "$(CURDIR)/backend/tests:/app/tests:ro" -v "$(CURDIR)/backend/scripts:/app/scripts:ro" \
		nexora-backend:latest python -m scripts.image_smoke

test-live: .env ## Real-provider tests using LLM_API_KEYS / LLM_MODEL from .env (costs tokens)
	@set -a; . ./.env; set +a; cd backend && NEXORA_LIVE=1 .venv/bin/python -m pytest -m live -v -rs

test-e2e: ## Browser tests (Playwright) against the test-only backend on ports 8100/3100
	cd frontend && npm run test:e2e

smoke: ## End-to-end curl checks against a running backend (default http://localhost:8000)
	./backend/scripts/smoke_test.sh $${BASE_URL:-http://localhost:8000}

clean: ## Stop the stack AND delete the SQLite volume (destroys history)
	$(COMPOSE) down -v

.env:
	@cp .env.example .env
	@echo "Created .env from .env.example - put your real keys in LLM_API_KEYS."
