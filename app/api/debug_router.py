from typing import List, Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas.schemas import RelevantResource
from app.service.context import build_context
from app.llm.llm import LLMService, ChatDecision


router = APIRouter()


@router.get("/relevants")
def get_relevant_resources(
    question: str = Query(..., min_length=2, max_length=200),
    language: Literal["uz", "ru", "en"] | None = None,
) -> List[RelevantResource]:
    try:
        context = build_context(
            question,
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


@router.get("/debug/analyze", response_model=ChatDecision)
def debug_analyze(
        question: str = Query(..., min_length=2, max_length=500),
) -> ChatDecision:
    llm = LLMService()

    return llm.analyze(question)
