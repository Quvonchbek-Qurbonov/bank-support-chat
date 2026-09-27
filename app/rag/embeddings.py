from __future__ import annotations

import logging
import time

import torch
from sentence_transformers import SentenceTransformer

from app.core.config import settings


logger = logging.getLogger("agrobank.embeddings")


class EmbeddingService:
    def __init__(self) -> None:

        self.batch_size = settings.embedding_batch_size
        self.device = settings.embedding_device

        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning(
                "CUDA requested but unavailable. Falling back to CPU."
            )
            self.device = "cpu"

        started = time.monotonic()
        logger.info(
            "embedding.loading model=%s device=%s",
            settings.embedding_model,
            self.device,
        )

        self.model = SentenceTransformer(
            settings.embedding_model,
            device=self.device,
        )

        logger.info("embedding.ready duration_ms=%.1f", (time.monotonic() - started) * 1000)

    def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]: #for embedding the information of the web site
        if not texts:
            return []

        prepared = [
            f"passage: {text}"
            for text in texts
        ]

        logger.debug(
            "embedding.documents_started chunks=%s device=%s batch_size=%s",
            len(prepared),
            self.device,
            self.batch_size,
        )

        vectors = self.model.encode(
            prepared,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        return vectors.tolist()

    def embed_query(
        self,
        text: str,
    ) -> list[float]:     #for embedding the user question
        vector = self.model.encode(
            [f"query: {text}"],
            batch_size=1,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )[0]

        return vector.tolist()


_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _service

    if _service is None:
        _service = EmbeddingService()

    return _service
