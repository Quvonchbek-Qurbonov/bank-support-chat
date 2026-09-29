import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import ChatMessage
from app.main import app
from app.service import chat_history


class ChatHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        ChatMessage.__table__.create(engine)
        self.addCleanup(engine.dispose)
        patcher = patch.object(chat_history, "SessionLocal", sessionmaker(bind=engine))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_recent_sessions_are_unique_and_ordered_by_last_message(self) -> None:
        ids = [str(uuid4()) for _ in range(10)]
        for index, session_id in enumerate(ids):
            chat_history.append_turn(session_id, f"Question {index}", f"Answer {index}")
        chat_history.append_turn(ids[0], "Later question", "Later answer")

        sessions = chat_history.list_recent_sessions()

        self.assertEqual(len(sessions), 8)
        self.assertEqual(sessions[0], {"session_id": ids[0], "title": "Question 0"})
        self.assertNotIn(ids[1], [item["session_id"] for item in sessions])

    def test_recent_sessions_are_visible_without_browser_session_ids(self) -> None:
        session_id = str(uuid4())
        chat_history.append_turn(session_id, "Existing database chat", "Saved reply")
        client = TestClient(app)

        self.assertEqual(
            client.get("/chat/sessions").json(),
            [{"session_id": session_id, "title": "Existing database chat"}],
        )

    def test_session_messages_include_entire_conversation_in_order(self) -> None:
        session_id = str(uuid4())
        chat_history.append_turn(session_id, "First", "Reply")
        chat_history.append_turn(session_id, "Second", "Another reply")

        self.assertEqual(chat_history.get_session_messages(session_id), [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Reply"},
            {"role": "user", "content": "Second"},
            {"role": "assistant", "content": "Another reply"},
        ])

    def test_api_accepts_uuid_session_ids_and_rejects_invalid_ones(self) -> None:
        session_id = str(uuid4())
        client = TestClient(app)
        chat_history.append_turn(session_id, "Card fees?", "See the tariff page.")
        response = client.get("/chat/sessions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"session_id": session_id, "title": "Card fees?"}])
        self.assertEqual(
            client.post("/chat/session", json={"session_id": session_id}).json(),
            [
                {"role": "user", "content": "Card fees?"},
                {"role": "assistant", "content": "See the tariff page."},
            ],
        )
        self.assertEqual(
            client.post("/chat/session", json={"session_id": "not-a-uuid"}).status_code,
            422,
        )

    def test_delete_session_removes_only_the_selected_chat(self) -> None:
        deleted_id = str(uuid4())
        retained_id = str(uuid4())
        chat_history.append_turn(deleted_id, "Delete me", "Old answer")
        chat_history.append_turn(retained_id, "Keep me", "Saved answer")
        client = TestClient(app)

        response = client.request("DELETE", "/chat/session", json={"session_id": deleted_id})

        self.assertEqual(response.status_code, 204)
        self.assertEqual(chat_history.get_session_messages(deleted_id), [])
        self.assertEqual(len(chat_history.get_session_messages(retained_id)), 2)
        self.assertEqual(
            client.request("DELETE", "/chat/session", json={"session_id": deleted_id}).status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
