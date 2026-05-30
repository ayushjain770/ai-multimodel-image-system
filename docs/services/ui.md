# Next.js UI

**Port:** 3000  
**Path:** `services/ui/`  
**Role:** Browser-facing chat application with streaming, session sidebar, and image display.

## Why this service exists

Provides the end-user interface. It talks only to the FastAPI backend (`:8080`) —
never directly to vLLM, ComfyUI, or Qdrant — keeping the browser surface minimal
and secure.

## Architecture

```
services/ui/
├── app/
│   ├── page.tsx         main chat page (sidebar + messages + composer)
│   ├── layout.tsx       root layout
│   └── globals.css      dark theme, layout, sidebar, bubble styles
├── lib/
│   └── api.ts           typed API client (REST + SSE parser)
├── next.config.mjs      Next.js config
└── Dockerfile           multi-stage build
```

## Features

### Streaming chat

`streamChat()` in `lib/api.ts` calls `POST /api/v1/chat/stream` and parses SSE:

| Event | Handler | UI effect |
| ----- | ------- | --------- |
| `meta` | `onMeta` | Shows intent badge (normal/scripture/image) |
| `token` | `onToken` | Appends delta to assistant bubble |
| `final` | `onFinal` | Sets final reply, image URL, moderation info |

On **image** turns, the assistant text is a deterministic template ("Creating your
artwork… please wait") streamed in `token` events; the PNG arrives in `final`.
While streaming before text arrives, the UI shows **"Generating artwork…"** when
intent is `image`.
| `done` | — | Marks streaming complete |

### Session sidebar (Phase 10)

- Lists conversations from `GET /api/v1/sessions`
- Clicking a session loads full history via `GET /api/v1/session/{id}/history`
- "New chat" mints a fresh `session_id`
- Delete removes via `DELETE /api/v1/session/{id}`
- Active session id persisted in `localStorage` (`christ-ai.session-id`)
- Sidebar refreshes after each reply and after delete

### Composer controls

- **Denomination** selector: neutral, catholic, protestant, orthodox
- **Image toggle**: forces image generation regardless of intent
- **Send**: submits via streaming endpoint

### Image rendering

Images are shown from `image_url` (persisted, served at `/media/...`) with fallback
to inline `image_base64` when the durable store is disabled.

## Key configuration

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8080` | Backend URL (browser-reachable) |
| `PUBLIC_HOST` | _(auto on EC2)_ | Host printed in startup URLs (display only) |
| `UI_PORT` | `3000` | Host port mapping |

In prod/EC2, `./startup.sh prod` auto-detects the instance public IP via AWS
metadata and sets `NEXT_PUBLIC_API_URL` before the UI image is built. Override
`PUBLIC_HOST` and `NEXT_PUBLIC_API_URL` in `.env` when using a domain or Elastic IP.

## Dev mode

`docker-compose.dev.yml` bind-mounts the source and runs `npm run dev` for hot
reload. No rebuild needed for frontend changes.

## Related docs

- [Backend](backend.md) — API endpoints the UI calls
- [Postgres](postgres.md) — where session history is stored
