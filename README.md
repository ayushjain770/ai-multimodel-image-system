# Christianity AI Assistant

A multimodal, scripture-grounded Christian AI assistant. It answers faith questions with
real Bible citations, verifies scripture references to prevent hallucination, generates
reverent Christian artwork, and keeps durable conversation history — all behind a single
FastAPI gateway the UI and MCP agents talk to.

---

## Tech stack

| Layer | Technology | Role |
| ----- | ---------- | ---- |
| **UI** | Next.js 14, React, TypeScript | Streaming chat UI with session sidebar |
| **Gateway** | FastAPI, Pydantic, SQLAlchemy | Single API entrypoint; orchestrates every feature |
| **LLM** | Qwen2.5-VL-3B-Instruct via vLLM | Chat, summarization, optional intent/moderation judge |
| **Embeddings** | SentenceTransformers (BGE-small-en) | Query + document vectors for RAG |
| **Vector DB** | Qdrant | Stores ingested Bible verse embeddings |
| **Relational DB** | PostgreSQL 16 | Durable sessions, turns, image metadata |
| **Image gen** | ComfyUI + Juggernaut XL (SDXL) | Christian-themed image rendering |
| **Tools** | FastMCP (streamable-http) | Exposes backend capabilities to LangChain/agents |
| **Ingestion** | Python + kagglehub | Downloads and embeds the Kaggle Bible corpus |
| **Orchestration** | Docker Compose, `./startup.sh` | One project; dev/prod are deploy modes |
| **Testing** | LangChain tool-calling harness | Validates MCP tools and intent routing |

---

## Ports

| Service | Default port | Profile | Notes |
| ------- | ------------ | ------- | ----- |
| **UI** (Next.js) | 3000 | always | Browser-facing chat app |
| **Backend** (FastAPI) | 8080 | always | Single gateway for UI and MCP |
| **MCP server** (FastMCP) | 8001 | always | Tool surface for agents |
| **Postgres** | 5432 | always | Durable chat store |
| **Qdrant** (HTTP) | 6333 | always | Vector search for RAG |
| **Qdrant** (gRPC) | 6334 | always | Optional gRPC client |
| **vLLM** (Qwen2.5-VL) | 8000 | `gpu` | OpenAI-compatible LLM API |
| **ComfyUI** (Juggernaut) | 8188 | `gpu` | SDXL image generation |

All host ports are overridable via `.env` (`UI_PORT`, `BACKEND_PORT`, etc.). The UI
never talks to GPU services directly — only to the backend on `:8080`.

---

## How to run

One project, two **deploy modes** (same codebase — only the LLM/image backend changes).

| Mode | Command | LLM | Image | GPU |
| ---- | ------- | --- | ----- | --- |
| **dev** (default) | `./startup.sh` or `./startup.sh dev` | mock | mock | no |
| **prod** | `./startup.sh prod` | vLLM | ComfyUI | yes |

### Prerequisites

- Docker + Docker Compose v2
- **Dev:** Mac or any machine without a GPU
- **Prod:** Linux + NVIDIA GPU + NVIDIA Container Toolkit

### Quick start

`./startup.sh` handles preflight, build, model download (prod), startup, health checks,
Bible ingestion, and a smoke test. It bootstraps `.env` from `.env.example` on first run.
`make dev` / `make prod` are thin aliases to the same script.

```bash
chmod +x startup.sh   # first time only

./startup.sh          # dev mode (default)
./startup.sh prod     # full GPU stack
```

After `make dev`:

| URL | Purpose |
| --- | ------- |
| http://localhost:3000 | Chat UI |
| http://localhost:8080/health/readyz | Backend readiness |
| http://localhost:8080/docs | FastAPI Swagger UI |

### Other commands

```bash
make doctor    # preflight checks only
make build     # build images (with error detection)
make models    # download Juggernaut + pre-pull LLM (prod)
make ingest    # re-run Bible corpus ingestion
make health    # wait for all services healthy
make logs SVC=backend   # tail a service log
make down      # stop dev stack
make down-prod # stop prod stack
```

See [infrastructure/README.md](infrastructure/README.md) and
[docs/infrastructure.md](docs/infrastructure.md) for orchestrator details.

---

## What problem it solves

General-purpose LLMs hallucinate scripture, alter verses, and lack denomination-aware
framing. This project addresses that with a purpose-built pipeline:

1. **Grounded answers** — RAG retrieves real verses from an ingested Bible corpus
   (Kaggle `oswinrh/bible`, 7 translations) instead of relying on model memory.
2. **Anti-hallucination** — Post-generation verification checks every cited reference
   against a canonical verse store (valid, misquote, nonexistent, unknown book).
3. **Planner brain** — Planner → Execute → Synthesizer routes each turn; RAG miss
   returns an honest reply instead of hallucinating.
4. **Safety layer** — Rule-based input/output moderation blocks hateful, violent,
   jailbreak, and self-harm content with on-brand refusals.
5. **Conversational memory** — Rolling summary + last-N turns keep long chats coherent
   without blowing the context window; history persists in Postgres.
6. **Christian image generation** — ComfyUI + Juggernaut produces reverent artwork with
   style templating and content safety checks.
7. **Agent-ready tools** — FastMCP exposes search, verify, compose, image, and moderate
   so LangChain agents can chain the same capabilities.

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Browser (Next.js UI :3000)                                             │
│  streaming chat · session sidebar · denomination selector · images      │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ REST / SSE
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FastAPI Gateway (:8080)                                                │
│  chat · search · verify · image · compose · moderate · session · health │
│  ┌─────────────┐ ┌──────────────┐ ┌────────────┐ ┌───────────────────┐  │
│  │ Planner     │ │ Moderation   │ │ Retriever  │ │ Chat store        │  │
│  │ route+tool  │ │ input/output │ │ RAG + canon│ │ Postgres + media  │  │
│  └─────────────┘ └──────────────┘ └────────────┘ └───────────────────┘  │
└───────┬──────────────┬──────────────┬──────────────┬────────────────────┘
        │              │              │              │
        ▼              ▼              ▼              ▼
   vLLM :8000    ComfyUI :8188   Qdrant :6333   Postgres :5432
   Qwen2.5-VL    Juggernaut XL   verse vectors   sessions/turns/images
        ▲
        │ MCP tools delegate to backend
   FastMCP :8001  (scripture_search · verse_verify · generate_image ·
                   prompt_composer · moderate · ping)
```

**Request flow (chat):**

1. User message arrives via **HTTP POST** (JSON body — not SSE).
2. Input moderation → rewrite guard → load memory
3. **Planner** decides route (normal / scripture / image)
4. **Execute:** RAG retrieval or image prompt compose
5. **rag_miss** → honest template (no synthesizer) if no grounded verses
6. **Synthesizer** LLM streams reply via **SSE** to the UI
7. Render image, verify, persist

Details: [docs/services/planner.md](docs/services/planner.md)

Full diagrams and per-service detail: [docs/architecture/overview.md](docs/architecture/overview.md).

---

## API endpoints (FastAPI :8080)

### Chat & streaming

| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/api/v1/chat` | Full chat pipeline; returns JSON `ChatResponse` |
| `POST` | `/api/v1/chat/stream` | Same pipeline, streamed as SSE (`meta` → `token`* → `final` → `done`) |

Both accept `{ message, session_id?, denomination?, generate_image?, history? }`.

### RAG & verification

| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/api/v1/search` | Scripture retrieval; returns ranked verses + citations |
| `POST` | `/api/v1/verify` | Anti-hallucination check of references in text |

### Image

| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/api/v1/image` | Generate a Christian-themed image (safety guard + ComfyUI) |
| `POST` | `/api/v1/compose_image_prompt` | LLM-assisted scene prompt (no render) |

### Safety & sessions

| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/api/v1/moderate` | Screen text (`stage`: input \| output) |
| `GET` | `/api/v1/sessions` | List stored conversations |
| `GET` | `/api/v1/session/{id}/history` | Full turn history with image URLs |
| `GET` | `/api/v1/session/{id}` | Memory snapshot (summary + recent turns) |
| `DELETE` | `/api/v1/session/{id}` | Delete a conversation |

### Health & media

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/health/healthz` | Liveness |
| `GET` | `/health/readyz` | Readiness (LLM, image backend, Qdrant) |
| `GET` | `/media/{filename}` | Persisted generated images |

Interactive docs: http://localhost:8080/docs

---

## vLLM endpoint (:8000, prod only)

vLLM serves **Qwen/Qwen2.5-VL-3B-Instruct** with an OpenAI-compatible API:

| Path | Description |
| ---- | ----------- |
| `POST /v1/chat/completions` | Chat (used by backend `VLLMClient`) |
| `GET /health` | vLLM health |

The backend connects via `VLLM_BASE_URL=http://vllm:8000/v1`. In dev,
`LLM_BACKEND=mock` bypasses vLLM entirely.

---

## MCP tools (:8001)

| Tool | Delegates to | Purpose |
| ---- | ------------ | ------- |
| `ping` | — | Liveness |
| `scripture_search` | `POST /api/v1/search` | RAG verse retrieval |
| `verse_verify` | `POST /api/v1/verify` | Anti-hallucination check |
| `generate_image` | `POST /api/v1/image` | Image generation |
| `prompt_composer` | `POST /api/v1/compose_image_prompt` | LLM image prompt |
| `moderate` | `POST /api/v1/moderate` | Safety screening |

Transport: streamable-http at `http://localhost:8001/mcp`.

---

## RAG pipeline

1. **Ingest** — `services/ingest` downloads the Kaggle Bible corpus (or bundled sample),
   chunks verses, embeds with BGE-small-en, and upserts into Qdrant (`bible_verses`).
2. **Query** — On scripture intent, the retriever embeds the user message (with a BGE
   query prefix), searches Qdrant, and filters by denomination canon.
3. **Ground** — Top-K verses are injected into the system prompt as citations.
4. **Verify** — After the LLM reply, every referenced verse is checked against the
   canonical store (fuzzy match via `difflib`).

Configuration: `RAG_ENABLED`, `EMBEDDING_MODEL`, `QDRANT_COLLECTION`, `RAG_TOP_K`,
`BIBLE_SOURCES`, `VERIFY_ENABLED`, `VERIFY_TRANSLATION`.

Details: [docs/services/qdrant.md](docs/services/qdrant.md),
[docs/services/ingest.md](docs/services/ingest.md).

---

## Documentation

| Document | Contents |
| -------- | -------- |
| [docs/README.md](docs/README.md) | Documentation index |
| [docs/architecture/overview.md](docs/architecture/overview.md) | System architecture, data flow, phase map |
| [docs/services/backend.md](docs/services/backend.md) | FastAPI gateway — Planner pipeline |
| [docs/services/planner.md](docs/services/planner.md) | Planner brain, routes, RAG miss policy |
| [docs/services/ui.md](docs/services/ui.md) | Next.js chat UI — streaming, sidebar, API client |
| [docs/services/mcp-server.md](docs/services/mcp-server.md) | FastMCP tool server |
| [docs/services/vllm.md](docs/services/vllm.md) | vLLM + Qwen2.5-VL serving |
| [docs/services/comfyui.md](docs/services/comfyui.md) | ComfyUI + Juggernaut image generation |
| [docs/services/qdrant.md](docs/services/qdrant.md) | Vector DB, RAG retrieval, verification |
| [docs/services/postgres.md](docs/services/postgres.md) | Durable chat store, image persistence |
| [docs/services/ingest.md](docs/services/ingest.md) | Bible corpus ingestion pipeline |
| [docs/infrastructure.md](docs/infrastructure.md) | Orchestrator, Docker Compose, dev vs prod |
| [infrastructure/README.md](infrastructure/README.md) | Script commands and env vars |

---

## Project layout

```
docker-compose.yml          base service definitions
docker-compose.dev.yml      dev overrides (mocks, hot reload, no GPU)
docker-compose.prod.yml     prod overrides (GPU profile, restart policies)
.env.example                documented configuration
startup.sh                  single entrypoint (./startup.sh dev|prod)
Makefile                    thin wrappers around startup.sh
infrastructure/             one-command orchestration (script.sh + lib/)
docs/                       architecture and per-service documentation
services/
  backend/                  FastAPI gateway (:8080)
  mcp-server/               FastMCP server (:8001)
  ui/                       Next.js UI (:3000)
  comfyui/                  ComfyUI image (:8188)
  ingest/                   one-shot Bible ingestion job
models/                     mounted checkpoints (gitignored)
tests/langchain_tools/      MCP + intent routing test harness
```

---

## EC2 / production notes

- Requires NVIDIA driver + NVIDIA Container Toolkit on the host.
- Open security-group inbound ports **3000** (UI) and **8080** (backend API). Optional: 6333 (Qdrant dashboard), 8001 (MCP).
- In `.env`, set your EC2 public IP or domain:
  - `PUBLIC_HOST=<ec2-public-ip>` — startup prints browser URLs with this host
  - `NEXT_PUBLIC_API_URL=http://<ec2-public-ip>:8080` — where the UI calls the API from the browser
- **Rebuild the UI** after changing `NEXT_PUBLIC_API_URL` (it is baked in at build time):
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.prod.yml build ui
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d ui
  ```
- Open the app at `http://<ec2-public-ip>:3000` (not `localhost` from your laptop).
- MCP has no page at `/` — use `http://<host>:8001/mcp` for the MCP endpoint. A `GET /` 404 is normal.
- Set `LLM_BACKEND=vllm` and `IMAGE_BACKEND=comfy` in `.env`.
- Set `HF_TOKEN` if the Qwen model repo is gated.
- Weights live in Docker volumes (`hf_cache`, `models/`) — not committed to git.
