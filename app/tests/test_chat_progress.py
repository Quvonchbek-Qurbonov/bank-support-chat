import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api import routes
from app.api.schemas.schemas import AnswerPart
from app.main import app
from app.llm.llm import ChatDecision, FinalAnswer


def decision(*, tool: str = "none", retrieve_information: bool = False) -> ChatDecision:
    return ChatDecision(
        question_clear=True,
        in_scope=True,
        retrieve_information=retrieve_information,
        tool=tool,
        language="en",
        follow_up_question="",
        search_query="Agrobank card details" if retrieve_information else "",
        direct_answer="" if tool != "none" or retrieve_information else "Hello!",
    )


def stream_events(question: str) -> list[dict]:
    with TestClient(app).stream("POST", "/chat/stream", json={"question": question}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        return [json.loads(line) for line in response.iter_lines() if line]


class ChatProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.llm = MagicMock()
        self.llm.answer.return_value = FinalAnswer(parts=[
            AnswerPart(kind="paragraph", text="Verified answer", source_ids=[1]),
        ])
        self.source = {
            "title": "Official page",
            "page_url": "https://agrobank.uz/en/person/exchange_rates",
            "score": 1.0,
            "text": "Verified information",
        }

    def test_live_rate_question_reports_real_phases_in_order(self) -> None:
        self.llm.analyze.return_value = decision(tool="exchange_rates")
        with (
            patch.object(routes, "LLMService", return_value=self.llm),
            patch.object(routes, "get_history", return_value=[]),
            patch.object(routes, "append_turn"),
            patch.object(routes, "get_exchange_rate_context", return_value=[self.source]) as live,
            patch.object(routes, "build_context") as vector,
        ):
            events = stream_events("What is the USD exchange rate?")

        self.assertEqual([event.get("phase", event["type"]) for event in events], [
            "analyzing", "exchange_rates", "generating", "result",
        ])
        self.assertEqual(events[-1]["data"]["parts"][0]["source_ids"], [1])
        live.assert_called_once_with("en")
        vector.assert_not_called()

    def test_vector_question_reports_retrieval_then_generation(self) -> None:
        self.llm.analyze.return_value = decision(retrieve_information=True)
        with (
            patch.object(routes, "LLMService", return_value=self.llm),
            patch.object(routes, "get_history", return_value=[]),
            patch.object(routes, "append_turn"),
            patch.object(routes, "build_context", return_value=[self.source]),
        ):
            events = stream_events("Tell me about an Agrobank card")

        self.assertEqual([event.get("phase", event["type"]) for event in events], [
            "analyzing", "retrieving", "generating", "result",
        ])

    def test_direct_answer_finishes_after_analysis(self) -> None:
        self.llm.analyze.return_value = decision()
        with (
            patch.object(routes, "LLMService", return_value=self.llm),
            patch.object(routes, "get_history", return_value=[]),
            patch.object(routes, "append_turn"),
        ):
            events = stream_events("Hello there")

        self.assertEqual([event.get("phase", event["type"]) for event in events], [
            "analyzing", "result",
        ])
        self.assertEqual(events[-1]["data"]["answer"], "Hello!")
        self.llm.answer.assert_not_called()

    def test_stream_sends_error_event_instead_of_stale_rate_answer(self) -> None:
        self.llm.analyze.return_value = decision(tool="exchange_rates")
        with (
            patch.object(routes, "LLMService", return_value=self.llm),
            patch.object(routes, "get_history", return_value=[]),
            patch.object(routes, "append_turn") as append,
            patch.object(routes, "get_exchange_rate_context", side_effect=RuntimeError("Rates unavailable")),
        ):
            events = stream_events("What is the current USD rate?")

        self.assertEqual([event.get("phase", event["type"]) for event in events], [
            "analyzing", "exchange_rates", "error",
        ])
        self.assertEqual(events[-1]["detail"], "Rates unavailable")
        append.assert_not_called()

    def test_final_answer_failure_sends_error_without_saving_history(self) -> None:
        self.llm.analyze.return_value = decision(retrieve_information=True)
        self.llm.answer.side_effect = RuntimeError(
            "The AI service could not produce a valid response. Please try again."
        )
        with (
            patch.object(routes, "LLMService", return_value=self.llm),
            patch.object(routes, "get_history", return_value=[]),
            patch.object(routes, "append_turn") as append,
            patch.object(routes, "build_context", return_value=[self.source]),
        ):
            events = stream_events("Tell me about an Agrobank card")

        self.assertEqual([event.get("phase", event["type"]) for event in events], [
            "analyzing", "retrieving", "generating", "error",
        ])
        self.assertIn("Please try again", events[-1]["detail"])
        append.assert_not_called()


if __name__ == "__main__":
    unittest.main()
