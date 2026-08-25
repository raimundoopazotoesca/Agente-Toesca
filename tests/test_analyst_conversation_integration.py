from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from scripts import ingesta_server
from tools.analyst_runtime.session import AnalystSessionResult
from tools.analyst_workspace.conversation_service import ConversationService
from tools.analyst_workspace.store import WorkspaceStore


@dataclass
class FakeSession:
    responses: list[AnalystSessionResult | Exception]

    def ask(self, text: str) -> AnalystSessionResult:
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@dataclass
class FakeFactory:
    responses: list[AnalystSessionResult | Exception]
    histories: list[list] = field(default_factory=list)

    def create(self, conversation, visible_messages, runtime_context=None):
        self.histories.append(list(visible_messages))
        return FakeSession(list(self.responses))


@pytest.fixture
def service(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.initialize()
    ingesta_server.app.config["ANALYST_TEST_USER_ID"] = store.create_user("test", "Test", "test-password")
    factory = FakeFactory([AnalystSessionResult("Respuesta"), AnalystSessionResult("Segunda")])
    return ConversationService(store, factory)


@pytest.fixture
def client(monkeypatch, service):
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_CONVERSATION_SERVICE_FACTORY", lambda: service)
    with ingesta_server.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def headers():
    return {"X-Analyst-Test-User-Id": "test-user"}


def test_http_uses_real_service_and_persists_visible_transcript(client, headers, service):
    created = client.post("/api/analyst/conversations", headers=headers, json={"context": {"fund": "PT"}})
    conversation_id = created.get_json()["id"]
    sent = client.post(f"/api/analyst/conversations/{conversation_id}/messages", headers=headers, json={"text": "Pregunta"})
    assert created.status_code == 201
    assert sent.status_code == 201
    assert sent.get_json()["content"] == "Respuesta"
    assert [(item.role, item.content) for item in service.list_messages(conversation_id)] == [
        ("user", "Pregunta"), ("assistant", "Respuesta")
    ]
    transcript = client.get(f"/api/analyst/conversations/{conversation_id}/messages", headers=headers)
    assert transcript.status_code == 200
    assert [(item["role"], item["content"]) for item in transcript.get_json()["messages"]] == [
        ("user", "Pregunta"), ("assistant", "Respuesta")
    ]
    assert "reasoning" not in str(transcript.get_json())


def test_http_real_store_supports_get_list_rename_archive_and_feedback(client, headers, service):
    conversation_id = client.post("/api/analyst/conversations", headers=headers, json={}).get_json()["id"]
    assert client.get(f"/api/analyst/conversations/{conversation_id}", headers=headers).status_code == 200
    assert client.get("/api/analyst/conversations", headers=headers).get_json()["conversations"][0]["id"] == conversation_id
    assert client.patch(f"/api/analyst/conversations/{conversation_id}", headers=headers, json={"title": "Renombrado"}).get_json()["title"] == "Renombrado"
    assistant = client.post(f"/api/analyst/conversations/{conversation_id}/messages", headers=headers, json={"text": "Pregunta"}).get_json()
    assert client.post(f"/api/analyst/messages/{assistant['id']}/feedback", headers=headers, json={"rating": "up"}).get_json() == {"rating": "up", "note": None}
    assert client.patch(f"/api/analyst/conversations/{conversation_id}", headers=headers, json={"archived": True}).get_json()["archived_at"]


def test_http_maps_real_workspace_errors_to_404_and_400(client, headers):
    assert client.get("/api/analyst/conversations/missing", headers=headers).status_code == 404
    assert client.post("/api/analyst/messages/missing/feedback", headers=headers, json={"rating": "up"}).status_code == 404
    assert client.post("/api/analyst/messages/missing/feedback", headers=headers, json={"rating": "bad"}).status_code == 400


def test_http_runtime_failure_is_safe_503_and_keeps_only_user_message(client, headers, service):
    service.session_factory = FakeFactory([RuntimeError("private provider failure")])
    conversation_id = client.post("/api/analyst/conversations", headers=headers, json={}).get_json()["id"]
    response = client.post(f"/api/analyst/conversations/{conversation_id}/messages", headers=headers, json={"text": "Pregunta"})
    assert response.status_code == 503
    assert response.get_json() == {"error": "service_unavailable"}
    assert [(item.role, item.content) for item in service.list_messages(conversation_id)] == [("user", "Pregunta")]


def test_restart_recreates_service_from_visible_history_without_raw_reasoning(client, headers, service):
    conversation_id = client.post("/api/analyst/conversations", headers=headers, json={}).get_json()["id"]
    client.post(f"/api/analyst/conversations/{conversation_id}/messages", headers=headers, json={"text": "Primera"})
    restarted_factory = FakeFactory([AnalystSessionResult("Luego")])
    restarted = ConversationService(service.store, restarted_factory)
    ingesta_server.app.config["ANALYST_CONVERSATION_SERVICE_FACTORY"] = lambda: restarted
    response = client.post(f"/api/analyst/conversations/{conversation_id}/messages", headers=headers, json={"text": "Segunda"})
    assert response.status_code == 201
    assert [(item.role, item.content) for item in restarted_factory.histories[0]] == [
        ("user", "Primera"), ("assistant", "Respuesta")
    ]
    assert "raw_reasoning" not in str(response.get_json())


def test_default_lazy_factory_reuses_one_service_instance(monkeypatch):
    import tools.analyst_runtime.session as runtime_session
    import tools.analyst_workspace.conversation_service as conversation_service
    import tools.analyst_workspace.store as workspace_store

    created = []

    class FakeStore:
        def __init__(self, path):
            self.path = path
            self.initialized = False

        def initialize(self):
            self.initialized = True

    class FakeSessionFactory:
        def __init__(self, path):
            self.path = path

    class FakeService:
        def __init__(self, store, factory):
            created.append((store, factory))

    monkeypatch.setattr(workspace_store, "WorkspaceStore", FakeStore)
    monkeypatch.setattr(runtime_session, "OpenAIResponsesAnalystSessionFactory", FakeSessionFactory)
    monkeypatch.setattr(conversation_service, "ConversationService", FakeService)
    ingesta_server.app.extensions.pop("analyst_conversation_service", None)
    try:
        first = ingesta_server._create_analyst_conversation_service()
        second = ingesta_server._create_analyst_conversation_service()
        assert first is second
        assert len(created) == 1
        assert created[0][0].initialized is True
    finally:
        ingesta_server.app.extensions.pop("analyst_conversation_service", None)
