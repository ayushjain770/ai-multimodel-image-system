"""Thin async wrapper around the Qdrant vector DB.

Phase 1 only exposes a health probe; collections and search land in the RAG
phase.
"""

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class VectorDBClient:
    def __init__(self) -> None:
        self._base_url = settings.qdrant_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=10.0)

    async def health(self) -> tuple[bool, str]:
        try:
            resp = await self._client.get(f"{self._base_url}/readyz")
            ok = resp.status_code == 200
            return ok, f"qdrant /readyz -> {resp.status_code}"
        except httpx.HTTPError as exc:
            return False, f"qdrant unreachable: {exc}"

    async def aclose(self) -> None:
        await self._client.aclose()


def build_vector_client() -> VectorDBClient:
    logger.info("Using Qdrant at %s", settings.qdrant_url)
    return VectorDBClient()
