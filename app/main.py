from __future__ import annotations
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.db import init_db

from app.api.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield

app = FastAPI(title="Agrobank RAG Backend", version="0.1.0", lifespan=lifespan)


app.include_router(router)