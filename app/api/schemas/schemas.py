from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=2)
    session_id: str | None = Field(default=None, max_length=200)


class Source(BaseModel):
    title: str | None
    page_url: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    session_id: str


class ResourceRequest(BaseModel):
    question: str = Field(min_length=2, max_length=200)

class RelevantResource(BaseModel):
    title: str | None
    page_url: str
    score: float
    content: str| Any