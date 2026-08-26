"""Route-level authorization/isolation tests for the Pilot Control Center (v1).

Mirrors the fixture pattern used by tests/analyst_workspace/test_feedback_reports.py:
a real Flask test client against a real temp-file WorkspaceStore, wired in via
ANALYST_WORKSPACE_STORE_FACTORY / ANALYST_CONVERSATION_SERVICE_FACTORY.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

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


def _wire(monkeypatch, store, service):
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_WORKSPACE_STORE_FACTORY", lambda: store)
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_CONVERSATION_SERVICE_FACTORY", lambda: service)
    ingesta_server.app.extensions.pop("analyst_conversation_service", None)


def _send_turn(client, text="hola"):
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
    a = workspace.create_user("alice", "Alice Ann", "password-a")
    b = workspace.create_user("bob", "Bob Ben", "password-b")
    observer_id = workspace.create_user("olivia", "Olivia Observer", "password-o")
    workspace.grant_capability(observer_id, "pilot_observer")
    service = ConversationService(workspace, _Factory())
    _wire(monkeypatch, workspace, service)
    client_a, client_b, client_o = (
        ingesta_server.app.test_client(), ingesta_server.app.test_client(), ingesta_server.app.test_client(),
    )
    _login(client_a, "alice", "password-a")
    _login(client_b, "bob", "password-b")
    _login(client_o, "olivia", "password-o")
    return {"a": client_a, "b": client_b, "o": client_o, "a_id": a, "b_id": b, "o_id": observer_id, "workspace": workspace}


PILOT_CONTROL_ROUTES = [
    "/api/analyst/pilot_control/overview",
    "/api/analyst/pilot_control/users",
    "/api/analyst/pilot_control/conversations",
    "/api/analyst/pilot_control/questions",
]


# ── 1. Unauthenticated ───────────────────────────────────────────────────────

def test_unauthenticated_requests_are_rejected():
    anon = ingesta_server.app.test_client()
    for route in PILOT_CONTROL_ROUTES:
        resp = anon.get(route)
        assert resp.status_code == 401, route
    assert anon.get("/pilot-control").status_code in (302, 401)


# ── 2. role=user without pilot_observer -> 403 ──────────────────────────────

def test_normal_user_without_capability_gets_403_on_every_route(clients):
    for route in PILOT_CONTROL_ROUTES:
        resp = clients["a"].get(route)
        assert resp.status_code == 403, route


def test_normal_user_without_capability_gets_403_on_html_page(clients):
    resp = clients["a"].get("/pilot-control")
    assert resp.status_code == 403


# ── 3. pilot_observer can access overview ───────────────────────────────────

def test_observer_can_access_overview(clients):
    resp = clients["o"].get("/api/analyst/pilot_control/overview")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "total_users" in body and "latency_ms" in body


def test_observer_can_access_html_page(clients):
    resp = clients["o"].get("/pilot-control")
    assert resp.status_code == 200
    assert b"Pilot Control Center" in resp.data


# ── 4. pilot_observer can inspect conversations across users ───────────────

def test_observer_can_inspect_conversations_across_users(clients):
    conv_a, _ = _send_turn(clients["a"], "pregunta de alice")
    conv_b, _ = _send_turn(clients["b"], "pregunta de bob")

    resp = clients["o"].get("/api/analyst/pilot_control/conversations")
    assert resp.status_code == 200
    ids = {c["id"] for c in resp.get_json()["conversations"]}
    assert {conv_a, conv_b} <= ids

    detail_a = clients["o"].get(f"/api/analyst/pilot_control/conversations/{conv_a}")
    assert detail_a.status_code == 200
    assert detail_a.get_json()["owner_username"] == "alice"

    detail_b = clients["o"].get(f"/api/analyst/pilot_control/conversations/{conv_b}")
    assert detail_b.status_code == 200
    assert detail_b.get_json()["owner_username"] == "bob"

    users_resp = clients["o"].get(f"/api/analyst/pilot_control/users/{clients['b_id']}")
    assert users_resp.status_code == 200
    assert users_resp.get_json()["username"] == "bob"


# ── 5. Normal conversation APIs remain owner-scoped (regression) ───────────

def test_owner_scoped_conversation_apis_unchanged_for_normal_users(clients):
    conv_a, _ = _send_turn(clients["a"], "privado de alice")
    # Bob cannot see or read Alice's conversation through the normal (non-observer) API.
    assert clients["b"].get(f"/api/analyst/conversations/{conv_a}").status_code == 404
    assert clients["b"].get(f"/api/analyst/conversations/{conv_a}/messages").status_code == 404
    listing = clients["b"].get("/api/analyst/conversations").get_json()
    assert conv_a not in {c["id"] for c in listing["conversations"]}
    # And Alice's own listing only contains her conversation.
    own_listing = clients["a"].get("/api/analyst/conversations").get_json()
    assert {c["id"] for c in own_listing["conversations"]} == {conv_a}


def test_observer_without_normal_ownership_still_owner_scoped_on_normal_routes(clients):
    conv_a, _ = _send_turn(clients["a"], "privado de alice")
    # Olivia has pilot_observer but does not own conv_a -- the *normal* (non-observer)
    # conversation route must still 404 for her, proving the observer capability does
    # not become a blanket bypass of ownership on /api/analyst/conversations/*.
    assert clients["o"].get(f"/api/analyst/conversations/{conv_a}").status_code == 404


# ── 6. Observer capability cannot post as another user ──────────────────────

def test_observer_cannot_post_a_message_as_another_user(clients):
    conv_a, _ = _send_turn(clients["a"], "primero")
    # Olivia does not own conv_a, so even authenticated+observer, posting into it 404s
    # (the normal route scopes by request.analyst_user, which is Olivia's own id).
    resp = clients["o"].post(f"/api/analyst/conversations/{conv_a}/messages", json={"text": "intrusion"})
    assert resp.status_code == 404


# ── 7. Cannot edit/delete another user's messages ───────────────────────────

def test_observer_cannot_rename_or_archive_another_users_conversation(clients):
    conv_a, _ = _send_turn(clients["a"], "primero")
    assert clients["o"].patch(f"/api/analyst/conversations/{conv_a}", json={"title": "hijacked"}).status_code == 404
    assert clients["o"].patch(f"/api/analyst/conversations/{conv_a}", json={"archived": True}).status_code == 404


def test_observer_cannot_set_feedback_on_another_users_message(clients):
    conv_a, msg_id = _send_turn(clients["a"], "primero")
    resp = clients["o"].post(f"/api/analyst/messages/{msg_id}/feedback", json={"rating": "down"})
    assert resp.status_code == 404


# ── 8. Removing the capability removes access ───────────────────────────────

def test_revoking_capability_removes_access(clients):
    assert clients["o"].get("/api/analyst/pilot_control/overview").status_code == 200
    clients["workspace"].revoke_capability(clients["o_id"], "pilot_observer")
    assert clients["o"].get("/api/analyst/pilot_control/overview").status_code == 403
    assert clients["o"].get("/pilot-control").status_code == 403


# ── Diagnostics never leak secrets over the wire ────────────────────────────

def test_conversation_detail_over_http_never_includes_forbidden_fields(clients):
    conv_a, msg_id = _send_turn(clients["a"], "primero")
    # Attach fabricated telemetry via the store directly (simulating a real turn) to
    # verify the HTTP response only carries the safe allowlist.
    clients["workspace"].append_message(conv_a, "assistant", "respuesta con telemetria", metadata={
        "latency_ms": 500.0, "sql_queries": ["SELECT password_hash FROM user"],
        "system_prompt": "should never appear", "api_key": "sk-should-not-leak",
    })
    detail = clients["o"].get(f"/api/analyst/pilot_control/conversations/{conv_a}").get_json()
    raw = str(detail)
    assert "sql_queries" not in raw
    assert "SELECT password_hash" not in raw
    assert "system_prompt" not in raw
    assert "sk-should-not-leak" not in raw
    assert "password_hash" not in raw
