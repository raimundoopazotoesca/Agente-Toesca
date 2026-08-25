from __future__ import annotations

import sqlite3
import time

import pytest

from tools.analyst_workspace.store import (
    ConversationNotFoundError,
    MessageNotFoundError,
    ValidationError,
    WorkspaceStore,
)


@pytest.fixture
def store(tmp_path):
    workspace = WorkspaceStore(tmp_path / "workspace.db")
    workspace.initialize()
    return workspace


def test_initialize_creates_versioned_schema(tmp_path):
    path = tmp_path / "workspace.db"
    WorkspaceStore(path).initialize()

    conn = sqlite3.connect(path)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"conversation", "message", "feedback", "user", "user_session"} <= tables
        assert {"analytical_turn", "fact_claim", "evidence_snapshot", "claim_dependency", "analytical_turn_evidence"} <= tables
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    finally:
        conn.close()


def test_initialize_is_idempotent_and_preserves_data(tmp_path):
    workspace = WorkspaceStore(tmp_path / "workspace.db")
    workspace.initialize()
    conversation = workspace.create_conversation(title="Persistente")
    workspace.initialize()
    assert workspace.get_conversation(conversation.id) == conversation


def test_create_and_get_conversation_round_trips_context(store):
    context = {"source_surface": "factsheet", "fund": "PT", "period": "2026-06"}
    conversation = store.create_conversation(context=context)
    loaded = store.get_conversation(conversation.id)
    assert loaded.title == "Nuevo chat"
    assert loaded.context == context
    assert loaded.archived_at is None


def test_list_conversations_orders_by_most_recent_update(store):
    first = store.create_conversation(title="Primero")
    second = store.create_conversation(title="Segundo")
    store.rename_conversation(first.id, "Primero actualizado")
    assert [conversation.id for conversation in store.list_conversations()] == [first.id, second.id]


def test_rename_updates_title_and_updated_at(store):
    conversation = store.create_conversation(title="Antes")
    time.sleep(0.001)
    renamed = store.rename_conversation(conversation.id, "Después")
    assert renamed.title == "Después"
    assert renamed.updated_at > conversation.updated_at


def test_archive_hides_conversation_and_unarchive_restores_it(store):
    conversation = store.create_conversation()
    archived = store.archive_conversation(conversation.id)
    assert archived.archived_at is not None
    assert store.list_conversations() == []
    assert [item.id for item in store.list_conversations(include_archived=True)] == [conversation.id]
    assert store.unarchive_conversation(conversation.id).archived_at is None
    assert [item.id for item in store.list_conversations()] == [conversation.id]


def test_append_messages_preserves_chronological_order_and_updates_conversation(store):
    conversation = store.create_conversation()
    before = conversation.updated_at
    user = store.append_message(conversation.id, "user", "Hola")
    assistant = store.append_message(conversation.id, "assistant", "¿En qué ayudo?")
    assert [message.id for message in store.list_messages(conversation.id)] == [user.id, assistant.id]
    assert store.get_conversation(conversation.id).updated_at >= before


def test_message_metadata_round_trips_as_opaque_json(store):
    conversation = store.create_conversation()
    metadata = {"latency_ms": 12, "sql_queries": ["SELECT 1"], "usage": {"input": 3}}
    message = store.append_message(conversation.id, "assistant", "Resultado", metadata=metadata)
    assert store.list_messages(conversation.id)[0].metadata == metadata
    assert message.metadata == metadata


@pytest.mark.parametrize("role", ["system", "tool", "USER", ""])
def test_invalid_message_role_is_rejected(store, role):
    conversation = store.create_conversation()
    with pytest.raises(ValidationError, match="role"):
        store.append_message(conversation.id, role, "contenido")


def test_feedback_upsert_keeps_one_current_feedback_per_message(store):
    conversation = store.create_conversation()
    message = store.append_message(conversation.id, "assistant", "Respuesta")
    first = store.set_feedback(message.id, "up", "útil")
    second = store.set_feedback(message.id, "down", "incompleta")
    assert second.id == first.id
    assert store.get_feedback(message.id).rating == "down"
    assert store.get_feedback(message.id).note == "incompleta"


def test_feedback_requires_an_assistant_message(store):
    conversation = store.create_conversation()
    message = store.append_message(conversation.id, "user", "Pregunta")
    with pytest.raises(ValidationError, match="assistant"):
        store.set_feedback(message.id, "up")


@pytest.mark.parametrize("rating", ["neutral", "UP", ""])
def test_invalid_feedback_rating_is_rejected(store, rating):
    conversation = store.create_conversation()
    message = store.append_message(conversation.id, "assistant", "Respuesta")
    with pytest.raises(ValidationError, match="rating"):
        store.set_feedback(message.id, rating)


def test_foreign_keys_prevent_orphan_rows(store):
    conversation = store.create_conversation()
    conn = store._connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO message VALUES ('orphan', 'missing', 'user', 'x', 't', NULL)")
        conn.rollback()
        message = store.append_message(conversation.id, "assistant", "Respuesta")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO feedback VALUES ('orphan', 'missing', 'up', NULL, 't')")
        conn.rollback()
    finally:
        conn.close()


def test_store_reports_missing_conversation_and_message(store):
    with pytest.raises(ConversationNotFoundError):
        store.get_conversation("missing")
    with pytest.raises(ConversationNotFoundError):
        store.append_message("missing", "user", "Hola")
    with pytest.raises(MessageNotFoundError):
        store.set_feedback("missing", "up")


def test_data_survives_store_reopen(tmp_path):
    path = tmp_path / "workspace.db"
    first = WorkspaceStore(path)
    first.initialize()
    conversation = first.create_conversation(context={"fund": "TRI"})
    message = first.append_message(conversation.id, "assistant", "Guardado")
    first.set_feedback(message.id, "up")

    second = WorkspaceStore(path)
    second.initialize()
    assert second.get_conversation(conversation.id).context == {"fund": "TRI"}
    assert second.list_messages(conversation.id)[0].content == "Guardado"
    assert second.get_feedback(message.id).rating == "up"


def test_conversations_are_isolated(store):
    first = store.create_conversation()
    second = store.create_conversation()
    store.append_message(first.id, "user", "Solo primero")
    assert len(store.list_messages(first.id)) == 1
    assert store.list_messages(second.id) == []


def test_durable_analytical_claims_round_trip_and_are_owner_scoped(store):
    first = store.create_conversation()
    other_user = store.create_user("other", "Other", "password1")
    second = store.create_conversation(owner_user_id=other_user)
    user = store.append_message(first.id, "user", "Pregunta")
    assistant = store.append_message(first.id, "assistant", "Respuesta")
    store.persist_analytical_turn(first.id, user.id, assistant.id, {
        "evidence": [{"evidence_id": "e1", "evidence_class": "canonical_metric", "source": {"tool_name": "x"},
                      "scope": {"fund": "PT"}, "semantic_contract": {}, "provenance": {"source": "fixture"},
                      "coverage": {"status": "complete"},
                      "facts": [{"metric_key": "noi", "value": 10.0, "unit": "UF", "entity_id": "PT", "period": "2025"}]}],
        "envelope": {"canonical_metric_claims": [{"claim_id": "c1", "evidence_id": "e1", "metric_key": "noi", "value": 10.0, "unit": "UF", "entity_id": "PT", "period": "2025"}],
                     "derived_metric_claims": []},
    })
    durable = store.load_durable_context_for_user(first.id, first.owner_user_id)
    assert durable["claims"][0]["claim_id"] == "c1"
    assert durable["evidence"][0]["coverage"]["status"] == "complete"
    with pytest.raises(ConversationNotFoundError):
        store.load_durable_context_for_user(first.id, second.owner_user_id)


def test_durable_none_coverage_survives_without_a_numeric_claim(store):
    conversation = store.create_conversation()
    user = store.append_message(conversation.id, "user", "Seguros")
    assistant = store.append_message(conversation.id, "assistant", "Sin evidencia")
    store.persist_analytical_turn(conversation.id, user.id, assistant.id, {"evidence": [{
        "evidence_id": "none", "evidence_class": "governed_dataset", "source": {}, "scope": {"fund": "Apo"},
        "semantic_contract": {}, "provenance": {}, "coverage": {"status": "none"}, "facts": []}],
        "envelope": {"canonical_metric_claims": [], "derived_metric_claims": []}})
    durable = store.load_durable_context_for_user(conversation.id, conversation.owner_user_id)
    assert durable["claims"] == []
    assert durable["evidence"][0]["coverage"]["status"] == "none"


@pytest.mark.parametrize("field", ["context", "metadata"])
def test_non_serializable_json_is_rejected_cleanly(store, field):
    with pytest.raises(ValidationError, match="serializable"):
        if field == "context":
            store.create_conversation(context={"bad": {1, 2}})
        else:
            conversation = store.create_conversation()
            store.append_message(conversation.id, "assistant", "x", metadata={"bad": {1, 2}})
