# Phase 1/2 - thin wrappers around startup.sh (single entrypoint).

STARTUP := ./startup.sh

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: dev
dev: ## Full dev startup (Mac, mocks, no GPU)
	$(STARTUP) dev

.PHONY: prod
prod: ## Full prod startup (EC2, GPU)
	$(STARTUP) prod

.PHONY: doctor
doctor: ## Run preflight checks only
	$(STARTUP) doctor

.PHONY: build
build: ## Build images only (with error detection)
	$(STARTUP) build

.PHONY: models
models: ## Download Juggernaut (+ pre-pull LLM in prod)
	$(STARTUP) models

.PHONY: ingest
ingest: ## Run Bible corpus ingestion (idempotent)
	$(STARTUP) ingest

.PHONY: health
health: ## Wait for health + probe endpoints
	$(STARTUP) health

.PHONY: logs
logs: ## Tail logs. Scope with SVC=backend: make logs SVC=backend
	$(STARTUP) logs $(SVC)

.PHONY: down
down: ## Stop and remove the stack (dev)
	$(STARTUP) down dev

.PHONY: down-prod
down-prod: ## Stop and remove the stack (prod)
	$(STARTUP) down prod
