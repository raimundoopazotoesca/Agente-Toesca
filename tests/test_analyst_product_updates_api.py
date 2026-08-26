"""HTTP contract tests for /api/analyst/product_updates* (the "Novedades" feed).

Pure workspace-store reads/writes -- these routes never touch
ConversationService/AnalystSession, so a session factory that raises on any
use doubles as a guard against an accidental LLM/tool call from this feature.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from scripts import ingesta_server
from tools.analyst_workspace.conversation_service import ConversationService
from tools.analyst_workspace.store import WorkspaceStore


class _ExplodingSessionFactory:
    """Any call into the analytical runtime from this feature is a bug."""

    def create(self, *args, **kwargs):
        raise AssertionError("product updates must never construct an AnalystSession")


def _wire(monkeypatch, store, service):
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_WORKSPACE_STORE_FACTORY", lambda: store)
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_CONVERSATION_SERVICE_FACTORY", lambda: service)
    ingesta_server.app.extensions.pop("analyst_conversation_service", None)


def _login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


@pytest.fixture
def workspace(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.initialize()
    return store


@pytest.fixture
def clients(workspace, monkeypatch):
    a = workspace.create_user("alice", "Alice", "password-a")
    b = workspace.create_user("bob", "Bob", "password-b")
    service = ConversationService(workspace, _ExplodingSessionFactory())
    _wire(monkeypatch, workspace, service)
    client_a, client_b = ingesta_server.app.test_client(), ingesta_server.app.test_client()
    _login(client_a, "alice", "password-a")
    _login(client_b, "bob", "password-b")
    return {"a": client_a, "b": client_b, "a_id": a, "b_id": b}


def test_published_active_update_appears_to_authenticated_user(clients, workspace):
    workspace.create_product_update("Reportar problema", "Ahora puedes reportar.", publish=True)

    resp = clients["a"].get("/api/analyst/product_updates")

    assert resp.status_code == 200
    body = resp.get_json()["product_updates"]
    assert len(body) == 1
    assert body[0]["title"] == "Reportar problema"
    assert body[0]["seen"] is False


def test_inactive_update_does_not_appear(clients, workspace):
    update = workspace.create_product_update("Title", "Body", publish=True)
    workspace.deactivate_product_update(update.id)

    resp = clients["a"].get("/api/analyst/product_updates")

    assert resp.get_json()["product_updates"] == []


def test_unpublished_draft_does_not_appear(clients, workspace):
    workspace.create_product_update("Draft", "Not yet", publish=False)

    resp = clients["a"].get("/api/analyst/product_updates")

    assert resp.get_json()["product_updates"] == []


def test_unauthenticated_request_is_rejected(clients, workspace):
    anon = ingesta_server.app.test_client()

    resp = anon.get("/api/analyst/product_updates")

    assert resp.status_code == 401


def test_viewing_marks_only_the_viewer_seen(clients, workspace):
    update = workspace.create_product_update("Title", "Body", publish=True)

    seen_resp = clients["a"].post(f"/api/analyst/product_updates/{update.id}/seen")
    assert seen_resp.status_code == 200
    assert seen_resp.get_json() == {"ok": True}

    a_view = clients["a"].get("/api/analyst/product_updates").get_json()["product_updates"]
    b_view = clients["b"].get("/api/analyst/product_updates").get_json()["product_updates"]
    assert a_view[0]["seen"] is True
    assert b_view[0]["seen"] is False


def test_unread_count_updates_correctly(clients, workspace):
    update = workspace.create_product_update("Title", "Body", publish=True)

    before = clients["a"].get("/api/analyst/product_updates/unseen_count").get_json()["count"]
    clients["a"].post(f"/api/analyst/product_updates/{update.id}/seen")
    after = clients["a"].get("/api/analyst/product_updates/unseen_count").get_json()["count"]

    assert before == 1
    assert after == 0
    # user B's count is unaffected by A's view.
    assert clients["b"].get("/api/analyst/product_updates/unseen_count").get_json()["count"] == 1


def test_marking_seen_twice_is_idempotent(clients, workspace):
    update = workspace.create_product_update("Title", "Body", publish=True)

    first = clients["a"].post(f"/api/analyst/product_updates/{update.id}/seen")
    second = clients["a"].post(f"/api/analyst/product_updates/{update.id}/seen")

    assert first.status_code == 200
    assert second.status_code == 200
    assert clients["a"].get("/api/analyst/product_updates/unseen_count").get_json()["count"] == 0


def test_unknown_update_id_fails_safely(clients, workspace):
    resp = clients["a"].post("/api/analyst/product_updates/does-not-exist/seen")

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_client_cannot_write_seen_state_for_another_user(clients, workspace):
    """The route never reads a user id from the request body -- only the
    session-derived principal is used, matching every other write in
    /api/analyst/*. Passing bob's id in the body (were it even accepted)
    must not affect bob's own unseen state."""
    update = workspace.create_product_update("Title", "Body", publish=True)

    clients["a"].post(
        f"/api/analyst/product_updates/{update.id}/seen",
        json={"user_id": clients["b_id"]},
    )

    assert clients["b"].get("/api/analyst/product_updates/unseen_count").get_json()["count"] == 1
    assert clients["a"].get("/api/analyst/product_updates/unseen_count").get_json()["count"] == 0


def test_visible_content_has_no_technical_fields(clients, workspace):
    workspace.create_product_update("Title", "Body", publish=True)

    body = clients["a"].get("/api/analyst/product_updates").get_json()["product_updates"][0]

    allowed = {"id", "title", "body", "cta_label", "cta_config", "published_at", "created_at", "seen", "seen_at"}
    assert set(body.keys()) <= allowed
    assert "active" not in body


def test_viewing_and_marking_seen_never_touches_the_analytical_runtime(clients, workspace):
    """_ExplodingSessionFactory.create raises if the product-updates routes
    ever construct an AnalystSession -- these assertions would raise a 500
    (surfaced as a non-200 status) if that guard tripped."""
    update = workspace.create_product_update("Title", "Body", publish=True)

    list_resp = clients["a"].get("/api/analyst/product_updates")
    count_resp = clients["a"].get("/api/analyst/product_updates/unseen_count")
    seen_resp = clients["a"].post(f"/api/analyst/product_updates/{update.id}/seen")

    assert list_resp.status_code == 200
    assert count_resp.status_code == 200
    assert seen_resp.status_code == 200
