from typing import List, Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas.schemas import ResourceRequest, RelevantResource
from app.service.context import build_context
from app.rag.llm import LLMService, ChatDecision
from app.service.language import LanguageDetectionError, detect_language


router = APIRouter()


@router.get("/relevants")
def get_relevant_resources(payload: Annotated[ResourceRequest, Query()]) -> List[RelevantResource]:
    try:
        try:
            language = detect_language(payload.question)
        except LanguageDetectionError:
            language = None
        print(f"<<<<<<<<<<<<<<<<<{language}>>>>>>>>>>>>>>>>>>>>>>>>>>")
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


@router.get("/debug/analyze", response_model=ChatDecision)
def debug_analyze(
        question: str = Query(..., min_length=2, max_length=500),
) -> ChatDecision:
    llm = LLMService()

    return llm.analyze(question)