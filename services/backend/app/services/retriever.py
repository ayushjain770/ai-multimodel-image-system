"""Scripture retrieval: embed a query, search Qdrant, return grounded verses.

Denomination maps to a canon tag so that, e.g., Protestant queries do not match
deuterocanonical books. `neutral`/unknown searches the whole corpus.
"""

import asyncio

from app.clients.embeddings import EmbeddingClient
from app.clients.qdrant_client import VectorDBClient
from app.core.config import settings
from app.schemas import Citation, Denomination


def _canon_for(denomination: Denomination) -> str | None:
    mapping = {
        Denomination.CATHOLIC: "catholic",
        Denomination.ORTHODOX: "orthodox",
        Denomination.PROTESTANT: "protestant",
    }
    return mapping.get(denomination)  # neutral -> None (no filter)


class Retriever:
    def __init__(self, embedder: EmbeddingClient, vectors: VectorDBClient) -> None:
        self._embedder = embedder
        self._vectors = vectors

    async def retrieve(
        self,
        query: str,
        denomination: Denomination = Denomination.NEUTRAL,
        top_k: int | None = None,
    ) -> list[Citation]:
        vector = await asyncio.to_thread(self._embedder.embed_query, query)
        hits = await self._vectors.search(
            vector=vector,
            top_k=top_k or settings.rag_top_k,
            canon=_canon_for(denomination),
        )
        return [
            Citation(
                ref=h["ref"],
                translation=h["translation"],
                book=h["book"],
                chapter=h["chapter"],
                verse=h["verse"],
                text=h["text"],
                score=round(float(h["score"]), 4),
            )
            for h in hits
        ]
