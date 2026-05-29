# Qdrant (vector database)

**Port:** 6333 (HTTP), 6334 (gRPC)  
**Image:** `qdrant/qdrant:v1.12.4`  
**Role:** Stores embedded Bible verses for RAG retrieval and canonical lookup for verification.

## Why this service exists

Scripture grounding requires fast semantic search over hundreds of thousands of
verse chunks. Qdrant is a lightweight, Docker-native vector database that supports
payload filtering (used for denomination canon tags and translation selection).

The same collection serves two purposes:

1. **RAG retrieval** — find verses semantically similar to the user's question.
2. **Verification** — look up canonical text for a parsed reference to detect
   misquotes and fabricated verses.

## Data model

**Collection:** `bible_verses` (configurable via `QDRANT_COLLECTION`)

Each point represents one verse chunk:

| Payload field | Example | Used for |
| ------------- | ------- | -------- |
| `book` | `Genesis` | Filtering, display |
| `chapter` | `1` | Reference parsing |
| `verse` | `1` | Reference parsing |
| `text` | `In the beginning…` | Citation content, fuzzy verify |
| `translation` | `KJV` | Canon selection |
| `canon` | `protestant` | Denomination filter |

Vectors are 384-dimensional (BGE-small-en-v1.5).

## RAG retrieval flow

```
User message
    │
    ▼
EmbeddingClient.encode(query + BGE prefix)
    │
    ▼
Qdrant.search(collection, vector, top_k, filter=canon)
    │
    ▼
Retriever → Citation[] → injected into system prompt
```

Configuration: `RAG_ENABLED`, `RAG_TOP_K` (default 5), `EMBEDDING_QUERY_PREFIX`.

## Verification flow

```
LLM reply text
    │
    ▼
Verifier.parse_references()  →  ["John 3:16", "Genesis 1:1", …]
    │
    ▼
For each reference:
    Qdrant lookup (book + chapter + verse + translation)
    │
    ▼
difflib fuzzy match quoted text vs canonical
    │
    ▼
Status: valid | misquote | nonexistent | unknown_book
```

Configuration: `VERIFY_ENABLED`, `VERIFY_TRANSLATION` (default KJV),
`VERIFY_FUZZY_THRESHOLD` (default 0.6).

## Ingestion

Verses are embedded and upserted by the one-shot ingest job. See
[ingest.md](ingest.md). Ingestion is idempotent — the orchestrator skips re-ingest
unless `REINGEST=true`.

## Key configuration

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `QDRANT_URL` | `http://qdrant:6333` | Internal API URL |
| `QDRANT_COLLECTION` | `bible_verses` | Collection name |
| `QDRANT_PORT` | `6333` | Host HTTP port |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Must match ingest model |
| `RAG_TOP_K` | `5` | Verses retrieved per query |

## Storage

Data persists in the `qdrant_data` Docker named volume.

## Related docs

- [Ingest](ingest.md) — how verses get into Qdrant
- [Backend](backend.md) — `retriever.py`, `verifier.py`, `qdrant_client.py`
