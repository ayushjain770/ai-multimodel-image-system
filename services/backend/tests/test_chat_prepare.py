"""Unit tests for prepare_turn RAG and synthesizer routing."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.clients.llm_client import MockLLMClient
from app.core.config import settings
from app.routers.chat import prepare_turn
from app.schemas import ChatRequest, Denomination


class FakeVectorClient:
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    async def collection_ready(self) -> bool:
        return self._ready


class FakeRetriever:
    async def retrieve(self, message: str, denomination) -> list:
        return []


def _make_request(app) -> MagicMock:
    req = MagicMock()
    req.app = app
    return req


def _make_app(*, collection_ready: bool) -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            verifier=None,
            memory=None,
            moderator=None,
            planner=None,
            retriever=FakeRetriever(),
            vector_client=FakeVectorClient(collection_ready),
            llm_client=MockLLMClient(),
        )
    )


class TestPrepareTurnRag(unittest.IsolatedAsyncioTestCase):
    async def test_scripture_rag_miss_when_collection_not_ready(self) -> None:
        app = _make_app(collection_ready=False)
        payload = ChatRequest(
            message="What does the Bible say about love?",
            denomination=Denomination.NEUTRAL,
        )
        early, prepared = await prepare_turn(_make_request(app), payload)
        self.assertIsNotNone(early)
        self.assertIsNone(prepared)
        assert early is not None
        self.assertEqual(early.reply, settings.rag_miss_reply)
        self.assertTrue(early.intent.rag_miss)

    async def test_synthesizer_uses_image_route_when_forced(self) -> None:
        app = _make_app(collection_ready=True)
        payload = ChatRequest(
            message="Hello there",
            denomination=Denomination.NEUTRAL,
            generate_image=True,
        )
        early, prepared = await prepare_turn(_make_request(app), payload)
        self.assertIsNone(early)
        self.assertIsNotNone(prepared)
        assert prepared is not None
        self.assertIn("Route: image", prepared.system_prompt)
        self.assertIsNotNone(prepared.image_params)


if __name__ == "__main__":
    unittest.main()
