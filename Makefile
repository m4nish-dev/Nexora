.DEFAULT_GOAL := help
COMPOSE ?= docker compose

.PHONY: help up down logs ps restart test clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

up: .env ## Build and start the stack (backend :8000, frontend :3000)
	$(COMPOSE) up -d --build
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

test: ## Run backend tests (uses backend/.venv if present)
	cd backend && $$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 ) -m pytest -q

clean: ## Stop the stack AND delete the SQLite volume (destroys history)
	$(COMPOSE) down -v

.env:
	@cp .env.example .env
	@echo "Created .env from .env.example - put your real keys in LLM_API_KEYS."
