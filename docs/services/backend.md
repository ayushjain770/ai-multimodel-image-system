# FastAPI backend (gateway)

**Port:** 8080  
**Path:** `services/backend/`  
**Role:** Single entrypoint for the UI, MCP server, and tests. Owns all business logic.

## Why this service exists

Every feature — chat, RAG, verification, moderation, image generation, session
management — runs here so clients stay thin. The UI only streams SSE; MCP tools
only proxy HTTP calls. This keeps behaviour identical across interfaces and makes
the mock/prod swap transparent.

## Architecture

```
app/
├── main.py              FastAPI app, lifespan, CORS, static /media mount
├── core/
│   ├── config.py        pydantic-settings (all env vars)
│   └── logging.py       structured logging
├── routers/
│   ├── chat.py          POST /chat, POST /chat/stream
│   ├── search.py        POST /search (RAG)
│   ├── verify.py        POST /verify (anti-hallucination)
│   ├── image.py         POST /image
│   ├── compose.py       POST /compose_image_prompt
│   ├── moderate.py      POST /moderate
│   ├── session.py       GET/DELETE sessions, history
│   └── health.py        GET /health/healthz, /health/readyz
├── services/
│   ├── orchestrator.py  intent classification (normal/scripture/image)
│   ├── moderation.py    input/output safety rules + optional LLM judge
│   ├── retriever.py     embed query → Qdrant search → citations
│   ├── verifier.py      parse references → canonical lookup → fuzzy match
│   ├── prompt_builder.py system prompt (persona + denomination + citations)
│   ├── image_prompt.py  safety guard, style template, LLM compose
│   ├── memory.py        in-process session memory (dev fallback)
│   └── chat_store.py    Postgres-backed memory + image persistence
├── clients/
│   ├── llm_client.py    MockLLMClient | VLLMClient (chat + stream + summarize)
│   ├── embeddings.py    SentenceTransformers (BGE)
│   ├── qdrant_client.py Qdrant REST wrapper
│   └── comfy_client.py  MockImageClient | ComfyUI workflow runner
└── db/
    ├── models.py        Session, Turn, Image ORM models
    └── engine.py        async SQLAlchemy engine
```

## Chat pipeline

Both `/chat` and `/chat/stream` share `prepare_turn()` and `postprocess()`:

| Step | Function | What happens |
| ---- | -------- | -------------- |
| 0 | `prepare_turn` | Input moderation; rewrite/alter guard |
| 1 | `prepare_turn` | Load memory (summary + `CONTEXT_RECENT_TURNS`) |
| 2 | `prepare_turn` | Intent classification via orchestrator |
| 3 | `prepare_turn` | RAG retrieve (scripture intent only) |
| 4 | `prepare_turn` | Build system prompt → call LLM |
| 5 | `postprocess` | Output moderation |
| 6 | `postprocess` | Verse verification |
| 7 | `postprocess` | Image compose + render (image intent) |
| 8 | both | Persist turn to chat store |

Streaming emits SSE events: `meta` → `token`* → `final` → `done`.

## Key configuration

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `LLM_BACKEND` | `mock` | `mock` or `vllm` |
| `IMAGE_BACKEND` | `mock` | `mock` or `comfy` |
| `RAG_ENABLED` | `true` | Enable retrieval |
| `ORCHESTRATOR_ENABLED` | `true` | Intent routing |
| `MODERATION_ENABLED` | `true` | Safety layer |
| `CHAT_STORE_ENABLED` | `true` | Postgres persistence |
| `CONTEXT_RECENT_TURNS` | `3` | Turns sent to LLM per request |
| `MEMORY_MAX_TURNS` | `8` | Turns kept verbatim in store |

## Dependencies

| Dependency | Used for |
| ---------- | -------- |
| Qdrant | RAG search, canonical verse lookup |
| Postgres | Durable sessions/turns/images |
| vLLM | Chat, summarization, optional judge (prod) |
| ComfyUI | Image rendering (prod) |

## Health checks

- `/health/healthz` — process alive
- `/health/readyz` — LLM client, image client, and Qdrant reachable

## Related docs

- [vLLM](vllm.md) — LLM client target
- [Qdrant](qdrant.md) — RAG and verification data
- [Postgres](postgres.md) — chat store
- [ComfyUI](comfyui.md) — image backend
