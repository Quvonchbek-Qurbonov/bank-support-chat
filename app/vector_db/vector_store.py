from __future__ import annotations

import logging
import time
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance, FieldCondition, Filter, Fusion, FusionQuery, MatchValue, Modifier,
    PointStruct, PointVectors, Prefetch, SparseVectorConfig, SparseVectorNameConfig,
    VectorParams,
)

from app.core.config import settings
from app.encoder.sparse_embeddings import get_sparse_embedding_service


SPARSE_VECTOR_NAME = "bm25"
logger = logging.getLogger("agrobank.vector_store")


class VectorStore:
    def __init__(self) -> None:
        self.client = QdrantClient(url=settings.qdrant_url)
        self.collection = settings.qdrant_collection
        self.dim = settings.embedding_dim
        self.ensure_collection()

    def ensure_collection(self) -> None: #function to create collection to store information
        collections = {c.name for c in self.client.get_collections().collections}
        if self.collection not in collections:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
            )
            logger.info("vector_collection.created collection=%s dim=%d", self.collection, self.dim)
        info = self.client.get_collection(self.collection)
        if SPARSE_VECTOR_NAME not in (info.config.params.sparse_vectors or {}):
            self.client.create_vector_name(
                collection_name=self.collection,
                vector_name=SPARSE_VECTOR_NAME,
                vector_name_config=SparseVectorNameConfig(
                    sparse=SparseVectorConfig(modifier=Modifier.IDF),
                ),
            )
            logger.info("vector_collection.sparse_enabled collection=%s", self.collection)

    def replace_resource_chunks(
        self,
        resource_id: int,
        page_url: str,
        language: str,
        title: str | None,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> None:
        sparse_vectors = get_sparse_embedding_service().embed_documents(
            [self._sparse_text(title, chunk) for chunk in chunks]
        ) if chunks else []

        points = []
        for index, (chunk, embedding, sparse) in enumerate(zip(chunks, embeddings, sparse_vectors)):
            point_id = _stable_point_id(resource_id, index)
            points.append(
                PointStruct(
                    id=point_id,
                    vector={
                        "": embedding,
                        **({SPARSE_VECTOR_NAME: sparse} if sparse.indices else {}),
                    },
                    payload={
                        "resource_id": resource_id,
                        "chunk_index": index,
                        "language": language,
                        "title": title,
                        "page_url": page_url,
                        "text": chunk,
                    },
                )
            )

        # Finish BM25 encoding before replacing existing points so a model
        # download/encoding failure cannot remove the previous index entries.
        self.client.delete(
            collection_name=self.collection,
            points_selector=FilterSelector(resource_id).to_filter(),
            wait=True,
        )
        if points:
            self.client.upsert(collection_name=self.collection, points=points, wait=True)

    @staticmethod
    def _sparse_text(title: str | None, chunk: str) -> str:
        return f"{title or ''}\n{chunk}"

    def backfill_sparse_vectors(self, batch_size: int = 64) -> int:
        """Add BM25 vectors to existing dense points without re-embedding or deleting them."""
        sparse_embedder = get_sparse_embedding_service()
        offset = None
        updated = 0
        while True:
            records, offset = self.client.scroll(
                collection_name=self.collection,
                limit=batch_size,
                offset=offset,
                with_payload=["title", "text"],
                with_vectors=[SPARSE_VECTOR_NAME],
            )
            missing = [
                point for point in records
                if not isinstance(point.vector, dict) or SPARSE_VECTOR_NAME not in point.vector
            ]
            if missing:
                sparse_vectors = sparse_embedder.embed_documents([
                    self._sparse_text((point.payload or {}).get("title"), (point.payload or {}).get("text") or "")
                    for point in missing
                ])
                updates = [
                    PointVectors(id=point.id, vector={SPARSE_VECTOR_NAME: sparse})
                    for point, sparse in zip(missing, sparse_vectors)
                    if sparse.indices
                ]
                if updates:
                    self.client.update_vectors(
                        collection_name=self.collection, points=updates, wait=True,
                    )
                    updated += len(updates)
            if offset is None:
                return updated

    def delete_resource_chunks(self, resource_id: int) -> None:
        """Delete all Qdrant vectors belonging to a resource."""
        self.client.delete(
            collection_name=self.collection,
            points_selector=FilterSelector(resource_id).to_filter(),
            wait=True,
        )

    def search(
        self, vector: list[float], limit: int, language: str | None = None,
        query_text: str | None = None,
    ) -> list[dict[str, Any]]:
        started = time.monotonic()
        query_filter = None
        if language:
            query_filter = Filter(
                must=[FieldCondition(key="language", match=MatchValue(value=language))]
            )

        if query_text:
            sparse = get_sparse_embedding_service().embed_query(query_text)
        else:
            sparse = None

        if sparse is not None and sparse.indices:
            response = self.client.query_points(
                collection_name=self.collection,
                prefetch=[
                    Prefetch(query=vector, filter=query_filter, limit=limit),
                    Prefetch(query=sparse, using=SPARSE_VECTOR_NAME, filter=query_filter, limit=limit),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        else:
            response = self.client.query_points(
                collection_name=self.collection,
                query=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        hits = [
            {
                "score": hit.score,
                "resource_id": hit.payload.get("resource_id"),
                "title": hit.payload.get("title"),
                "page_url": hit.payload.get("page_url"),
                "text": hit.payload.get("text"),
            }
            for hit in response.points
        ]
        logger.info(
            "vector_search.completed mode=%s language=%s limit=%d returned_chunks=%d duration_ms=%.1f",
            "hybrid" if sparse is not None and sparse.indices else "dense",
            language or "all",
            limit,
            len(hits),
            (time.monotonic() - started) * 1000,
        )
        return hits


class FilterSelector:
    def __init__(self, resource_id: int) -> None:
        self.resource_id = resource_id

    def to_filter(self) -> Filter:
        return Filter(
            must=[
                FieldCondition(
                    key="resource_id",
                    match=MatchValue(value=self.resource_id),
                )
            ]
        )


def _stable_point_id(resource_id: int, chunk_index: int) -> int:  # this function updating easier without removing the old data
    return resource_id * 1_000_000 + chunk_index


_store: VectorStore | None = None

def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
