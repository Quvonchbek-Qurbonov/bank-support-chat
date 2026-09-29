from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from groq import BadRequestError, Groq
from pydantic import BaseModel, ValidationError

from app.api.schemas.schemas import AnswerPart
from app.core.config import settings
from app.service.llm_system_promts import FINAL_SYSTEM_PROMPT, ROUTER_SYSTEM_PROMPT


logger = logging.getLogger("agrobank.llm")


class ChatDecision(BaseModel):
    question_clear: bool
    in_scope: bool
    retrieve_information: bool
    tool: Literal["none", "exchange_rates"] = "none"
    language: Literal["uz", "ru", "en"]
    follow_up_question: str
    search_query: str
    direct_answer: str


CHAT_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "question_clear": {"type": "boolean"},
        "in_scope": {"type": "boolean"},
        "retrieve_information": {"type": "boolean"},
        "tool": {"type": "string", "enum": ["none", "exchange_rates"]},
        "language": {"type": "string", "enum": ["uz", "ru", "en"]},
        "follow_up_question": {"type": "string"},
        "search_query": {"type": "string"},
        "direct_answer": {"type": "string"},
    },
    "required": [
        "question_clear",
        "in_scope",
        "retrieve_information",
        "tool",
        "language",
        "follow_up_question",
        "search_query",
        "direct_answer",
    ],
    "additionalProperties": False,
}


class FinalAnswer(BaseModel):
    parts: list[AnswerPart]


FINAL_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["heading", "paragraph", "bullet", "step", "notice"],
                    },
                    "text": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["kind", "text", "source_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["parts"],
    "additionalProperties": False,
}


def _complete_json(client: Groq, *, stage: str, schema: dict, **options):
    """Retry one provider-side JSON validation failure with JSON Object Mode."""
    try:
        return client.chat.completions.create(
            **options,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": stage, "strict": True, "schema": schema},
            },
        )
    except BadRequestError as exc:
        body = exc.body if isinstance(exc.body, dict) else {}
        error = body.get("error", body)
        if not isinstance(error, dict) or error.get("code") != "json_validate_failed":
            raise

        logger.warning("llm.json_validation_failed stage=%s model=%s fallback=json_object", stage, options["model"])
        try:
            return client.chat.completions.create(
                **options,
                response_format={"type": "json_object"},
            )
        except BadRequestError as retry_exc:
            logger.warning(
                "llm.json_fallback_failed stage=%s model=%s",
                stage,
                options["model"],
            )
            raise RuntimeError(
                "The AI service could not produce a valid response. Please try again."
            ) from retry_exc


class LLMService:
    def __init__(self) -> None:

        self.router_client = Groq(
            api_key=settings.groq_router_api_key
        )

        self.final_client = Groq(
            api_key=settings.groq_final_api_key
        )

        self.router_model = settings.groq_router_model
        self.final_model = settings.groq_final_model

    def analyze(
        self,
        question: str,
        history: list[dict] | None = None,
    ) -> ChatDecision:
        started = time.monotonic()
        messages: list[dict] = [
            {
                "role": "system",
                "content": ROUTER_SYSTEM_PROMPT,
            }
        ]

        if history:
            messages.extend(history)

        messages.append(
            {
                "role": "user",
                "content": question,
            }
        )

        completion = _complete_json(
            self.router_client,
            stage="chat_decision",
            schema=CHAT_DECISION_SCHEMA,
            model=self.router_model,
            messages=messages,
            temperature=0,
            max_completion_tokens=2048,
            reasoning_effort="low",
            reasoning_format="hidden",
        )

        message = completion.choices[0].message
        content = (message.content or "").strip()

        if not content:
            raise RuntimeError(
                f"Router LLM returned an empty response. "
                f"finish_reason={completion.choices[0].finish_reason}"
            )

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Router LLM returned invalid JSON. Please try again."
            ) from exc

        try:
            decision = ChatDecision.model_validate(data)
        except ValidationError as exc:
            raise RuntimeError(
                "Router LLM returned an invalid decision. Please try again."
            ) from exc

        self._validate_decision(decision)

        logger.info(
            "llm.router_completed model=%s language=%s in_scope=%s clear=%s "
            "retrieval_needed=%s tool=%s duration_ms=%.1f",
            self.router_model,
            decision.language,
            decision.in_scope,
            decision.question_clear,
            decision.retrieve_information,
            decision.tool,
            (time.monotonic() - started) * 1000,
        )

        return decision

    @staticmethod
    def _validate_decision(decision: ChatDecision) -> None:
        if not decision.in_scope and decision.tool != "none":
            raise RuntimeError("An out-of-scope question cannot use a live tool.")

        if not decision.question_clear:
            if not decision.follow_up_question.strip():
                raise RuntimeError(
                    "Router returned an unclear question without "
                    "a follow-up question."
                )

            if decision.retrieve_information:
                raise RuntimeError(
                    "Invalid router decision: unclear question "
                    "cannot require retrieval."
                )

            if decision.tool != "none":
                raise RuntimeError("An unclear question cannot use a live tool.")

            return

        if decision.retrieve_information or decision.tool != "none":
            if decision.retrieve_information and not decision.search_query.strip():
                raise RuntimeError(
                    "Router requested retrieval without a search query."
                )
            if not decision.retrieve_information and decision.search_query.strip():
                raise RuntimeError("Router supplied a search query without vector retrieval.")

            if decision.follow_up_question.strip():
                raise RuntimeError(
                    "Router requested retrieval but also returned "
                    "a follow-up question."
                )

            if decision.direct_answer.strip():
                raise RuntimeError(
                    "Router requested retrieval but also returned "
                    "a direct answer."
                )

            return

        if not decision.direct_answer.strip():
            raise RuntimeError(
                "Router did not request retrieval and returned "
                "no direct answer."
            )

    def answer(
        self,
        question: str,
        search_query: str,
        language: Literal["uz", "ru", "en"],
        context: list[dict],
        history: list[dict] | None = None,
    ) -> FinalAnswer:
        started = time.monotonic()
        context_parts: list[str] = []

        for index, item in enumerate(context, start=1):
            context_parts.append(
                "\n".join(
                    [
                        f"Source {index}",
                        f"Title: {item.get('title') or ''}",
                        f"Content: {item.get('text') or ''}",
                    ]
                )
            )

        context_text = "\n\n".join(context_parts)

        user_content = (
            f"Today's date in Uzbekistan: "
            f"{datetime.now(ZoneInfo('Asia/Tashkent')).date().isoformat()}\n\n"
            f"Response language: {language}\n\n"
            f"Original user question:\n{question}\n\n"
            f"Search query used:\n{search_query}\n\n"
            f"Retrieved Agrobank information:\n"
            f"{context_text}"
        )

        messages: list[dict] = [
            {
                "role": "system",
                "content": FINAL_SYSTEM_PROMPT,
            }
        ]

        if history:
            messages.extend(history)

        messages.append(
            {
                "role": "user",
                "content": user_content,
            }
        )

        completion = _complete_json(
            self.final_client,
            stage="final_answer",
            schema=FINAL_ANSWER_SCHEMA,
            model=self.final_model,
            reasoning_effort="medium",
            messages=messages,
            temperature=0.2,
            max_completion_tokens=2048,
        )

        content = completion.choices[0].message.content

        if not content:
            raise RuntimeError(
                "Final LLM returned an empty response."
            )

        try:
            answer = FinalAnswer.model_validate_json(content)
        except ValidationError as exc:
            raise RuntimeError("Final LLM returned invalid answer JSON.") from exc

        def validate_parts(result: FinalAnswer) -> None:
            if not result.parts or not any(part.text.strip() for part in result.parts):
                raise RuntimeError("Final LLM returned no answer text.")

            for part in result.parts:
                part.text = part.text.strip()
                if not part.text:
                    raise RuntimeError("Final LLM returned an empty answer part.")

                if re.search(
                    r"\[[^\]]+\]\([^)]+\)|</?[a-z][^>]*>|&#(?:x[0-9a-f]+|\d+);|https?://",
                    part.text,
                    flags=re.IGNORECASE,
                ):
                    raise RuntimeError("Final LLM returned markup instead of plain text.")

                if any(source_id < 1 or source_id > len(context) for source_id in part.source_ids):
                    raise RuntimeError("Final LLM cited a source outside the retrieved context.")

                if len(part.source_ids) != len(set(part.source_ids)):
                    raise RuntimeError("Final LLM returned duplicate source IDs.")

                if part.kind == "heading" and part.source_ids:
                    part.source_ids = []

                if part.kind == "notice" and part.source_ids:
                    part.kind = "paragraph"

                if part.kind in {"paragraph", "bullet", "step"} and not part.source_ids:
                    raise RuntimeError("A factual answer part is missing its source.")

        validate_parts(answer)

        logger.info(
            "llm.answer_completed model=%s language=%s context_chunks=%d answer_parts=%d "
            "duration_ms=%.1f",
            self.final_model,
            language,
            len(context),
            len(answer.parts),
            (time.monotonic() - started) * 1000,
        )

        return answer
