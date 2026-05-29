# FastMCP server

**Port:** 8001  
**Path:** `services/mcp-server/`  
**Role:** Exposes backend capabilities as MCP tools for LangChain agents and external clients.

## Why this service exists

AI agents (LangChain ReAct, Cursor, custom bots) need a standard tool interface.
FastMCP wraps the backend REST API as typed tools over streamable-http transport,
so agents can search scripture, verify verses, compose image prompts, and generate
images without reimplementing the pipeline.

## Architecture

```
services/mcp-server/
├── server.py       FastMCP app + tool definitions
├── requirements.txt
└── Dockerfile
```

Every tool is a thin HTTP proxy to the backend:

```
Agent  →  MCP :8001  →  httpx  →  Backend :8080  →  Qdrant / vLLM / ComfyUI
```

No business logic lives in the MCP server. This ensures tools always match the
gateway behaviour (moderation, RAG, safety).

## Tools

| Tool | Backend endpoint | Purpose |
| ---- | ---------------- | ------- |
| `ping` | — | Liveness check |
| `scripture_search` | `POST /api/v1/search` | RAG verse retrieval |
| `verse_verify` | `POST /api/v1/verify` | Anti-hallucination check |
| `generate_image` | `POST /api/v1/image` | Christian image generation |
| `prompt_composer` | `POST /api/v1/compose_image_prompt` | LLM scene prompt (no render) |
| `moderate` | `POST /api/v1/moderate` | Safety screening |

## Transport

- Protocol: MCP streamable-http
- URL: `http://localhost:8001/mcp`
- Requires an `initialize` handshake before tool calls (see `tests/langchain_tools/`)

## Key configuration

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `BACKEND_URL` | `http://backend:8080` | Gateway URL (internal DNS) |
| `MCP_PORT` | `8001` | Host port mapping |
| `MCP_HTTP_TIMEOUT` | `30` | Per-tool HTTP timeout (seconds) |

## Testing

The LangChain harness in `tests/langchain_tools/test_tool_calling.py` validates:

- MCP handshake and tool listing
- Intent routing (scripture → search, image → compose + generate)
- End-to-end tool call chains

## Related docs

- [Backend](backend.md) — where all tool logic executes
- [Architecture overview](../architecture/overview.md) — agent integration diagram
