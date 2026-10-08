# Project Glasshaus — common tasks. `make help` lists targets.
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help
COMPOSE := docker compose
# Separate project name: never touches a production stack running on the same host.
DEV_COMPOSE := $(COMPOSE) -p glasshaus-dev -f docker-compose.yml -f docker-compose.dev.yml
BACKEND := cd backend &&
FRONTEND := cd frontend &&
# Read from the repository's .env when make starts (recipes `cd backend`, so no runtime lookups).
env_get = $(shell grep -m1 '^$(1)=' .env 2>/dev/null | cut -d= -f2-)
DEV_DB_URL ?= postgresql+asyncpg://glasshaus_app:$(call env_get,POSTGRES_APP_PASSWORD)@127.0.0.1:15432/glasshaus
DEV_OWNER_DB_URL ?= postgresql+asyncpg://glasshaus:$(call env_get,POSTGRES_PASSWORD)@127.0.0.1:15432/glasshaus
DEV_REDIS_URL ?= redis://:$(call env_get,REDIS_PASSWORD)@127.0.0.1:16379/0
DEV_ENV = GLASSHAUS_ENV=development GLASSHAUS_LOG_JSON=false GLASSHAUS_DATABASE_URL=$(DEV_DB_URL) \
	GLASSHAUS_MIGRATION_DATABASE_URL=$(DEV_OWNER_DB_URL) GLASSHAUS_REDIS_URL=$(DEV_REDIS_URL) \
	GLASSHAUS_ADMIN_PASSWORD=$(call env_get,GLASSHAUS_ADMIN_PASSWORD)

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

##@ Stack
.PHONY: setup up down restart ps logs update backup restore demo
setup: ## First-run install (idempotent)
	./setup.sh
up: ## Start the stack
	$(COMPOSE) up -d
down: ## Stop the stack
	$(COMPOSE) down
restart: ## Restart app services
	$(COMPOSE) restart api worker mcp web
ps: ## Show service status
	$(COMPOSE) ps
logs: ## Tail logs (SERVICE=api to filter)
	$(COMPOSE) logs -f --tail 100 $(SERVICE)
update: ## Safe upgrade with automatic rollback
	./update.sh
backup: ## On-demand database backup
	scripts/backup.sh
restore: ## Restore database: make restore FILE=backups/x.dump
	scripts/restore.sh $(FILE)
demo: ## Load demo data into the running stack
	$(COMPOSE) run --rm --no-deps migrate glasshaus seed --demo

##@ Development
.PHONY: install dev-deps dev-api dev-worker dev-mcp dev-web migrate migration openapi seed
install: ## Install backend + frontend deps and git hooks
	$(BACKEND) uv sync
	$(FRONTEND) npm ci
	uvx pre-commit install
dev-deps: ## Run Postgres + Redis for local development (ports 15432/16379)
	@test -f .env || ./setup.sh --no-start
	$(DEV_COMPOSE) up -d postgres redis
dev-api: ## Run the API with reload on :8471
	$(BACKEND) $(DEV_ENV) uv run uvicorn glasshaus.main:app --reload --port 8471
dev-worker: ## Run the worker
	$(BACKEND) $(DEV_ENV) uv run arq glasshaus.worker.WorkerSettings --watch src
dev-mcp: ## Run the MCP server on :8472
	$(BACKEND) $(DEV_ENV) uv run glasshaus-mcp --port 8472
dev-web: ## Run the Vite dev server on :5173 (proxies /api to :8471)
	$(FRONTEND) npm run dev
migrate: ## Apply migrations to the dev database
	$(BACKEND) $(DEV_ENV) uv run glasshaus migrate
migration: ## Autogenerate a migration: make migration MSG="add tasks"
	$(BACKEND) $(DEV_ENV) GLASSHAUS_DATABASE_URL=$(DEV_OWNER_DB_URL) uv run alembic -c src/glasshaus/migrations/alembic.ini revision --autogenerate -m "$(MSG)"
openapi: ## Regenerate docs/openapi.json and the frontend's typed client
	$(BACKEND) GLASSHAUS_ENV=test uv run glasshaus openapi ../docs/openapi.json
	$(FRONTEND) npm run gen:api
	python3 scripts/copilot_openapi.py docs/openapi.json docs/integrations/m365/openapi.json
seed: ## Seed the dev database with demo data
	$(BACKEND) $(DEV_ENV) uv run glasshaus seed --demo

##@ Quality
.PHONY: lint fmt typecheck test test-backend test-integration test-web check scan precommit
lint: ## Lint everything
	$(BACKEND) uv run ruff check . && uv run ruff format --check .
	$(FRONTEND) npm run lint && npm run format:check
	shellcheck -x setup.sh update.sh scripts/*.sh
	scripts/check-version.sh
fmt: ## Auto-format everything
	$(BACKEND) uv run ruff check --fix . && uv run ruff format .
	$(FRONTEND) npm run format
typecheck: ## Static type checks
	$(BACKEND) uv run mypy src tests
	$(FRONTEND) npm run typecheck
test-backend: ## Backend unit tests
	$(BACKEND) uv run pytest
test-integration: ## Backend tests incl. Postgres/Redis (needs `make dev-deps`)
	$(BACKEND) $(DEV_ENV) GLASSHAUS_ENV=test GLASSHAUS_INTEGRATION=1 uv run pytest
test-web: ## Frontend unit tests
	$(FRONTEND) npm test
test: test-backend test-web ## All unit tests
check: lint typecheck test ## Everything CI runs before building
scan: ## Dependency vulnerability scan
	$(BACKEND) uv export --no-dev --no-hashes --no-emit-project -q > /tmp/glasshaus-req.txt && uv run pip-audit -r /tmp/glasshaus-req.txt
	$(FRONTEND) npm audit --omit=dev --audit-level=high
precommit: ## Run all pre-commit hooks on all files
	uvx pre-commit run --all-files

##@ Release
.PHONY: build bump
build: ## Build container images
	$(COMPOSE) build
bump: ## Set version everywhere: make bump V=0.2.0
	scripts/bump-version.sh $(V)
