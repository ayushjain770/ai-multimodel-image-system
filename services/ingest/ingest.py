"""One-shot Bible corpus ingestion into Qdrant.

Reads a config-driven source manifest, embeds each verse with a
sentence-transformers model, and upserts into a Qdrant collection.

Format-agnostic design
----------------------
Each manifest source separates three concerns so a new data shape is a small
plugin rather than a rewrite:

* ``transport`` - where the files live: ``kaggle`` (kagglehub download) or
  ``local`` (bundled path). Adding ``url``/etc. is one function in TRANSPORTS.
* ``format``    - how a file is parsed into rows: ``csv`` or ``json``. Adding
  ``sqlite``/``xml`` is one function in FORMAT_READERS.
* ``fields``    - maps the canonical ``book/chapter/verse/text`` onto whatever
  columns/keys the source uses (with sensible fallbacks).

Book names are resolved independently of format: a name column is used as-is,
otherwise a numeric book id (BBCCCVVV convention) is mapped via the dataset's
key file (when present) or a bundled 66-book fallback.

Behaviour
---------
* ``INGEST_TRANSLATIONS`` (comma-separated) limits which translations from a
  filterable source are embedded - CPU ingestion scales with this.
* Idempotent: an already-populated collection is reused unless ``REINGEST=true``.
* Graceful fallback: if a remote (kaggle) source fails, the bundled sample is
  ingested so the stack still comes up. Nothing is hardcoded.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s [ingest] %(message)s",
)
log = logging.getLogger("ingest")

_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")  # URL namespace

# Standard 66-book number -> canonical name fallback (used when a dataset does
# not ship a key file). Matches the BBCCCVVV id convention.
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

# Default canonical-field aliases tolerated across datasets.
_FIELD_ALTS: dict[str, list[str]] = {
    "book": ["b", "book", "book_number", "book_name"],
    "chapter": ["c", "chapter"],
    "verse": ["v", "verse"],
    "text": ["t", "text", "verse_text"],
}


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _point_id(ref: str, translation: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{translation}:{ref}"))


def _find_file(root: Path, filename: str) -> Path | None:
    """Case-insensitive recursive lookup for a file inside a directory tree."""
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
    return {
        "translation": translation,
        "book": book,
        "chapter": chapter,
        "verse": verse,
        "canon_tags": canon_tags,
        "text": text,
        "ref": f"{book} {chapter}:{verse}",
    }


# ---------------------------------------------------------------------------
# Transports: resolve a manifest source to a root directory + file locator.
# ---------------------------------------------------------------------------
def _transport_kaggle(src: dict, base: Path, cache_dir: str) -> Path:
    import kagglehub

    if cache_dir:
        os.environ.setdefault("KAGGLEHUB_CACHE", cache_dir)
    dataset = os.environ.get(
        src.get("dataset_env", "KAGGLE_DATASET"), src.get("dataset", "oswinrh/bible")
    )
    log.info("downloading Kaggle dataset '%s' via kagglehub ...", dataset)
    root = Path(kagglehub.dataset_download(dataset))
    log.info("dataset available at %s", root)
    return root


def _transport_local(src: dict, base: Path, cache_dir: str) -> Path:
    return base


TRANSPORTS: dict[str, Callable[[dict, Path, str], Path]] = {
    "kaggle": _transport_kaggle,
    "local": _transport_local,
}

# Remote transports get the translation filter + graceful fallback applied.
_REMOTE_TRANSPORTS = {"kaggle"}


def _locate(root: Path, filename: str, transport: str) -> Path | None:
    if transport in _REMOTE_TRANSPORTS:
        return _find_file(root, filename)
    p = root / filename
    return p if p.exists() else None


# ---------------------------------------------------------------------------
# Format readers: parse a file into a list of row dicts.
# ---------------------------------------------------------------------------
def _read_csv(path: Path) -> list[dict]:
    import pandas as pd

    df = pd.read_csv(path)
    cols = list(df.columns)
    return [dict(zip(cols, row)) for row in df.itertuples(index=False, name=None)]


def _read_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    return list(data)


FORMAT_READERS: dict[str, Callable[[Path], list[dict]]] = {
    "csv": _read_csv,
    "json": _read_json,
}


def _load_key_map(rows: list[dict]) -> dict[int, str]:
    """Build a book-number -> name map from a key file's rows (format-agnostic)."""
    if not rows:
        return {}
    keys = list(rows[0].keys())
    num_col = _pick_col(keys, None, ["b", "book_number", "number", "id"])
    name_col = _pick_col(keys, None, ["n", "name", "book", "book_name"])
    if not num_col or not name_col:
        return {}
    return {int(r[num_col]): str(r[name_col]).strip() for r in rows}


def _to_records(
    rows: list[dict],
    fields: dict,
    canon_tags: list[str],
    translation: str,
    num2name: dict[int, str],
) -> list[dict]:
    """Map arbitrary rows onto canonical verse records using the field map."""
    if not rows:
        return []
    keys = list(rows[0].keys())
    book_col = _pick_col(keys, fields.get("book"), _FIELD_ALTS["book"])
    chap_col = _pick_col(keys, fields.get("chapter"), _FIELD_ALTS["chapter"])
    verse_col = _pick_col(keys, fields.get("verse"), _FIELD_ALTS["verse"])
    text_col = _pick_col(keys, fields.get("text"), _FIELD_ALTS["text"])
    if not all([book_col, chap_col, verse_col, text_col]):
        log.warning("could not map fields for %s (have %s); skipping", translation, keys)
        return []

    out: list[dict] = []
    for row in rows:
        book = _resolve_book(row.get(book_col), num2name)
        text = row.get(text_col)
        if not book or text is None or str(text).strip() == "":
            continue
        out.append(
            _record(
                translation,
                book,
                int(row[chap_col]),
                int(row[verse_col]),
                str(text).strip(),
                canon_tags,
            )
        )
    return out


def _load_source(
    src: dict, base: Path, translations_filter: set[str], cache_dir: str
) -> list[dict]:
    transport = src.get("transport")
    fmt = src.get("format")
    if transport not in TRANSPORTS:
        log.warning("unknown transport '%s' for source '%s'; skipping", transport, src.get("name"))
        return []
    if fmt not in FORMAT_READERS:
        log.warning("unknown format '%s' for source '%s'; skipping", fmt, src.get("name"))
        return []

    root = TRANSPORTS[transport](src, base, cache_dir)
    reader = FORMAT_READERS[fmt]

    # Optional book-name key file (e.g. key_english.csv); always parsed as CSV.
    num2name = dict(_BOOK_NUM2NAME)
    key_file = src.get("options", {}).get("key_file")
    if key_file:
        key_path = _locate(root, key_file, transport)
        if key_path:
            mapping = _load_key_map(_read_csv(key_path))
            if mapping:
                num2name.update(mapping)
                log.info("loaded %d book names from %s", len(mapping), key_path.name)

    fields = src.get("fields", {})
    records: list[dict] = []
    for tr in src.get("translations", []):
        name = tr["name"]
        if translations_filter and name.upper() not in translations_filter:
            continue
        path = _locate(root, tr["file"], transport)
        if not path:
            log.warning("file '%s' (%s) not found for source '%s'; skipping", tr["file"], name, src.get("name"))
            continue
        recs = _to_records(reader(path), fields, tr["canon_tags"], name, num2name)
        records += recs
        log.info("loaded %d verses for %s from %s", len(recs), name, path.name)
    return records


def _load_fallback_sample(base: Path) -> list[dict]:
    """Ingest the bundled sample corpus when a remote source is unavailable."""
    sample_manifest = base / "sample" / "sources.json"
    log.warning("falling back to bundled sample corpus at %s", sample_manifest)
    manifest = json.loads(sample_manifest.read_text())
    default_fields = {"book": "book", "chapter": "chapter", "verse": "verse", "text": "text"}
    records: list[dict] = []
    for tr in manifest["translations"]:
        rows = _read_json(sample_manifest.parent / tr["file"])
        records += _to_records(rows, default_fields, tr["canon_tags"], tr["name"], _BOOK_NUM2NAME)
    return records


def load_verses(manifest_path: Path, translations_filter: set[str], cache_dir: str) -> list[dict]:
    """Resolve every source in the manifest into flat verse records."""
    manifest = json.loads(manifest_path.read_text())
    base = manifest_path.parent
    default_fields = {"book": "book", "chapter": "chapter", "verse": "verse", "text": "text"}

    # Legacy/simple manifest (a flat list of JSON translations).
    if "sources" not in manifest and "translations" in manifest:
        records: list[dict] = []
        for tr in manifest["translations"]:
            rows = _read_json(base / tr["file"])
            records += _to_records(rows, default_fields, tr["canon_tags"], tr["name"], _BOOK_NUM2NAME)
        return records

    records = []
    remote_attempted = False
    remote_records = 0
    for src in manifest.get("sources", []):
        is_remote = src.get("transport") in _REMOTE_TRANSPORTS
        if is_remote:
            remote_attempted = True
        # The filter only applies to filterable sources (default: remote ones),
        # so small canon samples (e.g. deuterocanon) are always included.
        apply_filter = src.get("filter_translations", is_remote)
        active_filter = translations_filter if apply_filter else set()
        try:
            recs = _load_source(src, base, active_filter, cache_dir)
            if is_remote:
                remote_records += len(recs)
            records += recs
        except Exception as exc:  # noqa: BLE001 - any failure -> graceful fallback
            log.warning("source '%s' failed (%s)", src.get("name"), exc)

    if remote_attempted and remote_records == 0:
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
