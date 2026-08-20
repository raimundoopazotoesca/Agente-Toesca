"""Conversation orchestration over persistent workspace data and F4 sessions.

Only visible user/assistant messages are persisted. Provider-native replay
state stays inside an in-memory session and is intentionally discarded on a
process restart.
"""
from __future__ import annotations

import time
from typing import Any

from tools.analyst_runtime.session import AnalystSession, AnalystSessionFactory, AnalystSessionResult
from tools.analyst_workspace.models import Conversation, Feedback, Message
from tools.analyst_workspace.store import DEFAULT_TITLE, WorkspaceStore


class ConversationServiceError(Exception):
    """Raised for service-level input errors before an analyst call."""


class ConversationService:
    def __init__(self, store: WorkspaceStore, session_factory: AnalystSessionFactory):
        self.store = store
        self.session_factory = session_factory
        self._sessions: dict[str, AnalystSession] = {}

    def create_conversation(self, context: dict[str, Any] | None = None, title: str | None = None) -> Conversation:
        return self.store.create_conversation(context=context, title=title)

    def get_conversation(self, conversation_id: str) -> Conversation:
        return self.store.get_conversation(conversation_id)

    def list_conversations(self, include_archived: bool = False) -> list[Conversation]:
        return self.store.list_conversations(include_archived=include_archived)

    def rename_conversation(self, conversation_id: str, title: str) -> Conversation:
        return self.store.rename_conversation(conversation_id, title)

    def archive_conversation(self, conversation_id: str) -> Conversation:
        conversation = self.store.archive_conversation(conversation_id)
        self._sessions.pop(conversation_id, None)
        return conversation

    def unarchive_conversation(self, conversation_id: str) -> Conversation:
        return self.store.unarchive_conversation(conversation_id)

    def send_message(self, conversation_id: str, text: str) -> Message:
        if not isinstance(text, str) or not text.strip():
            raise ConversationServiceError("message text cannot be empty")
        conversation = self.store.get_conversation(conversation_id)
        user_message = self.store.append_message(conversation_id, "user", text)
        if conversation.title == DEFAULT_TITLE and len(self.store.list_messages(conversation_id)) == 1:
            conversation = self.store.rename_conversation(conversation_id, _auto_title(text))
        else:
            conversation = self.store.get_conversation(conversation_id)

        session = self._sessions.get(conversation_id)
        if session is None:
            messages = self.store.list_messages(conversation_id)
            visible_history = messages[:-1] if messages and messages[-1].id == user_message.id else messages
            session = self.session_factory.create(conversation, visible_history, runtime_context=conversation.context)
            self._sessions[conversation_id] = session

        started = time.monotonic()
        result = session.ask(text)
        latency_ms = (time.monotonic() - started) * 1000
        return self.store.append_message(
            conversation_id, "assistant", result.text, metadata=runtime_result_to_metadata(result, latency_ms)
        )

    def list_messages(self, conversation_id: str) -> list[Message]:
        return self.store.list_messages(conversation_id)

    def set_feedback(self, message_id: str, rating: str, note: str | None = None) -> Feedback:
        return self.store.set_feedback(message_id, rating, note)

    def get_feedback(self, message_id: str) -> Feedback | None:
        return self.store.get_feedback(message_id)


def runtime_result_to_metadata(result: AnalystSessionResult, latency_ms: float) -> dict[str, Any]:
    """Return only the operational fields safe to retain in workspace SQLite."""
    usage = result.usage
    token_usage = {
        name: value for name, value in {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "cached_tokens": usage.cached_tokens,
        }.items() if value is not None
    }
    tool_calls = [
        {
            "name": call.name,
            "ok": call.ok,
            "duration_ms": call.duration_ms,
            **({"trace": call.trace} if call.trace else {}),
        }
        for call in result.tool_calls
    ]
    metadata = {
        "latency_ms": latency_ms,
        "model_calls": usage.calls,
        "action_count": len(result.tool_calls),
        "sql_count": len(result.sql_queries),
        "sql_queries": list(result.sql_queries),
        "tool_calls": tool_calls,
        "token_usage": token_usage,
        "provider": usage.provider,
        "model": usage.model,
    }
    presentation = {
        "presentation_applied": result.presentation_applied,
        "presentation_provider": result.presentation_provider,
        "presentation_model": result.presentation_model,
        "presentation_latency_ms": result.presentation_latency_ms,
        "presentation_integrity_status": result.presentation_integrity_status,
        "original_answer_hash": result.original_answer_hash,
        "presented_answer_hash": result.presented_answer_hash,
    }
    metadata.update({name: value for name, value in presentation.items() if value is not None})
    return metadata


def _auto_title(text: str) -> str:
    words = text.strip().split()
    title = " ".join(words[:7])
    return title + "…" if len(words) > 7 else title
