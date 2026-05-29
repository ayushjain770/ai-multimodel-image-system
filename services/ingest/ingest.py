"""One-shot Bible corpus ingestion into Qdrant.

Reads a config-driven source manifest with typed sources, embeds each verse
with a sentence-transformers model, and upserts into a Qdrant collection.

Source types
------------
* ``kaggle``     - download a Kaggle dataset via ``kagglehub`` and load the
                   configured per-translation CSVs (e.g. ``t_kjv.csv``). Book
                   names come from a name column when present, else are resolved
                   from the numeric book id via the dataset's ``key_english`` map
                   (with a bundled fallback).
* ``local_json`` - load a bundled JSON verse list (used for the deuterocanon
                   sample so denomination/canon filtering stays demonstrable).

Behaviour
---------
* ``INGEST_TRANSLATIONS`` (comma-separated) controls which Kaggle translations
  are embedded - CPU ingestion scales with this, so dev defaults to ``KJV``.
* Idempotent: an already-populated collection is left untouched unless
  ``REINGEST=true``.
* Graceful fallback: if the Kaggle download/auth fails the bundled sample is
  ingested instead so the stack still comes up. Nothing is hardcoded - every
  setting comes from the environment or the manifest.
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

# Standard 66-book number -> canonical name fallback (used when the Kaggle
# dataset does not ship a key_english map). Matches the BBCCCVVV id convention.
_BOOK_NUM2NAME: dict[int, str] = {
    1: "Genesis", 2: "Exodus", 3: "Leviticus", 4: "Numbers", 5: "Deuteronomy",
    6: "Joshua", 7: "Judges", 8: "Ruth", 9: "1 Samuel", 10: "2 Samuel",
    11: "1 Kings", 12: "2 Kings", 13: "1 Chronicles", 14: "2 Chronicles",
    15: "Ezra", 16: "Nehemiah", 17: "Esther", 18: "Job", 19: "Psalms",
    20: "Proverbs", 21: "Ecclesiastes", 22: "Song of Solomon", 23: "Isaiah",
    24: "Jeremiah", 25: "Lamentations", 26: "Ezekiel", 27: "Daniel", 28: "Hosea",
    29: "Joel", 30: "Amos", 31: "Obadiah", 32: "Jonah", 33: "Micah", 34: "Nahum",
    35: "Habakkuk", 36: "Zephaniah", 37: "Haggai", 38: "Zechariah", 39: "Malachi",
    40: "Matthew", 41: "Mark", 42: "Luke", 43: "John", 44: "Acts", 45: "Romans",
    46: "1 Corinthians", 47: "2 Corinthians", 48: "Galatians", 49: "Ephesians",
    50: "Philippians", 51: "Colossians", 52: "1 Thessalonians",
    53: "2 Thessalonians", 54: "1 Timothy", 55: "2 Timothy", 56: "Titus",
    57: "Philemon", 58: "Hebrews", 59: "James", 60: "1 Peter", 61: "2 Peter",
    62: "1 John", 63: "2 John", 64: "3 John", 65: "Jude", 66: "Revelation",
}


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _point_id(ref: str, translation: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{translation}:{ref}"))


def _find_file(root: Path, filename: str) -> Path | None:
    """Case-insensitive recursive lookup for a file inside a downloaded dataset."""
    target = filename.lower()
    for p in root.rglob("*"):
        if p.is_file() and p.name.lower() == target:
            return p
    return None


def _pick_col(columns: list[str], configured: str | None, alternatives: list[str]) -> str | None:
    lower = {c.lower(): c for c in columns}
    if configured and configured.lower() in lower:
        return lower[configured.lower()]
    for alt in alternatives:
        if alt.lower() in lower:
            return lower[alt.lower()]
    return None


def _resolve_book(value: object, num2name: dict[int, str]) -> str | None:
    """A book field may be a name string or a numeric id - normalise to a name."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return num2name.get(int(text))
    return text


def _record(translation: str, book: str, chapter: int, verse: int, text: str, canon_tags: list[str]) -> dict:
    ref = f"{book} {chapter}:{verse}"
    return {
        "translation": translation,
        "book": book,
        "chapter": chapter,
        "verse": verse,
        "canon_tags": canon_tags,
        "text": text,
        "ref": ref,
    }


def _load_local_json(path: Path, translation: str, canon_tags: list[str]) -> list[dict]:
    verses = json.loads(path.read_text())
    out: list[dict] = []
    for v in verses:
        out.append(
            _record(
                translation,
                str(v["book"]),
                int(v["chapter"]),
                int(v["verse"]),
                str(v["text"]),
                canon_tags,
            )
        )
    return out


def _load_key_english(path: Path) -> dict[int, str]:
    import pandas as pd

    df = pd.read_csv(path)
    cols = list(df.columns)
    num_col = _pick_col(cols, None, ["b", "book_number", "number", "id"])
    name_col = _pick_col(cols, None, ["n", "name", "book", "book_name"])
    if not num_col or not name_col:
        return {}
    return {int(row[num_col]): str(row[name_col]).strip() for _, row in df.iterrows()}


def _load_kaggle_source(
    src: dict, base: Path, translations_filter: set[str], cache_dir: str
) -> list[dict]:
    """Download a Kaggle dataset and load the configured translation CSVs."""
    import kagglehub
    import pandas as pd

    if cache_dir:
        os.environ.setdefault("KAGGLEHUB_CACHE", cache_dir)

    dataset = os.environ.get(src.get("dataset_env", "KAGGLE_DATASET"), src.get("dataset", "oswinrh/bible"))
    log.info("downloading Kaggle dataset '%s' via kagglehub ...", dataset)
    root = Path(kagglehub.dataset_download(dataset))
    log.info("dataset available at %s", root)

    num2name = dict(_BOOK_NUM2NAME)
    key_name = src.get("key_english", "key_english.csv")
    key_path = _find_file(root, key_name)
    if key_path:
        mapping = _load_key_english(key_path)
        if mapping:
            num2name.update(mapping)
            log.info("loaded %d book names from %s", len(mapping), key_path.name)

    cfg_cols = src.get("columns", {})
    records: list[dict] = []
    for tr in src.get("translations", []):
        name = tr["name"]
        if translations_filter and name.upper() not in translations_filter:
            continue
        csv_path = _find_file(root, tr["file"])
        if not csv_path:
            log.warning("translation file '%s' (%s) not found in dataset; skipping", tr["file"], name)
            continue

        df = pd.read_csv(csv_path)
        cols = list(df.columns)
        book_col = _pick_col(cols, cfg_cols.get("book"), ["b", "book", "book_number", "book_name"])
        chap_col = _pick_col(cols, cfg_cols.get("chapter"), ["c", "chapter"])
        verse_col = _pick_col(cols, cfg_cols.get("verse"), ["v", "verse"])
        text_col = _pick_col(cols, cfg_cols.get("text"), ["t", "text", "verse_text"])
        if not all([book_col, chap_col, verse_col, text_col]):
            log.warning("could not map columns for %s (have %s); skipping", name, cols)
            continue

        before = len(records)
        for row in df.itertuples(index=False):
            row_d = dict(zip(df.columns, row))
            book = _resolve_book(row_d[book_col], num2name)
            text = row_d[text_col]
            if not book or text is None or str(text).strip() == "":
                continue
            records.append(
                _record(
                    name,
                    book,
                    int(row_d[chap_col]),
                    int(row_d[verse_col]),
                    str(text).strip(),
                    tr["canon_tags"],
                )
            )
        log.info("loaded %d verses for %s from %s", len(records) - before, name, csv_path.name)
    return records


def _load_fallback_sample(base: Path) -> list[dict]:
    """Ingest the bundled sample corpus when the real dataset is unavailable."""
    sample_manifest = base / "sample" / "sources.json"
    log.warning("falling back to bundled sample corpus at %s", sample_manifest)
    manifest = json.loads(sample_manifest.read_text())
    records: list[dict] = []
    for tr in manifest["translations"]:
        records += _load_local_json(
            sample_manifest.parent / tr["file"], tr["name"], tr["canon_tags"]
        )
    return records


def load_verses(manifest_path: Path, translations_filter: set[str], cache_dir: str) -> list[dict]:
    """Resolve every source in the manifest into flat verse records."""
    manifest = json.loads(manifest_path.read_text())
    base = manifest_path.parent

    # Legacy/simple manifest (Phase 2 sample) with a flat translations list.
    if "sources" not in manifest and "translations" in manifest:
        records: list[dict] = []
        for tr in manifest["translations"]:
            records += _load_local_json(base / tr["file"], tr["name"], tr["canon_tags"])
        return records

    records = []
    kaggle_attempted = False
    kaggle_records = 0
    for src in manifest.get("sources", []):
        stype = src.get("type")
        if stype == "kaggle":
            kaggle_attempted = True
            try:
                kr = _load_kaggle_source(src, base, translations_filter, cache_dir)
                kaggle_records += len(kr)
                records += kr
            except Exception as exc:  # noqa: BLE001 - any failure -> graceful fallback
                log.warning("Kaggle source failed (%s); will use bundled sample", exc)
        elif stype == "local_json":
            records += _load_local_json(base / src["file"], src["name"], src["canon_tags"])
        else:
            log.warning("unknown source type '%s'; skipping", stype)

    if kaggle_attempted and kaggle_records == 0:
        records += _load_fallback_sample(base)

    return records


def ensure_collection(client: QdrantClient, name: str, dim: int, reingest: bool) -> bool:
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
    # Indexed payload fields we filter on at query / verification time.
    client.create_payload_index(name, "canon_tags", models.PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "translation", models.PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "book", models.PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "chapter", models.PayloadSchemaType.INTEGER)
    client.create_payload_index(name, "verse", models.PayloadSchemaType.INTEGER)
    return True


def main() -> int:
    qdrant_url = _env("QDRANT_URL", "http://qdrant:6333")
    collection = _env("QDRANT_COLLECTION", "bible_verses")
    model_name = _env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    sources = Path(_env("BIBLE_SOURCES", "/app/data/sources.json"))
    reingest = _env("REINGEST", "false").lower() == "true"
    batch = int(_env("EMBED_BATCH", "64"))
    cache_dir = _env("KAGGLEHUB_CACHE", "")
    translations_filter = {
        t.strip().upper() for t in _env("INGEST_TRANSLATIONS", "KJV").split(",") if t.strip()
    }

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

    records = load_verses(sources, translations_filter, cache_dir)
    if not records:
        log.error("no verses resolved from any source; aborting")
        return 1
    log.info("ingesting %d verses (translations filter: %s)", len(records), sorted(translations_filter) or "all")

    texts = [r["text"] for r in records]
    vectors = model.encode(
        texts, batch_size=batch, normalize_embeddings=True, show_progress_bar=False
    )

    points = [
        models.PointStruct(id=_point_id(r["ref"], r["translation"]), vector=vec.tolist(), payload=r)
        for r, vec in zip(records, vectors)
    ]
    # Upsert in chunks to keep request sizes bounded for large corpora.
    chunk = 1000
    for i in range(0, len(points), chunk):
        client.upsert(collection_name=collection, points=points[i : i + chunk], wait=True)
        log.info("upserted %d/%d", min(i + chunk, len(points)), len(points))

    total = client.count(collection, exact=True).count
    log.info("done; collection '%s' now has %d points", collection, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
