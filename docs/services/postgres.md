# PostgreSQL (durable chat store)

**Port:** 5432  
**Image:** `postgres:16`  
**Role:** Persists conversation sessions, turns, and image metadata across restarts.

## Why this service exists

In-process memory is lost on restart and cannot be shared across replicas. Postgres
provides durable, queryable storage for the full conversation history, enabling the
UI sidebar to list, switch, and delete past conversations.

The chat store implements the same `SessionMemory` interface as the in-memory
fallback, so the prompt window logic (rolling summary + last-N turns) is unchanged.

## Schema

Defined in `services/backend/app/db/models.py`. Created automatically on startup
via `Base.metadata.create_all`.

### `sessions`

| Column | Type | Purpose |
| ------ | ---- | ------- |
| `id` | string (PK) | Client-provided session_id |
| `denomination` | string | Last-used denomination |
| `summary` | text | Rolling LLM summary of older turns |
| `summary_turn_count` | int | Turns folded into summary |
| `created_at` | timestamp | First turn time |
| `updated_at` | timestamp | Last turn time |

### `turns`

| Column | Type | Purpose |
| ------ | ---- | ------- |
| `id` | int (PK) | Auto-increment |
| `session_id` | FK → sessions | Parent conversation |
| `role` | string | `user` or `assistant` |
| `content` | text | Message text |
| `intent_kind` | string | normal / scripture / image |
| `created_at` | timestamp | Turn time |

### `images`

| Column | Type | Purpose |
| ------ | ---- | ------- |
| `id` | string (PK) | UUID |
| `session_id` | FK → sessions | Parent conversation |
| `turn_id` | FK → turns | Linked assistant turn |
| `filename` | string | `{id}.png` on disk |
| `positive` | text | Composed positive prompt |
| `negative` | text | Negative prompt |
| `created_at` | timestamp | Render time |

Cascade deletes: deleting a session removes its turns and image records.

## Image file persistence

When an image is generated:

1. PNG bytes are written to `MEDIA_DIR` (`/data/media/{id}.png`) on the `media_data` volume.
2. An `Image` row is inserted linking to the session and turn.
3. The API returns `image_url: "/media/{id}.png"` (relative).
4. The backend serves files via `StaticFiles` at `MEDIA_URL_PATH`.
5. The UI resolves the full URL with `mediaUrl()`.

## API endpoints (via backend)

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `GET` | `/api/v1/sessions` | List all sessions with preview + turn count |
| `GET` | `/api/v1/session/{id}/history` | Full turn history with image URLs |
| `GET` | `/api/v1/session/{id}` | Memory snapshot (summary + recent) |
| `DELETE` | `/api/v1/session/{id}` | Delete session + cascade |

## Fallback behaviour

When `CHAT_STORE_ENABLED=false` or Postgres is unreachable at startup:

- Backend falls back to `InMemorySessionMemory`
- Images returned as base64 instead of URLs
- UI sidebar stays empty (no sessions to list)

## Key configuration

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `CHAT_STORE_ENABLED` | `true` | Enable Postgres store |
| `DATABASE_URL` | `postgresql+asyncpg://christai:christai@postgres:5432/christai` | SQLAlchemy URL |
| `POSTGRES_USER/PASSWORD/DB` | `christai` | Container credentials |
| `POSTGRES_PORT` | `5432` | Host port |
| `MEDIA_DIR` | `/data/media` | Image file storage |
| `MEDIA_URL_PATH` | `/media` | Static serve path |

## Storage

- Database: `pg_data` Docker named volume
- Images: `media_data` Docker named volume

## Related docs

- [Backend](backend.md) — `chat_store.py`, `db/models.py`
- [UI](ui.md) — session sidebar consumes these endpoints
