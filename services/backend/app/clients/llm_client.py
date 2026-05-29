"""Swappable LLM client.

`LLMBackend` selects the implementation at startup:
  - MockLLMClient: deterministic replies, no network/GPU (Mac dev).
  - VLLMClient: real Qwen2.5-VL via the vLLM OpenAI-compatible API (EC2/prod).

Later phases add grounding/safety on top of this interface without changing
callers.
"""

from abc import ABC, abstractmethod

import httpx

from app.core.config import LLMBackend, settings
from app.core.logging import get_logger
from app.schemas import ChatMessage, Citation

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a Christianity-focused assistant. Be pastoral, humble, and "
    "non-dogmatic. Ground your answers in the Scripture passages provided in "
    "the context and cite them by reference (e.g. John 3:16). If the context "
    "does not contain a relevant passage, say so rather than inventing one."
)


def _format_context(citations: list[Citation]) -> str:
    if not citations:
        return ""
    lines = [f"- {c.ref} ({c.translation}): {c.text}" for c in citations]
    return "Scripture context:\n" + "\n".join(lines)


class LLMClient(ABC):
    @abstractmethod
    async def chat(
        self,
        message: str,
        history: list[ChatMessage],
        citations: list[Citation] | None = None,
    ) -> str: ...

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
    ) -> str:
        turn = len([m for m in history if m.role == "user"]) + 1
        cites = citations or []
        if cites:
            refs = "; ".join(f"{c.ref} ({c.translation})" for c in cites)
            grounding = f" Grounded in: {refs}."
        else:
            grounding = " No matching scripture was retrieved."
        return (
            f"[mock-llm] Peace be with you. You asked: \"{message}\" "
            f"(turn {turn}).{grounding}"
        )

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
    ) -> str:
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        messages += [{"role": m.role, "content": m.content} for m in history]
        context = _format_context(citations or [])
        user_content = f"{context}\n\nQuestion: {message}" if context else message
        messages.append({"role": "user", "content": user_content})

        resp = await self._client.post(
            f"{self._base_url}/chat/completions",
            json={"model": self._model, "messages": messages, "temperature": 0.4},
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
