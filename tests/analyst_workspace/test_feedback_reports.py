from __future__ import annotations

from dataclasses import dataclass

import pytest

from scripts import ingesta_server
from tools.analyst_runtime.session import AnalystSessionResult
from tools.analyst_workspace.conversation_service import ConversationService
from tools.analyst_workspace.store import ValidationError, WorkspaceStore


@dataclass
class _Session:
    def ask(self, text): return AnalystSessionResult(f"Respuesta: {text}")


class _Factory:
    def create(self, *args, **kwargs): return _Session()


def _login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def _wire(monkeypatch, store, service):
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_WORKSPACE_STORE_FACTORY", lambda: store)
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_CONVERSATION_SERVICE_FACTORY", lambda: service)
    ingesta_server.app.extensions.pop("analyst_conversation_service", None)


def _make_reported_turn(client, text="hola"):
    created = client.post("/api/analyst/conversations", json={"title": "Privado"})
    assert created.status_code == 201
    conversation_id = created.get_json()["id"]
    sent = client.post(f"/api/analyst/conversations/{conversation_id}/messages", json={"text": text})
    assert sent.status_code == 201
    return conversation_id, sent.get_json()["id"]


@pytest.fixture
def workspace(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.initialize()
    return store


@pytest.fixture
def clients(workspace, monkeypatch):
    a = workspace.create_user("alice", "Alice", "password-a")
    b = workspace.create_user("bob", "Bob", "password-b")
    reviewer_id = workspace.create_user("carol", "Carol Reviewer", "password-c")
    workspace.grant_capability(reviewer_id, "feedback_reviewer")
    service = ConversationService(workspace, _Factory())
    _wire(monkeypatch, workspace, service)
    client_a, client_b, client_r = (
        ingesta_server.app.test_client(), ingesta_server.app.test_client(), ingesta_server.app.test_client(),
    )
    _login(client_a, "alice", "password-a")
    _login(client_b, "bob", "password-b")
    _login(client_r, "carol", "password-c")
    return {"a": client_a, "b": client_b, "r": client_r, "a_id": a, "b_id": b, "r_id": reviewer_id}


# ── Submission ───────────────────────────────────────────────────────────────

def test_authenticated_user_can_report_own_conversation(clients, workspace):
    conversation_id, message_id = _make_reported_turn(clients["a"])
    resp = clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": message_id, "comment": "No comparó los activos.",
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["comment"] == "No comparó los activos."
    assert body["conversation_id"] == conversation_id
    assert body["anchor_message_id"] == message_id
    assert body["status"] == "new"


def test_snapshot_includes_full_visible_conversation_up_to_anchor_inclusive(clients, workspace):
    client = clients["a"]
    conversation_id, first_assistant_id = _make_reported_turn(client, "primera pregunta")
    second = client.post(f"/api/analyst/conversations/{conversation_id}/messages", json={"text": "segunda pregunta"})
    assert second.status_code == 201

    resp = client.post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": first_assistant_id, "comment": "problema",
    })
    assert resp.status_code == 201
    snapshot = resp.get_json()["conversation_snapshot"]
    # user1, assistant1 -- NOT user2/assistant2, which came after the anchor.
    assert [m["role"] for m in snapshot] == ["user", "assistant"]
    assert snapshot[0]["content"] == "primera pregunta"
    assert snapshot[-1]["message_id"] == first_assistant_id


def test_messages_after_anchor_are_not_retroactively_included(clients):
    client = clients["a"]
    conversation_id, first_assistant_id = _make_reported_turn(client, "uno")
    client.post(f"/api/analyst/conversations/{conversation_id}/messages", json={"text": "dos"})
    resp = client.post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": first_assistant_id, "comment": "x",
    })
    contents = [m["content"] for m in resp.get_json()["conversation_snapshot"]]
    assert "dos" not in contents


def test_continuing_conversation_after_reporting_does_not_mutate_snapshot(clients, workspace):
    client = clients["a"]
    conversation_id, anchor_id = _make_reported_turn(client, "primero")
    resp = client.post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
    })
    report_id = resp.get_json()["id"]
    original_snapshot = resp.get_json()["conversation_snapshot"]

    client.post(f"/api/analyst/conversations/{conversation_id}/messages", json={"text": "despues del reporte"})

    stored = workspace.get_feedback_report(report_id)
    assert stored.conversation_snapshot == original_snapshot
    assert not any(m["content"] == "despues del reporte" for m in stored.conversation_snapshot)


def test_archiving_conversation_does_not_destroy_report_snapshot(clients, workspace):
    client = clients["a"]
    conversation_id, anchor_id = _make_reported_turn(client)
    resp = client.post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
    })
    report_id = resp.get_json()["id"]

    archived = client.patch(f"/api/analyst/conversations/{conversation_id}", json={"archived": True})
    assert archived.status_code == 200

    stored = workspace.get_feedback_report(report_id)
    assert stored.conversation_snapshot
    assert stored.comment == "x"


def test_reporter_identity_comes_from_authenticated_state_not_client(clients):
    client = clients["a"]
    conversation_id, anchor_id = _make_reported_turn(client)
    resp = client.post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
        "reporter_user_id": clients["b_id"], "display_name": "Not Alice",
    })
    assert resp.status_code == 201
    assert resp.get_json()["reporter_user_id"] == clients["a_id"]
    assert resp.get_json()["reporter_display_name"] == "Alice"


def test_user_cannot_report_another_users_conversation(clients):
    conversation_id, anchor_id = _make_reported_turn(clients["a"])
    resp = clients["b"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "attack",
    })
    assert resp.status_code == 404


def test_user_cannot_anchor_to_message_from_another_conversation(clients):
    conversation_id_a, anchor_a = _make_reported_turn(clients["a"])
    conversation_id_b, _anchor_b = _make_reported_turn(clients["b"])
    # Alice owns conversation_id_a but tries to anchor to a message from conversation_id_b.
    resp = clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id_a, "anchor_message_id": _anchor_b, "comment": "x",
    })
    assert resp.status_code == 404


def test_unauthenticated_submit_returns_401():
    anon = ingesta_server.app.test_client()
    resp = anon.post("/api/analyst/feedback_reports", json={
        "conversation_id": "whatever", "anchor_message_id": "whatever", "comment": "x",
    })
    assert resp.status_code == 401


def test_hidden_reasoning_and_credentials_are_never_stored(clients, workspace):
    client = clients["a"]
    conversation_id, anchor_id = _make_reported_turn(client)
    resp = client.post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
    })
    stored = workspace.get_feedback_report(resp.get_json()["id"])
    for message in stored.conversation_snapshot:
        assert set(message.keys()) == {"message_id", "role", "content", "created_at"}
    if stored.technical_context:
        forbidden = {"system_prompt", "api_key", "session_token", "password", "cookie", "reasoning", "chain_of_thought"}
        assert not (forbidden & set(stored.technical_context.keys()))


# ── Review ───────────────────────────────────────────────────────────────────

def test_authorized_reviewer_can_list_reports(clients):
    conversation_id, anchor_id = _make_reported_turn(clients["a"])
    clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
    })
    resp = clients["r"].get("/api/analyst/feedback_reports")
    assert resp.status_code == 200
    assert len(resp.get_json()["reports"]) == 1


def test_authorized_reviewer_can_read_full_detail(clients):
    conversation_id, anchor_id = _make_reported_turn(clients["a"])
    created = clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "detalle",
    })
    report_id = created.get_json()["id"]
    resp = clients["r"].get(f"/api/analyst/feedback_reports/{report_id}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["comment"] == "detalle"
    assert body["conversation_snapshot"]


def test_normal_user_without_capability_cannot_list_reports(clients):
    resp = clients["b"].get("/api/analyst/feedback_reports")
    assert resp.status_code == 403


def test_normal_user_cannot_read_another_users_report(clients):
    conversation_id, anchor_id = _make_reported_turn(clients["a"])
    created = clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
    })
    report_id = created.get_json()["id"]
    resp = clients["b"].get(f"/api/analyst/feedback_reports/{report_id}")
    assert resp.status_code == 403


def test_reviewer_can_update_status(clients):
    conversation_id, anchor_id = _make_reported_turn(clients["a"])
    created = clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
    })
    report_id = created.get_json()["id"]
    resp = clients["r"].patch(f"/api/analyst/feedback_reports/{report_id}", json={"status": "reviewing"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "reviewing"


def test_invalid_status_fails_closed(clients):
    conversation_id, anchor_id = _make_reported_turn(clients["a"])
    created = clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
    })
    report_id = created.get_json()["id"]
    resp = clients["r"].patch(f"/api/analyst/feedback_reports/{report_id}", json={"status": "closed_forever"})
    assert resp.status_code == 400
    assert clients["r"].get(f"/api/analyst/feedback_reports/{report_id}").get_json()["status"] == "new"


def test_status_changes_do_not_mutate_transcript_snapshot(clients, workspace):
    conversation_id, anchor_id = _make_reported_turn(clients["a"])
    created = clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
    })
    report_id = created.get_json()["id"]
    before = workspace.get_feedback_report(report_id).conversation_snapshot
    clients["r"].patch(f"/api/analyst/feedback_reports/{report_id}", json={"status": "resolved"})
    after = workspace.get_feedback_report(report_id).conversation_snapshot
    assert before == after


def test_report_survives_new_store_instance_against_same_db(clients, workspace, tmp_path):
    conversation_id, anchor_id = _make_reported_turn(clients["a"])
    created = clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "sobrevive reinicio",
    })
    report_id = created.get_json()["id"]

    reopened = WorkspaceStore(workspace.db_path)
    reopened.initialize()
    stored = reopened.get_feedback_report(report_id)
    assert stored.comment == "sobrevive reinicio"


# ── Cross-user isolation ───────────────────────────────────────────────────

def test_reporter_b_report_is_invisible_to_and_unmutable_by_reporter_a(clients):
    conversation_id, anchor_id = _make_reported_turn(clients["b"])
    created = clients["b"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "de bob",
    })
    report_id = created.get_json()["id"]

    assert clients["a"].get(f"/api/analyst/feedback_reports/{report_id}").status_code == 403
    assert clients["a"].get("/api/analyst/feedback_reports").status_code == 403
    assert clients["a"].patch(f"/api/analyst/feedback_reports/{report_id}", json={"status": "dismissed"}).status_code == 403

    # The reviewer, unlike a random pilot user, can see and act on it.
    assert clients["r"].get(f"/api/analyst/feedback_reports/{report_id}").status_code == 200


# ── Capability grant/revoke ─────────────────────────────────────────────────

def test_grant_and_revoke_capability_round_trip(workspace):
    user_id = workspace.create_user("dave", "Dave", "password-d")
    assert workspace.user_has_capability(user_id, "feedback_reviewer") is False
    workspace.grant_capability(user_id, "feedback_reviewer")
    assert workspace.user_has_capability(user_id, "feedback_reviewer") is True
    workspace.revoke_capability(user_id, "feedback_reviewer")
    assert workspace.user_has_capability(user_id, "feedback_reviewer") is False


def test_capability_grant_does_not_change_role(workspace):
    user_id = workspace.create_user("erin", "Erin", "password-e")
    workspace.grant_capability(user_id, "feedback_reviewer")
    context = workspace.get_authenticated_user_context(user_id)
    assert context["role"] == "user"


def test_report_requires_nonblank_comment(clients):
    conversation_id, anchor_id = _make_reported_turn(clients["a"])
    resp = clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "   ",
    })
    assert resp.status_code == 400


def test_store_rejects_feedback_report_on_user_message(workspace):
    user_id = workspace.create_user("frank", "Frank", "password-f")
    conversation = workspace.create_conversation(owner_user_id=user_id)
    user_message = workspace.append_message(conversation.id, "user", "hola")
    with pytest.raises(ValidationError):
        workspace.create_feedback_report_for_user(user_id, conversation.id, user_message.id, "comentario")
