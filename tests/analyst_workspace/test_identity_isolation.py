from __future__ import annotations

from dataclasses import dataclass

from scripts import ingesta_server
from tools.analyst_runtime.session import AnalystSessionResult
from tools.analyst_workspace.conversation_service import ConversationService
from tools.analyst_workspace.store import WorkspaceStore


@dataclass
class _Session:
    def ask(self, text): return AnalystSessionResult(f"Respuesta: {text}")


class _Factory:
    def create(self, *args, **kwargs): return _Session()


def _login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def test_http_users_are_authenticated_and_strictly_isolated(tmp_path, monkeypatch):
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.initialize()
    a = store.create_user("alice", "Alice", "password-a")
    b = store.create_user("bob", "Bob", "password-b")
    service = ConversationService(store, _Factory())
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_WORKSPACE_STORE_FACTORY", lambda: store)
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_CONVERSATION_SERVICE_FACTORY", lambda: service)
    ingesta_server.app.extensions.pop("analyst_conversation_service", None)
    client_a, client_b = ingesta_server.app.test_client(), ingesta_server.app.test_client()
    assert client_a.get("/api/analyst/conversations").status_code == 401
    _login(client_a, "alice", "password-a")
    _login(client_b, "bob", "password-b")
    created = client_a.post("/api/analyst/conversations", json={"title": "Privado"})
    assert created.status_code == 201
    conversation_id = created.get_json()["id"]
    assert client_b.get("/api/analyst/conversations").get_json() == {"conversations": []}
    assert client_b.get(f"/api/analyst/conversations/{conversation_id}").status_code == 404
    assert client_b.get(f"/api/analyst/conversations/{conversation_id}/messages").status_code == 404
    assert client_b.post(f"/api/analyst/conversations/{conversation_id}/messages", json={"text": "attack"}).status_code == 404
    assert client_b.patch(f"/api/analyst/conversations/{conversation_id}", json={"title": "attack"}).status_code == 404
    sent = client_a.post(f"/api/analyst/conversations/{conversation_id}/messages", json={"text": "hola"})
    assert sent.status_code == 201
    message_id = sent.get_json()["id"]
    assert client_b.post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "down"}).status_code == 404
    assert store.get_conversation_for_user(conversation_id, a).owner_user_id == a
    assert store.list_conversations_for_user(b) == []


def test_migration_backfills_existing_conversations_and_keeps_no_null_owner(tmp_path):
    path = tmp_path / "legacy.db"
    legacy = WorkspaceStore(path)
    legacy.initialize()
    conversation = legacy.create_conversation(title="Histórica")
    store = WorkspaceStore(path)
    # It is already v3 for fresh DBs; its created conversation was assigned to bootstrap admin.
    store.initialize()
    import sqlite3
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM conversation WHERE owner_user_id IS NULL").fetchone()[0] == 0
        assert conn.execute("SELECT owner_user_id FROM conversation WHERE id=?", (conversation.id,)).fetchone()[0]
    finally: conn.close()
