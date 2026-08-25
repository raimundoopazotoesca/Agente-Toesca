"""Offline HTTP contract tests for the provisional analyst conversation API."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts import ingesta_server
from tools.analyst_workspace.store import ConversationNotFoundError, MessageNotFoundError


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

    def create_conversation(self, *, title=None, context=None, user_id=None):
        if self.raise_on_create:
            raise self.raise_on_create
        self.conversation = FakeConversation(title=title or "Nuevo chat", context=context)
        return self.conversation

    def list_conversations(self, *, include_archived=False):
        return [self.conversation]

    def get_conversation(self, conversation_id):
        if conversation_id != self.conversation.id:
            raise ConversationNotFoundError(conversation_id)
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

    def list_messages(self, conversation_id):
        self.get_conversation(conversation_id)
        return [
            FakeMessage(
                id="msg-user",
                conversation_id=conversation_id,
                role="user",
                content="¿Cuál es la vacancia de TRI en junio de 2026?",
                created_at="2026-08-19T12:00:00Z",
                metadata={"source": "factsheet"},
                reasoning=["private"],
                raw_provider_payload={"secret": "private"},
            ),
            self.message,
        ]

    def set_feedback(self, message_id, rating, note=None):
        if message_id != self.message.id:
            raise MessageNotFoundError(message_id)
        return FakeFeedback(rating=rating, note=note)

    # Ownership-aware production API used by the HTTP adapter.
    def list_conversations_for_user(self, user_id, include_archived=False): return self.list_conversations(include_archived=include_archived)
    def get_conversation_for_user(self, conversation_id, user_id): return self.get_conversation(conversation_id)
    def list_messages_for_user(self, conversation_id, user_id): return self.list_messages(conversation_id)
    def rename_conversation_for_user(self, conversation_id, user_id, title): return self.rename_conversation(conversation_id, title)
    def archive_conversation_for_user(self, conversation_id, user_id): return self.archive_conversation(conversation_id)
    def unarchive_conversation_for_user(self, conversation_id, user_id): return self.conversation
    def send_message_for_user(self, conversation_id, user_id, text): return self.send_message(conversation_id, text)
    def set_feedback_for_user(self, message_id, user_id, rating, note=None): return self.set_feedback(message_id, rating, note)


@pytest.fixture
def service():
    return FakeConversationService()


@pytest.fixture
def client(service):
    original_factory = ingesta_server.app.config["ANALYST_CONVERSATION_SERVICE_FACTORY"]
    ingesta_server.app.config.update(
        TESTING=True,
        ANALYST_CONVERSATION_SERVICE_FACTORY=lambda: service,
    )
    with ingesta_server.app.test_client() as test_client:
        yield test_client
    ingesta_server.app.config["ANALYST_CONVERSATION_SERVICE_FACTORY"] = original_factory


@pytest.fixture
def headers():
    return {"X-Analyst-Test-User-Id": "test-user"}


def test_analyst_api_requires_token(client):
    response = client.get("/api/analyst/conversations")
    assert response.status_code == 401


def test_analyst_api_rejects_invalid_token(client):
    response = client.get("/api/analyst/conversations", headers={"X-Ingesta-Token": "invalid"})
    assert response.status_code == 401


def test_get_messages_requires_token(client):
    response = client.get("/api/analyst/conversations/conv-1/messages")
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


def test_get_messages_returns_chronological_public_transcript(client, headers):
    response = client.get("/api/analyst/conversations/conv-1/messages", headers=headers)
    assert response.status_code == 200
    assert response.get_json() == {
        "messages": [
            {
                "id": "msg-user",
                "conversation_id": "conv-1",
                "role": "user",
                "content": "¿Cuál es la vacancia de TRI en junio de 2026?",
                "created_at": "2026-08-19T12:00:00Z",
                "metadata": {"source": "factsheet"},
            },
            {
                "id": "msg-1",
                "conversation_id": "conv-1",
                "role": "assistant",
                "content": "Respuesta",
                "created_at": "2026-08-19T12:01:00Z",
                "metadata": {"source": "test"},
            },
        ]
    }
    assert "private" not in response.get_data(as_text=True)


def test_get_messages_for_missing_conversation_is_404(client, headers):
    response = client.get("/api/analyst/conversations/missing/messages", headers=headers)
    assert response.status_code == 404
    assert response.get_json() == {"error": "not_found"}


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


def test_send_message_contract_requires_json_content_type(client, headers, service):
    body = '{"text":"¿Cuál es la vacancia de TRI en junio de 2026?"}'

    valid = client.post(
        "/api/analyst/conversations/conv-1/messages",
        headers={**headers, "Content-Type": "application/json"},
        data=body.encode("utf-8"),
    )
    assert valid.status_code == 201
    assert service.message.content == "¿Cuál es la vacancia de TRI en junio de 2026?"

    missing_content_type = client.post(
        "/api/analyst/conversations/conv-1/messages",
        headers=headers,
        data=body.encode("utf-8"),
    )
    assert missing_content_type.status_code == 400
    assert missing_content_type.get_json() == {
        "error": "validation_error",
        "details": [{
            "field": "body",
            "code": "invalid_json_object",
            "message": "JSON body must be an object",
        }],
    }


@pytest.mark.parametrize("text", [
    "¿Cuál es la vacancia de TRI en junio de 2026?",
    "¿Cómo evolucionó la ocupación en Viña Centro?",
    "¡Año ñandú: áéíóú!",
])
def test_send_message_preserves_utf8_json_exactly(client, headers, service, text):
    response = client.post("/api/analyst/conversations/conv-1/messages", headers=headers, json={"text": text})
    assert response.status_code == 201
    assert service.message.content == text
    assert response.get_json()["content"] == text


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
    response = client.post("/api/chat", headers={"X-Ingesta-Token": ingesta_server.API_TOKEN}, json={"question": "Pregunta", "history": []})
    assert response.status_code == 200
    assert response.get_json()["answer_md"] == "legacy"
    assert called["question"] == "Pregunta"


def test_importing_server_preserves_existing_workspace_state():
    workspace_db = Path("memory/analyst_workspace.db")
    before = workspace_db.read_bytes() if workspace_db.exists() else None
    code = """
import os
import sqlite3
from pathlib import Path
os.environ.pop('OPENAI_API_KEY', None)
def forbidden(*args, **kwargs):
    raise AssertionError('sqlite connection opened during module import')
sqlite3.connect = forbidden
import scripts.ingesta_server
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, env={key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"})
    assert result.returncode == 0, result.stderr
    after = workspace_db.read_bytes() if workspace_db.exists() else None
    assert after == before
