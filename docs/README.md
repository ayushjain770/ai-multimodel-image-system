# Documentation

Architecture and per-service reference for the Christianity AI Assistant.

## Architecture

- [System overview](architecture/overview.md) — end-to-end architecture, request flows,
  phase map, and design decisions

## Services

| Service | Port | Doc |
| ------- | ---- | --- |
| FastAPI backend | 8080 | [backend.md](services/backend.md) |
| **Planner (brain)** | — | [planner.md](services/planner.md) |
| Next.js UI | 3000 | [ui.md](services/ui.md) |
| FastMCP server | 8001 | [mcp-server.md](services/mcp-server.md) |
| vLLM (Qwen2.5-VL) | 8000 | [vllm.md](services/vllm.md) |
| ComfyUI (Juggernaut) | 8188 | [comfyui.md](services/comfyui.md) |
| Qdrant | 6333 | [qdrant.md](services/qdrant.md) |
| PostgreSQL | 5432 | [postgres.md](services/postgres.md) |
| Bible ingest (job) | — | [ingest.md](services/ingest.md) |

## Infrastructure

- [Orchestrator & Docker Compose](infrastructure.md) — `./startup.sh`, dev vs prod modes,
  health checks, model download

## Quick links

- [Root README](../README.md) — tech stack, ports, how to run, API summary
- [infrastructure/README.md](../infrastructure/README.md) — script commands
- [.env.example](../.env.example) — all configuration variables
