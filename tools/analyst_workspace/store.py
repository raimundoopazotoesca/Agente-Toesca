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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from werkzeug.security import check_password_hash, generate_password_hash

from tools.analyst_workspace.models import Conversation, Feedback, FeedbackReport, Message, ProductUpdate, preferred_name
from tools.analyst_workspace.percentile import average, nearest_rank_percentile

SCHEMA_VERSION = 9
DEFAULT_TITLE = "Nueva conversación"
_ROLES = {"user", "assistant"}
_RATINGS = {"up", "down"}
_REPORT_STATUSES = {"new", "reviewing", "resolved", "dismissed"}
# Only these keys from message.metadata_json are safe/expected to be copied into a
# feedback report's technical_context. Never widen this by just spreading the dict --
# new metadata fields must be reviewed before they can leave the workspace DB this way.
_SAFE_TECHNICAL_CONTEXT_KEYS = (
    "provider", "model", "latency_ms", "model_calls", "action_count", "sql_count",
    "tool_calls", "token_usage", "turn_metrics", "termination_reason",
    "presentation_applied", "presentation_provider", "presentation_model",
    "presentation_latency_ms", "presentation_integrity_status",
    "original_answer_hash", "presented_answer_hash",
)


class WorkspaceStoreError(Exception):
    """Base error for workspace persistence failures."""


class ConversationNotFoundError(WorkspaceStoreError):
    """Raised when a conversation id cannot be found."""


class MessageNotFoundError(WorkspaceStoreError):
    """Raised when a message id cannot be found."""


class FeedbackReportNotFoundError(WorkspaceStoreError):
    """Raised when a feedback report id cannot be found."""


class ValidationError(WorkspaceStoreError):
    """Raised for invalid store input before it is persisted."""


class AuthenticationError(WorkspaceStoreError):
    """Raised when a local account cannot authenticate."""


class ProductUpdateNotFoundError(WorkspaceStoreError):
    """Raised when a product update id cannot be found."""


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
                    version = 3
                if version < 4:
                    self._backup_before_durable_context_migration()
                    conn.executescript("""
                    CREATE TABLE analytical_turn (
                        id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversation(id),
                        user_message_id TEXT NOT NULL REFERENCES message(id),
                        assistant_message_id TEXT NOT NULL UNIQUE REFERENCES message(id), created_at TEXT NOT NULL
                    );
                    CREATE TABLE evidence_snapshot (
                        id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, evidence_class TEXT NOT NULL,
                        scope_json TEXT NOT NULL, provenance_json TEXT NOT NULL, coverage_json TEXT,
                        semantic_contract_json TEXT NOT NULL, source_json TEXT NOT NULL, facts_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE fact_claim (
                        id TEXT PRIMARY KEY, analytical_turn_id TEXT NOT NULL REFERENCES analytical_turn(id),
                        kind TEXT NOT NULL CHECK(kind IN ('fact','derived_fact')),
                        claim_key TEXT NOT NULL, metric_key TEXT, entity_id TEXT, period TEXT,
                        value REAL, unit TEXT, evidence_snapshot_id TEXT REFERENCES evidence_snapshot(id),
                        source_fingerprint TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
                    );
                    CREATE TABLE claim_dependency (
                        derived_claim_id TEXT NOT NULL REFERENCES fact_claim(id),
                        operand_claim_id TEXT NOT NULL REFERENCES fact_claim(id), ordinal INTEGER NOT NULL,
                        PRIMARY KEY (derived_claim_id, ordinal)
                    );
                    CREATE INDEX idx_analytical_turn_conversation_created ON analytical_turn(conversation_id, created_at DESC);
                    CREATE INDEX idx_fact_claim_turn ON fact_claim(analytical_turn_id);
                    """)
                    conn.execute("PRAGMA user_version = 4")
                    version = 4
                if version < 5:
                    conn.executescript("""
                    CREATE TABLE analytical_turn_evidence (
                        analytical_turn_id TEXT NOT NULL REFERENCES analytical_turn(id),
                        evidence_snapshot_id TEXT NOT NULL REFERENCES evidence_snapshot(id),
                        PRIMARY KEY (analytical_turn_id, evidence_snapshot_id)
                    );
                    CREATE INDEX idx_turn_evidence_turn ON analytical_turn_evidence(analytical_turn_id);
                    """)
                    conn.execute("PRAGMA user_version = 5")
                    version = 5
                if version < 6:
                    conn.executescript("""
                    ALTER TABLE conversation ADD COLUMN title_origin TEXT NOT NULL DEFAULT 'default'
                        CHECK(title_origin IN ('default', 'auto', 'manual'));
                    UPDATE conversation
                    SET title_origin = CASE WHEN title IN ('Nueva conversación', 'Nuevo chat') THEN 'default' ELSE 'manual' END;
                    """)
                    conn.execute("PRAGMA user_version = 6")
                    version = 6
                if version < 7:
                    conn.executescript("""
                    CREATE TABLE feedback_report (
                        id TEXT PRIMARY KEY,
                        reporter_user_id TEXT NOT NULL REFERENCES user(id),
                        reporter_display_name TEXT NOT NULL,
                        conversation_id TEXT NOT NULL REFERENCES conversation(id),
                        anchor_message_id TEXT NOT NULL REFERENCES message(id),
                        comment TEXT NOT NULL,
                        conversation_snapshot_json TEXT NOT NULL,
                        technical_context_json TEXT,
                        status TEXT NOT NULL DEFAULT 'new'
                            CHECK(status IN ('new', 'reviewing', 'resolved', 'dismissed')),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX idx_feedback_report_created ON feedback_report(created_at DESC, id DESC);
                    CREATE INDEX idx_feedback_report_reporter ON feedback_report(reporter_user_id);
                    CREATE INDEX idx_feedback_report_status ON feedback_report(status);
                    CREATE TABLE user_capability (
                        user_id TEXT NOT NULL REFERENCES user(id),
                        capability TEXT NOT NULL,
                        granted_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, capability)
                    );
                    """)
                    conn.execute("PRAGMA user_version = 7")
                    version = 7
                if version < 8:
                    # Additive: message-level thumbs feedback (v1). The existing `feedback`
                    # table already enforces UNIQUE(message_id) -- one row per message -- and
                    # every message belongs to exactly one conversation with exactly one
                    # owner, so that constraint already implies one current rating per
                    # user/message. `user_id` is added for explicit audit/reviewer
                    # attribution, not to relax or replace that invariant.
                    conn.executescript("""
                    ALTER TABLE feedback ADD COLUMN user_id TEXT REFERENCES user(id);
                    ALTER TABLE feedback ADD COLUMN updated_at TEXT;
                    """)
                    conn.execute(
                        """UPDATE feedback SET
                            user_id = (
                                SELECT c.owner_user_id FROM message m
                                JOIN conversation c ON c.id = m.conversation_id
                                WHERE m.id = feedback.message_id
                            ),
                            updated_at = created_at
                        WHERE user_id IS NULL"""
                    )
                    conn.executescript("""
                    CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id);
                    CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC, id DESC);
                    """)
                    conn.execute("PRAGMA user_version = 8")
                    version = 8
                if version < 9:
                    conn.executescript("""
                    CREATE TABLE product_update (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        body TEXT NOT NULL,
                        cta_label TEXT,
                        cta_config_json TEXT,
                        published_at TEXT,
                        active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE product_update_seen (
                        user_id TEXT NOT NULL REFERENCES user(id),
                        product_update_id TEXT NOT NULL REFERENCES product_update(id),
                        seen_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, product_update_id)
                    );
                    CREATE INDEX idx_product_update_visible
                        ON product_update(active, published_at DESC, id DESC);
                    CREATE INDEX idx_product_update_seen_user
                        ON product_update_seen(user_id);
                    """)
                    conn.execute("PRAGMA user_version = 9")
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
                title_origin = "default" if normalized_title == DEFAULT_TITLE else "manual"
                conversation = Conversation(conversation_id, normalized_title, now, now, context, None, owner, title_origin)
                conn.execute(
                    "INSERT INTO conversation (id,title,created_at,updated_at,context_json,archived_at,owner_user_id,title_origin) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (conversation.id, conversation.title, conversation.created_at, conversation.updated_at,
                     serialized_context, conversation.archived_at, owner, conversation.title_origin),
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

    def reset_user_password(self, username: str, new_password: str) -> str:
        """Administrative password rotation for an EXISTING account.

        Not an authenticated self-service endpoint -- no HTTP route calls
        this (see admin.py). Replaces password_hash only: username,
        display_name, role, is_active, conversation ownership and durable
        context ownership are all untouched. Existing sessions for this
        user are revoked in the same transaction, so a credential rotated
        away from (e.g. because it leaked) cannot keep an old session
        alive.
        """
        if not isinstance(new_password, str) or len(new_password) < 8:
            raise ValidationError("password must contain at least 8 characters")
        conn = self._connect()
        try:
            with conn:
                row = conn.execute("SELECT id FROM user WHERE username=?", (username.strip().lower(),)).fetchone()
                if row is None:
                    raise ValidationError("user does not exist")
                conn.execute("UPDATE user SET password_hash=?, updated_at=? WHERE id=?",
                             (generate_password_hash(new_password), _utc_now(), row["id"]))
                conn.execute("UPDATE user_session SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                             (_utc_now(), row["id"]))
                return row["id"]
        finally:
            conn.close()

    def authenticate(self, username: str, password: str) -> sqlite3.Row:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM user WHERE username = ?", (username.strip().lower(),)).fetchone()
        finally:
            conn.close()
        if row is None or not row["is_active"] or not check_password_hash(row["password_hash"], password):
            raise AuthenticationError("invalid credentials")
        return row

    def get_authenticated_user_context(self, user_id: str) -> dict[str, str]:
        """Return the minimal trusted identity context safe for the runtime."""
        conn = self._connect()
        try:
            row = self._require_user(conn, user_id)
            return {
                **{key: str(row[key]) for key in ("display_name", "username", "role")},
                "short_name": preferred_name(str(row["display_name"])),
            }
        finally:
            conn.close()

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
        """Set (create or replace) the caller's current rating on their own assistant message.

        This is the sole write path for thumbs feedback. Ownership of the
        conversation and the assistant-role of the message are re-checked
        here from authenticated state -- the caller only supplies
        message_id, rating (and an unused optional note). No LLM call, no
        tool call, no SQL against the knowledge DB, no new conversation
        message, no Durable Context mutation.
        """
        return self.set_feedback(message_id, rating, note, user_id=user_id, _scope_owner_id=user_id)

    def clear_feedback_for_user(self, message_id: str, user_id: str) -> None:
        """Remove the caller's current rating, if any. Idempotent: a repeat
        call when no rating exists is a safe no-op, not an error."""
        conn = self._connect()
        try:
            with conn:
                self._require_owned_assistant_message(conn, message_id, user_id)
                conn.execute("DELETE FROM feedback WHERE message_id = ? AND user_id = ?", (message_id, user_id))
        finally:
            conn.close()

    def get_feedback_for_user(self, message_id: str, user_id: str) -> Feedback | None:
        conn = self._connect()
        try:
            self._require_owned_assistant_message(conn, message_id, user_id)
            row = conn.execute(
                "SELECT * FROM feedback WHERE message_id = ? AND user_id = ?", (message_id, user_id)
            ).fetchone()
        finally:
            conn.close()
        return _feedback_from_row(row) if row is not None else None

    def list_feedback_for_conversation(self, conversation_id: str, user_id: str) -> dict[str, str]:
        """Return {message_id: rating} for the caller's own current ratings in
        one conversation -- used to hydrate the UI on load/reload."""
        conn = self._connect()
        try:
            self._get_conversation_scoped_conn(conn, conversation_id, user_id)
            rows = conn.execute(
                """SELECT f.message_id, f.rating FROM feedback f
                JOIN message m ON m.id = f.message_id
                WHERE m.conversation_id = ? AND f.user_id = ?""",
                (conversation_id, user_id),
            ).fetchall()
        finally:
            conn.close()
        return {row["message_id"]: row["rating"] for row in rows}

    def get_feedback_summary(self) -> dict[str, Any]:
        """Smallest useful reviewer read surface: counts only, no dashboard."""
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT
                    SUM(CASE WHEN rating='up' THEN 1 ELSE 0 END) AS up_count,
                    SUM(CASE WHEN rating='down' THEN 1 ELSE 0 END) AS down_count,
                    COUNT(*) AS total
                FROM feedback"""
            ).fetchone()
        finally:
            conn.close()
        up_count, down_count, total = row["up_count"] or 0, row["down_count"] or 0, row["total"] or 0
        return {
            "up_count": up_count,
            "down_count": down_count,
            "total_rated": total,
            "positive_rate": (up_count / total) if total else None,
        }

    def list_recent_feedback(self, limit: int = 20) -> list[dict[str, Any]]:
        """Smallest useful reviewer read surface: a short recent list, no analytics."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT f.message_id, f.rating, f.created_at, f.updated_at, f.user_id,
                    m.conversation_id, m.content AS assistant_content, u.display_name
                FROM feedback f
                JOIN message m ON m.id = f.message_id
                LEFT JOIN user u ON u.id = f.user_id
                ORDER BY f.updated_at DESC, f.created_at DESC, f.message_id DESC
                LIMIT ?""",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "message_id": row["message_id"],
                "conversation_id": row["conversation_id"],
                "rating": row["rating"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "user_id": row["user_id"],
                "user_display_name": row["display_name"],
                "assistant_content_preview": (row["assistant_content"] or "")[:140],
            }
            for row in rows
        ]

    def create_feedback_report_for_user(
        self, reporter_user_id: str, conversation_id: str, anchor_message_id: str, comment: str,
        release_revision: str | None = None,
    ) -> FeedbackReport:
        """Snapshot the visible conversation up to ``anchor_message_id`` and store a report.

        This is the sole write path for "Reportar problema". Everything here is
        derived from server-side/authenticated state -- the caller only supplies
        conversation_id, anchor_message_id, and comment. Ownership of the
        conversation and membership of the anchor message in that conversation
        are both re-checked here, not assumed from the caller.
        """
        if not isinstance(comment, str) or not comment.strip():
            raise ValidationError("comment is required")
        conn = self._connect()
        try:
            with conn:
                reporter = self._require_user(conn, reporter_user_id)
                conversation = conn.execute(
                    "SELECT id FROM conversation WHERE id=? AND owner_user_id=?",
                    (conversation_id, reporter_user_id),
                ).fetchone()
                if conversation is None:
                    raise ConversationNotFoundError("conversation not found")
                anchor = conn.execute(
                    "SELECT * FROM message WHERE id=? AND conversation_id=?",
                    (anchor_message_id, conversation_id),
                ).fetchone()
                if anchor is None:
                    raise MessageNotFoundError("message not found")
                if anchor["role"] != "assistant":
                    raise ValidationError("feedback can only be reported on an assistant response")
                rows = conn.execute(
                    "SELECT id, role, content, created_at FROM message WHERE conversation_id=? "
                    "ORDER BY created_at ASC, id ASC",
                    (conversation_id,),
                ).fetchall()
                snapshot: list[dict[str, Any]] = []
                for row in rows:
                    snapshot.append({
                        "message_id": row["id"], "role": row["role"],
                        "content": row["content"], "created_at": row["created_at"],
                    })
                    if row["id"] == anchor_message_id:
                        break
                metadata = _deserialize_object(anchor["metadata_json"]) or {}
                technical_context = {
                    key: metadata[key] for key in _SAFE_TECHNICAL_CONTEXT_KEYS if key in metadata
                }
                if release_revision:
                    technical_context["release_revision"] = release_revision
                now, report_id = _utc_now(), str(uuid4())
                conn.execute(
                    """INSERT INTO feedback_report
                    (id, reporter_user_id, reporter_display_name, conversation_id, anchor_message_id, comment,
                     conversation_snapshot_json, technical_context_json, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
                    (report_id, reporter_user_id, reporter["display_name"], conversation_id, anchor_message_id,
                     comment.strip(), json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                     json.dumps(technical_context, ensure_ascii=False, separators=(",", ":")) if technical_context else None,
                     now, now),
                )
        finally:
            conn.close()
        return self.get_feedback_report(report_id)

    def list_feedback_reports(self, status: str | None = None, reporter_user_id: str | None = None) -> list[FeedbackReport]:
        if status is not None and status not in _REPORT_STATUSES:
            raise ValidationError("invalid status filter")
        sql = "SELECT * FROM feedback_report WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if reporter_user_id:
            sql += " AND reporter_user_id = ?"
            params.append(reporter_user_id)
        sql += " ORDER BY created_at DESC, id DESC"
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [_feedback_report_from_row(row) for row in rows]

    def get_feedback_report(self, report_id: str) -> FeedbackReport:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM feedback_report WHERE id = ?", (report_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise FeedbackReportNotFoundError(f"feedback report not found: {report_id}")
        return _feedback_report_from_row(row)

    def update_feedback_report_status(self, report_id: str, status: str) -> FeedbackReport:
        if status not in _REPORT_STATUSES:
            raise ValidationError("status must be one of: " + ", ".join(sorted(_REPORT_STATUSES)))
        conn = self._connect()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE feedback_report SET status=?, updated_at=? WHERE id=?",
                    (status, _utc_now(), report_id),
                )
                if cursor.rowcount == 0:
                    raise FeedbackReportNotFoundError(f"feedback report not found: {report_id}")
                row = conn.execute("SELECT * FROM feedback_report WHERE id = ?", (report_id,)).fetchone()
        finally:
            conn.close()
        return _feedback_report_from_row(row)

    # ── Product updates ("Novedades") ──────────────────────────────────────
    # Pure product-discovery data: no analytical runtime, no LLM/tool calls,
    # no ties to conversations or evidence. Publishing is store/CLI-only --
    # there is no in-product write path for title/body/cta/publish state.

    def create_product_update(
        self, title: str, body: str, *, cta_label: str | None = None,
        cta_config: dict[str, Any] | None = None, publish: bool = False,
    ) -> ProductUpdate:
        if not isinstance(title, str) or not title.strip():
            raise ValidationError("title is required")
        if not isinstance(body, str) or not body.strip():
            raise ValidationError("body is required")
        if cta_label is not None and (not isinstance(cta_label, str) or not cta_label.strip()):
            raise ValidationError("cta_label must be a non-blank string or None")
        serialized_cta = _serialize_object(cta_config, "cta_config")
        now, update_id = _utc_now(), str(uuid4())
        published_at = now if publish else None
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO product_update (id, title, body, cta_label, cta_config_json, published_at, active, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (update_id, title.strip(), body.strip(), cta_label.strip() if cta_label else None,
                     serialized_cta, published_at, now, now),
                )
        finally:
            conn.close()
        return self.get_product_update(update_id)

    def get_product_update(self, update_id: str) -> ProductUpdate:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM product_update WHERE id=?", (update_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ProductUpdateNotFoundError(f"product update not found: {update_id}")
        return _product_update_from_row(row)

    def deactivate_product_update(self, update_id: str) -> ProductUpdate:
        conn = self._connect()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE product_update SET active=0, updated_at=? WHERE id=?", (_utc_now(), update_id)
                )
                if cursor.rowcount == 0:
                    raise ProductUpdateNotFoundError(f"product update not found: {update_id}")
        finally:
            conn.close()
        return self.get_product_update(update_id)

    def list_product_updates_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Published+active updates, newest first, annotated with this user's seen state."""
        now = _utc_now()
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT pu.*, pus.seen_at AS user_seen_at
                FROM product_update pu
                LEFT JOIN product_update_seen pus
                    ON pus.product_update_id = pu.id AND pus.user_id = ?
                WHERE pu.active = 1 AND pu.published_at IS NOT NULL AND pu.published_at <= ?
                ORDER BY pu.published_at DESC, pu.id DESC""",
                (user_id, now),
            ).fetchall()
        finally:
            conn.close()
        return [_product_update_view(row) for row in rows]

    def count_unseen_product_updates_for_user(self, user_id: str) -> int:
        now = _utc_now()
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT COUNT(*) AS n
                FROM product_update pu
                LEFT JOIN product_update_seen pus
                    ON pus.product_update_id = pu.id AND pus.user_id = ?
                WHERE pu.active = 1 AND pu.published_at IS NOT NULL AND pu.published_at <= ?
                    AND pus.seen_at IS NULL""",
                (user_id, now),
            ).fetchone()
        finally:
            conn.close()
        return int(row["n"])

    def mark_product_update_seen_for_user(self, update_id: str, user_id: str) -> None:
        """Idempotent: marking the same update seen twice by the same user is a no-op."""
        conn = self._connect()
        try:
            with conn:
                self._require_user(conn, user_id)
                exists = conn.execute("SELECT 1 FROM product_update WHERE id=?", (update_id,)).fetchone()
                if exists is None:
                    raise ProductUpdateNotFoundError(f"product update not found: {update_id}")
                conn.execute(
                    "INSERT INTO product_update_seen (user_id, product_update_id, seen_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(user_id, product_update_id) DO NOTHING",
                    (user_id, update_id, _utc_now()),
                )
        finally:
            conn.close()

    def grant_capability(self, user_id: str, capability: str) -> None:
        if not isinstance(capability, str) or not capability.strip():
            raise ValidationError("capability is required")
        conn = self._connect()
        try:
            with conn:
                self._require_user(conn, user_id)
                conn.execute(
                    "INSERT INTO user_capability (user_id, capability, granted_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(user_id, capability) DO NOTHING",
                    (user_id, capability.strip(), _utc_now()),
                )
        finally:
            conn.close()

    def revoke_capability(self, user_id: str, capability: str) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM user_capability WHERE user_id=? AND capability=?", (user_id, capability)
                )
        finally:
            conn.close()

    def user_has_capability(self, user_id: str, capability: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM user_capability WHERE user_id=? AND capability=?", (user_id, capability)
            ).fetchone()
        finally:
            conn.close()
        return row is not None

    def get_user_id_by_username(self, username: str) -> str:
        conn = self._connect()
        try:
            row = conn.execute("SELECT id FROM user WHERE username=?", (username.strip().lower(),)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ValidationError("user does not exist")
        return row["id"]

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
        return self._update_conversation(conversation_id, "title = ?, title_origin = 'manual'", (normalized_title,))

    def auto_title_conversation(self, conversation_id: str, title: str) -> Conversation:
        normalized_title = _normalize_title(title)
        now = _utc_now()
        conn = self._connect()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE conversation SET title=?, title_origin='auto', updated_at=? WHERE id=? AND title_origin='default'",
                    (normalized_title, now, conversation_id),
                )
                if cursor.rowcount == 0:
                    self._require_conversation(conn, conversation_id)
            return self.get_conversation(conversation_id)
        finally:
            conn.close()

    def archive_conversation(self, conversation_id: str) -> Conversation:
        return self._update_conversation(conversation_id, "archived_at = ?", (_utc_now(),))

    def unarchive_conversation(self, conversation_id: str) -> Conversation:
        return self._update_conversation(conversation_id, "archived_at = NULL", ())

    def append_message(
        self, conversation_id: str, role: str, content: str, metadata: dict[str, Any] | None = None,
        *, message_id: str | None = None,
    ) -> Message:
        if role not in _ROLES:
            raise ValidationError("role must be 'user' or 'assistant'")
        if not isinstance(content, str):
            raise ValidationError("content must be a string")
        serialized_metadata = _serialize_object(metadata, "metadata")
        now = _utc_now()
        message = Message(message_id or str(uuid4()), conversation_id, role, content, now, metadata)
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

    def persist_analytical_turn(self, conversation_id: str, user_message_id: str, assistant_message_id: str,
                                memory: dict[str, Any]) -> None:
        """Persist validated structured facts, never prose or provider payloads."""
        if not isinstance(memory, dict):
            raise ValidationError("analytical memory must be a dict")
        evidence = memory.get("evidence", [])
        envelope = memory.get("envelope", {})
        if not isinstance(evidence, list) or not isinstance(envelope, dict):
            raise ValidationError("analytical memory is invalid")
        conn = self._connect()
        try:
            with conn:
                self._require_conversation(conn, conversation_id)
                if conn.execute("SELECT 1 FROM analytical_turn WHERE assistant_message_id=?", (assistant_message_id,)).fetchone():
                    return
                now, turn_id = _utc_now(), str(uuid4())
                conn.execute("INSERT INTO analytical_turn VALUES (?, ?, ?, ?, ?)",
                             (turn_id, conversation_id, user_message_id, assistant_message_id, now))
                evidence_ids: dict[str, str] = {}
                for item in evidence:
                    if not isinstance(item, dict) or not isinstance(item.get("evidence_id"), str):
                        continue
                    compact = {key: item.get(key) for key in ("evidence_class", "source", "scope", "semantic_contract", "provenance", "coverage", "facts")}
                    fingerprint = hashlib.sha256(json.dumps(compact, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
                    row = conn.execute("SELECT id FROM evidence_snapshot WHERE fingerprint=?", (fingerprint,)).fetchone()
                    snapshot_id = row["id"] if row else str(uuid4())
                    if row is None:
                        conn.execute("INSERT INTO evidence_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                            snapshot_id, fingerprint, str(item.get("evidence_class", "unknown")),
                            _serialize_object(item.get("scope") or {}, "scope"), _serialize_object(item.get("provenance") or {}, "provenance"),
                            _serialize_object(item.get("coverage"), "coverage"), _serialize_object(item.get("semantic_contract") or {}, "semantic_contract"),
                            _serialize_object(item.get("source") or {}, "source"), json.dumps(item.get("facts") or [], ensure_ascii=False, separators=(",", ":")), now))
                    evidence_ids[item["evidence_id"]] = snapshot_id
                    conn.execute("INSERT OR IGNORE INTO analytical_turn_evidence VALUES (?, ?)", (turn_id, snapshot_id))
                claim_ids: dict[str, str] = {}
                for claim in envelope.get("canonical_metric_claims", []):
                    if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str): continue
                    claim_id = str(uuid4()); claim_ids[claim["claim_id"]] = claim_id
                    snapshot_id = evidence_ids.get(claim.get("evidence_id"))
                    source = conn.execute("SELECT fingerprint FROM evidence_snapshot WHERE id=?", (snapshot_id,)).fetchone() if snapshot_id else None
                    conn.execute("INSERT INTO fact_claim VALUES (?, ?, 'fact', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (claim_id, turn_id, claim["claim_id"], claim.get("metric_key"), claim.get("entity_id"), claim.get("period"), claim.get("value"), claim.get("unit"), snapshot_id, source["fingerprint"] if source else None, _serialize_object(claim, "claim"), now))
                for claim in envelope.get("derived_metric_claims", []):
                    if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str): continue
                    claim_id = str(uuid4()); claim_ids[claim["claim_id"]] = claim_id
                    conn.execute("INSERT INTO fact_claim VALUES (?, ?, 'derived_fact', ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?)",
                        (claim_id, turn_id, claim["claim_id"], _serialize_object(claim, "claim"), now))
                    for ordinal, operand in enumerate((claim.get("lhs_claim_id"), claim.get("rhs_claim_id"))):
                        if operand in claim_ids: conn.execute("INSERT INTO claim_dependency VALUES (?, ?, ?)", (claim_id, claim_ids[operand], ordinal))
        finally:
            conn.close()

    def load_durable_context_for_user(self, conversation_id: str, user_id: str, limit: int = 24) -> dict[str, Any]:
        self._get_conversation_scoped(conversation_id, user_id)
        conn = self._connect()
        try:
            rows = conn.execute("""SELECT fc.*, es.evidence_class, es.source_json, es.scope_json, es.semantic_contract_json,
                es.provenance_json, es.coverage_json, es.facts_json FROM fact_claim fc
                JOIN analytical_turn at ON at.id=fc.analytical_turn_id LEFT JOIN evidence_snapshot es ON es.id=fc.evidence_snapshot_id
                WHERE at.conversation_id=? ORDER BY at.created_at DESC, fc.created_at DESC LIMIT ?""", (conversation_id, limit)).fetchall()
            evidence_rows = conn.execute("""SELECT DISTINCT es.* FROM analytical_turn at
                JOIN analytical_turn_evidence ate ON ate.analytical_turn_id=at.id JOIN evidence_snapshot es ON es.id=ate.evidence_snapshot_id
                WHERE at.conversation_id=? ORDER BY at.created_at DESC LIMIT ?""", (conversation_id, limit)).fetchall()
        finally:
            conn.close()
        evidence_by_id, claims, derived_claims = {}, [], []
        for row in reversed(rows):
            payload = _deserialize_object(row["payload_json"]) or {}
            payload["claim_id"] = row["claim_key"]
            if row["evidence_snapshot_id"]:
                payload["evidence_id"] = row["evidence_snapshot_id"]
            (derived_claims if row["kind"] == "derived_fact" else claims).append(payload)
            if row["evidence_snapshot_id"] and row["evidence_snapshot_id"] not in evidence_by_id:
                evidence_by_id[row["evidence_snapshot_id"]] = {"evidence_id": row["evidence_snapshot_id"], "evidence_class": row["evidence_class"],
                    "source": _deserialize_object(row["source_json"]) or {}, "scope": _deserialize_object(row["scope_json"]) or {},
                    "semantic_contract": _deserialize_object(row["semantic_contract_json"]) or {}, "provenance": _deserialize_object(row["provenance_json"]) or {},
                    "coverage": _deserialize_object(row["coverage_json"]), "facts": json.loads(row["facts_json"])}
        for row in evidence_rows:
            evidence_by_id.setdefault(row["id"], {"evidence_id": row["id"], "evidence_class": row["evidence_class"],
                "source": _deserialize_object(row["source_json"]) or {}, "scope": _deserialize_object(row["scope_json"]) or {},
                "semantic_contract": _deserialize_object(row["semantic_contract_json"]) or {}, "provenance": _deserialize_object(row["provenance_json"]) or {},
                "coverage": _deserialize_object(row["coverage_json"]), "facts": json.loads(row["facts_json"])})
        return {"claims": claims, "derived_claims": derived_claims, "evidence": list(evidence_by_id.values())}

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

    def set_feedback(
        self, message_id: str, rating: str, note: str | None = None, *,
        user_id: str | None = None, _scope_owner_id: str | None = None,
    ) -> Feedback:
        if rating not in _RATINGS:
            raise ValidationError("rating must be 'up' or 'down'")
        if note is not None and not isinstance(note, str):
            raise ValidationError("note must be a string or None")
        conn = self._connect()
        try:
            with conn:
                if _scope_owner_id is not None:
                    self._require_owned_assistant_message(conn, message_id, _scope_owner_id)
                else:
                    message = self._require_message(conn, message_id)
                    if message["role"] != "assistant":
                        raise ValidationError("feedback is only supported for assistant messages")
                existing = conn.execute("SELECT id FROM feedback WHERE message_id = ?", (message_id,)).fetchone()
                feedback_id = existing["id"] if existing else str(uuid4())
                now = _utc_now()
                conn.execute(
                    """INSERT INTO feedback (id, message_id, user_id, rating, note, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(message_id) DO UPDATE SET rating = excluded.rating, note = excluded.note,
                    user_id = excluded.user_id, created_at = excluded.created_at, updated_at = excluded.updated_at""",
                    (feedback_id, message_id, user_id, rating, note, now, now),
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

    # -- Pilot Control Center (v1) -- read-only observer queries -----------
    #
    # Everything below is derived entirely from existing tables (user,
    # conversation, message, feedback_report). No new schema. All queries
    # are plain SELECTs -- pilot scale is tiny so no aggregation infra is
    # needed. Never expose password_hash, session tokens, or raw
    # sql_queries text from message.metadata_json -- see
    # `_safe_turn_diagnostics` which applies the same allowlist used for
    # feedback_report.technical_context (_SAFE_TECHNICAL_CONTEXT_KEYS).

    def pilot_overview(self) -> dict[str, Any]:
        """Aggregate usage/quality snapshot for the Pilot Control Center."""
        now = _utc_now()
        today_start = _utc_day_start(now)
        window_7d_start = _utc_offset(now, days=-7)
        conn = self._connect()
        try:
            total_users = conn.execute("SELECT COUNT(*) AS n FROM user").fetchone()["n"]
            active_today = conn.execute(
                """SELECT COUNT(DISTINCT c.owner_user_id) AS n FROM message m
                   JOIN conversation c ON c.id = m.conversation_id
                   WHERE m.role='user' AND m.created_at >= ?""",
                (today_start,),
            ).fetchone()["n"]
            active_7d = conn.execute(
                """SELECT COUNT(DISTINCT c.owner_user_id) AS n FROM message m
                   JOIN conversation c ON c.id = m.conversation_id
                   WHERE m.role='user' AND m.created_at >= ?""",
                (window_7d_start,),
            ).fetchone()["n"]
            conversations_today = conn.execute(
                """SELECT COUNT(DISTINCT m.conversation_id) AS n FROM message m
                   WHERE m.created_at >= ?""",
                (today_start,),
            ).fetchone()["n"]
            conversations_7d = conn.execute(
                """SELECT COUNT(DISTINCT m.conversation_id) AS n FROM message m
                   WHERE m.created_at >= ?""",
                (window_7d_start,),
            ).fetchone()["n"]
            user_msgs_today = conn.execute(
                "SELECT COUNT(*) AS n FROM message WHERE role='user' AND created_at >= ?", (today_start,)
            ).fetchone()["n"]
            user_msgs_7d = conn.execute(
                "SELECT COUNT(*) AS n FROM message WHERE role='user' AND created_at >= ?", (window_7d_start,)
            ).fetchone()["n"]
            assistant_msgs_today = conn.execute(
                "SELECT COUNT(*) AS n FROM message WHERE role='assistant' AND created_at >= ?", (today_start,)
            ).fetchone()["n"]
            assistant_msgs_7d = conn.execute(
                "SELECT COUNT(*) AS n FROM message WHERE role='assistant' AND created_at >= ?", (window_7d_start,)
            ).fetchone()["n"]
            reports_new = conn.execute("SELECT COUNT(*) AS n FROM feedback_report WHERE status='new'").fetchone()["n"]
            reports_total = conn.execute("SELECT COUNT(*) AS n FROM feedback_report").fetchone()["n"]
            latency_rows = conn.execute(
                "SELECT metadata_json FROM message WHERE role='assistant' AND metadata_json IS NOT NULL"
            ).fetchall()
            rating_counts = _rating_counts_overview(conn)
        finally:
            conn.close()
        latencies = _extract_latencies(latency_rows)
        return {
            "total_users": total_users,
            "active_users_today": active_today,
            "active_users_7d": active_7d,
            "conversations_today": conversations_today,
            "conversations_7d": conversations_7d,
            "user_messages_today": user_msgs_today,
            "user_messages_7d": user_msgs_7d,
            "assistant_responses_today": assistant_msgs_today,
            "assistant_responses_7d": assistant_msgs_7d,
            "reports_new": reports_new,
            "reports_total": reports_total,
            "latency_ms": _latency_summary(latencies),
            "rating_counts": rating_counts,
            "generated_at": now,
        }

    def list_pilot_users(self) -> list[dict[str, Any]]:
        """Per-user usage metrics for the Users view. Never returns password_hash/sessions."""
        conn = self._connect()
        try:
            users = conn.execute(
                "SELECT id, username, display_name, role, is_active, created_at FROM user ORDER BY created_at ASC"
            ).fetchall()
            convo_counts = {r["owner_user_id"]: r["n"] for r in conn.execute(
                "SELECT owner_user_id, COUNT(*) AS n FROM conversation GROUP BY owner_user_id"
            ).fetchall()}
            msg_counts = conn.execute(
                """SELECT c.owner_user_id AS owner_user_id, m.role AS role, COUNT(*) AS n
                   FROM message m JOIN conversation c ON c.id = m.conversation_id
                   GROUP BY c.owner_user_id, m.role"""
            ).fetchall()
            last_activity = {r["owner_user_id"]: r["last_at"] for r in conn.execute(
                """SELECT c.owner_user_id AS owner_user_id, MAX(m.created_at) AS last_at
                   FROM message m JOIN conversation c ON c.id = m.conversation_id
                   WHERE m.role='user' GROUP BY c.owner_user_id"""
            ).fetchall()}
            report_counts = {r["reporter_user_id"]: r["n"] for r in conn.execute(
                "SELECT reporter_user_id, COUNT(*) AS n FROM feedback_report GROUP BY reporter_user_id"
            ).fetchall()}
            latency_by_owner: dict[str, list[dict[str, Any]]] = {}
            for row in conn.execute(
                """SELECT c.owner_user_id AS owner_user_id, m.metadata_json AS metadata_json
                   FROM message m JOIN conversation c ON c.id = m.conversation_id
                   WHERE m.role='assistant' AND m.metadata_json IS NOT NULL"""
            ).fetchall():
                latency_by_owner.setdefault(row["owner_user_id"], []).append(row)
            rating_by_owner = _rating_summary_by_owner(conn)
        finally:
            conn.close()
        user_msg_by_owner: dict[str, int] = {}
        assistant_msg_by_owner: dict[str, int] = {}
        for row in msg_counts:
            target = user_msg_by_owner if row["role"] == "user" else assistant_msg_by_owner
            target[row["owner_user_id"]] = row["n"]
        result = []
        for u in users:
            uid = u["id"]
            latencies = _extract_latencies(latency_by_owner.get(uid, []))
            result.append({
                "id": uid,
                "username": u["username"],
                "display_name": u["display_name"],
                "role": u["role"],
                "is_active": bool(u["is_active"]),
                "created_at": u["created_at"],
                "last_activity": last_activity.get(uid),
                "conversation_count": convo_counts.get(uid, 0),
                "user_message_count": user_msg_by_owner.get(uid, 0),
                "assistant_response_count": assistant_msg_by_owner.get(uid, 0),
                "report_count": report_counts.get(uid, 0),
                "latency_ms": _latency_summary(latencies),
                "rating_summary": rating_by_owner.get(uid),
            })
        return result

    def get_pilot_user_detail(self, user_id: str, *, recent_conversations_limit: int = 20) -> dict[str, Any] | None:
        """Summary + recent conversations for one pilot user (Users -> detail drill-down)."""
        conn = self._connect()
        try:
            user_row = conn.execute(
                "SELECT id, username, display_name, role, is_active, created_at FROM user WHERE id=?", (user_id,)
            ).fetchone()
            if user_row is None:
                return None
            conversations = conn.execute(
                """SELECT id, title, created_at, updated_at, archived_at
                   FROM conversation WHERE owner_user_id=?
                   ORDER BY updated_at DESC, created_at DESC, id DESC LIMIT ?""",
                (user_id, recent_conversations_limit),
            ).fetchall()
            conv_ids = [c["id"] for c in conversations]
            msg_counts_by_conv: dict[str, dict[str, int]] = {}
            latency_by_conv: dict[str, list[dict[str, Any]]] = {}
            if conv_ids:
                placeholders = ",".join("?" for _ in conv_ids)
                for row in conn.execute(
                    f"""SELECT conversation_id, role, COUNT(*) AS n FROM message
                        WHERE conversation_id IN ({placeholders}) GROUP BY conversation_id, role""",
                    conv_ids,
                ).fetchall():
                    msg_counts_by_conv.setdefault(row["conversation_id"], {})[row["role"]] = row["n"]
                for row in conn.execute(
                    f"""SELECT conversation_id, metadata_json FROM message
                        WHERE conversation_id IN ({placeholders}) AND role='assistant'
                        AND metadata_json IS NOT NULL""",
                    conv_ids,
                ).fetchall():
                    latency_by_conv.setdefault(row["conversation_id"], []).append(row)
            report_counts_by_conv = {}
            if conv_ids:
                placeholders = ",".join("?" for _ in conv_ids)
                report_counts_by_conv = {r["conversation_id"]: r["n"] for r in conn.execute(
                    f"""SELECT conversation_id, COUNT(*) AS n FROM feedback_report
                        WHERE conversation_id IN ({placeholders}) GROUP BY conversation_id""",
                    conv_ids,
                ).fetchall()}
            last_activity_row = conn.execute(
                """SELECT MAX(m.created_at) AS last_at FROM message m JOIN conversation c ON c.id=m.conversation_id
                   WHERE c.owner_user_id=? AND m.role='user'""",
                (user_id,),
            ).fetchone()
            report_total = conn.execute(
                "SELECT COUNT(*) AS n FROM feedback_report WHERE reporter_user_id=?", (user_id,)
            ).fetchone()["n"]
            all_latencies: list[dict[str, Any]] = []
            for rows in latency_by_conv.values():
                all_latencies.extend(rows)
            rating_by_conv = _rating_summary_by_conversation(conn, conv_ids)
            user_rating_summary = _rating_summary_by_owner(conn).get(user_id)
        finally:
            conn.close()
        conv_list = []
        for c in conversations:
            counts = msg_counts_by_conv.get(c["id"], {})
            conv_list.append({
                "id": c["id"],
                "title": c["title"],
                "created_at": c["created_at"],
                "updated_at": c["updated_at"],
                "archived": c["archived_at"] is not None,
                "user_message_count": counts.get("user", 0),
                "assistant_message_count": counts.get("assistant", 0),
                "report_count": report_counts_by_conv.get(c["id"], 0),
                "latency_ms": _latency_summary(_extract_latencies(latency_by_conv.get(c["id"], []))),
                "rating_summary": rating_by_conv.get(c["id"]),
            })
        return {
            "id": user_row["id"],
            "username": user_row["username"],
            "display_name": user_row["display_name"],
            "role": user_row["role"],
            "is_active": bool(user_row["is_active"]),
            "created_at": user_row["created_at"],
            "last_activity": last_activity_row["last_at"] if last_activity_row else None,
            "report_count": report_total,
            "latency_ms": _latency_summary(_extract_latencies(all_latencies)),
            "recent_conversations": conv_list,
            "rating_summary": user_rating_summary,
        }

    def list_pilot_conversations(
        self,
        *,
        user_id: str | None = None,
        since: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Global conversation browser (across all owners) for the Control Center.

        `since` is an ISO timestamp lower bound compared against `updated_at`.
        `search` is a case-insensitive substring match against the title.
        """
        clauses = ["1=1"]
        params: list[Any] = []
        if user_id:
            clauses.append("c.owner_user_id = ?")
            params.append(user_id)
        if since:
            clauses.append("c.updated_at >= ?")
            params.append(since)
        if search:
            clauses.append("LOWER(c.title) LIKE ?")
            params.append(f"%{search.strip().lower()}%")
        where = " AND ".join(clauses)
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""SELECT c.id, c.title, c.created_at, c.updated_at, c.archived_at,
                           c.owner_user_id, u.display_name, u.username
                    FROM conversation c JOIN user u ON u.id = c.owner_user_id
                    WHERE {where}
                    ORDER BY c.updated_at DESC, c.created_at DESC, c.id DESC
                    LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            ).fetchall()
            conv_ids = [r["id"] for r in rows]
            msg_counts_by_conv: dict[str, dict[str, int]] = {}
            latency_by_conv: dict[str, list[dict[str, Any]]] = {}
            report_counts_by_conv: dict[str, int] = {}
            if conv_ids:
                placeholders = ",".join("?" for _ in conv_ids)
                for row in conn.execute(
                    f"""SELECT conversation_id, role, COUNT(*) AS n FROM message
                        WHERE conversation_id IN ({placeholders}) GROUP BY conversation_id, role""",
                    conv_ids,
                ).fetchall():
                    msg_counts_by_conv.setdefault(row["conversation_id"], {})[row["role"]] = row["n"]
                for row in conn.execute(
                    f"""SELECT conversation_id, metadata_json FROM message
                        WHERE conversation_id IN ({placeholders}) AND role='assistant'
                        AND metadata_json IS NOT NULL""",
                    conv_ids,
                ).fetchall():
                    latency_by_conv.setdefault(row["conversation_id"], []).append(row)
                report_counts_by_conv = {r["conversation_id"]: r["n"] for r in conn.execute(
                    f"""SELECT conversation_id, COUNT(*) AS n FROM feedback_report
                        WHERE conversation_id IN ({placeholders}) GROUP BY conversation_id""",
                    conv_ids,
                ).fetchall()}
            rating_by_conv = _rating_summary_by_conversation(conn, conv_ids)
        finally:
            conn.close()
        result = []
        for r in rows:
            counts = msg_counts_by_conv.get(r["id"], {})
            result.append({
                "id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "archived": r["archived_at"] is not None,
                "owner_user_id": r["owner_user_id"],
                "owner_display_name": r["display_name"],
                "owner_username": r["username"],
                "user_message_count": counts.get("user", 0),
                "assistant_message_count": counts.get("assistant", 0),
                "report_count": report_counts_by_conv.get(r["id"], 0),
                "latency_ms": _latency_summary(_extract_latencies(latency_by_conv.get(r["id"], []))),
                "rating_summary": rating_by_conv.get(r["id"]),
            })
        return result

    def get_pilot_conversation_detail(self, conversation_id: str) -> dict[str, Any] | None:
        """Read-only conversation viewer for the Control Center: transcript + safe diagnostics."""
        conn = self._connect()
        try:
            conv = conn.execute(
                """SELECT c.id, c.title, c.created_at, c.updated_at, c.archived_at,
                          c.owner_user_id, u.display_name, u.username
                   FROM conversation c JOIN user u ON u.id = c.owner_user_id WHERE c.id=?""",
                (conversation_id,),
            ).fetchone()
            if conv is None:
                return None
            messages = conn.execute(
                "SELECT id, role, content, created_at, metadata_json FROM message WHERE conversation_id=? "
                "ORDER BY created_at ASC, id ASC",
                (conversation_id,),
            ).fetchall()
            reports = conn.execute(
                """SELECT id, anchor_message_id, comment, status, created_at, updated_at, reporter_display_name
                   FROM feedback_report WHERE conversation_id=? ORDER BY created_at ASC""",
                (conversation_id,),
            ).fetchall()
            message_ratings = _message_ratings_for_conversation(conn, conversation_id)
            rating_summary = _rating_summary_by_conversation(conn, [conversation_id]).get(conversation_id)
        finally:
            conn.close()
        reports_by_anchor: dict[str, list[dict[str, Any]]] = {}
        for r in reports:
            reports_by_anchor.setdefault(r["anchor_message_id"], []).append({
                "id": r["id"],
                "status": r["status"],
                "comment": r["comment"],
                "reporter_display_name": r["reporter_display_name"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            })
        message_list = []
        for m in messages:
            entry = {
                "id": m["id"],
                "role": m["role"],
                "content": m["content"],
                "created_at": m["created_at"],
                "reports": reports_by_anchor.get(m["id"], []),
            }
            if m["role"] == "assistant":
                entry["diagnostics"] = _safe_turn_diagnostics(m["metadata_json"])
                entry["rating"] = message_ratings.get(m["id"])
            message_list.append(entry)
        return {
            "id": conv["id"],
            "title": conv["title"],
            "created_at": conv["created_at"],
            "updated_at": conv["updated_at"],
            "archived": conv["archived_at"] is not None,
            "owner_user_id": conv["owner_user_id"],
            "owner_display_name": conv["display_name"],
            "owner_username": conv["username"],
            "messages": message_list,
            "rating_summary": rating_summary,
        }

    def list_latest_pilot_questions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Recent USER messages across all pilot users, newest first (Latest Questions feed)."""
        limit = max(1, min(int(limit), 200))
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT m.id AS message_id, m.content, m.created_at, m.conversation_id,
                          c.title AS conversation_title, c.owner_user_id, u.display_name, u.username
                   FROM message m
                   JOIN conversation c ON c.id = m.conversation_id
                   JOIN user u ON u.id = c.owner_user_id
                   WHERE m.role='user'
                   ORDER BY m.created_at DESC, m.id DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [{
            "message_id": r["message_id"],
            "content": r["content"],
            "created_at": r["created_at"],
            "conversation_id": r["conversation_id"],
            "conversation_title": r["conversation_title"],
            "owner_user_id": r["owner_user_id"],
            "owner_display_name": r["display_name"],
            "owner_username": r["username"],
        } for r in rows]


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

    def _backup_before_durable_context_migration(self) -> None:
        backup = self.db_path.with_suffix(self.db_path.suffix + ".pre_durable_context_v1.bak")
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

    @staticmethod
    def _get_conversation_scoped_conn(conn: sqlite3.Connection, conversation_id: str, user_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM conversation WHERE id=? AND owner_user_id=?", (conversation_id, user_id)
        ).fetchone()
        if row is None:
            raise ConversationNotFoundError("conversation not found")
        return row

    @staticmethod
    def _require_owned_assistant_message(conn: sqlite3.Connection, message_id: str, user_id: str) -> sqlite3.Row:
        """Fail safely (404) for a foreign/nonexistent message and (400) for a
        user-authored one -- never trusting the client's conversation/message
        pairing, always re-deriving ownership from the message's own conversation."""
        row = conn.execute(
            """SELECT m.* FROM message m JOIN conversation c ON c.id = m.conversation_id
            WHERE m.id = ? AND c.owner_user_id = ?""",
            (message_id, user_id),
        ).fetchone()
        if row is None:
            raise MessageNotFoundError("message not found")
        if row["role"] != "assistant":
            raise ValidationError("feedback is only supported for assistant messages")
        return row

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
                        _deserialize_object(row["context_json"]), row["archived_at"], row["owner_user_id"] if "owner_user_id" in row.keys() else None,
                        row["title_origin"] if "title_origin" in row.keys() else "default")


def _message_from_row(row: sqlite3.Row) -> Message:
    return Message(row["id"], row["conversation_id"], row["role"], row["content"], row["created_at"],
                   _deserialize_object(row["metadata_json"]))


def _feedback_from_row(row: sqlite3.Row) -> Feedback:
    keys = row.keys()
    return Feedback(
        row["id"], row["message_id"], row["rating"], row["note"], row["created_at"],
        row["user_id"] if "user_id" in keys else None,
        row["updated_at"] if "updated_at" in keys else None,
    )


def _feedback_report_from_row(row: sqlite3.Row) -> FeedbackReport:
    return FeedbackReport(
        row["id"], row["reporter_user_id"], row["reporter_display_name"], row["conversation_id"],
        row["anchor_message_id"], row["comment"], json.loads(row["conversation_snapshot_json"]),
        _deserialize_object(row["technical_context_json"]), row["status"], row["created_at"], row["updated_at"],
    )


def _deserialize_object(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value is not None else None


def _product_update_from_row(row: sqlite3.Row) -> ProductUpdate:
    return ProductUpdate(
        row["id"], row["title"], row["body"], row["cta_label"],
        _deserialize_object(row["cta_config_json"]), row["published_at"], bool(row["active"]),
        row["created_at"], row["updated_at"],
    )


def _product_update_view(row: sqlite3.Row) -> dict[str, Any]:
    """Shape a joined product_update + per-user seen row for the API/UI.

    Deliberately excludes internal fields (``active``) -- only
    published+active rows reach this helper's caller in the first place.
    """
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "cta_label": row["cta_label"],
        "cta_config": _deserialize_object(row["cta_config_json"]),
        "published_at": row["published_at"],
        "created_at": row["created_at"],
        "seen": row["user_seen_at"] is not None,
        "seen_at": row["user_seen_at"],
    }


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_day_start(now_iso: str) -> str:
    """Start of the UTC calendar day containing ``now_iso`` (same string format as _utc_now)."""
    date_part = now_iso.split("T", 1)[0]
    return f"{date_part}T00:00:00.000000Z"


def _utc_offset(now_iso: str, *, days: int) -> str:
    """``now_iso`` shifted by ``days`` (can be negative), same string format as _utc_now."""
    dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    shifted = dt + timedelta(days=days)
    return shifted.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _extract_latencies(metadata_rows: list[sqlite3.Row]) -> list[float]:
    """Pull ``latency_ms`` out of each row's metadata_json, skipping missing/invalid values.

    Rows without telemetry are excluded from the sample entirely -- never treated as zero.
    """
    values: list[float] = []
    for row in metadata_rows:
        raw = row["metadata_json"] if "metadata_json" in row.keys() else None
        if not raw:
            continue
        try:
            metadata = json.loads(raw)
        except (TypeError, ValueError):
            continue
        latency = metadata.get("latency_ms") if isinstance(metadata, dict) else None
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            values.append(float(latency))
    return values


def _latency_summary(latencies: list[float]) -> dict[str, Any]:
    return {
        "sample_size": len(latencies),
        "avg_ms": average(latencies),
        "p50_ms": nearest_rank_percentile(latencies, 50),
        "p90_ms": nearest_rank_percentile(latencies, 90),
    }


def _safe_turn_diagnostics(metadata_json: str | None) -> dict[str, Any] | None:
    """Return only the allowlisted, non-sensitive fields from an assistant message's metadata.

    Reuses `_SAFE_TECHNICAL_CONTEXT_KEYS` -- the same allowlist that already governs what
    leaves the workspace DB via feedback_report.technical_context. Deliberately excludes
    `sql_queries` (raw SQL text) and anything not on that list; system/developer prompt
    content is never present in message metadata in the first place.
    """
    metadata = _deserialize_object(metadata_json)
    if not metadata:
        return None
    return {key: metadata[key] for key in _SAFE_TECHNICAL_CONTEXT_KEYS if key in metadata}


# -- Pilot Control Center (v1) rating integration ----------------------------
#
# Generic aggregation over the (now integrated) Message Feedback `feedback`
# table. Deliberately minimal: counts + positive rate only, no charts/
# time-series. Fills the `rating_counts`/`rating_summary` seams that the
# original Control Center branch left as `None` placeholders.

def _rating_bucket(up: int, down: int) -> dict[str, Any]:
    total = up + down
    return {
        "total_rated": total,
        "up": up,
        "down": down,
        "positive_rate": (up / total) if total else None,
    }


def _rating_counts_overview(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """SELECT
            SUM(CASE WHEN rating='up' THEN 1 ELSE 0 END) AS up_count,
            SUM(CASE WHEN rating='down' THEN 1 ELSE 0 END) AS down_count
        FROM feedback"""
    ).fetchone()
    return _rating_bucket(row["up_count"] or 0, row["down_count"] or 0)


def _rating_summary_by_owner(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Rating summary per conversation owner (pilot user), keyed by user id."""
    rows = conn.execute(
        """SELECT c.owner_user_id AS owner_user_id, f.rating AS rating, COUNT(*) AS n
        FROM feedback f
        JOIN message m ON m.id = f.message_id
        JOIN conversation c ON c.id = m.conversation_id
        GROUP BY c.owner_user_id, f.rating"""
    ).fetchall()
    by_owner: dict[str, dict[str, int]] = {}
    for row in rows:
        by_owner.setdefault(row["owner_user_id"], {})[row["rating"]] = row["n"]
    return {
        owner_id: _rating_bucket(counts.get("up", 0), counts.get("down", 0))
        for owner_id, counts in by_owner.items()
    }


def _rating_summary_by_conversation(
    conn: sqlite3.Connection, conversation_ids: list[str]
) -> dict[str, dict[str, Any]]:
    if not conversation_ids:
        return {}
    placeholders = ",".join("?" for _ in conversation_ids)
    rows = conn.execute(
        f"""SELECT m.conversation_id AS conversation_id, f.rating AS rating, COUNT(*) AS n
        FROM feedback f JOIN message m ON m.id = f.message_id
        WHERE m.conversation_id IN ({placeholders})
        GROUP BY m.conversation_id, f.rating""",
        conversation_ids,
    ).fetchall()
    by_conv: dict[str, dict[str, int]] = {}
    for row in rows:
        by_conv.setdefault(row["conversation_id"], {})[row["rating"]] = row["n"]
    return {
        conv_id: _rating_bucket(counts.get("up", 0), counts.get("down", 0))
        for conv_id, counts in by_conv.items()
    }


def _message_ratings_for_conversation(conn: sqlite3.Connection, conversation_id: str) -> dict[str, str]:
    """{message_id: rating} for every rated message in one conversation, regardless of rater
    (the Control Center is a cross-user observer view, unlike the owner-scoped analyst API)."""
    rows = conn.execute(
        """SELECT f.message_id, f.rating FROM feedback f
        JOIN message m ON m.id = f.message_id
        WHERE m.conversation_id = ?""",
        (conversation_id,),
    ).fetchall()
    return {row["message_id"]: row["rating"] for row in rows}
