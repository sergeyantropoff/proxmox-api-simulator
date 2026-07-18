COMPOSE := docker compose -f docker/docker-compose.yml
ENV_FILE := .env

.PHONY: help env up down build seed test test-smoke clean-test-resources reports-dir

help: ## Show targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_-]+:.*## / {printf "%-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Copy .env.example → .env if missing
	@test -f $(ENV_FILE) || cp .env.example $(ENV_FILE)

up: env ## Start postgres + simulator + internal TLS (for pulumi-proxmoxve) + seed
	$(COMPOSE) --env-file $(ENV_FILE) up -d --build postgres migrate simulator tls-gateway
	$(COMPOSE) --env-file $(ENV_FILE) run --rm seed

down: ## Stop test stack
	$(COMPOSE) --env-file $(ENV_FILE) down -v

build: env ## Build simulator + pulumi runner
	$(COMPOSE) --env-file $(ENV_FILE) --profile pulumi build

seed: env ## Reseed simulator (small profile by default)
	$(COMPOSE) --env-file $(ENV_FILE) run --rm seed

reports-dir:
	@mkdir -p pulumi/reports reports

test: env reports-dir ## Full suite: surface majors 6–9 + lifecycle (HTML report)
	$(COMPOSE) --env-file $(ENV_FILE) --profile pulumi run --rm --entrypoint /usr/local/bin/python3 pulumi-runner \
		pulumi/run_suite.py \
		--report-html pulumi/reports/report.html \
		--report-json pulumi/reports/results.json \
		--report-junit pulumi/reports/junit.xml

test-smoke: env reports-dir ## Smoke: surface major 9 + short lifecycle
	$(COMPOSE) --env-file $(ENV_FILE) --profile pulumi run --rm --entrypoint /usr/local/bin/python3 pulumi-runner \
		pulumi/run_suite.py --smoke \
		--report-html pulumi/reports/report-smoke.html \
		--report-json pulumi/reports/results-smoke.json \
		--report-junit pulumi/reports/junit-smoke.xml

clean-test-resources: env ## Delete leftover hx* guests on simulator
	$(COMPOSE) --env-file $(ENV_FILE) --profile cleanup run --rm cleanup
