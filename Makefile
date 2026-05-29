# Phase 1/2 - thin wrappers around the orchestrator (infrastructure/script/script.sh).
# The script is the single source of truth for build/up/health/ingest sequencing.

SCRIPT := infrastructure/script/script.sh

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: dev
dev: ## Full dev startup (Mac, mocks, no GPU): preflight->build->up->health->ingest->smoke
	$(SCRIPT) up dev

.PHONY: prod
prod: ## Full prod startup (EC2, GPU): also downloads models before starting
	$(SCRIPT) up prod

.PHONY: doctor
doctor: ## Run preflight checks only
	$(SCRIPT) doctor

.PHONY: build
build: ## Build images only (with error detection)
	$(SCRIPT) build

.PHONY: models
models: ## Download Juggernaut (+ pre-pull LLM in prod)
	$(SCRIPT) models

.PHONY: ingest
ingest: ## Run Bible corpus ingestion (idempotent)
	$(SCRIPT) ingest

.PHONY: health
health: ## Wait for health + probe endpoints
	$(SCRIPT) health

.PHONY: logs
logs: ## Tail logs. Scope with SVC=backend: make logs SVC=backend
	$(SCRIPT) logs $(SVC)

.PHONY: down
down: ## Stop and remove the stack (dev)
	$(SCRIPT) down dev

.PHONY: down-prod
down-prod: ## Stop and remove the stack (prod)
	$(SCRIPT) down prod
