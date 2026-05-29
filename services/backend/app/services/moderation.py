"""Layered safety + moderation.

A deterministic rule layer (category regexes) runs first and works without a GPU,
so adversarial/jailbreak/hateful requests are blocked in dev too. When
`moderation_llm_judge` is enabled, an optional Qwen-as-judge second opinion runs
on borderline input via the injected LLM client.

This module is the single source of truth for unsafe-content patterns; the image
guard in `image_prompt.py` delegates here so the rules stay in one place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# text -> "ALLOW" | "BLOCK:<category>"
Judge = Callable[[str], Awaitable[str]]

_PATTERNS: dict[str, re.Pattern[str]] = {
    "sexual": re.compile(
        r"\b(nude|naked|nsfw|porn|pornographic|erotic|sexual|sexually\s+explicit)\b",
        re.IGNORECASE,
    ),
    "csam": re.compile(
        r"\b(child\s+abuse|child\s+porn\w*|csam|underage\s+sex\w*)\b", re.IGNORECASE
    ),
    "violence": re.compile(
        r"\b(gore|gory|graphic\s+violence|behead\w*|mutilat\w*|massacre|"
        r"how\s+to\s+(?:make|build)\s+(?:a\s+)?(?:bomb|weapon|explosive))\b",
        re.IGNORECASE,
    ),
    "hate": re.compile(
        r"\b(nazi|kkk|genocide|ethnic\s+cleansing|racial\s+slur|slur|terror\w*|"
        r"kill\s+all\s+\w+|hateful)\b",
        re.IGNORECASE,
    ),
    "self_harm": re.compile(
        r"\b(kill\s+myself|suicide|end\s+my\s+life|self[-\s]?harm|cut\s+myself)\b",
        re.IGNORECASE,
    ),
    "jailbreak": re.compile(
        r"(ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+instructions|"
        r"disregard\s+(?:the\s+)?(?:system|previous|above)\s+(?:prompt|instructions)|"
        r"ignore\s+your\s+(?:rules|guidelines|instructions)|"
        r"system\s+prompt|developer\s+mode|\bDAN\b|jailbreak|"
        r"no\s+(?:rules|restrictions|filters?)|"
        r"act\s+as\s+(?:a\s+)?(?:dan|jailbroken)|"
        r"pretend\s+you\s+(?:are\s+not|have\s+no|don't\s+have))",
        re.IGNORECASE,
    ),
    "disrespect": re.compile(
        r"\b(mock(?:ing)?|ridicul\w*|blasphem\w*|desecrat\w*|satanic|demonic)\b",
        re.IGNORECASE,
    ),
}

_REASONS: dict[str, str] = {
    "sexual": "Request involves sexual or explicit content.",
    "csam": "Request involves illegal content involving minors.",
    "violence": "Request involves graphic violence or weapons.",
    "hate": "Request involves hateful or extremist content.",
    "self_harm": "Request involves self-harm.",
    "jailbreak": "Request attempts to bypass the assistant's safety or instructions.",
    "disrespect": "Request asks to mock or blaspheme.",
    "policy": "Request violates the content policy.",
}

# Categories evaluated per stage.
_INPUT_CATEGORIES = ("csam", "hate", "sexual", "violence", "self_harm", "jailbreak")
_OUTPUT_CATEGORIES = ("csam", "hate", "sexual", "violence")

# Categories the image guard reuses (no jailbreak/self_harm for image prompts).
IMAGE_UNSAFE = ("sexual", "csam", "violence", "hate")
IMAGE_DISRESPECT = ("disrespect",)

_SELF_HARM_MESSAGE = (
    "I'm really sorry you're feeling this way, and I'm glad you reached out. I'm "
    "not able to help with that, but you don't have to face it alone - please "
    "consider contacting a local emergency number or a crisis line right now, and "
    "reach out to someone you trust. You matter, and there are people who want to "
    "help you through this."
)


@dataclass(frozen=True)
class ModerationResult:
    allowed: bool
    stage: str  # "input" | "output"
    category: str | None = None
    reason: str | None = None
    message: str | None = None  # user-facing text when blocked


def _scan(text: str, categories: tuple[str, ...]) -> str | None:
    for category in categories:
        if _PATTERNS[category].search(text):
            return category
    return None


def matches_any(text: str, categories: tuple[str, ...]) -> bool:
    """Whether text matches any of the given categories (used by the image guard)."""
    return _scan(text, categories) is not None


class Moderator:
    def __init__(self, judge: Judge | None = None) -> None:
        self._judge = judge

    async def moderate_input(self, text: str) -> ModerationResult:
        if not settings.moderation_enabled:
            return ModerationResult(allowed=True, stage="input")
        category = _scan(text, _INPUT_CATEGORIES)
        if category is not None:
            return self._block("input", category)
        if self._judge is not None:
            verdict = await self._safe_judge(text)
            if verdict.upper().startswith("BLOCK"):
                judged = (
                    verdict.split(":", 1)[1].strip().lower()
                    if ":" in verdict
                    else "policy"
                )
                return self._block("input", judged)
        return ModerationResult(allowed=True, stage="input")

    def moderate_output(self, text: str) -> ModerationResult:
        if not settings.moderation_enabled:
            return ModerationResult(allowed=True, stage="output")
        category = _scan(text, _OUTPUT_CATEGORIES)
        if category is not None:
            return self._block("output", category)
        return ModerationResult(allowed=True, stage="output")

    async def _safe_judge(self, text: str) -> str:
        try:
            return await self._judge(text)  # type: ignore[misc]
        except Exception as exc:  # never let the judge fail the request open-loud
            logger.warning("LLM judge failed; allowing: %s", exc)
            return "ALLOW"

    def _block(self, stage: str, category: str) -> ModerationResult:
        reason = _REASONS.get(category, _REASONS["policy"])
        if category == "self_harm":
            message = _SELF_HARM_MESSAGE
        else:
            message = settings.moderation_refusal
        logger.info("[moderation] blocked stage=%s category=%s", stage, category)
        return ModerationResult(
            allowed=False,
            stage=stage,
            category=category,
            reason=reason,
            message=message,
        )


def build_moderator(llm_client: object | None = None) -> Moderator:
    judge: Judge | None = None
    if settings.moderation_llm_judge and llm_client is not None:
        judge = llm_client.moderate  # type: ignore[attr-defined]
    logger.info("Moderator ready (llm_judge=%s)", judge is not None)
    return Moderator(judge=judge)
