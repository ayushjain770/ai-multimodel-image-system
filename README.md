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

```bash
cp .env.example .env     # or: make env
```

### Dev (this Mac, no GPU)

Runs UI + backend + MCP + Qdrant with hot reload. The backend uses a mock LLM
and a placeholder image generator, so no GPU is required.

```bash
make dev
```

Then:

- UI: http://localhost:3000
- Backend health: http://localhost:8080/health/readyz
- Send a chat: returns a deterministic mock reply + a placeholder image.

### Prod (EC2, GPU)

Brings up the full stack including real Qwen2.5-VL (vLLM) and ComfyUI/Juggernaut.

```bash
# 1. Put the image checkpoint in place (not committed):
#    models/checkpoints/juggernautXL.safetensors
# 2. Set HF_TOKEN in .env if the model repo is gated.
# 3. Switch backends in .env: LLM_BACKEND=vllm, IMAGE_BACKEND=comfy
make prod
make logs            # watch first-boot model download
```

The first prod boot downloads the Qwen2.5-VL weights into the `hf_cache` volume;
expect this to take a while. The 3B VL model fits comfortably on a single
mid-size GPU.

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
Makefile                  make dev | prod | down | logs | ps
services/
  backend/                FastAPI gateway (:8080)
  mcp-server/             FastMCP server (:8001)
  ui/                     Next.js UI (:3000)
  comfyui/                ComfyUI image (:8188)
models/                   mounted checkpoints (gitignored)
```

## Exit criteria (Phase 1)

- **Mac / dev:** `make dev` brings up UI, backend, MCP, and Qdrant; a chat
  round-trips through the mock LLM and returns a placeholder image;
  `/health/readyz` is green.
- **EC2 / prod:** `make prod` brings up the full GPU stack; a real Qwen2.5-VL
  reply and a real Juggernaut image are produced end-to-end.
# AI-Assisment-solulab
