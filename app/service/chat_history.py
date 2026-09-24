from __future__ import annotations

from sqlalchemy import select

from app.db import ChatMessage, SessionLocal

# Persistent, append-only. No TTL, no purge, no deletion anywhere in this
# module — every row written here stays in the database indefinitely.
# session_id has no auth behind it; it's just a grouping key the frontend
# mints fresh on every page reload, so a "new chat" is just a new
# session_id, not a wipe of the old one's rows.

MAX_TURNS_PER_SESSION = 6  # messages fed back into the LLM as history (3 exchanges)


def get_history(session_id: str) -> list[dict]:
    """Most recent MAX_TURNS_PER_SESSION messages for this session, oldest first."""
    session = SessionLocal()
    try:
        rows = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id,
                   ChatMessage.role == "user",)
            .order_by(ChatMessage.id.desc())
            .limit(MAX_TURNS_PER_SESSION)
        ).all()
    finally:
        session.close()

    rows.reverse()
    return [{"role": row.role, "content": row.content} for row in rows]


def append_turn(session_id: str, question: str, answer: str) -> None:
    session = SessionLocal()
    try:
        session.add_all(
            [
                ChatMessage(session_id=session_id, role="user", content=question),
                ChatMessage(session_id=session_id, role="assistant", content=answer),
            ]
        )
        session.commit()
    finally:
        session.close()