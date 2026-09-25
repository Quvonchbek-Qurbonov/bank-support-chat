from typing import List, Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.schemas.schemas import ChatResponse, ChatRequest, Source, ResourceRequest, RelevantResource
from app.service.context import build_context
from app.rag.llm import LLMService
from app.service.language import LanguageDetectionError, detect_language

import uuid

from app.service.chat_history import append_turn, get_history

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/relevants")
def get_relevant_resources(payload: Annotated[ResourceRequest, Query()]) -> List[RelevantResource]:
    try:
        try:
            language = detect_language(payload.question)
        except LanguageDetectionError:
            language = None

        context = build_context(
            payload.question,
            language,
        )

        return [
            RelevantResource(
                title=hit.get("title"),
                page_url=hit["page_url"],
                score=float(hit["score"]),
                content=hit["text"],
            )
            for hit in context
        ]

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    session_id = body.session_id or str(uuid.uuid4())

    try:
        try:
            language = detect_language(body.question)
        except LanguageDetectionError:
            language = None

        context = build_context(
            body.question,
            language,
        )

        llm = LLMService()

        history = get_history(session_id)

        answer = llm.answer(
            body.question,
            context,
            history=history,
        )

        append_turn(session_id, body.question, answer)

        sources = (
            [
                Source(
                    title=context[0].get("title"),
                    page_url=context[0]["page_url"],
                    score=float(context[0]["score"]),
                )
            ]
            if context
            else []
        )

        return ChatResponse(
            answer=answer,
            sources=sources,
            session_id=session_id,
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc