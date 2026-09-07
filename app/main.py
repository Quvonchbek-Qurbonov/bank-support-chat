from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal, Resource, init_db
from app.ingestion.sync_service import SyncService
from app.rag.embeddings import get_embedding_service
from app.rag.llm import LLMService
from app.rag.vector_store import get_vector_store


class ChatRequest(BaseModel):
    question: str = Field(min_length=2)
    language: str | None = None


class Source(BaseModel):
    title: str | None
    page_url: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Agrobank RAG Backend", version="0.1.0", lifespan=lifespan)


def build_context(question: str, language: str | None):
    settings = get_settings()
    embedder = get_embedding_service()
    vector_store = get_vector_store()

    query_vector = embedder.embed_query(question)
    hits = vector_store.search(query_vector, settings.top_k, language)
    return [hit for hit in hits if hit["score"] >= settings.min_retrieval_score]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sync")
def sync() -> dict[str, int]:
    service = SyncService()
    try:
        return service.sync()
    finally:
        service.close()


@app.get("/resources")
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


@app.post("/chat", response_model=ChatResponse)
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
