from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.schemas.schemas import ChatResponse, ChatRequest, Source
from app.db import SessionLocal, Resource
from app.service.context import build_context
from app.rag.llm import LLMService
from app.service.language import LanguageDetectionError, detect_language

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/resources")
def resources(limit: int = 50) -> list[dict]:
    session = SessionLocal()
    try:
        rows = session.scalars(
            select(Resource)
            .order_by(Resource.id.desc())
            .limit(min(limit, 500))
        ).all()

        return [
            {
                "id": row.id,
                "code": row.code,
                "language": row.language,
                "title": row.title,
                "page_url": row.page_url,
                "source_updated_at": row.source_updated_at,
                "is_active": row.is_active,
                "last_seen_at": row.last_seen_at,
                "last_processed_at": row.last_processed_at,
            }
            for row in rows
        ]
    finally:
        session.close()


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    try:
        # Language detection is optional.
        # If detection fails, continue with language=None.
        try:
            language = detect_language(body.question)
        except LanguageDetectionError:
            language = None

        context = build_context(
            body.question,
            language,
        )

        if not context:
            return ChatResponse(
                answer=(
                    "I could not find enough relevant information "
                    "in the current Agrobank website data."
                ),
                sources=[],
            )

        llm = LLMService()

        answer = llm.answer(
            body.question,
            context,
        )

        sources = [
            Source(
                title=context[0].get("title"),
                page_url=context[0]["page_url"],
                score=float(context[0]["score"]),
            )
        ]

        return ChatResponse(
            answer=answer,
            sources=sources,
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc