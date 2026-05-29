"""Query embedding client.

Wraps a sentence-transformers model (same family used by the ingest job) so the
backend can embed user queries for retrieval. Encoding is CPU-bound and sync, so
callers should invoke `embed_query` via `asyncio.to_thread`.
"""

from sentence_transformers import SentenceTransformer

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingClient:
    def __init__(self) -> None:
        logger.info("Loading embedding model: %s", settings.embedding_model)
        self._model = SentenceTransformer(settings.embedding_model)
        self._prefix = settings.embedding_query_prefix

    @property
    def dimension(self) -> int:
        return self._model.get_sentence_embedding_dimension()

    def embed_query(self, text: str) -> list[float]:
        vec = self._model.encode(
            f"{self._prefix}{text}", normalize_embeddings=True
        )
        return vec.tolist()


def build_embedding_client() -> EmbeddingClient:
    return EmbeddingClient()
