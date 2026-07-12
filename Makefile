PYTHON ?= python3.13
VENV ?= .venv
BIN := $(VENV)/bin
COMPOSE ?= docker compose

.PHONY: help install format lint typecheck test test-unit test-integration test-contract coverage run dev docker-build docker-up docker-down docker-logs db-up db-down db-migrate db-reset api-import api-diff seed clean ci

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_-]+:.*## / {printf "%-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Create the Python 3.13 environment and install development dependencies
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade "pip>=25.1,<26"
	$(BIN)/python -m pip install -e '.[dev]'

format: ## Format Python sources
	$(BIN)/ruff format .

lint: ## Run Ruff lint checks
	$(BIN)/ruff check .

typecheck: ## Run strict mypy checks
	$(BIN)/mypy

test: ## Run all offline tests
	$(BIN)/pytest

test-unit: ## Run unit tests
	$(BIN)/pytest tests/unit

test-integration: ## Run tests that require PostgreSQL
	$(BIN)/pytest -m integration

test-contract: ## Run offline API contract tests
	$(BIN)/pytest -m contract

coverage: ## Run tests with coverage enforcement
	$(BIN)/pytest --cov=app --cov-report=term-missing --cov-report=xml

run: ## Run the application
	$(BIN)/uvicorn app.main:app --host "$${APP_HOST:-0.0.0.0}" --port "$${APP_PORT:-8006}"

dev: ## Run with auto-reload
	$(BIN)/uvicorn app.main:app --reload --host "$${APP_HOST:-0.0.0.0}" --port "$${APP_PORT:-8006}"

docker-build: ## Build the runtime image
	$(COMPOSE) build simulator

docker-up: ## Start PostgreSQL and simulator
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d --build

docker-down: ## Stop local services
	$(COMPOSE) down

docker-logs: ## Follow simulator logs
	$(COMPOSE) logs -f simulator

db-up: ## Start PostgreSQL only
	$(COMPOSE) up -d postgres

db-down: ## Stop PostgreSQL
	$(COMPOSE) stop postgres

db-migrate: ## Apply database migrations
	$(BIN)/python -m app.db.migrate_cli

db-reset: ## Recreate the local database volume
	$(COMPOSE) down -v
	$(COMPOSE) up -d postgres

api-import: ## Import an API snapshot
	$(BIN)/proxmox-api-contract import $(ARGS)

api-diff: ## Compare API snapshots
	$(BIN)/proxmox-api-contract diff $(ARGS)

seed: ## Seed simulation data
	@echo "Database seed is scheduled for milestone D2" >&2; exit 2

clean: ## Remove generated local artifacts
	rm -rf $(VENV) .coverage coverage.xml htmlcov .mypy_cache .pytest_cache .ruff_cache

ci: format lint typecheck coverage ## Run the complete local quality gate
