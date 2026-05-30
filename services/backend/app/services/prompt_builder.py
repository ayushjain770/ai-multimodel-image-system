"""System-prompt construction: tone, denomination framing, and memory summary.

Centralizing prompt assembly keeps tone consistent across turns and makes the
denomination handling a framing concern (how doctrine is presented), distinct
from the retrieval-side canon filter in `retriever.py`.
"""

from app.core.config import settings
from app.schemas import Denomination
from app.services.planner import Plan

_TONE_RULES = (
    "Tone and conduct:\n"
    "- Speak warmly and pastorally; stay humble and non-dogmatic.\n"
    "- Keep answers concise and clear.\n"
    "- Ground claims in the Scripture context provided and cite references "
    "inline (e.g. John 3:16).\n"
    "- If the context lacks a relevant passage, say so rather than inventing one.\n"
    "- Never fabricate, alter, or rewrite the words of Scripture.\n"
    "- Acknowledge uncertainty honestly instead of overstating."
)

_NORMAL_ROUTE_RULES = (
    "Route: normal (direct answer, no scripture retrieval was used).\n"
    "- Answer as a pastoral Christianity-focused assistant.\n"
    "- If the question is clearly unrelated to Christianity, Scripture, or faith, "
    "politely redirect: you are focused on Christianity, Scripture, and faith.\n"
    "- Do not invent Bible verses or cite Scripture unless the user asks."
)

_SCRIPTURE_ROUTE_RULES = (
    "Route: scripture (grounded answer using retrieved passages below).\n"
    "- Ground every claim in the Scripture context provided.\n"
    "- Cite references inline (e.g. John 3:16).\n"
    "- Never fabricate or alter Scripture."
)

_IMAGE_ROUTE_RULES = (
    "Route: image (user requested visual art; an image is being generated).\n"
    "- Briefly acknowledge the request in one or two sentences.\n"
    "- Describe what kind of reverent Christian artwork was created.\n"
    "- Do not claim the image is already visible until the user sees it."
)

_DENOMINATION_FRAMING: dict[Denomination, str] = {
    Denomination.NEUTRAL: (
        "Denominational framing: The user has not stated a tradition. On doctrines "
        "where Christians differ, present the main views (Catholic, Protestant, "
        "Orthodox) fairly and let the user decide; do not declare one tradition the "
        "only correct one."
    ),
    Denomination.CATHOLIC: (
        "Denominational framing: The user identifies with the Catholic tradition. "
        "Frame answers within it (including the deuterocanonical books and Church "
        "teaching) while remaining respectful of other traditions."
    ),
    Denomination.PROTESTANT: (
        "Denominational framing: The user identifies with the Protestant tradition. "
        "Frame answers within it (the 66-book canon, emphasis on Scripture) while "
        "remaining respectful of other traditions."
    ),
    Denomination.ORTHODOX: (
        "Denominational framing: The user identifies with the Orthodox tradition. "
        "Frame answers within it (the broader canon and patristic teaching) while "
        "remaining respectful of other traditions."
    ),
}


def build_system_prompt(
    denomination: Denomination = Denomination.NEUTRAL,
    summary: str | None = None,
) -> str:
    """Legacy helper; prefer build_synthesizer_prompt for chat."""
    return build_synthesizer_prompt(
        Plan(route="scripture", tool="scripture_search", reason="", source="rules", needs_rag=True),
        denomination,
        summary,
    )


def build_synthesizer_prompt(
    plan: Plan,
    denomination: Denomination = Denomination.NEUTRAL,
    summary: str | None = None,
) -> str:
    """Build the synthesizer system prompt based on the planner route."""
    route_rules = {
        "normal": _NORMAL_ROUTE_RULES,
        "scripture": _SCRIPTURE_ROUTE_RULES,
        "image": _IMAGE_ROUTE_RULES,
    }
    parts = [
        settings.llm_persona,
        _TONE_RULES,
        route_rules.get(plan.route, _NORMAL_ROUTE_RULES),
        _DENOMINATION_FRAMING.get(
            denomination, _DENOMINATION_FRAMING[Denomination.NEUTRAL]
        ),
    ]
    if summary:
        parts.append("Conversation so far (summary of earlier turns):\n" + summary)
    if plan.reason:
        parts.append(f"Planner note: {plan.reason}")
    return "\n\n".join(parts)
