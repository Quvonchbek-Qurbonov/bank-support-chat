import unittest
from unittest.mock import MagicMock, patch

from app.api import routes
from app.api.schemas.schemas import AnswerPart, ChatRequest
from app.llm.llm import ChatDecision, FinalAnswer, LLMService
from app.tools.exchange_rates import get_exchange_rate_context, parse_exchange_rates


def rate_payload() -> dict:
    office = {"alpha3": "USD", "buy": 11780, "sale": 11870,
              "rate": 11825.4, "updated": "2026-09-28T15:30:51+05:00"}
    atm = {"alpha3": "EUR", "buy": 11000, "sale": 0,
           "rate": 13483.32, "updated": "2026-09-28T15:31:29+05:00"}
    transfer = {"alpha3": "USD", "buy": 11790, "sale": 11860,
                "rate": 11825.4, "updated": "2026-09-28T15:32:17+05:00"}
    return {"success": True, "data": {"sections": [{"blocks": [
        {"type": "tab", "content": {"code": "office"}},
        {"type": "currency-rates", "content": {"items": [office]}},
        {"type": "currency-calculator", "content": {"items": [office]}},
        {"type": "tab", "content": {"code": "atm"}},
        {"type": "currency-rates", "content": {"items": [atm]}},
        {"type": "currency-calculator", "content": {"items": [atm]}},
        {"type": "tab", "content": {"code": "international"}},
        {"type": "currency-rates", "content": {"items": [transfer]}},
        {"type": "currency-calculator", "content": {"items": [transfer]}},
    ]}]}}


class ExchangeRateTests(unittest.TestCase):
    def test_parser_uses_all_three_rate_tabs_without_calculator_duplicates(self) -> None:
        context = parse_exchange_rates(rate_payload(), "en")

        self.assertEqual(len(context), 3)
        self.assertEqual([item["title"] for item in context], [
            "Live Agrobank rates — Exchange office",
            "Live Agrobank rates — ATM",
            "Live Agrobank rates — International money transfer",
        ])
        self.assertIn("USD: buy 11780 UZS; sell 11870 UZS", context[0]["text"])
        self.assertIn("EUR: buy 11000 UZS; sell not published", context[1]["text"])
        self.assertIn("2026-09-28T15:32:17+05:00", context[2]["text"])
        self.assertEqual(context[0]["page_url"], "https://agrobank.uz/en/person/exchange_rates")

    def test_fetch_requests_live_page_without_cache(self) -> None:
        response = MagicMock()
        response.json.return_value = rate_payload()
        with patch("app.tools.exchange_rates.httpx.get", return_value=response) as get:
            context = get_exchange_rate_context("ru")

        self.assertEqual(len(context), 3)
        self.assertEqual(get.call_args.kwargs["params"], {
            "action": "pages", "code": "uz/person/exchange_rates",
        })
        self.assertEqual(context[0]["page_url"], "https://agrobank.uz/ru/person/exchange_rates")

    def test_rate_question_uses_live_tool_instead_of_vector_search(self) -> None:
        llm = MagicMock()
        llm.analyze.return_value = ChatDecision(
            question_clear=True, in_scope=True, retrieve_information=False,
            tool="exchange_rates", language="en", follow_up_question="",
            search_query="", direct_answer="",
        )
        llm.answer.return_value = FinalAnswer(parts=[
            AnswerPart(kind="paragraph", text="At exchange offices, USD buy is 11780 UZS.",
                       source_ids=[1]),
        ])
        context = parse_exchange_rates(rate_payload(), "en")

        with (
            patch.object(routes, "LLMService", return_value=llm),
            patch.object(routes, "get_history", return_value=[]),
            patch.object(routes, "append_turn"),
            patch.object(routes, "get_exchange_rate_context", return_value=context) as live,
            patch.object(routes, "build_context") as vector,
        ):
            response = routes.chat(ChatRequest(question="What is today's USD exchange rate?"))

        live.assert_called_once_with("en")
        vector.assert_not_called()
        self.assertEqual(len(response.sources), 3)
        self.assertIn("https://agrobank.uz/en/person/exchange_rates", response.answer)

    def test_router_requires_no_vector_query_for_rates_only(self) -> None:
        decision = ChatDecision(
            question_clear=True, in_scope=True, retrieve_information=False,
            tool="exchange_rates", language="en", follow_up_question="",
            search_query="", direct_answer="",
        )
        LLMService._validate_decision(decision)

    def test_api_failure_does_not_fall_back_to_stale_rates(self) -> None:
        with self.assertRaises(RuntimeError):
            parse_exchange_rates({"success": False, "data": {}}, "en")


if __name__ == "__main__":
    unittest.main()
