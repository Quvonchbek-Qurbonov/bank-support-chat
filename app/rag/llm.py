from __future__ import annotations

import json

from groq import Groq
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.service.llm_system_promts import FINAL_SYSTEM_PROMPT, ROUTER_SYSTEM_PROMPT


class ChatDecision(BaseModel):
    question_clear: bool
    in_scope: bool
    retrieve_information: bool
    follow_up_question: str
    search_query: str
    direct_answer: str


CHAT_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "question_clear": {"type": "boolean"},
        "in_scope": {"type": "boolean"},
        "retrieve_information": {"type": "boolean"},
        "follow_up_question": {"type": "string"},
        "search_query": {"type": "string"},
        "direct_answer": {"type": "string"},
    },
    "required": [
        "question_clear",
        "in_scope",
        "retrieve_information",
        "follow_up_question",
        "search_query",
        "direct_answer",
    ],
    "additionalProperties": False,
}


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

        completion = self.router_client.chat.completions.create(
            model=self.router_model,
            messages=messages,
            temperature=0,
            max_completion_tokens=2048,
            reasoning_effort="low",
            reasoning_format="hidden",
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "chat_decision",
                    "strict": True,
                    "schema": CHAT_DECISION_SCHEMA,
                },
            },
        )

        message = completion.choices[0].message
        content = (message.content or "").strip()

        if not content:
            raise RuntimeError(
                f"Final LLM returned an empty response. "
                f"finish_reason={completion.choices[0].finish_reason}"
            )

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Router LLM returned invalid JSON: {content}"
            ) from exc

        try:
            decision = ChatDecision.model_validate(data)
        except ValidationError as exc:
            raise RuntimeError(
                f"Router LLM returned an invalid decision: {content}"
            ) from exc

        self._validate_decision(decision)

        return decision

    @staticmethod
    def _validate_decision(decision: ChatDecision) -> None:
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

            return

        if decision.retrieve_information:
            if not decision.search_query.strip():
                raise RuntimeError(
                    "Router requested retrieval without a search query."
                )

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
        context: list[dict],
        history: list[dict] | None = None,
    ) -> str:
        context_parts: list[str] = []

        for index, item in enumerate(context, start=1):
            context_parts.append(
                "\n".join(
                    [
                        f"Source {index}",
                        f"Title: {item.get('title') or ''}",
                        f"URL: {item.get('page_url') or ''}",
                        f"Content: {item.get('text') or ''}",
                    ]
                )
            )

        context_text = "\n\n".join(context_parts)

        user_content = (
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

        completion = self.final_client.chat.completions.create(
            model=self.final_model,
            reasoning_effort="medium",
            messages=messages,
            temperature=0.2,
            max_completion_tokens=2048,
        )

        answer = completion.choices[0].message.content

        if not answer:
            raise RuntimeError(
                "Final LLM returned an empty response."
            )

        return answer.strip()