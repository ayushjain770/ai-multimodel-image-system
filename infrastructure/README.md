# Infrastructure - one-command orchestration

`script/script.sh` brings the entire stack up (or down) with a single command:
preflight checks, model download (prod), image build with error detection,
health waiting, Bible ingestion, and a smoke test. Everything is driven by
`.env` (auto-created from `.env.example`) - no hardcoded hosts, ports, models,
or paths.

## Usage

```bash
# Start everything (default mode = dev, from DEPLOY_MODE in .env)
infrastructure/script/script.sh up
infrastructure/script/script.sh up dev
infrastructure/script/script.sh up prod      # EC2/GPU: also downloads models

# Individual steps
infrastructure/script/script.sh doctor        # preflight checks only
infrastructure/script/script.sh build [dev|prod]
infrastructure/script/script.sh models [dev|prod]
infrastructure/script/script.sh ingest
infrastructure/script/script.sh health
infrastructure/script/script.sh logs [service]
infrastructure/script/script.sh down [dev|prod]
```

Or via the Makefile wrappers: `make dev`, `make prod`, `make doctor`,
`make ingest`, `make health`, `make down`.

## Files

| File | Responsibility |
| --- | --- |
| `script/script.sh` | Single entrypoint; orchestrates the full sequence |
| `lib/common.sh` | Logging, strict mode + error trap, retries, `.env` loader, `compose` wrapper |
| `lib/preflight.sh` | Docker daemon, Compose v2, disk, ports, env vars, GPU (prod) |
| `lib/health.sh` | Wait-for-healthy loop + HTTP endpoint probes |
| `lib/models.sh` | Idempotent Juggernaut download + optional LLM pre-pull |

## What `up` does

1. Load `.env` (create from `.env.example` if missing).
2. Preflight: fails fast with a clear message if Docker, Compose, disk, ports,
   env, or GPU (prod) are not ready.
3. prod only: download the Juggernaut checkpoint and pre-pull the LLM weights.
4. Build images; on failure, the failing build log tail is printed and the
   script exits nonzero (CI-friendly).
5. Start containers and wait until every service reports healthy
   (`HEALTH_TIMEOUT` / `HEALTH_INTERVAL`).
6. Probe HTTP endpoints (readyz, qdrant, and vLLM/ComfyUI in prod).
7. Run Bible ingestion (idempotent - skips if the collection is already
   populated unless `REINGEST=true`).
8. Smoke-test a grounded chat request and print the service URLs.

## Key environment variables

See `.env.example` for the full, documented list. Highlights:

- `DEPLOY_MODE`, `HEALTH_TIMEOUT`, `HEALTH_INTERVAL`, `DISK_MIN_GB`, `MODELS_DIR`
- `JUGGERNAUT_HF_REPO` / `JUGGERNAUT_HF_FILE` / `JUGGERNAUT_URL` / `JUGGERNAUT_SHA256` / `PREPULL_LLM`
- `RAG_ENABLED`, `EMBEDDING_MODEL`, `QDRANT_COLLECTION`, `RAG_TOP_K`, `BIBLE_SOURCES`
