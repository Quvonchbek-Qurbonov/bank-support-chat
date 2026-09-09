from pydantic import BaseModel, Field


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