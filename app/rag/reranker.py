from __future__ import annotations

import logging
import time
from typing import Any

import torch
from sentence_transformers import CrossEncoder

from app.core.config import settings


logger = logging.getLogger("agrobank.reranker")


class Reranker:
    def __init__(self) -> None:
        device = settings.embedding_device if torch.cuda.is_available() else "cpu"
        started = time.monotonic()
        logger.info("reranker.loading model=%s device=%s", settings.reranker_model, device)
        self.model = CrossEncoder(settings.reranker_model, device=device)
        logger.info("reranker.ready duration_ms=%.1f", (time.monotonic() - started) * 1000)

    def rerank(self, question: str, hits: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        if not hits:
            return []

        started = time.monotonic()
        pairs = [
            (question, "\n".join(filter(None, [hit.get("title"), hit.get("text")])))
            for hit in hits
        ]
        scores = self.model.predict(
            pairs,
            batch_size=settings.reranker_batch_size,
            show_progress_bar=False,
        )
        ranked = sorted(zip(hits, scores), key=lambda item: float(item[1]), reverse=True)
        selected = [dict(hit, rerank_score=float(score)) for hit, score in ranked[:limit]]
        logger.info(
            "reranker.completed input_chunks=%d selected_chunks=%d duration_ms=%.1f",
            len(hits), len(selected), (time.monotonic() - started) * 1000,
        )
        return selected


_service: Reranker | None = None


def get_reranker() -> Reranker:
    global _service
    if _service is None:
        _service = Reranker()
    return _service
