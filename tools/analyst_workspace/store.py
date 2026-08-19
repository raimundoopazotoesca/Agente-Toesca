"""SQLite persistence for conversations, messages, and current feedback.

This module owns only workspace state.  It never opens or references the
read-only real-estate knowledge database used by ``analyst_runtime``.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.analyst_workspace.models import Conversation, Feedback, Message

SCHEMA_VERSION = 1
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


class WorkspaceStore:
    """A short-lived-connection SQLite store for one local analyst workspace."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        """Create or validate schema version 1 without changing stored data."""
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
                    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        finally:
            conn.close()

    def create_conversation(
        self, context: dict[str, Any] | None = None, title: str | None = None
    ) -> Conversation:
        serialized_context = _serialize_object(context, "context")
        normalized_title = _normalize_title(title)
        now = _utc_now()
        conversation = Conversation(str(uuid4()), normalized_title, now, now, context, None)
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO conversation VALUES (?, ?, ?, ?, ?, ?)",
                    (conversation.id, conversation.title, conversation.created_at, conversation.updated_at,
                     serialized_context, conversation.archived_at),
                )
        finally:
            conn.close()
        return conversation

    def get_conversation(self, conversation_id: str) -> Conversation:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM conversation WHERE id = ?", (conversation_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ConversationNotFoundError(f"conversation not found: {conversation_id}")
        return _conversation_from_row(row)

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
                        _deserialize_object(row["context_json"]), row["archived_at"])


def _message_from_row(row: sqlite3.Row) -> Message:
    return Message(row["id"], row["conversation_id"], row["role"], row["content"], row["created_at"],
                   _deserialize_object(row["metadata_json"]))


def _feedback_from_row(row: sqlite3.Row) -> Feedback:
    return Feedback(row["id"], row["message_id"], row["rating"], row["note"], row["created_at"])


def _deserialize_object(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value is not None else None
