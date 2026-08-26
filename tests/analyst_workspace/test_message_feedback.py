"""Message-level thumbs feedback (v1): storage, API, and isolation tests.

Deliberately separate from feedback_report ("Reportar problema"): binary
rating only, no taxonomy, no reason picker. Mirrors the conventions in
test_feedback_reports.py.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pytest

from scripts import ingesta_server
from tools.analyst_runtime.session import AnalystSessionResult
from tools.analyst_workspace.conversation_service import ConversationService
from tools.analyst_workspace.store import ValidationError, WorkspaceStore


@dataclass
class _Session:
    calls: int = 0

    def ask(self, text):
        self.calls += 1
        return AnalystSessionResult(f"Respuesta: {text}")


class _Factory:
    def __init__(self):
        self.sessions: list[_Session] = []

    def create(self, *args, **kwargs):
        session = _Session()
        self.sessions.append(session)
        return session


def _login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def _wire(monkeypatch, store, service):
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_WORKSPACE_STORE_FACTORY", lambda: store)
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_CONVERSATION_SERVICE_FACTORY", lambda: service)
    ingesta_server.app.extensions.pop("analyst_conversation_service", None)


def _make_turn(client, text="hola"):
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
def factory():
    return _Factory()


@pytest.fixture
def clients(workspace, factory, monkeypatch):
    a = workspace.create_user("alice", "Alice", "password-a")
    b = workspace.create_user("bob", "Bob", "password-b")
    reviewer_id = workspace.create_user("carol", "Carol Reviewer", "password-c")
    workspace.grant_capability(reviewer_id, "feedback_reviewer")
    service = ConversationService(workspace, factory)
    _wire(monkeypatch, workspace, service)
    client_a, client_b, client_r = (
        ingesta_server.app.test_client(), ingesta_server.app.test_client(), ingesta_server.app.test_client(),
    )
    _login(client_a, "alice", "password-a")
    _login(client_b, "bob", "password-b")
    _login(client_r, "carol", "password-c")
    return {"a": client_a, "b": client_b, "r": client_r, "a_id": a, "b_id": b, "r_id": reviewer_id}


# ── 1/2: basic rate up/down ────────────────────────────────────────────────

def test_authenticated_user_can_thumbs_up_own_message(clients):
    _conv, message_id = _make_turn(clients["a"])
    resp = clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    assert resp.status_code == 200
    assert resp.get_json()["rating"] == "up"


def test_authenticated_user_can_thumbs_down_own_message(clients):
    _conv, message_id = _make_turn(clients["a"])
    resp = clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "down"})
    assert resp.status_code == 200
    assert resp.get_json()["rating"] == "down"


# ── 3/4: one current rating, idempotent repeats ────────────────────────────

def test_only_one_current_rating_exists_per_user_message(clients, workspace):
    _conv, message_id = _make_turn(clients["a"])
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "down"})
    conn = sqlite3.connect(workspace.db_path)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM feedback WHERE message_id=?", (message_id,)).fetchall()
        assert rows[0][0] == 1
    finally:
        conn.close()


def test_repeated_identical_rating_is_idempotent_no_duplicate_row(clients, workspace):
    _conv, message_id = _make_turn(clients["a"])
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    conn = sqlite3.connect(workspace.db_path)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM feedback WHERE message_id=?", (message_id,)).fetchall()
        assert rows[0][0] == 1
    finally:
        conn.close()


# ── 5/6: toggling changes the rating ───────────────────────────────────────

def test_up_then_down_changes_rating(clients):
    _conv, message_id = _make_turn(clients["a"])
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    resp = clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "down"})
    assert resp.get_json()["rating"] == "down"


def test_down_then_up_changes_rating(clients):
    _conv, message_id = _make_turn(clients["a"])
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "down"})
    resp = clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    assert resp.get_json()["rating"] == "up"


# ── 7/8: clear, and it stays cleared after restart ─────────────────────────

def test_rating_can_be_removed(clients, workspace):
    conv_id, message_id = _make_turn(clients["a"])
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    resp = clients["a"].delete(f"/api/analyst/messages/{message_id}/feedback")
    assert resp.status_code == 200
    listed = clients["a"].get(f"/api/analyst/conversations/{conv_id}/feedback")
    assert message_id not in listed.get_json()["feedback"]


def test_removed_rating_remains_absent_after_restart(clients, workspace):
    conv_id, message_id = _make_turn(clients["a"])
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    clients["a"].delete(f"/api/analyst/messages/{message_id}/feedback")

    reopened = WorkspaceStore(workspace.db_path)
    reopened.initialize()
    assert reopened.get_feedback_for_user(message_id, clients["a_id"]) is None


def test_clearing_an_absent_rating_is_a_safe_no_op(clients):
    _conv, message_id = _make_turn(clients["a"])
    resp = clients["a"].delete(f"/api/analyst/messages/{message_id}/feedback")
    assert resp.status_code == 200


# ── 9/10: cross-conversation / cross-user ownership ────────────────────────

def test_user_cannot_rate_another_users_conversation_message(clients):
    _conv, message_id = _make_turn(clients["a"])
    resp = clients["b"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    assert resp.status_code == 404


def test_user_cannot_see_ratings_from_a_different_owned_conversation_via_pairing(clients):
    conv1, message1 = _make_turn(clients["a"], "primera")
    conv2, _message2 = _make_turn(clients["a"], "segunda")
    clients["a"].post(f"/api/analyst/messages/{message1}/feedback", json={"rating": "up"})
    # Both conversations are owned by Alice, but the feedback for conv1's
    # message must not leak into conv2's scoped listing.
    listed_conv2 = clients["a"].get(f"/api/analyst/conversations/{conv2}/feedback")
    assert message1 not in listed_conv2.get_json()["feedback"]
    listed_conv1 = clients["a"].get(f"/api/analyst/conversations/{conv1}/feedback")
    assert listed_conv1.get_json()["feedback"][message1] == "up"


# ── 11/12: message-kind guards ──────────────────────────────────────────────

def test_user_cannot_rate_a_user_authored_message(clients):
    conv_id, _assistant_id = _make_turn(clients["a"])
    messages = clients["a"].get(f"/api/analyst/conversations/{conv_id}/messages").get_json()["messages"]
    user_message_id = next(m["id"] for m in messages if m["role"] == "user")
    resp = clients["a"].post(f"/api/analyst/messages/{user_message_id}/feedback", json={"rating": "up"})
    assert resp.status_code == 400


def test_nonexistent_message_fails_safely(clients):
    resp = clients["a"].post("/api/analyst/messages/does-not-exist/feedback", json={"rating": "up"})
    assert resp.status_code == 404


# ── 13/14: authentication and identity spoofing ─────────────────────────────

def test_unauthenticated_rating_request_returns_401():
    anon = ingesta_server.app.test_client()
    resp = anon.post("/api/analyst/messages/whatever/feedback", json={"rating": "up"})
    assert resp.status_code == 401


def test_client_supplied_user_id_is_ignored(clients):
    _conv, message_id = _make_turn(clients["a"])
    resp = clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={
        "rating": "up", "user_id": clients["b_id"],
    })
    assert resp.status_code == 200
    # The rating is attributed to Alice (the authenticated principal), not
    # to the spoofed user_id -- Bob still cannot see or own it.
    assert clients["b"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "down"}).status_code == 404


def test_invalid_rating_value_is_rejected(clients):
    _conv, message_id = _make_turn(clients["a"])
    resp = clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "meh"})
    assert resp.status_code == 400


# ── 15: restart durability ──────────────────────────────────────────────────

def test_rating_survives_workspace_store_restart(clients, workspace):
    _conv, message_id = _make_turn(clients["a"])
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})

    reopened = WorkspaceStore(workspace.db_path)
    reopened.initialize()
    assert reopened.get_feedback_for_user(message_id, clients["a_id"]).rating == "up"


# ── 16: feedback_report snapshots are untouched ─────────────────────────────

def test_existing_feedback_report_snapshot_is_not_mutated_by_rating_actions(clients, workspace):
    conv_id, message_id = _make_turn(clients["a"])
    reported = clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conv_id, "anchor_message_id": message_id, "comment": "algo",
    })
    report_id = reported.get_json()["id"]
    before = workspace.get_feedback_report(report_id).conversation_snapshot

    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "down"})
    clients["a"].delete(f"/api/analyst/messages/{message_id}/feedback")
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})

    after = workspace.get_feedback_report(report_id).conversation_snapshot
    assert before == after


# ── 17/18: no side effects on the conversation or the Analyst ──────────────

def test_rating_creates_no_new_conversation_message(clients, workspace):
    conv_id, message_id = _make_turn(clients["a"])
    before = len(workspace.list_messages(conv_id))
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "down"})
    clients["a"].delete(f"/api/analyst/messages/{message_id}/feedback")
    after = len(workspace.list_messages(conv_id))
    assert after == before


def test_rating_causes_no_llm_or_tool_invocation(clients, factory):
    _conv, message_id = _make_turn(clients["a"])
    calls_before = sum(s.calls for s in factory.sessions)
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "down"})
    clients["a"].delete(f"/api/analyst/messages/{message_id}/feedback")
    calls_after = sum(s.calls for s in factory.sessions)
    assert calls_after == calls_before


# ── User isolation ───────────────────────────────────────────────────────────

def test_two_users_have_fully_independent_rating_state(clients):
    conv_a, message_a = _make_turn(clients["a"], "de alice")
    conv_b, message_b = _make_turn(clients["b"], "de bob")

    clients["a"].post(f"/api/analyst/messages/{message_a}/feedback", json={"rating": "up"})
    clients["b"].post(f"/api/analyst/messages/{message_b}/feedback", json={"rating": "down"})

    # B cannot access or change A's rating through A's conversation.
    assert clients["b"].post(f"/api/analyst/messages/{message_a}/feedback", json={"rating": "up"}).status_code == 404
    assert clients["b"].delete(f"/api/analyst/messages/{message_a}/feedback").status_code == 404
    assert clients["b"].get(f"/api/analyst/conversations/{conv_a}/feedback").status_code == 404

    # Each user's own state is unaffected by the other's actions.
    assert clients["a"].get(f"/api/analyst/conversations/{conv_a}/feedback").get_json()["feedback"][message_a] == "up"
    assert clients["b"].get(f"/api/analyst/conversations/{conv_b}/feedback").get_json()["feedback"][message_b] == "down"


# ── Reviewer summary surface ─────────────────────────────────────────────────

def test_feedback_summary_requires_reviewer_capability(clients):
    _conv, message_id = _make_turn(clients["a"])
    clients["a"].post(f"/api/analyst/messages/{message_id}/feedback", json={"rating": "up"})
    assert clients["a"].get("/api/analyst/feedback_summary").status_code == 403


def test_feedback_summary_reports_counts_and_positive_rate(clients):
    _c1, m1 = _make_turn(clients["a"], "uno")
    _c2, m2 = _make_turn(clients["a"], "dos")
    clients["a"].post(f"/api/analyst/messages/{m1}/feedback", json={"rating": "up"})
    clients["a"].post(f"/api/analyst/messages/{m2}/feedback", json={"rating": "down"})
    resp = clients["r"].get("/api/analyst/feedback_summary")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["up_count"] == 1
    assert body["down_count"] == 1
    assert body["total_rated"] == 2
    assert body["positive_rate"] == 0.5
    assert len(body["recent"]) == 2


# ── Store-level guard (unit, not through HTTP) ──────────────────────────────

def test_store_rejects_feedback_on_user_message(workspace):
    user_id = workspace.create_user("frank", "Frank", "password-f")
    conversation = workspace.create_conversation(owner_user_id=user_id)
    user_message = workspace.append_message(conversation.id, "user", "hola")
    with pytest.raises(ValidationError):
        workspace.set_feedback_for_user(user_message.id, user_id, "up")
