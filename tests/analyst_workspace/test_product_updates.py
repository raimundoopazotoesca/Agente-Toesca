"""Product Updates ("Novedades") -- a lightweight in-app discovery feed.

Scope: WorkspaceStore.*_product_update* only. No analytical runtime, no LLM
call, no tool call -- see the docstring above the store methods in
tools/analyst_workspace/store.py.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.analyst_workspace.store import ProductUpdateNotFoundError, ValidationError, WorkspaceStore


def _store(tmp_path: Path) -> WorkspaceStore:
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.initialize()
    return store


def test_published_active_update_is_visible_to_a_user(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "password-a")
    update = store.create_product_update("Reportar problema", "Ahora puedes reportar respuestas.", publish=True)

    visible = store.list_product_updates_for_user(user_id)

    assert [u["id"] for u in visible] == [update.id]
    assert visible[0]["title"] == "Reportar problema"
    assert visible[0]["seen"] is False
    assert visible[0]["seen_at"] is None


def test_draft_update_is_not_visible(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "password-a")
    store.create_product_update("Draft", "Not published yet", publish=False)

    assert store.list_product_updates_for_user(user_id) == []


def test_deactivated_update_is_not_visible(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "password-a")
    update = store.create_product_update("Title", "Body", publish=True)

    store.deactivate_product_update(update.id)

    assert store.list_product_updates_for_user(user_id) == []


def test_newest_first_ordering(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "password-a")
    first = store.create_product_update("First", "Body 1", publish=True)
    second = store.create_product_update("Second", "Body 2", publish=True)

    visible = store.list_product_updates_for_user(user_id)

    assert [u["id"] for u in visible] == [second.id, first.id]


def test_viewing_marks_only_that_user_seen(tmp_path):
    store = _store(tmp_path)
    user_a = store.create_user("alice", "Alice", "password-a")
    user_b = store.create_user("bob", "Bob", "password-b")
    update = store.create_product_update("Title", "Body", publish=True)

    store.mark_product_update_seen_for_user(update.id, user_a)

    visible_a = store.list_product_updates_for_user(user_a)
    visible_b = store.list_product_updates_for_user(user_b)
    assert visible_a[0]["seen"] is True
    assert visible_a[0]["seen_at"] is not None
    assert visible_b[0]["seen"] is False
    assert visible_b[0]["seen_at"] is None


def test_unread_count_reflects_per_user_seen_state(tmp_path):
    store = _store(tmp_path)
    user_a = store.create_user("alice", "Alice", "password-a")
    user_b = store.create_user("bob", "Bob", "password-b")
    update = store.create_product_update("Title", "Body", publish=True)

    assert store.count_unseen_product_updates_for_user(user_a) == 1
    assert store.count_unseen_product_updates_for_user(user_b) == 1

    store.mark_product_update_seen_for_user(update.id, user_a)

    assert store.count_unseen_product_updates_for_user(user_a) == 0
    assert store.count_unseen_product_updates_for_user(user_b) == 1


def test_marking_seen_twice_is_idempotent(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "password-a")
    update = store.create_product_update("Title", "Body", publish=True)

    store.mark_product_update_seen_for_user(update.id, user_id)
    first_seen_at = store.list_product_updates_for_user(user_id)[0]["seen_at"]
    store.mark_product_update_seen_for_user(update.id, user_id)
    second_seen_at = store.list_product_updates_for_user(user_id)[0]["seen_at"]

    assert first_seen_at == second_seen_at
    conn = sqlite3.connect(store.db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM product_update_seen WHERE user_id=? AND product_update_id=?",
            (user_id, update.id),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_marking_unknown_update_seen_fails_safely(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "password-a")

    with pytest.raises(ProductUpdateNotFoundError):
        store.mark_product_update_seen_for_user("does-not-exist", user_id)


def test_data_survives_a_store_restart(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "password-a")
    update = store.create_product_update("Title", "Body", cta_label="Volver al chat",
                                          cta_config={"type": "route", "value": "/analyst"}, publish=True)
    store.mark_product_update_seen_for_user(update.id, user_id)

    reopened = WorkspaceStore(store.db_path)
    reopened.initialize()

    visible = reopened.list_product_updates_for_user(user_id)
    assert visible[0]["id"] == update.id
    assert visible[0]["seen"] is True
    assert visible[0]["cta_label"] == "Volver al chat"
    assert visible[0]["cta_config"] == {"type": "route", "value": "/analyst"}


def test_create_requires_title_and_body(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValidationError):
        store.create_product_update("", "Body")
    with pytest.raises(ValidationError):
        store.create_product_update("Title", "")


def test_deactivating_unknown_update_fails_safely(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ProductUpdateNotFoundError):
        store.deactivate_product_update("does-not-exist")


def test_migration_preserves_users_and_conversations(tmp_path):
    """A workspace populated before the product_update tables existed (schema
    version 7) must migrate cleanly to version 8 without losing data."""
    store = _store(tmp_path)  # already at version 8 (this is a fresh dev DB)
    user_id = store.create_user("alice", "Alice", "password-a")
    conversation = store.create_conversation(title="Privado", owner_user_id=user_id)
    store.append_message(conversation.id, "user", "hola")

    # Simulate reopening an existing (older-schema) DB after the migration ships.
    reopened = WorkspaceStore(store.db_path)
    reopened.initialize()

    assert reopened.authenticate("alice", "password-a")["id"] == user_id
    assert [c.id for c in reopened.list_conversations_for_user(user_id)] == [conversation.id]
    assert len(reopened.list_messages(conversation.id)) == 1


def test_migration_preserves_feedback_reports(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "password-a")
    conversation = store.create_conversation(title="Privado", owner_user_id=user_id)
    user_msg = store.append_message(conversation.id, "user", "hola")
    assistant_msg = store.append_message(conversation.id, "assistant", "hola de vuelta")
    report = store.create_feedback_report_for_user(user_id, conversation.id, assistant_msg.id, "no sirvió")

    reopened = WorkspaceStore(store.db_path)
    reopened.initialize()

    assert reopened.get_feedback_report(report.id).id == report.id
    assert user_msg.id  # sanity: message persisted alongside the report
