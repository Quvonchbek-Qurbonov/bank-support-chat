import logging
import time

from app.rag.embeddings import get_embedding_service
from app.rag.vector_store import get_vector_store
from app.rag.reranker import get_reranker
from app.core.config import settings


logger = logging.getLogger("agrobank.retrieval")


def _document_count(hits: list[dict]) -> int:
    return len({
        ("resource", hit["resource_id"]) if hit.get("resource_id") is not None
        else ("url", hit["page_url"]) if hit.get("page_url")
        else ("chunk", index)
        for index, hit in enumerate(hits)
    })


def build_context(question: str, language: str | None = None):
    started = time.monotonic()
    embedder = get_embedding_service()
    vector_store = get_vector_store()

    query_vector = embedder.embed_query(question)
    embedded_at = time.monotonic()

    hits = vector_store.search(
        query_vector, max(settings.retrieval_candidate_k, settings.context_top_k),
        language, query_text=question,
    )
    searched_at = time.monotonic()

    # RRF and cross-encoder scores are not cosine similarities. Do not apply
    # the old cosine cutoff to hybrid candidates before reranking.
    selected = get_reranker().rerank(question, hits, settings.context_top_k) if hits else []
    finished_at = time.monotonic()
    logger.info(
        "retrieval.completed language=%s candidate_chunks=%d candidate_documents=%d "
        "selected_chunks=%d selected_documents=%d embed_ms=%.1f search_ms=%.1f "
        "rerank_ms=%.1f total_ms=%.1f",
        language or "all",
        len(hits),
        _document_count(hits),
        len(selected),
        _document_count(selected),
        (embedded_at - started) * 1000,
        (searched_at - embedded_at) * 1000,
        (finished_at - searched_at) * 1000,
        (finished_at - started) * 1000,
    )
    return selected
