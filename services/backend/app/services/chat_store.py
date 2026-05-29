"""Postgres-backed durable chat store.

Implements the `SessionMemory` interface (so the session router and the prompt
window keep working) and adds durable extras: full history, image persistence,
and a session listing for the history sidebar (Phase 10).

Full turn history is always retained; the rolling `summary` only bounds what is
fed back to the model, mirroring `InMemorySessionMemory` semantics.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Image, Session, Turn
from app.schemas import ChatMessage
from app.services.memory import SessionMemory, SessionState, Summarizer

logger = get_logger(__name__)


@dataclass(frozen=True)
class ImageRef:
    id: str
    filename: str
    url: str


class PostgresChatStore(SessionMemory):
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        summarizer: Summarizer,
        max_turns: int,
        summary_threshold: int,
        media_dir: str,
        media_url_path: str,
    ) -> None:
        self._sm = sessionmaker
        self._summarizer = summarizer
        self._max_turns = max(0, max_turns)
        self._summary_threshold = max(self._max_turns + 1, summary_threshold)
        self._media_dir = Path(media_dir)
        self._media_url_path = media_url_path.rstrip("/")
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_id] = lock
            return lock

    # ----- SessionMemory interface -------------------------------------------

    async def load(self, session_id: str) -> tuple[str, list[ChatMessage]]:
        async with self._sm() as db:
            session = await db.get(Session, session_id)
            if session is None:
                return "", []
            rows = await self._unsummarized_rows(db, session)
            return session.summary, [
                ChatMessage(role=r.role, content=r.content) for r in rows
            ]

    async def append(
        self, session_id: str, user_message: str, assistant_message: str
    ) -> None:
        await self.record_turn(session_id, None, user_message, assistant_message)

    async def snapshot(self, session_id: str) -> SessionState | None:
        async with self._sm() as db:
            session = await db.get(Session, session_id)
            if session is None:
                return None
            rows = await self._unsummarized_rows(db, session)
            return SessionState(
                summary=session.summary,
                recent=[ChatMessage(role=r.role, content=r.content) for r in rows],
            )

    async def reset(self, session_id: str) -> bool:
        async with await self._lock_for(session_id):
            async with self._sm() as db:
                session = await db.get(Session, session_id)
                if session is None:
                    return False
                await db.delete(session)
                await db.commit()
        async with self._guard:
            self._locks.pop(session_id, None)
        return True

    # ----- Durable extras -----------------------------------------------------

    async def record_turn(
        self,
        session_id: str,
        denomination: str | None,
        user_message: str,
        assistant_message: str,
        intent_kind: str | None = None,
        image_id: str | None = None,
    ) -> None:
        async with await self._lock_for(session_id):
            async with self._sm() as db:
                session = await db.get(Session, session_id)
                if session is None:
                    session = Session(
                        id=session_id, denomination=denomination or "neutral"
                    )
                    db.add(session)
                elif denomination:
                    session.denomination = denomination

                db.add(Turn(session_id=session_id, role="user", content=user_message))
                assistant = Turn(
                    session_id=session_id,
                    role="assistant",
                    content=assistant_message,
                    intent_kind=intent_kind,
                )
                db.add(assistant)
                await db.flush()

                if image_id:
                    img = await db.get(Image, image_id)
                    if img is not None:
                        img.turn_id = assistant.id

                await self._maybe_summarize(db, session)
                await db.commit()

    async def save_image(
        self, session_id: str, png_base64: str, positive: str, negative: str
    ) -> ImageRef:
        image_id = uuid.uuid4().hex
        filename = f"{image_id}.png"
        self._media_dir.mkdir(parents=True, exist_ok=True)
        (self._media_dir / filename).write_bytes(base64.b64decode(png_base64))
        async with self._sm() as db:
            # The image is persisted before the turn, so guarantee the parent
            # session row exists (flushed first) to satisfy the FK; record_turn
            # fills in the rest.
            if await db.get(Session, session_id) is None:
                db.add(Session(id=session_id))
                await db.flush()
            db.add(
                Image(
                    id=image_id,
                    session_id=session_id,
                    filename=filename,
                    positive=positive,
                    negative=negative,
                )
            )
            await db.commit()
        url = f"{self._media_url_path}/{filename}"
        logger.info("[chat-store] saved image %s for session %s", filename, session_id)
        return ImageRef(id=image_id, filename=filename, url=url)

    async def get_history(self, session_id: str) -> list[dict] | None:
        async with self._sm() as db:
            session = await db.get(Session, session_id)
            if session is None:
                return None
            rows = (
                await db.execute(
                    select(Turn)
                    .where(Turn.session_id == session_id)
                    .order_by(Turn.id)
                )
            ).scalars().all()
            images = (
                await db.execute(
                    select(Image).where(Image.session_id == session_id)
                )
            ).scalars().all()
            by_turn = {img.turn_id: img for img in images if img.turn_id is not None}
            history: list[dict] = []
            for r in rows:
                image = by_turn.get(r.id)
                history.append(
                    {
                        "role": r.role,
                        "content": r.content,
                        "intent_kind": r.intent_kind,
                        "image_url": f"{self._media_url_path}/{image.filename}"
                        if image
                        else None,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                )
            return history

    async def list_sessions(self) -> list[dict]:
        async with self._sm() as db:
            sessions = (
                await db.execute(select(Session).order_by(Session.updated_at.desc()))
            ).scalars().all()
            out: list[dict] = []
            for s in sessions:
                turn_count = (
                    await db.execute(
                        select(func.count(Turn.id)).where(Turn.session_id == s.id)
                    )
                ).scalar_one()
                first_user = (
                    await db.execute(
                        select(Turn.content)
                        .where(Turn.session_id == s.id, Turn.role == "user")
                        .order_by(Turn.id)
                        .limit(1)
                    )
                ).scalar_one_or_none()
                out.append(
                    {
                        "session_id": s.id,
                        "denomination": s.denomination,
                        "turns": turn_count // 2,
                        "preview": (first_user or "")[:80],
                        "created_at": s.created_at.isoformat() if s.created_at else None,
                        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                    }
                )
            return out

    # ----- internals ----------------------------------------------------------

    async def _unsummarized_rows(self, db: AsyncSession, session: Session) -> list[Turn]:
        return list(
            (
                await db.execute(
                    select(Turn)
                    .where(Turn.session_id == session.id)
                    .order_by(Turn.id)
                    .offset(session.summary_turn_count)
                )
            ).scalars().all()
        )

    async def _maybe_summarize(self, db: AsyncSession, session: Session) -> None:
        rows = await self._unsummarized_rows(db, session)
        # One turn == 2 rows (user + assistant); thresholds are in turns.
        if len(rows) <= self._summary_threshold * 2:
            return
        keep = self._max_turns * 2
        overflow = rows[:-keep] if keep else rows
        if not overflow:
            return
        try:
            new_summary = await self._summarizer(
                [ChatMessage(role=r.role, content=r.content) for r in overflow],
                session.summary,
            )
        except Exception as exc:  # don't drop turns if summarization fails
            logger.warning("Summarization failed; keeping full window: %s", exc)
            return
        session.summary = new_summary.strip()
        session.summary_turn_count += len(overflow)


def build_chat_store(
    sessionmaker: async_sessionmaker[AsyncSession], summarizer: Summarizer
) -> PostgresChatStore:
    logger.info(
        "Using PostgresChatStore (max_turns=%s, summary_threshold=%s, media=%s)",
        settings.memory_max_turns,
        settings.memory_summary_threshold,
        settings.media_dir,
    )
    return PostgresChatStore(
        sessionmaker=sessionmaker,
        summarizer=summarizer,
        max_turns=settings.memory_max_turns,
        summary_threshold=settings.memory_summary_threshold,
        media_dir=settings.media_dir,
        media_url_path=settings.media_url_path,
    )
