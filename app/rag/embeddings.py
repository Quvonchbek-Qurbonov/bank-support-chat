from __future__ import annotations

import logging

import torch
from sentence_transformers import SentenceTransformer

from app.core.config import settings


logger = logging.getLogger("agrobank.embeddings")


class EmbeddingService:
    def __init__(self) -> None:

        self.batch_size = settings.embedding_batch_size
        self.device = settings.embedding_device

        if not torch.cuda.is_available():
            logger.warning(
                "CUDA requested but unavailable. Falling back to CPU."
            )
            self.device = "cpu"

        logger.info(
            "Loading embedding MODEL=%s DEVICE=%s GPU=%s",
            settings.embedding_model,
            self.device,
            torch.cuda.get_device_name(0) if self.device == "cuda" else "Your cpu",
        )

        self.model = SentenceTransformer(
            settings.embedding_model,
            device=self.device,
        )

        logger.info("Embedding model loaded")

    def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        if not texts:
            return []

        prepared = [
            f"passage: {text}"
            for text in texts
        ]

        logger.info(
            "Embedding %s chunks | device=%s | batch_size=%s",
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
    ) -> list[float]:
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