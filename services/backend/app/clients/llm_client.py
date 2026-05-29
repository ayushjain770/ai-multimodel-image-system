"""Swappable LLM client.

`LLMBackend` selects the implementation at startup:
  - MockLLMClient: deterministic replies, no network/GPU (Mac dev).
  - VLLMClient: real Qwen2.5-VL via the vLLM OpenAI-compatible API (EC2/prod).

The interface carries grounding (citations), tone (system_prompt) and memory
(summarize) so callers stay backend-agnostic.
"""

from abc import ABC, abstractmethod

import httpx

from app.core.config import LLMBackend, settings
from app.core.logging import get_logger
from app.schemas import ChatMessage, Citation

logger = get_logger(__name__)

# Fallback used only when a caller does not supply a built system prompt.
_SYSTEM_PROMPT = (
    "You are a Christianity-focused assistant. Be pastoral, humble, and "
    "non-dogmatic. Ground your answers in the Scripture passages provided in "
    "the context and cite them by reference (e.g. John 3:16). If the context "
    "does not contain a relevant passage, say so rather than inventing one."
)

_SUMMARY_SYSTEM_PROMPT = (
    "You compress chat history into a concise third-person summary that captures "
    "the user's questions, any stated preferences (e.g. denomination), and key "
    "points discussed. Keep it under 150 words. Do not add new information."
)


def _format_context(citations: list[Citation]) -> str:
    if not citations:
        return ""
    lines = [f"- {c.ref} ({c.translation}): {c.text}" for c in citations]
    return "Scripture context:\n" + "\n".join(lines)


def _denomination_tag(system_prompt: str | None) -> str:
    if system_prompt:
        for tradition in ("Catholic", "Protestant", "Orthodox"):
            if f"{tradition} tradition" in system_prompt:
                return tradition.lower()
    return "neutral"


class LLMClient(ABC):
    @abstractmethod
    async def chat(
        self,
        message: str,
        history: list[ChatMessage],
        citations: list[Citation] | None = None,
        system_prompt: str | None = None,
    ) -> str: ...

    @abstractmethod
    async def summarize(
        self, messages: list[ChatMessage], prior_summary: str = ""
    ) -> str:
        """Fold messages (plus any prior summary) into an updated summary."""

    @abstractmethod
    async def health(self) -> tuple[bool, str]:
        """Return (ok, detail)."""

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        return None


class MockLLMClient(LLMClient):
    """Deterministic stand-in so the stack runs without a GPU."""

    async def chat(
        self,
        message: str,
        history: list[ChatMessage],
        citations: list[Citation] | None = None,
        system_prompt: str | None = None,
    ) -> str:
        turn = len([m for m in history if m.role == "user"]) + 1
        cites = citations or []
        if cites:
            refs = "; ".join(f"{c.ref} ({c.translation})" for c in cites)
            grounding = f" Grounded in: {refs}."
        else:
            grounding = " No matching scripture was retrieved."
        has_summary = bool(system_prompt and "Conversation so far" in system_prompt)
        if has_summary or turn > 1:
            memory = " I recall our earlier conversation."
        else:
            memory = ""
        framing = f" [{_denomination_tag(system_prompt)} framing]"
        return (
            f"[mock-llm] Peace be with you. You asked: \"{message}\" "
            f"(turn {turn}).{memory}{framing}{grounding}"
        )

    async def summarize(
        self, messages: list[ChatMessage], prior_summary: str = ""
    ) -> str:
        topics = [m.content.strip()[:60] for m in messages if m.role == "user"]
        base = f"{prior_summary} " if prior_summary else ""
        if not topics:
            return prior_summary
        return (base + "Earlier the user asked about: " + "; ".join(topics)).strip()

    async def health(self) -> tuple[bool, str]:
        return True, "mock backend always ready"


class VLLMClient(LLMClient):
    """Calls the vLLM OpenAI-compatible chat completions endpoint."""

    def __init__(self) -> None:
        self._base_url = settings.vllm_base_url.rstrip("/")
        self._model = settings.vllm_model
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout)

    async def chat(
        self,
        message: str,
        history: list[ChatMessage],
        citations: list[Citation] | None = None,
        system_prompt: str | None = None,
    ) -> str:
        messages = [{"role": "system", "content": system_prompt or _SYSTEM_PROMPT}]
        messages += [{"role": m.role, "content": m.content} for m in history]
        context = _format_context(citations or [])
        user_content = f"{context}\n\nQuestion: {message}" if context else message
        messages.append({"role": "user", "content": user_content})

        resp = await self._client.post(
            f"{self._base_url}/chat/completions",
            json={
                "model": self._model,
                "messages": messages,
                "temperature": settings.llm_temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def summarize(
        self, messages: list[ChatMessage], prior_summary: str = ""
    ) -> str:
        convo = "\n".join(f"{m.role}: {m.content}" for m in messages)
        prefix = f"Existing summary:\n{prior_summary}\n\n" if prior_summary else ""
        user_content = (
            f"{prefix}New turns to fold into the summary:\n{convo}\n\n"
            "Return the updated summary only."
        )
        resp = await self._client.post(
            f"{self._base_url}/chat/completions",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.2,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def health(self) -> tuple[bool, str]:
        # vLLM exposes /health at the server root (one level above /v1).
        root = self._base_url.rsplit("/v1", 1)[0]
        try:
            resp = await self._client.get(f"{root}/health", timeout=5.0)
            ok = resp.status_code == 200
            return ok, f"vllm /health -> {resp.status_code}"
        except httpx.HTTPError as exc:
            return False, f"vllm unreachable: {exc}"

    async def aclose(self) -> None:
        await self._client.aclose()


def build_llm_client() -> LLMClient:
    if settings.llm_backend is LLMBackend.VLLM:
        logger.info("Using VLLMClient (%s)", settings.vllm_model)
        return VLLMClient()
    logger.info("Using MockLLMClient")
    return MockLLMClient()
