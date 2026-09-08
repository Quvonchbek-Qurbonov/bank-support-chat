from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from app.core.config import get_settings


class VectorStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.client = QdrantClient(url=settings.qdrant_url)
        self.collection = settings.qdrant_collection
        self.dim = settings.embedding_dim
        self.ensure_collection()

    def ensure_collection(self) -> None:
        collections = {c.name for c in self.client.get_collections().collections}
        if self.collection not in collections:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
            )

    def replace_resource_chunks(
        self,
        resource_id: int,
        page_url: str,
        language: str,
        title: str | None,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> None:
        # Delete old vectors for this resource before inserting the new version.
        self.client.delete(
            collection_name=self.collection,
            points_selector=FilterSelector(resource_id).to_filter(),
        )

        points = []
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            point_id = _stable_point_id(resource_id, index)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding,
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

        if points:
            self.client.upsert(collection_name=self.collection, points=points, wait=True)

    def search(self, vector: list[float], limit: int, language: str | None = None) -> list[dict[str, Any]]:
        query_filter = None
        if language:
            query_filter = Filter(
                must=[FieldCondition(key="language", match=MatchValue(value=language))]
            )

        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return [
            {
                "score": hit.score,
                "resource_id": hit.payload.get("resource_id"),
                "title": hit.payload.get("title"),
                "page_url": hit.payload.get("page_url"),
                "text": hit.payload.get("text"),
            }
            for hit in response.points
        ]


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


def _stable_point_id(resource_id: int, chunk_index: int) -> int:
    # Deterministic integer for Qdrant without storing UUID mapping.
    return resource_id * 1_000_000 + chunk_index


_store: VectorStore | None = None

def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
