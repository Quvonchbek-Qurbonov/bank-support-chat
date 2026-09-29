from __future__ import annotations

from sqlalchemy import delete, func, select

from app.db import ChatMessage, SessionLocal


MAX_TURNS_PER_SESSION = 6


def get_history(session_id: str) -> list[dict]:
    """Most recent MAX_TURNS_PER_SESSION messages for this session, oldest first."""
    session = SessionLocal()
    try:
        rows = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
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


def list_recent_sessions(limit: int = 8) -> list[dict]:
    """List the most recently active sessions in the database."""
    session = SessionLocal()
    try:
        recent = session.execute(
            select(ChatMessage.session_id, func.max(ChatMessage.id).label("last_id"))
            .group_by(ChatMessage.session_id)
            .order_by(func.max(ChatMessage.id).desc())
            .limit(limit)
        ).all()
        if not recent:
            return []

        selected_ids = [row.session_id for row in recent]
        first_user_ids = (
            select(func.min(ChatMessage.id))
            .where(ChatMessage.session_id.in_(selected_ids), ChatMessage.role == "user")
            .group_by(ChatMessage.session_id)
        )
        titles = {
            row.session_id: row.content
            for row in session.scalars(
                select(ChatMessage).where(ChatMessage.id.in_(first_user_ids))
            )
        }
        return [
            {"session_id": row.session_id, "title": titles.get(row.session_id, "Chat")}
            for row in recent
        ]
    finally:
        session.close()


def get_session_messages(session_id: str) -> list[dict]:
    """Return the full saved conversation for display, oldest first."""
    session = SessionLocal()
    try:
        rows = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id)
        ).all()
        return [{"role": row.role, "content": row.content} for row in rows]
    finally:
        session.close()


def delete_session_messages(session_id: str) -> bool:
    """Permanently remove one conversation, returning whether it existed."""
    session = SessionLocal()
    try:
        result = session.execute(
            delete(ChatMessage).where(ChatMessage.session_id == session_id)
        )
        session.commit()
        return bool(result.rowcount)
    finally:
        session.close()
