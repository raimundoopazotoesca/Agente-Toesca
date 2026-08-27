"""HTTP-level tests for PILOT EXPORT v1: feedback markdown export and batch
conversation markdown export.

Fixture pattern mirrors tests/analyst_workspace/test_pilot_control_api.py and
test_feedback_reports.py: a real Flask test client against a real temp-file
WorkspaceStore, wired in via ANALYST_WORKSPACE_STORE_FACTORY /
ANALYST_CONVERSATION_SERVICE_FACTORY.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from scripts import ingesta_server
from tools import analyst_api
from tools.analyst_runtime.session import AnalystSessionResult
from tools.analyst_workspace.conversation_service import ConversationService
from tools.analyst_workspace.store import WorkspaceStore
from tools.db import connection as db_connection


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
    reviewer_id = workspace.create_user("carol", "Carol Reviewer", "password-c")
    observer_id = workspace.create_user("olivia", "Olivia Observer", "password-o")
    workspace.grant_capability(reviewer_id, "feedback_reviewer")
    workspace.grant_capability(observer_id, "pilot_observer")
    service = ConversationService(workspace, _Factory())
    _wire(monkeypatch, workspace, service)
    client_a, client_b, client_r, client_o = (
        ingesta_server.app.test_client(), ingesta_server.app.test_client(),
        ingesta_server.app.test_client(), ingesta_server.app.test_client(),
    )
    _login(client_a, "alice", "password-a")
    _login(client_b, "bob", "password-b")
    _login(client_r, "carol", "password-c")
    _login(client_o, "olivia", "password-o")
    return {
        "a": client_a, "b": client_b, "r": client_r, "o": client_o,
        "a_id": a, "b_id": b, "r_id": reviewer_id, "o_id": observer_id,
        "workspace": workspace,
    }


FEEDBACK_EXPORT_ROUTE = "/api/analyst/feedback_reports/export.md"
CONV_EXPORT_ROUTE = "/api/analyst/pilot_control/conversations/export.md"


# ── Authorization: feedback export ──────────────────────────────────────────

def test_feedback_export_unauthenticated_is_401():
    anon = ingesta_server.app.test_client()
    resp = anon.get(FEEDBACK_EXPORT_ROUTE)
    assert resp.status_code == 401


def test_feedback_export_authenticated_without_capability_is_403(clients):
    resp = clients["a"].get(FEEDBACK_EXPORT_ROUTE)
    assert resp.status_code == 403


def test_feedback_export_pilot_observer_alone_is_not_enough(clients):
    # pilot_observer is a *different* capability from feedback_reviewer.
    resp = clients["o"].get(FEEDBACK_EXPORT_ROUTE)
    assert resp.status_code == 403


def test_feedback_export_reviewer_can_download(clients):
    conversation_id, anchor_id = _send_turn(clients["a"])
    clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "problema",
    })
    resp = clients["r"].get(FEEDBACK_EXPORT_ROUTE)
    assert resp.status_code == 200


# ── Authorization: batch conversation export ────────────────────────────────

def test_conversations_export_unauthenticated_is_401():
    anon = ingesta_server.app.test_client()
    resp = anon.post(CONV_EXPORT_ROUTE, json={"conversation_ids": ["x"]})
    assert resp.status_code == 401


def test_conversations_export_authenticated_without_capability_is_403(clients):
    conversation_id, _ = _send_turn(clients["a"])
    resp = clients["a"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conversation_id]})
    assert resp.status_code == 403


def test_conversations_export_feedback_reviewer_alone_is_not_enough(clients):
    conversation_id, _ = _send_turn(clients["a"])
    resp = clients["r"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conversation_id]})
    assert resp.status_code == 403


def test_conversations_export_observer_can_download(clients):
    conversation_id, _ = _send_turn(clients["a"])
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conversation_id]})
    assert resp.status_code == 200


# ── Headers ──────────────────────────────────────────────────────────────────

def test_feedback_export_headers(clients):
    resp = clients["r"].get(FEEDBACK_EXPORT_ROUTE)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "text/markdown; charset=utf-8"
    disposition = resp.headers["Content-Disposition"]
    assert disposition.startswith("attachment; filename=\"toesca_pilot_feedback_")
    assert disposition.endswith(".md\"")
    filename = disposition.split('filename="')[1].rstrip('"')
    assert all(c not in filename for c in '/\\:*?"<>|')


def test_conversations_export_headers(clients):
    conversation_id, _ = _send_turn(clients["a"])
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conversation_id]})
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "text/markdown; charset=utf-8"
    disposition = resp.headers["Content-Disposition"]
    assert disposition.startswith("attachment; filename=\"toesca_pilot_conversations_")
    assert disposition.endswith(".md\"")
    filename = disposition.split('filename="')[1].rstrip('"')
    assert all(c not in filename for c in '/\\:*?"<>|')


# ── Content correctness: feedback export ────────────────────────────────────

def test_feedback_export_content_matches_immutable_snapshot_and_live_rating(clients):
    client = clients["a"]
    conversation_id, anchor_id = _send_turn(client, "primera pregunta")
    created = client.post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "Faltó comparar activos.",
    })
    assert created.status_code == 201

    # Rating changes AFTER the report -- export must reflect the *current*
    # rating, not whatever existed (nothing, here) at report time.
    rate = client.post(f"/api/analyst/messages/{anchor_id}/feedback", json={"rating": "down"})
    assert rate.status_code == 200

    resp = clients["r"].get(FEEDBACK_EXPORT_ROUTE)
    text = resp.get_data(as_text=True)
    assert "Faltó comparar activos." in text
    assert "primera pregunta" in text
    assert "\U0001F44E down" in text  # live rating, set after the report
    assert "**Total reportes:** 1" in text
    assert "**Estado `new`:** 1" in text


def test_feedback_export_unrated_is_shown_when_no_rating_set(clients):
    client = clients["a"]
    conversation_id, anchor_id = _send_turn(client)
    client.post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
    })
    resp = clients["r"].get(FEEDBACK_EXPORT_ROUTE)
    assert "sin calificar" in resp.get_data(as_text=True)


def test_feedback_export_status_filter(clients):
    conversation_id, anchor_id = _send_turn(clients["a"], "uno")
    created = clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "primero",
    })
    report_id = created.get_json()["id"]
    clients["r"].patch(f"/api/analyst/feedback_reports/{report_id}", json={"status": "resolved"})

    conversation_id_2, anchor_id_2 = _send_turn(clients["b"], "dos")
    clients["b"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id_2, "anchor_message_id": anchor_id_2, "comment": "segundo",
    })

    resp = clients["r"].get(FEEDBACK_EXPORT_ROUTE + "?status=resolved")
    text = resp.get_data(as_text=True)
    assert "primero" in text
    assert "segundo" not in text
    assert "**Total reportes:** 1" in text


def test_feedback_export_snapshot_never_reconstructed_from_live_state(clients, workspace):
    client = clients["a"]
    conversation_id, anchor_id = _send_turn(client, "original")
    created = client.post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
    })
    assert created.status_code == 201
    # Send another turn AFTER the report -- must not leak into the export.
    client.post(f"/api/analyst/conversations/{conversation_id}/messages", json={"text": "despues del reporte"})

    resp = clients["r"].get(FEEDBACK_EXPORT_ROUTE)
    assert "despues del reporte" not in resp.get_data(as_text=True)


def test_feedback_export_empty_state(clients):
    resp = clients["r"].get(FEEDBACK_EXPORT_ROUTE)
    assert resp.status_code == 200
    assert "**Total reportes:** 0" in resp.get_data(as_text=True)


# ── Content correctness: batch conversation export ──────────────────────────

def test_conversations_export_aggregate_and_transcript(clients):
    conv_a, msg_a = _send_turn(clients["a"], "pregunta de alice")
    conv_b, msg_b = _send_turn(clients["b"], "pregunta de bob")
    clients["a"].post(f"/api/analyst/messages/{msg_a}/feedback", json={"rating": "up"})

    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conv_a, conv_b]})
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "**Conversaciones:** 2" in text
    assert "**Usuarios distintos:** 2" in text
    assert "pregunta de alice" in text
    assert "pregunta de bob" in text
    assert "\U0001F44D 1" in text  # one up-rated response


def test_conversations_export_marks_reported_message(clients):
    conv_a, msg_a = _send_turn(clients["a"], "pregunta")
    clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conv_a, "anchor_message_id": msg_a, "comment": "no sirvió",
    })
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conv_a]})
    text = resp.get_data(as_text=True)
    assert "reportado: sí" in text
    assert "no sirvió" in text
    assert "**Respuestas reportadas:** 1" in text


def test_conversations_export_missing_diagnostics_are_explicit_not_invented(clients):
    client = clients["a"]
    conversation_id = client.post("/api/analyst/conversations", json={"title": "Sin telemetria"}).get_json()["id"]
    client.post(f"/api/analyst/conversations/{conversation_id}/messages", json={"text": "hola"})
    # An assistant message with metadata=None (no turn telemetry attached at
    # all) must show diagnostics as explicitly absent, never fabricated.
    clients["workspace"].append_message(conversation_id, "assistant", "respuesta sin telemetria", metadata=None)
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conversation_id]})
    assert "sin telemetría" in resp.get_data(as_text=True)


def test_conversations_export_dedupes_ids(clients):
    conv_a, _ = _send_turn(clients["a"])
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conv_a, conv_a, conv_a]})
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "**Conversaciones:** 1" in text
    assert text.count("## Conversación:") == 1


def test_conversations_export_ordering_follows_request_order(clients):
    conv_a, _ = _send_turn(clients["a"], "primera de alice")
    conv_b, _ = _send_turn(clients["b"], "primera de bob")
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conv_b, conv_a]})
    text = resp.get_data(as_text=True)
    assert text.index("primera de bob") < text.index("primera de alice")


def test_conversations_export_rejects_whole_batch_on_nonexistent_id(clients):
    conv_a, _ = _send_turn(clients["a"], "existe")
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conv_a, "does-not-exist"]})
    assert 400 <= resp.status_code < 500
    assert resp.status_code != 200
    # No partial export: the valid conversation's content must not appear
    # in an error response body.
    body = resp.get_data(as_text=True)
    assert "existe" not in body


def test_conversations_export_rejects_batch_exceeding_cap(clients):
    ids = [f"nonexistent-{i}" for i in range(101)]
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": ids})
    assert resp.status_code in (400, 413)


def test_conversations_export_accepts_batch_at_cap(clients):
    conv_ids = []
    for i in range(100):
        cid, _ = _send_turn(clients["a"], f"pregunta {i}")
        conv_ids.append(cid)
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": conv_ids})
    assert resp.status_code == 200
    assert resp.get_data(as_text=True).count("## Conversación:") == 100


def test_conversations_export_empty_ids_rejected(clients):
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": []})
    assert resp.status_code == 400


def test_conversations_export_missing_body_rejected(clients):
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={})
    assert resp.status_code == 400


def test_conversations_export_non_string_ids_rejected(clients):
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [123]})
    assert resp.status_code == 400


def test_conversations_export_ignores_client_supplied_rating_and_diagnostics(clients):
    """Server resolves everything itself -- extraneous client-supplied fields
    in the body must have zero effect on the exported content."""
    conv_a, msg_a = _send_turn(clients["a"], "pregunta real")
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={
        "conversation_ids": [conv_a],
        "ratings": {msg_a: "up"},
        "diagnostics": {msg_a: {"latency_ms": 1}},
        "text_override": {msg_a: "texto falso"},
    })
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "texto falso" not in text
    assert "sin calificar" in text  # server-side truth: no rating was ever set


# ── Forbidden fields never appear (seeded via real metadata_json) ──────────

_FORBIDDEN_METADATA = {
    "provider": "openai", "model": "gpt-5", "latency_ms": 42.0,
    "api_key": "sk-should-not-leak", "password_hash": "hash-should-not-leak",
    "system_prompt": "should never appear", "developer_prompt": "should never appear either",
    "chain_of_thought": "hidden reasoning should never appear", "session_token": "tok-should-not-leak",
}


def test_conversations_export_forbidden_fields_absent(clients):
    conv_a, _ = _send_turn(clients["a"], "primero")
    clients["workspace"].append_message(conv_a, "assistant", "respuesta con telemetria", metadata=_FORBIDDEN_METADATA)
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conv_a]})
    text = resp.get_data(as_text=True)
    for forbidden_value in ("sk-should-not-leak", "hash-should-not-leak", "should never appear",
                             "should never appear either", "hidden reasoning should never appear",
                             "tok-should-not-leak"):
        assert forbidden_value not in text
    for forbidden_key in ("api_key", "password_hash", "system_prompt", "developer_prompt",
                           "chain_of_thought", "session_token"):
        assert forbidden_key not in text
    assert "openai" in text  # sanity: allowlisted fields DO come through


def test_feedback_export_forbidden_fields_absent(clients):
    client = clients["a"]
    conversation_id = client.post("/api/analyst/conversations", json={"title": "Privado"}).get_json()["id"]
    client.post(f"/api/analyst/conversations/{conversation_id}/messages", json={"text": "hola"})
    # Attach a second assistant message carrying tainted metadata directly
    # (simulating a real turn) and report *that* one.
    tainted = clients["workspace"].append_message(conversation_id, "assistant", "respuesta con telemetria", metadata=_FORBIDDEN_METADATA)
    reported = client.post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": tainted.id, "comment": "x",
    })
    assert reported.status_code == 201

    resp = clients["r"].get(FEEDBACK_EXPORT_ROUTE)
    text = resp.get_data(as_text=True)
    for forbidden_value in ("sk-should-not-leak", "hash-should-not-leak", "should never appear",
                             "should never appear either", "hidden reasoning should never appear",
                             "tok-should-not-leak"):
        assert forbidden_value not in text
    for forbidden_key in ("api_key", "password_hash", "system_prompt", "developer_prompt",
                           "chain_of_thought", "session_token"):
        assert forbidden_key not in text


# ── UTF-8 correctness ────────────────────────────────────────────────────────

_UTF8_TEXT = "Vacancia 12,5% en UF/m² para Parque Titanium — año 2026 — ñandú 🏢 café"


def test_conversations_export_utf8_roundtrip(clients):
    conv_a, _ = _send_turn(clients["a"], _UTF8_TEXT)
    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conv_a]})
    assert resp.headers["Content-Type"] == "text/markdown; charset=utf-8"
    text = resp.get_data(as_text=True)
    assert _UTF8_TEXT in text
    resp.get_data(as_text=False).decode("utf-8")  # must not raise


def test_feedback_export_utf8_roundtrip(clients):
    conversation_id, anchor_id = _send_turn(clients["a"])
    clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": _UTF8_TEXT,
    })
    resp = clients["r"].get(FEEDBACK_EXPORT_ROUTE)
    text = resp.get_data(as_text=True)
    assert _UTF8_TEXT in text
    resp.get_data(as_text=False).decode("utf-8")  # must not raise


# ── No LLM / tool / knowledge-DB calls during export ────────────────────────

def test_feedback_export_never_touches_analyst_runtime_or_knowledge_db(clients, monkeypatch):
    conversation_id, anchor_id = _send_turn(clients["a"])
    clients["a"].post("/api/analyst/feedback_reports", json={
        "conversation_id": conversation_id, "anchor_message_id": anchor_id, "comment": "x",
    })

    def _boom(*_args, **_kwargs):
        raise AssertionError("export path must never construct an OpenAI-backed analyst session")

    monkeypatch.setattr(
        "tools.analyst_runtime.session.OpenAIResponsesAnalystSessionFactory.__init__", _boom,
    )
    monkeypatch.setattr(db_connection, "get_conn", lambda: (_ for _ in ()).throw(AssertionError("knowledge DB must never open during export")))
    monkeypatch.setattr(db_connection, "get_conn_for", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("knowledge DB must never open during export")))
    monkeypatch.setattr(analyst_api, "get_adapter", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("export path must never go through the analyst API adapter")))

    resp = clients["r"].get(FEEDBACK_EXPORT_ROUTE)
    assert resp.status_code == 200


def test_conversations_export_never_touches_analyst_runtime_or_knowledge_db(clients, monkeypatch):
    conv_a, _ = _send_turn(clients["a"])

    def _boom(*_args, **_kwargs):
        raise AssertionError("export path must never construct an OpenAI-backed analyst session")

    monkeypatch.setattr(
        "tools.analyst_runtime.session.OpenAIResponsesAnalystSessionFactory.__init__", _boom,
    )
    monkeypatch.setattr(db_connection, "get_conn", lambda: (_ for _ in ()).throw(AssertionError("knowledge DB must never open during export")))
    monkeypatch.setattr(db_connection, "get_conn_for", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("knowledge DB must never open during export")))
    monkeypatch.setattr(analyst_api, "get_adapter", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("export path must never go through the analyst API adapter")))

    resp = clients["o"].post(CONV_EXPORT_ROUTE, json={"conversation_ids": [conv_a]})
    assert resp.status_code == 200
