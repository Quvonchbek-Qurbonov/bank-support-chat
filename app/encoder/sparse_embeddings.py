from __future__ import annotations

import logging
import time

from qdrant_client.http.models import SparseVector

from fastembed import SparseTextEmbedding


logger = logging.getLogger("agrobank.sparse_embeddings")


class SparseEmbeddingService:
    """BM25 tokens shared by indexing and querying, without English-only stemming."""

    def __init__(self) -> None:

        started = time.monotonic()
        logger.info("bm25.loading model=Qdrant/bm25")
        self.model = SparseTextEmbedding(
            model_name="Qdrant/bm25",
            disable_stemmer=True,
        )
        logger.info("bm25.ready duration_ms=%.1f", (time.monotonic() - started) * 1000)

    def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        return [
            SparseVector(indices=embedding.indices.tolist(), values=embedding.values.tolist())
            for embedding in self.model.embed(texts)
        ]

    def embed_query(self, text: str) -> SparseVector:
        embedding = next(iter(self.model.query_embed(text)))
        return SparseVector(indices=embedding.indices.tolist(), values=embedding.values.tolist())


_service: SparseEmbeddingService | None = None


def get_sparse_embedding_service() -> SparseEmbeddingService:
    global _service
    if _service is None:
        _service = SparseEmbeddingService()
    return _service
