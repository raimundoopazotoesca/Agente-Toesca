"""Administrative password rotation for an existing local account.

Scope: WorkspaceStore.reset_user_password + the admin CLI's reset-password
subcommand only. No HTTP endpoint, no role/session-model changes, no
forgot-password flow -- see tools/analyst_workspace/admin.py's docstring.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.analyst_workspace.store import AuthenticationError, ValidationError, WorkspaceStore

ADMIN_MODULE = Path(__file__).resolve().parents[2] / "tools" / "analyst_workspace" / "admin.py"


def _store(tmp_path: Path) -> WorkspaceStore:
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.initialize()
    return store


def test_existing_user_password_can_be_rotated(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "old-password")

    returned_id = store.reset_user_password("alice", "new-password-123")

    assert returned_id == user_id
    assert store.authenticate("alice", "new-password-123")["id"] == user_id


def test_old_password_no_longer_authenticates_after_rotation(tmp_path):
    store = _store(tmp_path)
    store.create_user("alice", "Alice", "old-password")
    store.reset_user_password("alice", "new-password-123")

    with pytest.raises(AuthenticationError):
        store.authenticate("alice", "old-password")


def test_rotation_preserves_identity_and_role(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "old-password", role="user")

    store.reset_user_password("alice", "new-password-123")

    row = store.authenticate("alice", "new-password-123")
    assert row["id"] == user_id
    assert row["username"] == "alice"
    assert row["display_name"] == "Alice"
    assert row["role"] == "user"
    assert row["is_active"] == 1


def test_rotation_preserves_owned_conversations(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "old-password")
    conversation = store.create_conversation(title="Privado", owner_user_id=user_id)

    store.reset_user_password("alice", "new-password-123")

    assert store.get_conversation_for_user(conversation.id, user_id).owner_user_id == user_id
    assert [c.id for c in store.list_conversations_for_user(user_id)] == [conversation.id]


def test_rotation_fails_closed_for_nonexistent_user(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValidationError):
        store.reset_user_password("nobody", "new-password-123")


def test_rotation_never_creates_a_duplicate_user(tmp_path):
    store = _store(tmp_path)
    store.create_user("alice", "Alice", "old-password")

    store.reset_user_password("alice", "new-password-123")

    import sqlite3
    conn = sqlite3.connect(store.db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM user WHERE username='alice'").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_rotation_on_admin_target_updates_hash_without_creating_a_new_admin(tmp_path):
    """The generic reset must not weaken set_initial_admin_password's
    bootstrap guard: rotating an EXISTING admin's password is an ordinary
    admin operation, but a nonexistent admin username must still fail
    closed exactly like any other nonexistent user (never silently
    provision a new admin account)."""
    store = _store(tmp_path)
    admin_id = store.set_initial_admin_password("admin", "old-admin-password")

    store.reset_user_password("admin", "new-admin-password-123")

    row = store.authenticate("admin", "new-admin-password-123")
    assert row["id"] == admin_id
    assert row["role"] == "admin"
    with pytest.raises(ValidationError):
        store.reset_user_password("not-yet-an-admin", "whatever-password-123")
    import sqlite3
    conn = sqlite3.connect(store.db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM user").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_rotation_revokes_all_existing_sessions_for_that_user(tmp_path):
    store = _store(tmp_path)
    user_id = store.create_user("alice", "Alice", "old-password")
    store.create_session(user_id, "token-1", "2099-01-01T00:00:00Z")
    store.create_session(user_id, "token-2", "2099-01-01T00:00:00Z")
    assert store.get_session_user("token-1") is not None
    assert store.get_session_user("token-2") is not None

    store.reset_user_password("alice", "new-password-123")

    assert store.get_session_user("token-1") is None
    assert store.get_session_user("token-2") is None


def test_rotation_does_not_revoke_other_users_sessions(tmp_path):
    store = _store(tmp_path)
    store.create_user("alice", "Alice", "old-password")
    bob_id = store.create_user("bob", "Bob", "bob-password")
    store.create_session(bob_id, "bob-token", "2099-01-01T00:00:00Z")

    store.reset_user_password("alice", "new-password-123")

    assert store.get_session_user("bob-token") is not None


def test_plaintext_new_password_is_never_persisted(tmp_path):
    store = _store(tmp_path)
    store.create_user("alice", "Alice", "old-password")

    store.reset_user_password("alice", "super-secret-plaintext-123")

    import sqlite3
    conn = sqlite3.connect(store.db_path)
    try:
        stored_hash = conn.execute("SELECT password_hash FROM user WHERE username='alice'").fetchone()[0]
    finally:
        conn.close()
    assert "super-secret-plaintext-123" not in stored_hash
    assert stored_hash.startswith("scrypt:") or stored_hash.startswith("pbkdf2:")


def test_cli_reset_password_reads_password_from_stdin(tmp_path, monkeypatch):
    workspace_db = tmp_path / "memory" / "analyst_workspace.db"
    store = WorkspaceStore(workspace_db)
    store.initialize()
    store.create_user("alice", "Alice", "old-password")

    monkeypatch.setattr(
        "tools.analyst_workspace.admin.__file__",
        str(tmp_path / "tools" / "analyst_workspace" / "admin.py"),
    )
    import importlib
    admin_module = importlib.import_module("tools.analyst_workspace.admin")
    monkeypatch.setattr(sys, "argv", ["admin.py", "reset-password", "alice", "--password-stdin"])
    monkeypatch.setattr("sys.stdin", type("_Stdin", (), {"readline": staticmethod(lambda: "new-password-123\n")})())
    monkeypatch.setattr("builtins.input", lambda: "new-password-123")

    exit_code = admin_module.main()

    assert exit_code == 0
    assert store.authenticate("alice", "new-password-123")["username"] == "alice"


def test_cli_reset_password_fails_closed_for_nonexistent_user(tmp_path, monkeypatch):
    workspace_db = tmp_path / "memory" / "analyst_workspace.db"
    WorkspaceStore(workspace_db).initialize()

    monkeypatch.setattr(
        "tools.analyst_workspace.admin.__file__",
        str(tmp_path / "tools" / "analyst_workspace" / "admin.py"),
    )
    import importlib
    admin_module = importlib.import_module("tools.analyst_workspace.admin")
    monkeypatch.setattr(sys, "argv", ["admin.py", "reset-password", "nobody", "--password-stdin"])
    monkeypatch.setattr("builtins.input", lambda: "new-password-123")

    with pytest.raises(SystemExit):
        admin_module.main()
