# Phase 1 - Foundation & Infrastructure
# Convenience wrappers around docker compose for dev (Mac, mocks) and prod (EC2, GPU).

COMPOSE_BASE := docker-compose.yml
COMPOSE_DEV  := docker-compose.dev.yml
COMPOSE_PROD := docker-compose.prod.yml

DEV  := docker compose -f $(COMPOSE_BASE) -f $(COMPOSE_DEV)
PROD := docker compose -f $(COMPOSE_BASE) -f $(COMPOSE_PROD) --profile gpu

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ----------------------------------------------------------------------------
# Dev (this Mac, no GPU, mock LLM + mock image)
# ----------------------------------------------------------------------------
.PHONY: dev
dev: env ## Build + start the dev stack (UI, backend, mcp, qdrant) with hot reload
	$(DEV) up --build

.PHONY: dev-down
dev-down: ## Stop and remove the dev stack
	$(DEV) down

# ----------------------------------------------------------------------------
# Prod (EC2, GPU: real vLLM + ComfyUI)
# ----------------------------------------------------------------------------
.PHONY: prod
prod: env ## Build + start the full GPU stack in the background
	$(PROD) up --build -d

.PHONY: prod-down
prod-down: ## Stop and remove the prod stack
	$(PROD) down

# ----------------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------------
.PHONY: down
down: ## Stop everything regardless of profile
	docker compose -f $(COMPOSE_BASE) -f $(COMPOSE_DEV) -f $(COMPOSE_PROD) --profile gpu down

.PHONY: logs
logs: ## Tail logs (dev). Override SVC=backend to scope: make logs SVC=backend
	$(DEV) logs -f $(SVC)

.PHONY: ps
ps: ## List running services (dev)
	$(DEV) ps

.PHONY: env
env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")
