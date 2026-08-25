"""SQLite persistence for conversations, messages, and current feedback.

This module owns only workspace state.  It never opens or references the
read-only real-estate knowledge database used by ``analyst_runtime``.
"""
from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from werkzeug.security import check_password_hash, generate_password_hash

from tools.analyst_workspace.models import Conversation, Feedback, Message

SCHEMA_VERSION = 3
DEFAULT_TITLE = "Nuevo chat"
_ROLES = {"user", "assistant"}
_RATINGS = {"up", "down"}


class WorkspaceStoreError(Exception):
    """Base error for workspace persistence failures."""


class ConversationNotFoundError(WorkspaceStoreError):
    """Raised when a conversation id cannot be found."""


class MessageNotFoundError(WorkspaceStoreError):
    """Raised when a message id cannot be found."""


class ValidationError(WorkspaceStoreError):
    """Raised for invalid store input before it is persisted."""


class AuthenticationError(WorkspaceStoreError):
    """Raised when a local account cannot authenticate."""


class WorkspaceStore:
    """A short-lived-connection SQLite store for one local analyst workspace."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        """Apply small, sequential workspace migrations without touching knowledge data."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._open_connection()
        try:
            with conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise WorkspaceStoreError(
                        f"workspace schema version {version} is newer than supported version {SCHEMA_VERSION}"
                    )
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS conversation (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        context_json TEXT,
                        archived_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS message (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL REFERENCES conversation(id),
                        role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        metadata_json TEXT
                    );
                    CREATE TABLE IF NOT EXISTS feedback (
                        id TEXT PRIMARY KEY,
                        message_id TEXT NOT NULL UNIQUE REFERENCES message(id),
                        rating TEXT NOT NULL CHECK(rating IN ('up', 'down')),
                        note TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_message_conversation_created
                        ON message(conversation_id, created_at, id);
                    CREATE INDEX IF NOT EXISTS idx_conversation_updated
                        ON conversation(updated_at DESC, created_at DESC, id DESC);
                    """
                )
                if version == 0:
                    conn.execute("PRAGMA user_version = 1")
                    version = 1
                if version < 2:
                    self._backup_before_migration()
                    conn.executescript("""
                    CREATE TABLE user (
                        id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                        display_name TEXT NOT NULL, role TEXT NOT NULL,
                        password_hash TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE user_session (
                        id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES user(id),
                        token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL, last_seen_at TEXT, revoked_at TEXT
                    );
                    CREATE INDEX idx_user_session_token ON user_session(token_hash);
                    ALTER TABLE conversation ADD COLUMN owner_user_id TEXT REFERENCES user(id);
                    CREATE INDEX idx_conversation_owner_updated
                        ON conversation(owner_user_id, updated_at DESC, created_at DESC, id DESC);
                    """)
                    admin_id = self._create_initial_admin(conn)
                    conn.execute("UPDATE conversation SET owner_user_id = ? WHERE owner_user_id IS NULL", (admin_id,))
                    conn.execute("PRAGMA user_version = 2")
                    version = 2
                if version < 3:
                    null_count = conn.execute("SELECT COUNT(*) FROM conversation WHERE owner_user_id IS NULL").fetchone()[0]
                    if null_count:
                        raise WorkspaceStoreError("workspace migration cannot enforce ownership while NULL owners remain")
                    conn.executescript("""
                    CREATE TRIGGER conversation_owner_required_insert
                    BEFORE INSERT ON conversation FOR EACH ROW WHEN NEW.owner_user_id IS NULL
                    BEGIN SELECT RAISE(ABORT, 'conversation owner_user_id is required'); END;
                    CREATE TRIGGER conversation_owner_required_update
                    BEFORE UPDATE OF owner_user_id ON conversation FOR EACH ROW WHEN NEW.owner_user_id IS NULL
                    BEGIN SELECT RAISE(ABORT, 'conversation owner_user_id is required'); END;
                    """)
                    conn.execute("PRAGMA user_version = 3")
        finally:
            conn.close()

    def create_conversation(
        self, context: dict[str, Any] | None = None, title: str | None = None, owner_user_id: str | None = None
    ) -> Conversation:
        serialized_context = _serialize_object(context, "context")
        normalized_title = _normalize_title(title)
        now = _utc_now()
        conversation_id = str(uuid4())
        conn = self._connect()
        try:
            with conn:
                owner = owner_user_id or self._initial_admin_id(conn)
                conversation = Conversation(conversation_id, normalized_title, now, now, context, None, owner)
                conn.execute(
                    "INSERT INTO conversation (id,title,created_at,updated_at,context_json,archived_at,owner_user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (conversation.id, conversation.title, conversation.created_at, conversation.updated_at,
                     serialized_context, conversation.archived_at, owner),
                )
        finally:
            conn.close()
        return conversation

    def create_user(self, username: str, display_name: str, password: str, role: str = "user", *, is_active: bool = True) -> str:
        if not isinstance(username, str) or not username.strip() or not isinstance(display_name, str) or not display_name.strip():
            raise ValidationError("username and display name are required")
        if role not in {"admin", "user"} or not isinstance(password, str) or len(password) < 8:
            raise ValidationError("role is invalid or password must contain at least 8 characters")
        now, user_id = _utc_now(), str(uuid4())
        conn = self._connect()
        try:
            with conn:
                conn.execute("INSERT INTO user VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (user_id, username.strip().lower(), display_name.strip(), role, generate_password_hash(password), int(is_active), now, now))
        except sqlite3.IntegrityError as exc:
            raise ValidationError("username already exists") from exc
        finally:
            conn.close()
        return user_id

    def set_initial_admin_password(self, username: str, password: str, display_name: str = "Initial admin") -> str:
        if not isinstance(password, str) or len(password) < 8:
            raise ValidationError("password must contain at least 8 characters")
        conn = self._connect()
        try:
            with conn:
                row = conn.execute("SELECT id FROM user WHERE username=? AND role='admin'", (username.strip().lower(),)).fetchone()
                if row is None: raise ValidationError("initial admin does not exist")
                conn.execute("UPDATE user SET password_hash=?, display_name=?, is_active=1, updated_at=? WHERE id=?", (generate_password_hash(password), display_name.strip() or "Initial admin", _utc_now(), row["id"]))
                return row["id"]
        finally: conn.close()

    def authenticate(self, username: str, password: str) -> sqlite3.Row:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM user WHERE username = ?", (username.strip().lower(),)).fetchone()
        finally:
            conn.close()
        if row is None or not row["is_active"] or not check_password_hash(row["password_hash"], password):
            raise AuthenticationError("invalid credentials")
        return row

    def create_session(self, user_id: str, token: str, expires_at: str) -> None:
        conn = self._connect()
        try:
            with conn:
                self._require_user(conn, user_id)
                conn.execute("INSERT INTO user_session VALUES (?, ?, ?, ?, ?, NULL, NULL)", (str(uuid4()), user_id, _token_hash(token), _utc_now(), expires_at))
        finally: conn.close()

    def get_session_user(self, token: str) -> sqlite3.Row | None:
        now = _utc_now()
        conn = self._connect()
        try:
            row = conn.execute("SELECT u.* FROM user_session s JOIN user u ON u.id=s.user_id WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.is_active=1", (_token_hash(token), now)).fetchone()
            if row is not None:
                conn.execute("UPDATE user_session SET last_seen_at=? WHERE token_hash=?", (now, _token_hash(token)))
                conn.commit()
            return row
        finally: conn.close()

    def revoke_session(self, token: str) -> None:
        conn = self._connect()
        try:
            with conn: conn.execute("UPDATE user_session SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (_utc_now(), _token_hash(token)))
        finally: conn.close()

    def get_conversation_for_user(self, conversation_id: str, user_id: str) -> Conversation:
        return self._get_conversation_scoped(conversation_id, user_id)

    def list_conversations_for_user(self, user_id: str, include_archived: bool = False) -> list[Conversation]:
        sql = "SELECT * FROM conversation WHERE owner_user_id = ?"
        if not include_archived: sql += " AND archived_at IS NULL"
        sql += " ORDER BY updated_at DESC, created_at DESC, id DESC"
        conn = self._connect()
        try: rows = conn.execute(sql, (user_id,)).fetchall()
        finally: conn.close()
        return [_conversation_from_row(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> Conversation:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM conversation WHERE id = ?", (conversation_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ConversationNotFoundError(f"conversation not found: {conversation_id}")
        return _conversation_from_row(row)

    def list_messages_for_user(self, conversation_id: str, user_id: str) -> list[Message]:
        self._get_conversation_scoped(conversation_id, user_id)
        return self.list_messages(conversation_id)

    def append_message_for_user(self, conversation_id: str, user_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> Message:
        self._get_conversation_scoped(conversation_id, user_id)
        return self.append_message(conversation_id, role, content, metadata)

    def rename_conversation_for_user(self, conversation_id: str, user_id: str, title: str) -> Conversation:
        self._get_conversation_scoped(conversation_id, user_id)
        return self.rename_conversation(conversation_id, title)

    def archive_conversation_for_user(self, conversation_id: str, user_id: str) -> Conversation:
        self._get_conversation_scoped(conversation_id, user_id)
        return self.archive_conversation(conversation_id)

    def unarchive_conversation_for_user(self, conversation_id: str, user_id: str) -> Conversation:
        self._get_conversation_scoped(conversation_id, user_id)
        return self.unarchive_conversation(conversation_id)

    def set_feedback_for_user(self, message_id: str, user_id: str, rating: str, note: str | None = None) -> Feedback:
        conn = self._connect()
        try:
            row = conn.execute("SELECT m.id FROM message m JOIN conversation c ON c.id=m.conversation_id WHERE m.id=? AND c.owner_user_id=?", (message_id, user_id)).fetchone()
        finally: conn.close()
        if row is None: raise MessageNotFoundError("message not found")
        return self.set_feedback(message_id, rating, note)

    def list_conversations(self, include_archived: bool = False) -> list[Conversation]:
        sql = "SELECT * FROM conversation"
        if not include_archived:
            sql += " WHERE archived_at IS NULL"
        sql += " ORDER BY updated_at DESC, created_at DESC, id DESC"
        conn = self._connect()
        try:
            rows = conn.execute(sql).fetchall()
        finally:
            conn.close()
        return [_conversation_from_row(row) for row in rows]

    def rename_conversation(self, conversation_id: str, title: str) -> Conversation:
        normalized_title = _normalize_title(title)
        return self._update_conversation(conversation_id, "title = ?", (normalized_title,))

    def archive_conversation(self, conversation_id: str) -> Conversation:
        return self._update_conversation(conversation_id, "archived_at = ?", (_utc_now(),))

    def unarchive_conversation(self, conversation_id: str) -> Conversation:
        return self._update_conversation(conversation_id, "archived_at = NULL", ())

    def append_message(
        self, conversation_id: str, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> Message:
        if role not in _ROLES:
            raise ValidationError("role must be 'user' or 'assistant'")
        if not isinstance(content, str):
            raise ValidationError("content must be a string")
        serialized_metadata = _serialize_object(metadata, "metadata")
        now = _utc_now()
        message = Message(str(uuid4()), conversation_id, role, content, now, metadata)
        conn = self._connect()
        try:
            with conn:
                self._require_conversation(conn, conversation_id)
                conn.execute(
                    "INSERT INTO message VALUES (?, ?, ?, ?, ?, ?)",
                    (message.id, message.conversation_id, message.role, message.content,
                     message.created_at, serialized_metadata),
                )
                conn.execute("UPDATE conversation SET updated_at = ? WHERE id = ?", (_utc_now(), conversation_id))
        finally:
            conn.close()
        return message

    def list_messages(self, conversation_id: str) -> list[Message]:
        conn = self._connect()
        try:
            self._require_conversation(conn, conversation_id)
            rows = conn.execute(
                "SELECT * FROM message WHERE conversation_id = ? ORDER BY created_at ASC, id ASC", (conversation_id,)
            ).fetchall()
        finally:
            conn.close()
        return [_message_from_row(row) for row in rows]

    def set_feedback(self, message_id: str, rating: str, note: str | None = None) -> Feedback:
        if rating not in _RATINGS:
            raise ValidationError("rating must be 'up' or 'down'")
        if note is not None and not isinstance(note, str):
            raise ValidationError("note must be a string or None")
        conn = self._connect()
        try:
            with conn:
                message = self._require_message(conn, message_id)
                if message["role"] != "assistant":
                    raise ValidationError("feedback is only supported for assistant messages")
                existing = conn.execute("SELECT id FROM feedback WHERE message_id = ?", (message_id,)).fetchone()
                feedback_id = existing["id"] if existing else str(uuid4())
                now = _utc_now()
                conn.execute(
                    """INSERT INTO feedback (id, message_id, rating, note, created_at) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(message_id) DO UPDATE SET rating = excluded.rating, note = excluded.note,
                    created_at = excluded.created_at""",
                    (feedback_id, message_id, rating, note, now),
                )
                row = conn.execute("SELECT * FROM feedback WHERE message_id = ?", (message_id,)).fetchone()
        finally:
            conn.close()
        return _feedback_from_row(row)

    def get_feedback(self, message_id: str) -> Feedback | None:
        conn = self._connect()
        try:
            self._require_message(conn, message_id)
            row = conn.execute("SELECT * FROM feedback WHERE message_id = ?", (message_id,)).fetchone()
        finally:
            conn.close()
        return _feedback_from_row(row) if row is not None else None

    def _update_conversation(self, conversation_id: str, assignment: str, values: tuple[Any, ...]) -> Conversation:
        conn = self._connect()
        try:
            with conn:
                self._require_conversation(conn, conversation_id)
                conn.execute(
                    f"UPDATE conversation SET {assignment}, updated_at = ? WHERE id = ?",
                    (*values, _utc_now(), conversation_id),
                )
                row = conn.execute("SELECT * FROM conversation WHERE id = ?", (conversation_id,)).fetchone()
        finally:
            conn.close()
        return _conversation_from_row(row)

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise WorkspaceStoreError(f"workspace database is not initialized: {self.db_path}")
        return self._open_connection()

    def _backup_before_migration(self) -> None:
        backup = self.db_path.with_suffix(self.db_path.suffix + ".pre_identity_v1.bak")
        if self.db_path.exists() and not backup.exists():
            shutil.copy2(self.db_path, backup)

    def _create_initial_admin(self, conn: sqlite3.Connection) -> str:
        username = os.environ.get("ANALYST_INITIAL_ADMIN_USERNAME", "admin").strip().lower()
        row = conn.execute("SELECT id FROM user WHERE username=?", (username,)).fetchone()
        if row: return row["id"]
        now, user_id = _utc_now(), str(uuid4())
        # The bootstrap account cannot authenticate until the operator sets a password via the CLI.
        conn.execute("INSERT INTO user VALUES (?, ?, ?, 'admin', '!', 0, ?, ?)", (user_id, username, "Initial admin", now, now))
        return user_id

    @staticmethod
    def _require_user(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM user WHERE id=?", (user_id,)).fetchone()
        if row is None: raise ValidationError("user not found")
        return row

    def _initial_admin_id(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT id FROM user WHERE role='admin' ORDER BY created_at LIMIT 1").fetchone()
        if row is None: return self._create_initial_admin(conn)
        return row["id"]

    def _get_conversation_scoped(self, conversation_id: str, user_id: str) -> Conversation:
        conn = self._connect()
        try: row = conn.execute("SELECT * FROM conversation WHERE id=? AND owner_user_id=?", (conversation_id, user_id)).fetchone()
        finally: conn.close()
        if row is None: raise ConversationNotFoundError("conversation not found")
        return _conversation_from_row(row)

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _require_conversation(conn: sqlite3.Connection, conversation_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM conversation WHERE id = ?", (conversation_id,)).fetchone()
        if row is None:
            raise ConversationNotFoundError(f"conversation not found: {conversation_id}")
        return row

    @staticmethod
    def _require_message(conn: sqlite3.Connection, message_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM message WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            raise MessageNotFoundError(f"message not found: {message_id}")
        return row


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _normalize_title(title: str | None) -> str:
    if title is None:
        return DEFAULT_TITLE
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("title must be a non-empty string")
    return title.strip()


def _serialize_object(value: dict[str, Any] | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be a dict or None")
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be JSON serializable") from exc


def _conversation_from_row(row: sqlite3.Row) -> Conversation:
    return Conversation(row["id"], row["title"], row["created_at"], row["updated_at"],
                        _deserialize_object(row["context_json"]), row["archived_at"], row["owner_user_id"] if "owner_user_id" in row.keys() else None)


def _message_from_row(row: sqlite3.Row) -> Message:
    return Message(row["id"], row["conversation_id"], row["role"], row["content"], row["created_at"],
                   _deserialize_object(row["metadata_json"]))


def _feedback_from_row(row: sqlite3.Row) -> Feedback:
    return Feedback(row["id"], row["message_id"], row["rating"], row["note"], row["created_at"])


def _deserialize_object(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value is not None else None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
