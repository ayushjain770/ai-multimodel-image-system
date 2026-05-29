# Bible corpus ingestion

**Path:** `services/ingest/`  
**Profile:** `ingest` (one-shot job, not a long-running service)  
**Role:** Downloads Bible translations, embeds verses, and upserts them into Qdrant.

## Why this service exists

RAG requires a real, searchable corpus. The Kaggle dataset `oswinrh/bible` provides
seven English translations (KJV, ASV, WEB, etc.) with structured verse metadata.
The ingest job transforms this into embedded vectors in Qdrant so the backend can
retrieve and verify scripture at runtime.

Without ingestion, RAG returns empty results and verification cannot check references.

## Architecture

```
services/ingest/
├── ingest.py              main ingestion script
├── data/
│   ├── sources.json       source manifest (transport + format + fields)
│   └── sample/            bundled fallback corpus (KJV sample)
├── Dockerfile
└── requirements.txt
```

## Source manifest

`sources.json` declares each data source in a format-agnostic way:

```json
{
  "sources": [
    {
      "name": "kaggle_bible",
      "transport": "kaggle",
      "format": "csv",
      "dataset": "oswinrh/bible",
      "fields": { "book": "book", "chapter": "chapter", "verse": "verse", "text": "text" },
      "canon": "protestant",
      "translations": ["KJV"]
    }
  ]
}
```

Adding a new source is a manifest entry + optional reader plugin — not a rewrite.

## Pipeline

```
1. Read sources.json
2. For each source:
   a. Transport: kaggle (kagglehub) or local (bundled sample)
   b. Format: csv or json reader
   c. Filter by INGEST_TRANSLATIONS (default: KJV)
3. Chunk: one point per verse
4. Embed: SentenceTransformers (BGE-small-en-v1.5)
5. Upsert: Qdrant collection (bible_verses)
```

## Transports

| Transport | When | Credentials |
| --------- | ---- | ----------- |
| `kaggle` | Primary (prod/dev with credentials) | `KAGGLE_USERNAME` + `KAGGLE_KEY` or `KAGGLE_API_TOKEN` |
| `local` | Fallback when Kaggle fails or creds missing | None (bundled sample) |

Kaggle cache persists in the `kagglehub_cache` Docker volume.

## Idempotency

The orchestrator runs ingestion after startup. It checks whether the Qdrant collection
already has points and skips unless `REINGEST=true`. Safe to run repeatedly.

```bash
make ingest          # via orchestrator
# or directly:
docker compose --profile ingest run --rm ingest
```

## Key configuration

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `QDRANT_URL` | `http://qdrant:6333` | Target vector DB |
| `QDRANT_COLLECTION` | `bible_verses` | Collection name |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Must match backend |
| `BIBLE_SOURCES` | `/app/data/sources.json` | Source manifest path |
| `INGEST_TRANSLATIONS` | `KJV` | Comma-separated translations to embed |
| `KAGGLE_DATASET` | `oswinrh/bible` | Kaggle dataset slug |
| `REINGEST` | `false` | Force re-ingestion |

## Dataset details (Kaggle `oswinrh/bible`)

| Translation | Code |
| ----------- | ---- |
| King James Version | KJV |
| American Standard Version | ASV |
| Bible in Basic English | BBE |
| Darby English Bible | DARBY |
| Webster's Bible | WBT |
| World English Bible | WEB |
| Young's Literal Translation | YLT |

Also includes cross-reference tables, genre classification, and version metadata.

Dev defaults to KJV only for fast CPU ingestion. Prod can ingest multiple
translations by setting `INGEST_TRANSLATIONS=KJV,WEB`.

## Related docs

- [Qdrant](qdrant.md) — where vectors are stored
- [Backend](backend.md) — retriever and verifier consume the collection
- [Infrastructure](../infrastructure.md) — ingest step in `script.sh up`
