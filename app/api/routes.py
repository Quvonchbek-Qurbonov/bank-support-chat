import json
import logging
from collections.abc import Iterator
from typing import List, Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from groq import RateLimitError

from app.api.schemas.schemas import (
    AnswerPart, ChatResponse, ChatRequest, ChatSession, SavedMessage,
    SessionMessagesRequest, Source,
)
from app.service.context import build_context
from app.tools.exchange_rates import get_exchange_rate_context
from app.llm.llm import LLMService, ChatDecision

import uuid

from app.service.chat_history import (
    append_turn, delete_session_messages, get_history, get_session_messages,
    list_recent_sessions,
)

router = APIRouter()
logger = logging.getLogger("agrobank.chat")


def format_answer_with_links(parts: list[AnswerPart], sources: list[Source]) -> str:
    """Keep the legacy answer field readable and cited without exposing source IDs."""
    lines: list[str] = []
    step_number = 0
    previous_kind = ""

    for part in parts:
        if part.kind != "step":
            step_number = 0

        if part.kind == "heading":
            line = f"### {part.text}"
        elif part.kind == "bullet":
            line = f"- {part.text}"
        elif part.kind == "step":
            step_number += 1
            line = f"{step_number}. {part.text}"
        else:
            line = part.text

        link = ""
        for source_id in part.source_ids:
            if not 1 <= source_id <= len(sources):
                continue
            url = sources[source_id - 1].page_url
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname or (
                parsed.hostname != "agrobank.uz"
                and not parsed.hostname.endswith(".agrobank.uz")
            ):
                continue
            link = f"[↗]({url.replace('(', '%28').replace(')', '%29')})"
            break

        rendered_line = f"{line}\u2060{link}" if link else line
        if part.kind in {"bullet", "step"} and part.kind == previous_kind:
            lines[-1] += f"\n{rendered_line}"
        else:
            lines.append(rendered_line)
        previous_kind = part.kind

    return "\n\n".join(lines)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/chat/sessions", response_model=list[ChatSession])
def recent_chat_sessions() -> list[dict]:
    return list_recent_sessions()


@router.post("/chat/session", response_model=list[SavedMessage])
def saved_chat_messages(body: SessionMessagesRequest) -> list[dict]:
    return get_session_messages(str(body.session_id))


@router.delete("/chat/session", status_code=204)
def delete_chat_session(body: SessionMessagesRequest) -> None:
    if not delete_session_messages(str(body.session_id)):
        raise HTTPException(status_code=404, detail="Chat not found")


def _chat_events(body: ChatRequest) -> Iterator[dict]:
    """Yield real processing phases, then the completed chat response."""
    session_id = body.session_id or str(uuid.uuid4())
    yield {"type": "phase", "phase": "analyzing"}
    llm = LLMService()
    history = get_history(session_id)

    decision = llm.analyze(body.question, history=history)

    if not decision.in_scope or not decision.question_clear or (
        not decision.retrieve_information and decision.tool == "none"
    ):
        answer = (
            decision.follow_up_question if decision.in_scope and not decision.question_clear
            else decision.direct_answer
        )
        append_turn(session_id, body.question, answer)
        yield {"type": "result", "data": ChatResponse(
            answer=answer, sources=[], session_id=session_id,
        )}
        return

    context: list[dict] = []
    if decision.tool == "exchange_rates":
        yield {"type": "phase", "phase": "exchange_rates"}
        context.extend(get_exchange_rate_context(decision.language))
    if decision.retrieve_information:
        yield {"type": "phase", "phase": "retrieving"}
        context.extend(build_context(decision.search_query, decision.language))

    yield {"type": "phase", "phase": "generating"}
    final_answer = llm.answer(
        question=body.question,
        search_query=decision.search_query,
        language=decision.language,
        context=context,
        history=history,
    )
    history_answer = "\n".join(part.text for part in final_answer.parts)
    append_turn(session_id, body.question, history_answer)

    sources = [
        Source(
            title=item.get("title"),
            page_url=item["page_url"],
            score=float(item["score"]),
        )
        for item in context
    ]
    yield {"type": "result", "data": ChatResponse(
        answer=format_answer_with_links(final_answer.parts, sources),
        sources=sources,
        session_id=session_id,
        parts=final_answer.parts,
    )}


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    """Keep the existing JSON API for clients that do not need progress."""
    try:
        for event in _chat_events(body):
            if event["type"] == "result":
                return event["data"]
        raise RuntimeError("The chat completed without an answer.")
    except RateLimitError as exc:
        raise HTTPException(
            status_code=503,
            detail="The AI service is temporarily rate-limited. Please try again later.",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/chat/stream")
def chat_stream(body: ChatRequest) -> StreamingResponse:
    """Send newline-delimited progress events over the same POST request."""
    def events() -> Iterator[str]:
        try:
            for event in _chat_events(body):
                if event["type"] == "result":
                    event["data"] = event["data"].model_dump()
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except RateLimitError:
            yield json.dumps({
                "type": "error",
                "detail": "The AI service is temporarily rate-limited. Please try again later.",
            }) + "\n"
        except RuntimeError as exc:
            yield json.dumps({"type": "error", "detail": str(exc)}) + "\n"
        except Exception:
            logger.exception("chat.stream_failed")
            yield json.dumps({
                "type": "error",
                "detail": "The chat service could not complete this request. Please try again.",
            }) + "\n"

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
