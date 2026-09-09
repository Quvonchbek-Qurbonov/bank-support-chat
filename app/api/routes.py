from fastapi import APIRouter, HTTPException

from app.api.schemas.schemas import ChatResponse, ChatRequest, Source
from app.db import SessionLocal, Resource
from sqlalchemy import select

from app.service.context import build_context
from app.rag.llm import LLMService

router = APIRouter()

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@router.get("/resources")
def resources(limit: int = 50) -> list[dict]:
    session = SessionLocal()
    try:
        rows = session.scalars(
            select(Resource).order_by(Resource.id.desc()).limit(min(limit, 500))
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
        context = build_context(body.question, body.language)
        if not context:
            return ChatResponse(
                answer="I could not find enough relevant information in the current Agrobank website data.",
                sources=[],
            )
        llm = LLMService()
        answer = llm.answer(body.question, context)
        sources = [
            Source(title=x.get("title"), page_url=x["page_url"], score=float(x["score"]))
            for x in context
        ]
        return ChatResponse(answer=answer, sources=sources)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
