import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from app.api import routes
from app.api.schemas.schemas import AnswerPart, ChatRequest
from app.llm.llm import ChatDecision, FinalAnswer
from app.vector_db.vector_store import VectorStore


class LanguageRoutingTests(unittest.TestCase):
    def test_router_rejects_unsupported_language(self) -> None:
        with self.assertRaises(ValidationError):
            ChatDecision(
                question_clear=True,
                in_scope=True,
                retrieve_information=True,
                language="fr",
                follow_up_question="",
                search_query="Agrobank cards",
                direct_answer="",
            )

    def test_chat_uses_router_language_for_retrieval_and_answer(self) -> None:
        for language in ("uz", "ru", "en"):
            with self.subTest(language=language):
                llm = MagicMock()
                llm.analyze.return_value = ChatDecision(
                    question_clear=True,
                    in_scope=True,
                    retrieve_information=True,
                    language=language,
                    follow_up_question="",
                    search_query="Agrobank cards",
                    direct_answer="",
                )
                llm.answer.return_value = FinalAnswer(
                    parts=[AnswerPart(kind="bullet", text="Card details", source_ids=[1])]
                )
                context = [{
                    "title": "Cards",
                    "page_url": f"https://agrobank.uz/{language}/person/cards",
                    "score": 0.9,
                    "text": "Card details",
                }]

                with (
                    patch.object(routes, "LLMService", return_value=llm),
                    patch.object(routes, "get_history", return_value=[]),
                    patch.object(routes, "append_turn"),
                    patch.object(routes, "build_context", return_value=context) as build,
                ):
                    response = routes.chat(ChatRequest(question="Which cards?"))

                build.assert_called_once_with("Agrobank cards", language)
                self.assertEqual(llm.answer.call_args.kwargs["language"], language)
                self.assertEqual(response.parts[0].source_ids, [1])

    def test_vector_search_filters_indexed_language(self) -> None:
        store = VectorStore.__new__(VectorStore)
        store.client = MagicMock()
        store.collection = "agrobank_pages"
        store.client.query_points.return_value = SimpleNamespace(points=[])

        store.search([0.1], 5, "ru")

        query_filter = store.client.query_points.call_args.kwargs["query_filter"]
        self.assertEqual(query_filter.must[0].key, "language")
        self.assertEqual(query_filter.must[0].match.value, "ru")


if __name__ == "__main__":
    unittest.main()
