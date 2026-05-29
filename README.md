# Christianity AI Assistant - Phase 1 (Foundation & Infrastructure)

A multimodal, scripture-grounded Christian AI assistant. This phase ships the
runnable skeleton of the whole system: six services wired together over Docker
Compose, with an app-only **dev** mode (mocks, runs on a Mac with no GPU) and a
full **prod** mode (real GPU models on EC2).

> No business logic yet beyond a chat round-trip and one test image. Grounding,
> safety, RAG, and the rest land in later phases.

## Architecture

```
UI (Next.js :3000)
   |  REST /api/v1
   v
FastAPI gateway (:8080) ---- MCP streamable-http ----> FastMCP server (:8001)
   |        |          \
   |        |           \--- OpenAI-compatible ------> vLLM Qwen2.5-VL-3B (:8000)
   |        |
   |        \------------- HTTP API ------------------> ComfyUI + Juggernaut (:8188)
   |
   \---------------------- REST/gRPC -----------------> Qdrant vector DB (:6333)
```

The backend is the single gateway; the UI never talks to the GPU services
directly. `vllm` and `comfyui` are gated behind a Compose `gpu` profile so the
Mac can skip them entirely.

## Ports

| Service          | Port        | Notes                              |
| ---------------- | ----------- | ---------------------------------- |
| UI (Next.js)     | 3000        |                                    |
| FastAPI gateway  | 8080        | single entrypoint for the UI       |
| vLLM (Qwen2.5-VL)| 8000        | GPU profile only                   |
| FastMCP server   | 8001        |                                    |
| ComfyUI          | 8188        | GPU profile only                   |
| Qdrant           | 6333 / 6334 | HTTP / gRPC                        |

## Prerequisites

- Docker + Docker Compose v2 (`docker compose`, not `docker-compose`).
- For prod: a Linux + NVIDIA GPU host (EC2) with the NVIDIA Container Toolkit so
  `nvidia-smi` works inside containers.

## Quick start

The single orchestrator (`infrastructure/script/script.sh`, wrapped by the
Makefile) handles everything: preflight, build with error detection, model
download (prod), startup, health waiting, Bible ingestion, and a smoke test.
It bootstraps `.env` from `.env.example` on first run.

### Dev (this Mac, no GPU)

Runs UI + backend + MCP + Qdrant with hot reload, a mock LLM, and a placeholder
image generator. RAG grounding is real (CPU embeddings + Qdrant), so chat
returns genuine verse citations without a GPU.

```bash
make dev
```

Then:

- UI: http://localhost:3000
- Backend health: http://localhost:8080/health/readyz
- Grounded search: `POST http://localhost:8080/api/v1/search`
- Chat returns a reply plus real `citations[]` from the ingested corpus.

### Prod (EC2, GPU)

Brings up the full stack including real Qwen2.5-VL (vLLM) and ComfyUI/Juggernaut.

```bash
# 1. Set HF_TOKEN in .env if the model repo is gated.
# 2. Switch backends in .env: LLM_BACKEND=vllm, IMAGE_BACKEND=comfy
make prod
```

`make prod` (i.e. `script.sh up prod`) additionally:

1. Downloads the Juggernaut checkpoint into `models/checkpoints/` from
   `JUGGERNAUT_HF_REPO`+`JUGGERNAUT_HF_FILE` (or `JUGGERNAUT_URL`), with optional
   `JUGGERNAUT_SHA256` verification - no manual file drop needed.
2. Pre-pulls the Qwen2.5-VL weights into the `hf_cache` volume when
   `PREPULL_LLM=true`, so the first vLLM boot is fast.

See [infrastructure/README.md](infrastructure/README.md) for all orchestrator
commands (`doctor`, `build`, `models`, `ingest`, `health`, `logs`, `down`).

## EC2 notes

- Requires the NVIDIA driver + NVIDIA Container Toolkit on the host.
- Open only the security-group ports you need (at minimum 3000 and 8080).
- Set `NEXT_PUBLIC_API_URL=http://<ec2-host-or-domain>:8080` in `.env` so the
  browser can reach the backend.
- `models/` and `hf_cache/` are gitignored; weights live on the host volume.

## Layout

```
docker-compose.yml        base service definitions
docker-compose.dev.yml    dev overrides (mocks, hot reload, no GPU)
docker-compose.prod.yml   prod overrides (built images, GPU, restart policies)
.env.example              documented configuration
Makefile                  thin wrappers around the orchestrator
infrastructure/           one-command orchestration (script.sh + lib/)
services/
  backend/                FastAPI gateway (:8080) - chat, RAG search, verify, image, session/memory, health
  mcp-server/             FastMCP server (:8001) - ping, scripture_search, verse_verify, generate_image
  ui/                     Next.js UI (:3000)
  comfyui/                ComfyUI image (:8188)
  ingest/                 one-shot Bible ingestion job (verses -> Qdrant)
models/                   mounted checkpoints (gitignored)
```

## API endpoints (backend :8080)

- `POST /api/v1/chat` - grounded chat; `generate_image: true` also returns a base64 image.
- `POST /api/v1/search` - scripture retrieval (RAG), denomination-filtered.
- `POST /api/v1/verify` - anti-hallucination check of references in text (valid | unknown_book | nonexistent | misquote).
- `POST /api/v1/image` - Christian-themed image generation (safety guard + style templating; refuses disallowed prompts).
- `GET /api/v1/session/{id}` - inspect conversation memory (summary + recent turns).
- `DELETE /api/v1/session/{id}` - clear a conversation's memory.
- `GET /health/readyz` - readiness (LLM, image, Qdrant).

## MCP tools (:8001)

`ping`, `scripture_search`, `verse_verify`, `generate_image` - all delegate to the backend (URL from env).

## Image generation (Phase 4)

ComfyUI + Juggernaut SDXL via [services/backend/workflows/baseline_sdxl.json](services/backend/workflows/baseline_sdxl.json).
All knobs are env-driven (`IMAGE_CHECKPOINT`, `IMAGE_STEPS`, `IMAGE_CFG`, `IMAGE_WIDTH`,
`IMAGE_HEIGHT`, `IMAGE_SAMPLER`, `IMAGE_SCHEDULER`, `IMAGE_STYLE_TEMPLATE`,
`IMAGE_NEGATIVE_PROMPT`, `IMAGE_SAFETY_ENABLED`). In dev the mock backend returns a
placeholder PNG; in prod (gpu profile) ComfyUI renders a real image.

## Conversational core (Phase 5)

Tone, memory, and denomination framing are decoupled so conversations stay
consistent across turns:

- **Tone** - the system prompt is composed in
  [services/backend/app/services/prompt_builder.py](services/backend/app/services/prompt_builder.py)
  from `LLM_PERSONA` + fixed conduct rules (pastoral, humble, cite inline, never
  alter Scripture). `LLM_TEMPERATURE` keeps sampling steady.
- **Memory** - pass a `session_id` on `POST /api/v1/chat` and the backend keeps
  server-side memory ([services/backend/app/services/memory.py](services/backend/app/services/memory.py)):
  the last `MEMORY_MAX_TURNS` turns verbatim plus a rolling summary of older
  turns, folded in by the LLM once a conversation passes `MEMORY_SUMMARY_THRESHOLD`.
  Without a `session_id` the endpoint stays stateless and uses the request's
  `history`. In-memory store fits dev / a single replica; the `SessionMemory`
  interface allows a shared backend (e.g. Redis) later.
- **Denomination framing** - `denomination` (neutral | catholic | protestant |
  orthodox) both filters the retrieval canon (`retriever.py`) and changes how
  disputed doctrine is framed in the system prompt. `neutral` presents the main
  views fairly; a specific tradition is framed within it.

The whole flow is demonstrable with the mock LLM (no GPU): the mock reflects the
turn number, memory recall, and the active denomination framing. In prod
Qwen2.5-VL produces the real replies and summaries.

## Data ingestion (format-agnostic)

[services/ingest/data/sources.json](services/ingest/data/sources.json) declares each source by
`transport` (`kaggle` | `local`), `format` (`csv` | `json`), and a `fields` map. Adding a new
format/transport is a small reader/transport plugin in [services/ingest/ingest.py](services/ingest/ingest.py),
not a rewrite. Kaggle (`oswinrh/bible`) is just one transport; a Kaggle failure falls back to the
bundled sample.

## Exit criteria (Phase 1)

- **Mac / dev:** `make dev` brings up UI, backend, MCP, and Qdrant; a chat
  round-trips through the mock LLM and returns a placeholder image;
  `/health/readyz` is green.
- **EC2 / prod:** `make prod` brings up the full GPU stack; a real Qwen2.5-VL
  reply and a real Juggernaut image are produced end-to-end.
# AI-Assisment-solulab
