from __future__ import annotations
from contextlib import asynccontextmanager
import logging

from app.rag.embeddings import get_embedding_service
from fastapi import FastAPI
from app.db import init_db
from app.api.routes import router
from app.rag.vector_store import get_vector_store

logger = logging.getLogger("agrobank.api")

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    get_embedding_service()
    get_vector_store()


    yield

app = FastAPI(title="Agrobank RAG Backend", version="0.1.0", lifespan=lifespan)


app.include_router(router)