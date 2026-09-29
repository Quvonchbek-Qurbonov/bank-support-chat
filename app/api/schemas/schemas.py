from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=2)
    session_id: str | None = Field(default=None, max_length=200)


class Source(BaseModel):
    title: str | None
    page_url: str
    score: float


class ResourceRequest(BaseModel):
    question: str = Field(min_length=2, max_length=200)

class RelevantResource(BaseModel):
    title: str | None
    page_url: str
    score: float
    content: str| Any


from typing import Literal

class AnswerPart(BaseModel):
    kind: Literal["heading", "paragraph", "bullet", "step", "notice"]
    text: str
    source_ids: list[int]

class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    session_id: str
    parts: list[AnswerPart] | None = None


class SessionMessagesRequest(BaseModel):
    session_id: UUID


class ChatSession(BaseModel):
    session_id: str
    title: str


class SavedMessage(BaseModel):
    role: str
    content: str
