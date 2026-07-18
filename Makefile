COMPOSE ?= docker compose
SERVICE_DEV := dev
SERVICE_SIM := simulator
PYTEST_OFFLINE := -m "not integration and not compatibility"

# Docker Hub release image (runtime target only — not the local bind-mount "dev" image).
DOCKERHUB_USER ?= inecs
IMAGE_NAME ?= proxmox-api-simulator
VERSION ?= $(shell sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
DOCKER_IMAGE ?= $(DOCKERHUB_USER)/$(IMAGE_NAME)
PUSH_LATEST ?= 1

COMPOSE_RELEASE ?= $(COMPOSE) -f docker-compose.release.yml
HELM_CHART ?= ./helm/proxmox-api-simulator

.PHONY: help install format lint typecheck test test-unit test-integration test-contract test-compatibility test-surface evidence coverage run dev up down restart logs docker-build docker-up docker-down docker-logs docker-restart db-up db-down db-migrate db-reset api-import api-diff seed clean ci ci-all shell release release-build release-up release-down release-seed helm-deps helm-template helm-lint pulumi-tests

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_-]+:.*## / {printf "%-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Build runtime and development images
	@test -f .env || cp .env.example .env
	$(COMPOSE) build simulator $(SERVICE_DEV)

format: ## Format Python sources
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) ruff format .

lint: ## Run Ruff lint checks
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) ruff check .

typecheck: ## Run strict mypy checks
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) mypy

test: ## Run offline unit and contract tests
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) pytest $(PYTEST_OFFLINE)

test-unit: ## Run unit tests
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) pytest tests/unit

test-integration: ## Run tests that require PostgreSQL
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm $(SERVICE_DEV) pytest -m integration

test-contract: ## Run offline API contract tests
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) pytest -m contract

test-compatibility: ## Run proxmoxer smoke flow (needs --profile tls; proxmoxer is HTTPS-only)
	@test -f .env || cp .env.example .env
	$(COMPOSE) --profile tls up -d --build --wait
	# Medium profile provides pve1/pve2/pve3 required by the proxmoxer migration smoke.
	$(COMPOSE) run --rm -e SEED_PROFILE=medium --entrypoint python $(SERVICE_SIM) \
		-m app.simulation.seed_cli
	$(COMPOSE) run --rm \
		-e PROXMOXER_HOST=tls-gateway \
		-e PROXMOXER_PORT=8443 \
		$(SERVICE_DEV) pytest -m compatibility

test-surface: ## Probe every declared method on majors 6-9 (0x501 / 0xexception)
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm $(SERVICE_DEV) pytest tests/compatibility/test_api_surface_probe.py -q

evidence: ## Regenerate per-major verified surface evidence ledgers
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) python -m app.evidence_gen

coverage: ## Run offline tests with coverage enforcement
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) pytest $(PYTEST_OFFLINE) --cov=app --cov-report=term-missing --cov-report=xml

run: ## Run the application in the foreground
	@test -f .env || cp .env.example .env
	$(COMPOSE) up --build

up: ## Start PostgreSQL and simulator (plain HTTP :8006)
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d --build --wait

down: ## Stop local services
	$(COMPOSE) down

restart: ## Rebuild and restart the stack
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d --build --force-recreate --wait

logs: ## Follow logs from all services
	$(COMPOSE) logs -f

dev: ## Run the application with auto-reload in Docker
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d postgres migrate
	$(COMPOSE) up simulator

docker-build: ## Build runtime and development images
	$(MAKE) install

docker-up: up ## Alias for up

docker-restart: ## Rebuild and recreate the simulator
	$(COMPOSE) up -d --build --force-recreate simulator

docker-down: down ## Alias for down

docker-logs: ## Follow simulator logs only
	$(COMPOSE) logs -f simulator

db-up: ## Start PostgreSQL only
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d postgres

db-down: ## Stop PostgreSQL
	$(COMPOSE) stop postgres

db-migrate: ## Apply database migrations
	@test -f .env || cp .env.example .env
	$(COMPOSE) run --rm migrate

db-reset: ## Recreate the local database volume
	$(COMPOSE) down -v
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm migrate

api-import: ## Import an API snapshot
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) proxmox-api-contract import $(ARGS)

api-diff: ## Compare API snapshots
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) proxmox-api-contract diff $(ARGS)

seed: ## Seed simulation data
	@test -f .env || cp .env.example .env
	SEED_PROFILE="$${PROFILE:-small}" $(COMPOSE) run --rm --entrypoint python $(SERVICE_SIM) -m app.simulation.seed_cli

shell: ## Open an interactive shell in the development container
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) bash

clean: ## Remove generated local artifacts
	rm -rf .coverage coverage.xml htmlcov .mypy_cache .pytest_cache .ruff_cache

ci: ## Offline quality gate + full API surface probe (Postgres)
	$(COMPOSE) run --rm --no-deps $(SERVICE_DEV) sh -c '\
		ruff format --check . && \
		ruff check . && \
		mypy && \
		pytest $(PYTEST_OFFLINE) --cov=app --cov-report=term-missing --cov-report=xml'
	$(MAKE) test-surface

ci-all: ## Full CI: offline + surface + remaining integration + proxmoxer
	$(MAKE) ci
	$(MAKE) test-integration
	$(MAKE) test-compatibility

release-build: ## Build the runtime image tagged for Docker Hub (no push)
	@test -n "$(VERSION)" || (echo "VERSION is empty; set VERSION=... or version in pyproject.toml" >&2; exit 1)
	@echo "Building $(DOCKER_IMAGE):$(VERSION) (target=runtime)"
	docker build \
		--target runtime \
		--build-arg APP_VERSION=$(VERSION) \
		-t $(DOCKER_IMAGE):$(VERSION) \
		$(if $(filter 1 true yes,$(PUSH_LATEST)),-t $(DOCKER_IMAGE):latest,) \
		.

release: release-build ## Build and push the runtime image to Docker Hub
	@echo "Pushing $(DOCKER_IMAGE):$(VERSION)"
	@docker push $(DOCKER_IMAGE):$(VERSION)
	@if [ "$(PUSH_LATEST)" = "1" ] || [ "$(PUSH_LATEST)" = "true" ] || [ "$(PUSH_LATEST)" = "yes" ]; then \
		echo "Pushing $(DOCKER_IMAGE):latest"; \
		docker push $(DOCKER_IMAGE):latest; \
	fi
	@echo "Released $(DOCKER_IMAGE):$(VERSION)$(if $(filter 1 true yes,$(PUSH_LATEST)), and $(DOCKER_IMAGE):latest,)"

release-up: ## Pull and start the published Hub stack (docker-compose.release.yml)
	IMAGE_TAG="$${IMAGE_TAG:-$(VERSION)}" DOCKER_IMAGE="$(DOCKER_IMAGE)" $(COMPOSE_RELEASE) pull
	IMAGE_TAG="$${IMAGE_TAG:-$(VERSION)}" DOCKER_IMAGE="$(DOCKER_IMAGE)" $(COMPOSE_RELEASE) up -d --wait

release-down: ## Stop the published Hub stack
	$(COMPOSE_RELEASE) down

release-seed: ## Seed the published Hub stack (PROFILE=small by default)
	SEED_PROFILE="$${PROFILE:-small}" IMAGE_TAG="$${IMAGE_TAG:-$(VERSION)}" DOCKER_IMAGE="$(DOCKER_IMAGE)" \
		$(COMPOSE_RELEASE) run --rm --entrypoint python simulator -m app.simulation.seed_cli

helm-deps: ## No-op placeholder (chart has no OCI dependencies)
	@echo "Chart $(HELM_CHART) vendors PostgreSQL templates; no helm dependency update required."

helm-lint: ## Lint the Helm chart (requires helm)
	helm lint $(HELM_CHART)
	helm lint $(HELM_CHART) -f $(HELM_CHART)/values-ingress-example.yaml \
		--set certManager.email=docs@example.com \
		--set secret.ticketSigningKey=docs-only-signing-key

helm-template: ## Render Helm manifests locally (requires helm)
	helm template pve-sim $(HELM_CHART) \
		-f $(HELM_CHART)/values-ingress-example.yaml \
		--set certManager.email=docs@example.com \
		--set secret.ticketSigningKey=docs-only-signing-key

pulumi-tests: ## Full Pulumi suite (surface majors 6–9 + lifecycle, HTML report)
	$(MAKE) -C pulumi-tests up
	$(MAKE) -C pulumi-tests test
