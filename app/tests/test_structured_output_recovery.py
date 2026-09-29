import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
from groq import BadRequestError

from app.llm.llm import LLMService, _complete_json


def provider_error(code: str) -> BadRequestError:
    body = {"error": {"code": code, "message": "Provider rejected generated JSON"}}
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        json=body,
    )
    return BadRequestError("Provider rejected generated JSON", response=response, body=body)


def completion(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(payload)), finish_reason="stop",
    )])


class StructuredOutputRecoveryTests(unittest.TestCase):
    def test_final_answer_recovers_from_provider_json_validation_error(self) -> None:
        service = LLMService.__new__(LLMService)
        service.final_client = MagicMock()
        service.final_model = "test-model"
        service.final_client.chat.completions.create.side_effect = [
            provider_error("json_validate_failed"),
            completion({"parts": [{
                "kind": "paragraph", "text": "The card costs 40,000 UZS.", "source_ids": [1],
            }]}),
        ]

        answer = service.answer(
            question="What does the card cost?",
            search_query="card cost",
            language="en",
            context=[{"title": "Card", "text": "Card fee: 40,000 UZS"}],
        )

        self.assertEqual(answer.parts[0].source_ids, [1])
        calls = service.final_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs["response_format"]["type"], "json_schema")
        self.assertEqual(calls[1].kwargs["response_format"], {"type": "json_object"})

    def test_router_also_recovers_from_provider_json_validation_error(self) -> None:
        service = LLMService.__new__(LLMService)
        service.router_client = MagicMock()
        service.router_model = "test-model"
        service.router_client.chat.completions.create.side_effect = [
            provider_error("json_validate_failed"),
            completion({
                "question_clear": True, "in_scope": True,
                "retrieve_information": False, "tool": "none", "language": "en",
                "follow_up_question": "", "search_query": "", "direct_answer": "Hello!",
            }),
        ]

        decision = service.analyze("Hello")

        self.assertEqual(decision.direct_answer, "Hello!")
        self.assertEqual(service.router_client.chat.completions.create.call_count, 2)

    def test_fallback_still_rejects_invalid_source_ids(self) -> None:
        service = LLMService.__new__(LLMService)
        service.final_client = MagicMock()
        service.final_model = "test-model"
        service.final_client.chat.completions.create.side_effect = [
            provider_error("json_validate_failed"),
            completion({"parts": [{
                "kind": "paragraph", "text": "Unsupported claim", "source_ids": [2],
            }]}),
        ]

        with self.assertRaisesRegex(RuntimeError, "outside the retrieved context"):
            service.answer(
                question="What does the card cost?",
                search_query="card cost",
                language="en",
                context=[{"title": "Card", "text": "Card fee: 40,000 UZS"}],
            )

    def test_unrelated_bad_request_is_not_retried(self) -> None:
        client = MagicMock()
        client.chat.completions.create.side_effect = provider_error("invalid_request_error")

        with self.assertRaises(BadRequestError):
            _complete_json(client, stage="test", schema={}, model="test-model", messages=[])

        client.chat.completions.create.assert_called_once()

    def test_repeated_provider_rejection_returns_safe_error(self) -> None:
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            provider_error("json_validate_failed"), provider_error("json_validate_failed"),
        ]

        with self.assertRaisesRegex(RuntimeError, "Please try again"):
            _complete_json(client, stage="test", schema={}, model="test-model", messages=[])

        self.assertEqual(client.chat.completions.create.call_count, 2)


if __name__ == "__main__":
    unittest.main()
