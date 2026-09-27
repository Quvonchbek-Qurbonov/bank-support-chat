import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, SparseVector

from app.api import debug_router
from app.main import app
from app.rag.reranker import Reranker
from app.rag.vector_store import SPARSE_VECTOR_NAME, VectorStore
from app.service import context


class FakeSparseEmbedder:
    @staticmethod
    def _embed(text):
        words = text.lower().split()
        indices = [token_id for word, token_id in (("humo", 1), ("uzcard", 2)) if word in words]
        return SparseVector(indices=indices, values=[1.0] * len(indices))

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)


class RetrievalPipelineTests(unittest.TestCase):
    def setUp(self):
        self.store = VectorStore.__new__(VectorStore)
        self.store.client = QdrantClient(":memory:")
        self.store.collection = "test_pages"
        self.store.dim = 2
        self.store.ensure_collection()

    def test_existing_dense_points_get_sparse_vectors_without_reembedding(self):
        self.store.client.upsert(
            self.store.collection,
            [PointStruct(id=1, vector=[1.0, 0.0], payload={
                "resource_id": 1, "title": "Humo", "text": "Humo card",
                "language": "en", "page_url": "https://agrobank.uz/en/humo",
            })],
        )
        with patch("app.rag.vector_store.get_sparse_embedding_service", return_value=FakeSparseEmbedder()):
            self.assertEqual(self.store.backfill_sparse_vectors(), 1)
            self.assertEqual(self.store.backfill_sparse_vectors(), 0)

        points, _ = self.store.client.scroll(self.store.collection, with_vectors=True)
        self.assertEqual(points[0].vector[""], [1.0, 0.0])
        self.assertIn(SPARSE_VECTOR_NAME, points[0].vector)

    def test_hybrid_search_keeps_language_filter(self):
        sparse = FakeSparseEmbedder()
        with patch("app.rag.vector_store.get_sparse_embedding_service", return_value=sparse):
            self.store.replace_resource_chunks(1, "https://agrobank.uz/en/humo", "en", "Humo", ["Humo card"], [[1.0, 0.0]])
            self.store.replace_resource_chunks(2, "https://agrobank.uz/ru/humo", "ru", "Humo", ["Humo card"], [[1.0, 0.0]])
            hits = self.store.search([1.0, 0.0], 10, "ru", query_text="humo")

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["page_url"], "https://agrobank.uz/ru/humo")

    def test_reranker_changes_order_but_keeps_source_metadata(self):
        reranker = Reranker.__new__(Reranker)
        reranker.model = MagicMock()
        reranker.model.predict.return_value = [0.2, 0.9]
        hits = [
            {"title": "First", "text": "less relevant", "page_url": "https://agrobank.uz/first", "score": 0.5},
            {"title": "Second", "text": "more relevant", "page_url": "https://agrobank.uz/second", "score": 0.4},
        ]

        with self.assertLogs("agrobank.reranker", level="INFO") as logs:
            result = reranker.rerank("which card?", hits, 1)

        self.assertEqual(result[0]["title"], "Second")
        self.assertEqual(result[0]["page_url"], "https://agrobank.uz/second")
        self.assertEqual(result[0]["rerank_score"], 0.9)
        self.assertEqual(result[0]["score"], 0.4)
        self.assertIn("input_chunks=2 selected_chunks=1", logs.output[0])
        self.assertNotIn("which card?", logs.output[0])

    def test_context_does_not_apply_old_cosine_cutoff_to_rrf_scores(self):
        hit = {"text": "Humo details", "score": 0.02}
        embedder = SimpleNamespace(embed_query=lambda _: [1.0, 0.0])
        store = MagicMock()
        store.search.return_value = [hit]
        reranker = MagicMock()
        reranker.rerank.return_value = [hit]

        with (
            patch.object(context, "get_embedding_service", return_value=embedder),
            patch.object(context, "get_vector_store", return_value=store),
            patch.object(context, "get_reranker", return_value=reranker),
        ):
            with self.assertLogs("agrobank.retrieval", level="INFO") as logs:
                result = context.build_context("Humo fees", "en")

        self.assertEqual(result, [hit])
        self.assertEqual(store.search.call_args.kwargs["query_text"], "Humo fees")
        reranker.rerank.assert_called_once()
        self.assertIn("candidate_chunks=1", logs.output[0])
        self.assertIn("selected_chunks=1", logs.output[0])
        self.assertNotIn("Humo fees", logs.output[0])

    def test_document_count_distinguishes_pages_from_chunks(self):
        self.assertEqual(context._document_count([
            {"resource_id": 1}, {"resource_id": 1}, {"resource_id": 2},
        ]), 2)

    def test_debug_relevants_uses_optional_language_without_detector(self):
        with patch.object(debug_router, "build_context", return_value=[]) as build:
            self.assertEqual(
                debug_router.get_relevant_resources("Humo card"),
                [],
            )
            build.assert_called_with("Humo card", None)

            debug_router.get_relevant_resources(
                "Humo card", language="uz",
            )
            build.assert_called_with("Humo card", "uz")

            response = TestClient(app).get(
                "/relevants", params={"question": "Humo card", "language": "uz"},
            )
            self.assertEqual(response.status_code, 200)
            build.assert_called_with("Humo card", "uz")


if __name__ == "__main__":
    unittest.main()
