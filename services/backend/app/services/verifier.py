"""Scripture verification - the anti-hallucination layer.

Parses scripture references out of free text, normalises book names against the
canonical 66-book metadata, and validates each reference against the canonical
verse store in Qdrant. When the text also quotes a verse, the quote is fuzzy
matched (difflib) to the canonical text to catch misquotes.

Statuses
--------
* ``valid``        - reference exists and (if quoted) the text matches.
* ``unknown_book`` - the book name does not resolve to a canonical book.
* ``nonexistent``  - book is real but the chapter:verse is not in the corpus.
* ``misquote``     - reference exists but the quoted text differs materially.

Also exposes a lightweight rewrite/alter intent detector so the assistant can
refuse to fabricate altered scripture and instead return the authentic verse.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from app.clients.qdrant_client import VectorDBClient
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_BOOKS_PATH = Path(__file__).resolve().parents[1] / "data" / "books.json"

# A book phrase is an optional 1-3 number prefix followed by capitalised words,
# with lowercase "of"/"the" connectors (e.g. "Song of Solomon"), immediately
# before a chapter:verse (with an optional verse range).
_REF_RE = re.compile(
    r"\b((?:[1-3]\s+)?[A-Z][a-zA-Z]+\.?(?:\s+(?:of\s+|the\s+)?[A-Z][a-zA-Z]+\.?){0,3})"
    r"\s+(\d+):(\d+)(?:\s*[-\u2013]\s*(\d+))?"
)

# A double/single/smart quoted span used to associate a quote with a reference.
_QUOTE_RE = re.compile(r"[\"\u201c\u2018']([^\"\u201d\u2019']{8,})[\"\u201d\u2019']")

# Mutation verbs that signal an attempt to alter Scripture.
_REWRITE_RE = re.compile(
    r"\b(rewrite|re-?word|reword|rephrase|change|alter|modify|edit|paraphrase|"
    r"twist|tweak|reinterpret|distort|corrupt|update)\b",
    re.IGNORECASE,
)
# "make/have ... say/read ..." pattern (e.g. "make John 3:16 say ...").
_MAKE_SAY_RE = re.compile(r"\b(make|have)\b[^.?!]*\b(say|read)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedRef:
    raw: str
    book: str | None  # canonical name, or None if unresolved
    chapter: int
    verse: int
    verse_end: int | None
    quote: str | None


@dataclass(frozen=True)
class VerificationResult:
    ref: str
    status: str  # valid | unknown_book | nonexistent | misquote
    book: str | None
    chapter: int | None
    verse: int | None
    canonical_text: str | None
    quoted_text: str | None
    similarity: float | None
    message: str


def _normalise_text(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _normalise_book_key(phrase: str) -> str:
    return re.sub(r"\s+", " ", phrase.replace(".", "").strip().lower())


class BookRegistry:
    """Resolves arbitrary book phrases/abbreviations to canonical book names."""

    def __init__(self, books: list[dict]) -> None:
        self._lookup: dict[str, str] = {}
        self._compact: dict[str, str] = {}
        for b in books:
            name = b["name"]
            keys = [name.lower(), *[a.lower() for a in b.get("abbrevs", [])]]
            for k in keys:
                nk = _normalise_book_key(k)
                self._lookup[nk] = name
                self._compact[nk.replace(" ", "")] = name

    def resolve(self, phrase: str) -> str | None:
        key = _normalise_book_key(phrase)
        if key in self._lookup:
            return self._lookup[key]
        return self._compact.get(key.replace(" ", ""))

    def resolve_phrase(self, phrase: str) -> str | None:
        """Resolve a captured phrase, tolerating leading non-book words.

        The reference regex can greedily capture a sentence-initial capitalised
        word (e.g. "As John 3:16" or "Make John 3:16"). We try the full phrase
        first, then progressively drop leading tokens and return the longest
        suffix that names a real book.
        """
        direct = self.resolve(phrase)
        if direct:
            return direct
        tokens = phrase.split()
        for i in range(1, len(tokens)):
            resolved = self.resolve(" ".join(tokens[i:]))
            if resolved:
                return resolved
        return None

    @classmethod
    def load(cls) -> "BookRegistry":
        data = json.loads(_BOOKS_PATH.read_text())
        return cls(data)


def _find_quote_for(text: str, after_index: int) -> str | None:
    """Nearest quoted span starting shortly after the reference, if any."""
    window = text[after_index : after_index + 400]
    m = _QUOTE_RE.search(window)
    return m.group(1).strip() if m else None


def parse_references(text: str, registry: BookRegistry) -> list[ParsedRef]:
    refs: list[ParsedRef] = []
    for m in _REF_RE.finditer(text):
        raw = m.group(0).strip()
        book = registry.resolve_phrase(m.group(1))
        chapter = int(m.group(2))
        verse = int(m.group(3))
        verse_end = int(m.group(4)) if m.group(4) else None
        quote = _find_quote_for(text, m.end())
        refs.append(ParsedRef(raw, book, chapter, verse, verse_end, quote))
    return refs


class Verifier:
    def __init__(self, vectors: VectorDBClient, registry: BookRegistry) -> None:
        self._vectors = vectors
        self._registry = registry
        self._translation = settings.verify_translation
        self._threshold = settings.verify_fuzzy_threshold

    async def lookup(self, book: str, chapter: int, verse: int) -> dict | None:
        return await self._vectors.get_verse(self._translation, book, chapter, verse)

    async def verify_reference(self, ref: ParsedRef) -> VerificationResult:
        display = ref.raw
        if ref.book is None:
            return VerificationResult(
                ref=display, status="unknown_book", book=None, chapter=ref.chapter,
                verse=ref.verse, canonical_text=None, quoted_text=ref.quote,
                similarity=None,
                message=f"'{display}' does not name a canonical book of the Bible.",
            )

        canonical_ref = f"{ref.book} {ref.chapter}:{ref.verse}"
        verse_payload = await self.lookup(ref.book, ref.chapter, ref.verse)
        if verse_payload is None:
            return VerificationResult(
                ref=canonical_ref, status="nonexistent", book=ref.book,
                chapter=ref.chapter, verse=ref.verse, canonical_text=None,
                quoted_text=ref.quote, similarity=None,
                message=f"{canonical_ref} was not found in the {self._translation} canon.",
            )

        canonical_text = str(verse_payload.get("text", ""))

        # Only fuzzy-check a single quoted verse (ranges aren't reliably comparable).
        if ref.quote and ref.verse_end is None:
            ratio = SequenceMatcher(
                None, _normalise_text(ref.quote), _normalise_text(canonical_text)
            ).ratio()
            if ratio < self._threshold:
                return VerificationResult(
                    ref=canonical_ref, status="misquote", book=ref.book,
                    chapter=ref.chapter, verse=ref.verse,
                    canonical_text=canonical_text, quoted_text=ref.quote,
                    similarity=round(ratio, 3),
                    message=(
                        f"The quoted text for {canonical_ref} does not match the "
                        f"{self._translation} text."
                    ),
                )
            return VerificationResult(
                ref=canonical_ref, status="valid", book=ref.book,
                chapter=ref.chapter, verse=ref.verse, canonical_text=canonical_text,
                quoted_text=ref.quote, similarity=round(ratio, 3),
                message=f"{canonical_ref} verified against the {self._translation} text.",
            )

        return VerificationResult(
            ref=canonical_ref, status="valid", book=ref.book, chapter=ref.chapter,
            verse=ref.verse, canonical_text=canonical_text, quoted_text=ref.quote,
            similarity=None,
            message=f"{canonical_ref} is a valid reference.",
        )

    async def verify_text(self, text: str) -> list[VerificationResult]:
        results: list[VerificationResult] = []
        for ref in parse_references(text, self._registry):
            results.append(await self.verify_reference(ref))
        return results

    def detect_rewrite_intent(self, text: str) -> ParsedRef | None:
        """Return the targeted reference if the user asks to alter scripture.

        Fires only when a mutation verb (or a "make ... say" pattern) is followed,
        within the same sentence, by a resolvable scripture reference - so normal
        requests like "make me a prayer about John 3:16" are not refused.
        """
        for match in list(_REWRITE_RE.finditer(text)) + list(_MAKE_SAY_RE.finditer(text)):
            sentence = re.split(r"[.?!]", text[match.start():])[0]
            for ref in parse_references(sentence, self._registry):
                if ref.book is not None:
                    return ref
        return None

    async def authentic_verse(self, ref: ParsedRef) -> str | None:
        if ref.book is None:
            return None
        payload = await self.lookup(ref.book, ref.chapter, ref.verse)
        return str(payload["text"]) if payload else None


def build_verifier(vectors: VectorDBClient) -> Verifier:
    registry = BookRegistry.load()
    logger.info(
        "Verifier ready (translation=%s, fuzzy_threshold=%.2f)",
        settings.verify_translation,
        settings.verify_fuzzy_threshold,
    )
    return Verifier(vectors, registry)
