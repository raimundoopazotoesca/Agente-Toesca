"""Offline HTTP contract tests for the provisional analyst conversation API."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts import ingesta_server


@dataclass
class FakeConversation:
    id: str = "conv-1"
    title: str = "Nuevo chat"
    created_at: str = "2026-08-19T12:00:00Z"
    updated_at: str = "2026-08-19T12:00:00Z"
    context: dict | None = None
    archived_at: str | None = None
    internal_only: str = "must never be serialized"


@dataclass
class FakeMessage:
    id: str = "msg-1"
    conversation_id: str = "conv-1"
    role: str = "assistant"
    content: str = "Respuesta"
    created_at: str = "2026-08-19T12:01:00Z"
    metadata: dict | None = None
    reasoning: list[str] | None = None
    raw_provider_payload: dict | None = None


@dataclass
class FakeFeedback:
    rating: str
    note: str | None = None
    hidden_trace: str = "must never be serialized"


class FakeConversationService:
    """Test-only service double; production receives a factory via app config."""

    def __init__(self):
        self.conversation = FakeConversation()
        self.message = FakeMessage(
            metadata={"source": "test"},
            reasoning=["private"],
            raw_provider_payload={"secret": "private"},
        )
        self.raise_on_create: Exception | None = None
        self.raise_on_send: Exception | None = None

    def create_conversation(self, *, title=None, context=None):
        if self.raise_on_create:
            raise self.raise_on_create
        self.conversation = FakeConversation(title=title or "Nuevo chat", context=context)
        return self.conversation

    def list_conversations(self, *, include_archived=False):
        return [self.conversation]

    def get_conversation(self, conversation_id):
        if conversation_id != self.conversation.id:
            raise KeyError(conversation_id)
        return self.conversation

    def rename_conversation(self, conversation_id, title):
        self.get_conversation(conversation_id)
        self.conversation.title = title
        return self.conversation

    def archive_conversation(self, conversation_id):
        self.get_conversation(conversation_id)
        self.conversation.archived_at = "2026-08-19T12:02:00Z"
        return self.conversation

    def send_message(self, conversation_id, text):
        self.get_conversation(conversation_id)
        if self.raise_on_send:
            raise self.raise_on_send
        self.message = FakeMessage(
            conversation_id=conversation_id,
            content=text,
            metadata={"source": "test"},
            reasoning=["private"],
            raw_provider_payload={"secret": "private"},
        )
        return self.message

    def set_feedback(self, message_id, rating, note=None):
        if message_id != self.message.id:
            raise KeyError(message_id)
        return FakeFeedback(rating=rating, note=note)


@pytest.fixture
def service():
    return FakeConversationService()


@pytest.fixture
def client(service):
    ingesta_server.app.config.update(
        TESTING=True,
        ANALYST_CONVERSATION_SERVICE_FACTORY=lambda: service,
    )
    with ingesta_server.app.test_client() as test_client:
        yield test_client
    ingesta_server.app.config.pop("ANALYST_CONVERSATION_SERVICE_FACTORY", None)


@pytest.fixture
def headers():
    return {"X-Ingesta-Token": ingesta_server.API_TOKEN}


def test_analyst_api_requires_token(client):
    response = client.get("/api/analyst/conversations")
    assert response.status_code == 401


def test_analyst_api_rejects_invalid_token(client):
    response = client.get("/api/analyst/conversations", headers={"X-Ingesta-Token": "invalid"})
    assert response.status_code == 401


def test_create_conversation_returns_public_schema(client, headers):
    response = client.post("/api/analyst/conversations", headers=headers, json={"title": "Plan", "context": {"fondo": "PT"}})
    assert response.status_code == 201
    assert response.get_json() == {"id": "conv-1", "title": "Plan", "created_at": "2026-08-19T12:00:00Z", "updated_at": "2026-08-19T12:00:00Z", "context": {"fondo": "PT"}, "archived_at": None}


def test_list_conversations_returns_public_schema(client, headers):
    response = client.get("/api/analyst/conversations", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["conversations"] == [{"id": "conv-1", "title": "Nuevo chat", "created_at": "2026-08-19T12:00:00Z", "updated_at": "2026-08-19T12:00:00Z", "context": None, "archived_at": None}]


def test_get_conversation(client, headers):
    response = client.get("/api/analyst/conversations/conv-1", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["id"] == "conv-1"


def test_missing_conversation_is_404(client, headers):
    response = client.get("/api/analyst/conversations/missing", headers=headers)
    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


def test_patch_renames_conversation(client, headers):
    response = client.patch("/api/analyst/conversations/conv-1", headers=headers, json={"title": "Renombrado"})
    assert response.status_code == 200
    assert response.get_json()["title"] == "Renombrado"


def test_patch_archives_conversation(client, headers):
    response = client.patch("/api/analyst/conversations/conv-1", headers=headers, json={"archived": True})
    assert response.status_code == 200
    assert response.get_json()["archived_at"] == "2026-08-19T12:02:00Z"


def test_send_message_returns_public_schema(client, headers):
    response = client.post("/api/analyst/conversations/conv-1/messages", headers=headers, json={"text": "Hola"})
    assert response.status_code == 201
    assert response.get_json() == {"id": "msg-1", "conversation_id": "conv-1", "role": "assistant", "content": "Hola", "created_at": "2026-08-19T12:01:00Z", "metadata": {"source": "test"}}


def test_blank_message_is_400(client, headers):
    response = client.post("/api/analyst/conversations/conv-1/messages", headers=headers, json={"text": "  "})
    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_feedback_up(client, headers):
    response = client.post("/api/analyst/messages/msg-1/feedback", headers=headers, json={"rating": "up"})
    assert response.status_code == 200
    assert response.get_json() == {"rating": "up", "note": None}


def test_feedback_down_with_note(client, headers):
    response = client.post("/api/analyst/messages/msg-1/feedback", headers=headers, json={"rating": "down", "note": "No usó el período"})
    assert response.status_code == 200
    assert response.get_json() == {"rating": "down", "note": "No usó el período"}


def test_invalid_rating_is_400(client, headers):
    response = client.post("/api/analyst/messages/msg-1/feedback", headers=headers, json={"rating": "maybe"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_service_exception_maps_to_safe_503(client, headers, service):
    service.raise_on_send = RuntimeError("provider details must not leak")
    response = client.post("/api/analyst/conversations/conv-1/messages", headers=headers, json={"text": "Hola"})
    assert response.status_code == 503
    assert response.get_json() == {"error": "service_unavailable"}


def test_create_service_exception_maps_to_safe_503(client, headers, service):
    service.raise_on_create = RuntimeError("provider details must not leak")
    response = client.post("/api/analyst/conversations", headers=headers, json={})
    assert response.status_code == 503
    assert response.get_json() == {"error": "service_unavailable"}


def test_raw_reasoning_is_never_serialized(client, headers):
    response = client.post("/api/analyst/conversations/conv-1/messages", headers=headers, json={"text": "Hola"})
    body = response.get_json()
    assert "reasoning" not in body
    assert "raw_provider_payload" not in body
    assert "private" not in str(body)


def test_patch_is_advertised_by_cors_preflight(client):
    response = client.options("/api/analyst/conversations/conv-1", headers={"Origin": "http://127.0.0.1:8765"})
    assert response.status_code == 200
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]


def test_legacy_chat_remains_registered_and_uses_db_chat(client, headers, monkeypatch):
    called = {}

    def fake_answer(question, history, *, session_id):
        called.update(question=question, history=history, session_id=session_id)
        return {"answer_md": "legacy", "sql": None, "columns": [], "rows": []}

    monkeypatch.setattr(ingesta_server.db_chat, "answer", fake_answer)
    response = client.post("/api/chat", headers=headers, json={"question": "Pregunta", "history": []})
    assert response.status_code == 200
    assert response.get_json()["answer_md"] == "legacy"
    assert called["question"] == "Pregunta"


def test_importing_server_has_no_workspace_db_provider_or_knowledge_db_side_effect(tmp_path):
    workspace_db = Path("memory/analyst_workspace.db")
    assert not workspace_db.exists(), "the A5 worktree must start without a workspace DB"
    code = """
import os
import sqlite3
from pathlib import Path
os.environ.pop('OPENAI_API_KEY', None)
def forbidden(*args, **kwargs):
    raise AssertionError('sqlite connection opened during module import')
sqlite3.connect = forbidden
import scripts.ingesta_server
assert not Path('memory/analyst_workspace.db').exists()
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, env={key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"})
    assert result.returncode == 0, result.stderr
