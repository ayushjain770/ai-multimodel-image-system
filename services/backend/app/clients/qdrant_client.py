"""Async-friendly wrapper around the Qdrant vector DB.

Health uses a lightweight httpx probe; search uses the official qdrant-client
(sync, so calls are dispatched to a thread). Collection name comes from config.
"""

import asyncio

import httpx
from qdrant_client import QdrantClient, models

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class VectorDBClient:
    def __init__(self) -> None:
        self._base_url = settings.qdrant_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=10.0)
        self._client = QdrantClient(url=self._base_url)
        self._collection = settings.qdrant_collection

    async def health(self) -> tuple[bool, str]:
        try:
            resp = await self._http.get(f"{self._base_url}/readyz")
            ok = resp.status_code == 200
            return ok, f"qdrant /readyz -> {resp.status_code}"
        except httpx.HTTPError as exc:
            return False, f"qdrant unreachable: {exc}"

    async def collection_ready(self) -> bool:
        def _check() -> bool:
            if not self._client.collection_exists(self._collection):
                return False
            return self._client.count(self._collection, exact=True).count > 0

        return await asyncio.to_thread(_check)

    async def search(
        self,
        vector: list[float],
        top_k: int,
        canon: str | None = None,
    ) -> list[dict]:
        """Vector search, optionally filtered to a denomination's canon."""
        query_filter = None
        if canon:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="canon_tags",
                        match=models.MatchValue(value=canon),
                    )
                ]
            )

        def _run() -> list[dict]:
            hits = self._client.search(
                collection_name=self._collection,
                query_vector=vector,
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
            )
            return [{"score": h.score, **(h.payload or {})} for h in hits]

        return await asyncio.to_thread(_run)

    async def aclose(self) -> None:
        await self._http.aclose()
        self._client.close()


def build_vector_client() -> VectorDBClient:
    logger.info(
        "Using Qdrant at %s (collection=%s)",
        settings.qdrant_url,
        settings.qdrant_collection,
    )
    return VectorDBClient()
