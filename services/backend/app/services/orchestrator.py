"""Intent orchestrator: decide what a turn needs before doing any work.

Rule-first classification keeps the hot path deterministic and GPU-free:
  - image     -> compose an art prompt and render (no RAG)
  - scripture -> retrieve grounded verses + verify (RAG)
  - normal    -> answer directly (no RAG)

When `orchestrator_llm_intent` is on and the rules are ambiguous, the LLM gives a
tiebreak verdict; the mock LLM just keeps the rule result so dev is unaffected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

IntentKind = Literal["normal", "scripture", "image"]

_IMAGE_RE = re.compile(
    r"\b(image|picture|photo|paint(?:ing)?|draw|drawing|illustrat\w*|render|"
    r"depict|portrait|art(?:work)?|wallpaper|generate\s+(?:an?\s+)?(?:image|picture))\b",
    re.IGNORECASE,
)
_SCRIPTURE_RE = re.compile(
    r"\b(jesus|christ\w*|bible|biblical|scriptur\w*|gospel|verse|psalm\w*|"
    r"god|lord|holy\s+spirit|church|disciple\w*|apostle\w*|prophet\w*|"
    r"salvation|prayer|pray|sin|grace|faith|cross|crucifix\w*|resurrection|"
    r"moses|paul|david|abraham|heaven|parable|commandment\w*)\b",
    re.IGNORECASE,
)

# Strong image cues mean image wins even when scripture words are present
# (e.g. "draw Jesus on the cross").
_INTENT_TOOL = {
    "image": "generate_image",
    "scripture": "scripture_search",
    "normal": None,
}


@dataclass(frozen=True)
class Intent:
    kind: IntentKind
    needs_rag: bool
    tool: str | None
    source: str  # "rules" | "llm" | "disabled"


def _make(kind: IntentKind, source: str) -> Intent:
    return Intent(
        kind=kind,
        needs_rag=(kind == "scripture"),
        tool=_INTENT_TOOL[kind],
        source=source,
    )


def _classify_rules(message: str) -> tuple[IntentKind, bool]:
    """Return (kind, ambiguous). Ambiguous when no rule matched at all."""
    has_image = _IMAGE_RE.search(message) is not None
    has_scripture = _SCRIPTURE_RE.search(message) is not None
    if has_image:
        return "image", False
    if has_scripture:
        return "scripture", False
    return "normal", True


class Orchestrator:
    def __init__(self, llm_client: object | None = None) -> None:
        self._llm = llm_client

    async def classify(self, message: str) -> Intent:
        if not settings.orchestrator_enabled:
            # Preserve the legacy behaviour: always allow RAG, no image gating.
            return Intent(kind="scripture", needs_rag=True, tool=None, source="disabled")

        kind, ambiguous = _classify_rules(message)
        if not ambiguous:
            return _make(kind, "rules")

        if settings.orchestrator_llm_intent and self._llm is not None:
            llm_kind = await self._classify_llm(message)
            if llm_kind is not None:
                return _make(llm_kind, "llm")

        return _make(kind, "rules")

    async def _classify_llm(self, message: str) -> IntentKind | None:
        instruction = (
            "Classify the user's message into exactly one label: 'normal', "
            "'scripture' (about Christianity, the Bible, faith, or God), or "
            "'image' (asking to create/generate a picture). Reply with only the label."
        )
        try:
            raw = await self._llm.chat(  # type: ignore[attr-defined]
                message, [], None, system_prompt=instruction
            )
        except Exception as exc:
            logger.warning("LLM intent classify failed; keeping rules: %s", exc)
            return None
        text = raw.lower()
        for kind in ("image", "scripture", "normal"):
            if kind in text:
                return kind  # type: ignore[return-value]
        return None


def build_orchestrator(llm_client: object | None = None) -> Orchestrator:
    logger.info(
        "Orchestrator ready (enabled=%s, llm_intent=%s)",
        settings.orchestrator_enabled,
        settings.orchestrator_llm_intent,
    )
    return Orchestrator(llm_client=llm_client)
