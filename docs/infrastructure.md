# Infrastructure & orchestration

**Path:** `infrastructure/`  
**Entrypoint:** `infrastructure/script/script.sh` (wrapped by `Makefile`)  
**Role:** One-command startup, health checks, model download, and Bible ingestion.

## Why this exists

Running eight services manually (build, wait, ingest, smoke-test) is error-prone.
The orchestrator automates the full sequence with preflight checks, idempotent
steps, and CI-friendly exit codes. Everything is env-driven — no hardcoded hosts,
ports, or model paths.

## File structure

```
infrastructure/
├── script/
│   └── script.sh          single entrypoint
├── lib/
│   ├── common.sh          logging, strict mode, .env loader, compose wrapper
│   ├── preflight.sh       Docker, Compose, disk, ports, GPU checks
│   ├── health.sh          wait-for-healthy + HTTP probes
│   └── models.sh          Juggernaut download + LLM pre-pull
└── README.md              command reference
```

## Commands

| Command | Makefile | What it does |
| ------- | -------- | ------------ |
| `script.sh up [dev\|prod]` | `make dev` / `make prod` | Full startup sequence |
| `script.sh doctor` | `make doctor` | Preflight checks only |
| `script.sh build [dev\|prod]` | `make build` | Build images with error detection |
| `script.sh models [dev\|prod]` | `make models` | Download Juggernaut + pre-pull LLM |
| `script.sh ingest` | `make ingest` | Run Bible corpus ingestion |
| `script.sh health` | `make health` | Wait for healthy + probe endpoints |
| `script.sh logs [service]` | `make logs SVC=…` | Tail service logs |
| `script.sh down [dev\|prod]` | `make down` / `make down-prod` | Stop and remove stack |

## What `up` does (sequential)

1. **Load `.env`** — create from `.env.example` if missing.
2. **Preflight** — Docker daemon, Compose v2, disk space, port availability,
   required env vars, GPU presence (prod).
3. **Download models** (prod only) — Juggernaut checkpoint to `models/checkpoints/`,
   optional LLM pre-pull to `hf_cache`.
4. **Build images** — on failure, prints the failing build log tail and exits nonzero.
5. **Start containers** — `docker compose up -d` with the appropriate override file.
6. **Wait for health** — polls until every service reports healthy
   (`HEALTH_TIMEOUT` / `HEALTH_INTERVAL`).
7. **Probe endpoints** — readyz, Qdrant, and vLLM/ComfyUI in prod.
8. **Ingest Bible corpus** — idempotent; skips if collection populated unless
   `REINGEST=true`.
9. **Smoke test** — grounded chat request; prints service URLs.

## Docker Compose profiles

| Profile | Services | When |
| ------- | -------- | ---- |
| (default) | backend, ui, mcp-server, qdrant, postgres | always |
| `gpu` | vllm, comfyui | prod (`make prod`) |
| `ingest` | ingest (one-shot) | triggered by orchestrator |

## Dev vs prod

| Aspect | Dev (`make dev`) | Prod (`make prod`) |
| ------ | ---------------- | ------------------- |
| Override file | `docker-compose.dev.yml` | `docker-compose.prod.yml` |
| LLM | mock | vLLM (Qwen2.5-VL) |
| Image | mock placeholder | ComfyUI + Juggernaut |
| GPU services | not started | started (gpu profile) |
| Hot reload | bind mounts for backend + UI | built images |
| Model download | skipped | Juggernaut + LLM pre-pull |
| Restart policy | none | `unless-stopped` |

## Key environment variables

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DEPLOY_MODE` | `dev` | Default mode for `script.sh up` |
| `HEALTH_TIMEOUT` | `600` | Max seconds to wait for healthy |
| `HEALTH_INTERVAL` | `5` | Poll interval (seconds) |
| `DISK_MIN_GB` | `15` | Minimum free disk for preflight |
| `MODELS_DIR` | `./models` | Host checkpoint directory |
| `JUGGERNAUT_HF_REPO` | `RunDiffusion/Juggernaut-XL-v9` | HF repo for checkpoint |
| `PREPULL_LLM` | `true` | Pre-pull Qwen weights in prod |
| `REINGEST` | `false` | Force Bible re-ingestion |

Full list: [.env.example](../.env.example).

## Volumes

| Volume | Service | Contents |
| ------ | ------- | -------- |
| `qdrant_data` | qdrant | Verse vectors |
| `pg_data` | postgres | Chat history |
| `media_data` | backend | Generated images |
| `hf_cache` | vllm | Qwen model weights |
| `kagglehub_cache` | ingest | Downloaded Bible dataset |

## Related docs

- [infrastructure/README.md](../infrastructure/README.md) — quick command reference
- [Architecture overview](architecture/overview.md) — system diagram
- [Root README](../README.md) — ports, quick start, API summary
