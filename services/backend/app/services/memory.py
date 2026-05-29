"""Server-side conversation memory keyed by session_id.

Each session keeps a small window of recent turns verbatim plus a running
summary of older turns, so prompts stay bounded across long conversations.
The summarizer is injected (the LLM client), keeping this module backend-free
and testable with the mock LLM.

`InMemorySessionMemory` is per-process and fits dev / a single replica. A shared
backend (e.g. Redis) can implement the same `SessionMemory` interface later for
horizontally scaled deployments.
"""

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import ChatMessage

logger = get_logger(__name__)

# (overflow_messages, prior_summary) -> updated_summary
Summarizer = Callable[[list[ChatMessage], str], Awaitable[str]]


@dataclass
class SessionState:
    summary: str = ""
    recent: list[ChatMessage] = field(default_factory=list)


class SessionMemory(ABC):
    @abstractmethod
    async def load(self, session_id: str) -> tuple[str, list[ChatMessage]]:
        """Return (summary, recent_messages) for the session (empty if unknown)."""

    @abstractmethod
    async def append(
        self, session_id: str, user_message: str, assistant_message: str
    ) -> None:
        """Record one user+assistant turn, summarizing older turns on overflow."""

    @abstractmethod
    async def snapshot(self, session_id: str) -> SessionState | None:
        """Return a copy of the stored state, or None if the session is unknown."""

    @abstractmethod
    async def reset(self, session_id: str) -> bool:
        """Clear a session. Returns True if anything was removed."""


class InMemorySessionMemory(SessionMemory):
    def __init__(
        self,
        summarizer: Summarizer,
        max_turns: int,
        summary_threshold: int,
    ) -> None:
        self._summarizer = summarizer
        self._max_turns = max(0, max_turns)
        self._summary_threshold = max(self._max_turns + 1, summary_threshold)
        self._store: dict[str, SessionState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_id] = lock
            return lock

    async def load(self, session_id: str) -> tuple[str, list[ChatMessage]]:
        lock = await self._lock_for(session_id)
        async with lock:
            state = self._store.get(session_id)
            if state is None:
                return "", []
            return state.summary, list(state.recent)

    async def append(
        self, session_id: str, user_message: str, assistant_message: str
    ) -> None:
        lock = await self._lock_for(session_id)
        async with lock:
            state = self._store.setdefault(session_id, SessionState())
            state.recent.append(ChatMessage(role="user", content=user_message))
            state.recent.append(
                ChatMessage(role="assistant", content=assistant_message)
            )
            await self._maybe_summarize(state)

    async def _maybe_summarize(self, state: SessionState) -> None:
        # One turn == 2 messages (user + assistant); thresholds are in turns.
        max_messages = self._summary_threshold * 2
        if len(state.recent) <= max_messages:
            return
        keep = self._max_turns * 2
        overflow = state.recent[:-keep] if keep else list(state.recent)
        if not overflow:
            return
        try:
            new_summary = await self._summarizer(overflow, state.summary)
        except Exception as exc:  # don't drop turns if summarization fails
            logger.warning("Summarization failed; keeping full window: %s", exc)
            return
        state.summary = new_summary.strip()
        state.recent = state.recent[-keep:] if keep else []

    async def snapshot(self, session_id: str) -> SessionState | None:
        lock = await self._lock_for(session_id)
        async with lock:
            state = self._store.get(session_id)
            if state is None:
                return None
            return SessionState(summary=state.summary, recent=list(state.recent))

    async def reset(self, session_id: str) -> bool:
        lock = await self._lock_for(session_id)
        async with lock:
            existed = self._store.pop(session_id, None) is not None
        async with self._guard:
            self._locks.pop(session_id, None)
        return existed


def build_memory(summarizer: Summarizer) -> SessionMemory:
    logger.info(
        "Using InMemorySessionMemory (max_turns=%s, summary_threshold=%s)",
        settings.memory_max_turns,
        settings.memory_summary_threshold,
    )
    return InMemorySessionMemory(
        summarizer=summarizer,
        max_turns=settings.memory_max_turns,
        summary_threshold=settings.memory_summary_threshold,
    )
