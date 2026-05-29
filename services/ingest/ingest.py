"""One-shot Bible corpus ingestion into Qdrant.

Reads a config-driven source manifest, chunks the text by verse, embeds each
verse with a sentence-transformers model, and upserts into a Qdrant collection.

Idempotent: if the collection already holds points it is left untouched unless
REINGEST=true. Every setting comes from the environment - nothing hardcoded.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s [ingest] %(message)s",
)
log = logging.getLogger("ingest")

_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")  # URL namespace


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _point_id(ref: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, ref))


def load_verses(manifest_path: Path) -> list[dict]:
    """Flatten the manifest's translations into verse records with metadata."""
    manifest = json.loads(manifest_path.read_text())
    base = manifest_path.parent
    records: list[dict] = []
    for tr in manifest["translations"]:
        verses = json.loads((base / tr["file"]).read_text())
        for v in verses:
            ref = f"{v['book']} {v['chapter']}:{v['verse']}"
            records.append(
                {
                    "translation": tr["name"],
                    "book": v["book"],
                    "chapter": int(v["chapter"]),
                    "verse": int(v["verse"]),
                    "canon_tags": tr["canon_tags"],
                    "text": v["text"],
                    "ref": ref,
                }
            )
    return records


def ensure_collection(
    client: QdrantClient, name: str, dim: int, reingest: bool
) -> bool:
    """Return True if we should ingest, False if an existing collection is reused."""
    if client.collection_exists(name):
        count = client.count(name, exact=True).count
        if count > 0 and not reingest:
            log.info("collection '%s' already has %d points; skipping (REINGEST=false)", name, count)
            return False
        log.info("recreating collection '%s' (reingest=%s, existing=%d)", name, reingest, count)
        client.delete_collection(name)
    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )
    # Indexed payload fields we filter on at query time.
    client.create_payload_index(name, "canon_tags", models.PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "translation", models.PayloadSchemaType.KEYWORD)
    return True


def main() -> int:
    qdrant_url = _env("QDRANT_URL", "http://qdrant:6333")
    collection = _env("QDRANT_COLLECTION", "bible_verses")
    model_name = _env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    sources = Path(_env("BIBLE_SOURCES", "/app/data/sample/sources.json"))
    reingest = _env("REINGEST", "false").lower() == "true"
    batch = int(_env("EMBED_BATCH", "64"))

    if not sources.exists():
        log.error("source manifest not found: %s", sources)
        return 1

    log.info("loading embedding model: %s", model_name)
    model = SentenceTransformer(model_name)
    dim = model.get_sentence_embedding_dimension()
    log.info("embedding dimension: %d", dim)

    client = QdrantClient(url=qdrant_url)

    if not ensure_collection(client, collection, dim, reingest):
        return 0

    records = load_verses(sources)
    log.info("ingesting %d verses from %s", len(records), sources)

    texts = [r["text"] for r in records]
    vectors = model.encode(
        texts, batch_size=batch, normalize_embeddings=True, show_progress_bar=False
    )

    points = [
        models.PointStruct(id=_point_id(r["ref"] + ":" + r["translation"]), vector=vec.tolist(), payload=r)
        for r, vec in zip(records, vectors)
    ]
    client.upsert(collection_name=collection, points=points, wait=True)

    total = client.count(collection, exact=True).count
    log.info("done; collection '%s' now has %d points", collection, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
