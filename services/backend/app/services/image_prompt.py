"""Image prompt construction + safety guard for Christian image generation.

Turns a free-text theme into a fully-formed, style-wrapped SDXL prompt
(`ImageParams`) and refuses disallowed imagery before anything is rendered.
Everything is env-driven (see `Settings.image_*`); nothing is hardcoded.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.clients.llm_client import IMAGE_COMPOSER_MARKER, LLMClient
from app.core.config import settings
from app.core.logging import get_logger
from app.services.moderation import IMAGE_DISRESPECT, IMAGE_UNSAFE, matches_any

logger = get_logger(__name__)

_MAX_SEED = 2**32 - 1


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
class ComposedImage:
    """LLM-composed scene plus fully wrapped SDXL params."""

    params: ImageParams
    scene: str


@dataclass(frozen=True)
class SafetyResult:
    ok: bool
    reason: str | None = None


def check_safety(text: str) -> SafetyResult:
    """Refuse disallowed image requests; allow everything else.

    Delegates to the shared moderation patterns so the rules live in one place.
    """
    if not settings.image_safety_enabled:
        return SafetyResult(ok=True)
    if matches_any(text, IMAGE_UNSAFE):
        return SafetyResult(ok=False, reason="Request asks for explicit, violent, or hateful imagery.")
    if matches_any(text, IMAGE_DISRESPECT):
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


async def compose_image_prompt(
    llm_client: LLMClient,
    request: str,
    denomination: str | None = None,
    negative_override: str | None = None,
) -> ComposedImage:
    """LLM-assisted composer: turn a raw request into a structured SDXL prompt.

    The LLM rewrites the request into a tasteful Christian-art scene, which is
    then wrapped in the configured style template. The mock LLM returns a clean
    deterministic scene (see IMAGE_COMPOSER_MARKER), so dev works without a GPU.
    """
    hint = request.strip()
    if denomination and denomination != "neutral":
        hint = f"{hint} (in the {denomination} tradition)"
    system = f"{IMAGE_COMPOSER_MARKER}\n{settings.image_composer_instruction}"
    scene = (
        await llm_client.chat(
            hint,
            [],
            None,
            system_prompt=system,
            temperature=settings.image_composer_temperature,
        )
    ).strip()
    if not scene:
        scene = hint
    logger.info("[image-composer] request=%r -> scene=%r", request[:60], scene[:80])
    params = build_prompt(scene, negative_override=negative_override)
    return ComposedImage(params=params, scene=scene)
