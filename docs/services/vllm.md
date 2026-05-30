# vLLM (Qwen2.5-VL)

**Port:** 8000  
**Image:** `vllm/vllm-openai:latest`  
**Profile:** `gpu` (prod only)  
**Role:** Serves the vision-language model for chat, summarization, and optional moderation.

## Why this service exists

Qwen2.5-VL-3B-Instruct is the project's chosen LLM — small enough for a single GPU,
multimodal-capable, and strong at instruction following. vLLM provides efficient
OpenAI-compatible serving with streaming, which the backend consumes via `VLLMClient`.

In dev, `LLM_BACKEND=mock` replaces vLLM with deterministic fake replies so the
full pipeline (moderation, RAG, memory, verification) is testable without a GPU.

## Model

| Setting | Default |
| ------- | ------- |
| Model | `Qwen/Qwen2.5-VL-3B-Instruct` |
| Context | 8192 tokens (`VLLM_MAX_MODEL_LEN`) |
| GPU memory | 85% utilization (`VLLM_GPU_MEMORY_UTILIZATION`) |

Weights are cached in the `hf_cache` Docker volume. The orchestrator can pre-pull
them during `make prod` when `PREPULL_LLM=true`.

## API (OpenAI-compatible)

| Endpoint | Used by backend for |
| -------- | ------------------- |
| `POST /v1/chat/completions` | Chat (`chat`, `stream_chat`), summarization, image prompt compose |
| `GET /health` | Readiness probe |

The backend connects via `VLLM_BASE_URL=http://vllm:8000/v1`.

### Streaming

`VLLMClient.stream_chat()` opens an SSE stream from vLLM and yields token deltas.
These are forwarded to the UI as SSE `token` events.

## What vLLM is used for

| Task | When | Config |
| ---- | ---- | ------ |
| **Planner** | Every chat turn when `LLM_BACKEND=vllm` | `PLANNER_INSTRUCTION` |
| **Synthesizer** | Streamed chat reply (normal and scripture routes only) | `LLM_TEMPERATURE` |
| Chat replies | Non-image turns | Always (or mock) |
| Conversation summarization | Turns exceed `MEMORY_SUMMARY_THRESHOLD` | `memory.py` / `chat_store.py` |
| Image prompt composition | Image route (execution phase) | `image_prompt.py`, `IMAGE_COMPOSER_TEMPERATURE` |
| Image turn user text | Not used — backend uses `IMAGE_REPLY_TEMPLATE` instead | — |
| Moderation judge | Borderline input | `MODERATION_LLM_JUDGE=true` |

## Key configuration

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `LLM_BACKEND` | `mock` | Set to `vllm` in prod |
| `VLLM_BASE_URL` | `http://vllm:8000/v1` | Internal API URL |
| `VLLM_MODEL` | `Qwen/Qwen2.5-VL-3B-Instruct` | Model identifier |
| `VLLM_PORT` | `8000` | Host port |
| `HF_TOKEN` | — | HuggingFace token if model is gated |
| `LLM_TEMPERATURE` | `0.4` | Sampling temperature |
| `LLM_TIMEOUT` | `120` | Request timeout (seconds) |

## Dev vs prod

| Mode | LLM_BACKEND | vLLM container | Behaviour |
| ---- | ----------- | -------------- | --------- |
| Dev | `mock` | Not started | Deterministic replies reflecting turn count, memory, denomination |
| Prod | `vllm` | Started (gpu profile) | Real Qwen2.5-VL inference |

## Related docs

- [Backend](backend.md) — `llm_client.py` wraps vLLM
- [Infrastructure](../infrastructure.md) — model pre-pull and GPU profile
