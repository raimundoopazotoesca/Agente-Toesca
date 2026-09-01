"""A2 static/API boundary contract: canonical Analyst stays db_chat-free and
trace persistence failures surface as an explicit, safe 503."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts import ingesta_server
from tools.analyst_workspace.conversation_service import TurnTracePersistenceError


CANONICAL_RUNTIME_FILES = (
    "tools/analyst_runtime/session.py",
    "tools/analyst_runtime/analyst_loop.py",
    "tools/analyst_runtime/actions.py",
    "tools/analyst_workspace/conversation_service.py",
)


@pytest.mark.parametrize("path", CANONICAL_RUNTIME_FILES)
def test_canonical_runtime_does_not_import_db_chat(path: str):
    assert "db_chat" not in Path(path).read_text(encoding="utf-8")


@dataclass
class _FakeConversation:
    id: str = "conv-1"
    title: str = "Nueva conversación"
    created_at: str = "2026-08-19T12:00:00Z"
    updated_at: str = "2026-08-19T12:00:00Z"
    context: dict | None = None
    archived_at: str | None = None


class _FakeConversationService:
    def __init__(self):
        self.conversation = _FakeConversation()

    def create_conversation(self, *, title=None, context=None, user_id=None):
        return self.conversation

    def get_conversation_for_user(self, conversation_id, user_id):
        return self.conversation

    def send_message_for_user(self, conversation_id, user_id, text):
        raise TurnTracePersistenceError("unable to persist analyst turn trace")


@pytest.fixture
def client():
    original_factory = ingesta_server.app.config["ANALYST_CONVERSATION_SERVICE_FACTORY"]
    ingesta_server.app.config.update(
        TESTING=True,
        ANALYST_CONVERSATION_SERVICE_FACTORY=lambda: _FakeConversationService(),
    )
    with ingesta_server.app.test_client() as test_client:
        yield test_client
    ingesta_server.app.config["ANALYST_CONVERSATION_SERVICE_FACTORY"] = original_factory


def test_trace_persistence_failure_has_explicit_safe_api_error(client):
    headers = {"X-Analyst-Test-User-Id": "test-user"}
    response = client.post("/api/analyst/conversations/conv-1/messages", headers=headers, json={"text": "x"})
    assert (response.status_code, response.get_json()["error"]) == (503, "trace_persistence_failed")
