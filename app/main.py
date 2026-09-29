from __future__ import annotations
from contextlib import asynccontextmanager
import logging
import time
import uuid

from app.encoder.embeddings import get_embedding_service
from fastapi import FastAPI, Request
from app.db import init_db
from app.api.routes import router as main_router
from app.api.debug_router import router as debug_router
from app.core.logging import bind_request_id, configure_logging, reset_request_id
from app.encoder.reranker import get_reranker
from app.vector_db.vector_store import get_vector_store

logger = logging.getLogger("agrobank.api")

@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    logger.info("api.starting")
    init_db()
    get_embedding_service()
    get_reranker()
    get_vector_store()
    logger.info("api.ready")
    yield
    logger.info("api.stopping")

app = FastAPI(title="Agrobank RAG Backend", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def log_request(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    token = bind_request_id(request_id)
    started = time.monotonic()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        level = logging.DEBUG if request.url.path == "/health" else logging.INFO
        logger.log(
            level,
            "http.completed method=%s path=%r status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response
    except Exception as exc:
        logger.error(
            "http.failed method=%s path=%r error_type=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            type(exc).__name__,
            (time.monotonic() - started) * 1000,
        )
        raise
    finally:
        reset_request_id(token)


app.include_router(main_router)
app.include_router(debug_router)
