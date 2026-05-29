"""Image prompt construction + safety guard for Christian image generation.

Turns a free-text theme into a fully-formed, style-wrapped SDXL prompt
(`ImageParams`) and refuses disallowed imagery before anything is rendered.
Everything is env-driven (see `Settings.image_*`); nothing is hardcoded.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_SEED = 2**32 - 1

# Disallowed image intents. Kept lightweight and explainable; a heavier
# moderation model is a later phase.
_UNSAFE_RE = re.compile(
    r"\b(nude|naked|nsfw|porn|sexual|erotic|gore|gory|graphic\s+violence|"
    r"behead|mutilat|slur|nazi|kkk|terror|child\s+abuse|csam)\b",
    re.IGNORECASE,
)
# Requests to mock, insult, or blaspheme are refused (assistant stays reverent).
_DISRESPECT_RE = re.compile(
    r"\b(mock(ing)?|insult|ridicul|blasphem|desecrat|satan(ic)?|demonic)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ImageParams:
    positive: str
    negative: str
    seed: int
    steps: int
    cfg: float
    width: int
    height: int
    sampler: str
    scheduler: str
    checkpoint: str


@dataclass(frozen=True)
class SafetyResult:
    ok: bool
    reason: str | None = None


def check_safety(text: str) -> SafetyResult:
    """Refuse disallowed image requests; allow everything else."""
    if not settings.image_safety_enabled:
        return SafetyResult(ok=True)
    if _UNSAFE_RE.search(text):
        return SafetyResult(ok=False, reason="Request asks for explicit, violent, or hateful imagery.")
    if _DISRESPECT_RE.search(text):
        return SafetyResult(ok=False, reason="Request asks for mocking or blasphemous religious imagery.")
    return SafetyResult(ok=True)


def build_prompt(
    theme: str,
    scripture_context: str | None = None,
    negative_override: str | None = None,
) -> ImageParams:
    """Wrap a theme in the configured style template and assemble SDXL params."""
    theme = theme.strip()
    positive = settings.image_style_template.format(theme=theme)
    if scripture_context:
        positive = f"{positive}, inspired by {scripture_context}"

    negative = negative_override.strip() if negative_override else settings.image_negative_prompt

    params = ImageParams(
        positive=positive,
        negative=negative,
        seed=random.randint(0, _MAX_SEED),
        steps=settings.image_steps,
        cfg=settings.image_cfg,
        width=settings.image_width,
        height=settings.image_height,
        sampler=settings.image_sampler,
        scheduler=settings.image_scheduler,
        checkpoint=settings.image_checkpoint,
    )
    logger.info("[image-prompt] seed=%d positive=%s", params.seed, params.positive[:100])
    return params
