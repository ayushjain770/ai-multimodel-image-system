"""Planner: decide route and tool before execution (Planner → Execute → Synthesizer).

When LLM_BACKEND=vllm the planner is an LLM call returning JSON.
When LLM_BACKEND=mock the planner uses deterministic regex rules (no extra call).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from app.core.config import LLMBackend, settings
from app.core.logging import get_logger
from app.clients.llm_client import PLANNER_MARKER

logger = get_logger(__name__)

RouteKind = Literal["normal", "scripture", "image"]

_IMAGE_RE = re.compile(
    r"\b(image|picture|photo|paint(?:ing)?|draw|drawing|illustrat\w*|render|"
    r"depict|portrait|art(?:work)?|wallpaper|generate\s+(?:an?\s+)?(?:image|picture)|"
    r"want to see|show me|let me see|see a|see the|visuali\w*)\b",
    re.IGNORECASE,
)
_SCRIPTURE_RE = re.compile(
    r"\b(jesus|christ\w*|bible|biblical|scriptur\w*|gospel|verse|psalm\w*|"
    r"god|lord|holy\s+spirit|church|disciple\w*|apostle\w*|prophet\w*|"
    r"salvation|prayer|pray|sin|grace|faith|cross|crucifix\w*|resurrection|"
    r"moses|paul|david|abraham|heaven|parable|commandment\w*)\b",
    re.IGNORECASE,
)

_ROUTE_TOOL: dict[RouteKind, str | None] = {
    "image": "generate_image",
    "scripture": "scripture_search",
    "normal": None,
}


@dataclass(frozen=True)
class Plan:
    route: RouteKind
    tool: str | None
    reason: str
    source: Literal["llm", "rules", "disabled"]
    needs_rag: bool


def _make_plan(route: RouteKind, reason: str, source: Literal["llm", "rules", "disabled"]) -> Plan:
    return Plan(
        route=route,
        tool=_ROUTE_TOOL[route],
        reason=reason,
        source=source,
        needs_rag=(route == "scripture"),
    )


def classify_rules(message: str) -> Plan:
    """Deterministic route from regex rules."""
    if _IMAGE_RE.search(message):
        return _make_plan("image", "User asked to create or generate visual art.", "rules")
    if _SCRIPTURE_RE.search(message):
        return _make_plan(
            "scripture",
            "Message mentions Christianity, Scripture, or faith topics.",
            "rules",
        )
    return _make_plan(
        "normal",
        "General message with no scripture or image cues; answer directly without RAG.",
        "rules",
    )


def _parse_planner_json(raw: str) -> Plan | None:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    route = str(data.get("route", "")).lower()
    if route not in ("normal", "scripture", "image"):
        return None
    reason = str(data.get("reason", "LLM planner classification."))
    return _make_plan(route, reason, "llm")  # type: ignore[arg-type]


class Planner:
    def __init__(self, llm_client: object | None = None) -> None:
        self._llm = llm_client

    async def plan(self, message: str) -> Plan:
        if not settings.orchestrator_enabled:
            return _make_plan(
                "scripture",
                "Orchestrator disabled; legacy scripture grounding path.",
                "disabled",
            )

        if settings.llm_backend is LLMBackend.VLLM and self._llm is not None:
            llm_plan = await self._plan_llm(message)
            if llm_plan is not None:
                return llm_plan
            logger.warning("LLM planner parse failed; falling back to rules")

        return classify_rules(message)

    async def _plan_llm(self, message: str) -> Plan | None:
        system = f"{PLANNER_MARKER}\n{settings.planner_instruction}"
        try:
            raw = await self._llm.chat(message, [], None, system_prompt=system)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("LLM planner call failed: %s", exc)
            return None
        return _parse_planner_json(raw)


def build_planner(llm_client: object | None = None) -> Planner:
    if settings.orchestrator_llm_intent:
        logger.warning(
            "ORCHESTRATOR_LLM_INTENT is deprecated; vLLM planner runs automatically "
            "when LLM_BACKEND=vllm"
        )
    logger.info(
        "Planner ready (enabled=%s, llm_backend=%s)",
        settings.orchestrator_enabled,
        settings.llm_backend.value,
    )
    return Planner(llm_client=llm_client)
