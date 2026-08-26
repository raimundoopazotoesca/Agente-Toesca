"""Conversation orchestration over persistent workspace data and F4 sessions.

Only visible user/assistant messages are persisted. Provider-native replay
state stays inside an in-memory session and is intentionally discarded on a
process restart.
"""
from __future__ import annotations

import time
from typing import Any

from tools.analyst_runtime.session import AnalystSession, AnalystSessionFactory, AnalystSessionResult
from tools.analyst_workspace.models import Conversation, Feedback, FeedbackReport, Message
from tools.analyst_workspace.store import DEFAULT_TITLE, WorkspaceStore
from tools.analyst_workspace.title_generator import LightweightTitleGenerator, TitleGenerator, is_substantive_text


class ConversationServiceError(Exception):
    """Raised for service-level input errors before an analyst call."""


class ConversationService:
    def __init__(self, store: WorkspaceStore, session_factory: AnalystSessionFactory,
                 title_generator: TitleGenerator | None = None):
        self.store = store
        self.session_factory = session_factory
        self.title_generator = title_generator or LightweightTitleGenerator()
        self._sessions: dict[str, AnalystSession] = {}

    def create_conversation(self, context: dict[str, Any] | None = None, title: str | None = None, user_id: str | None = None) -> Conversation:
        return self.store.create_conversation(context=context, title=title, owner_user_id=user_id)

    def get_conversation(self, conversation_id: str) -> Conversation:
        return self.store.get_conversation(conversation_id)

    def get_conversation_for_user(self, conversation_id: str, user_id: str) -> Conversation:
        return self.store.get_conversation_for_user(conversation_id, user_id)

    def list_conversations(self, include_archived: bool = False) -> list[Conversation]:
        return self.store.list_conversations(include_archived=include_archived)

    def list_conversations_for_user(self, user_id: str, include_archived: bool = False) -> list[Conversation]:
        return self.store.list_conversations_for_user(user_id, include_archived)

    def rename_conversation(self, conversation_id: str, title: str) -> Conversation:
        return self.store.rename_conversation(conversation_id, title)

    def rename_conversation_for_user(self, conversation_id: str, user_id: str, title: str) -> Conversation:
        return self.store.rename_conversation_for_user(conversation_id, user_id, title)

    def archive_conversation(self, conversation_id: str) -> Conversation:
        conversation = self.store.archive_conversation(conversation_id)
        self._sessions.pop(conversation_id, None)
        return conversation

    def archive_conversation_for_user(self, conversation_id: str, user_id: str) -> Conversation:
        self.store.get_conversation_for_user(conversation_id, user_id)
        return self.archive_conversation(conversation_id)

    def unarchive_conversation(self, conversation_id: str) -> Conversation:
        return self.store.unarchive_conversation(conversation_id)

    def unarchive_conversation_for_user(self, conversation_id: str, user_id: str) -> Conversation:
        return self.store.unarchive_conversation_for_user(conversation_id, user_id)

    def send_message(self, conversation_id: str, text: str) -> Message:
        if not isinstance(text, str) or not text.strip():
            raise ConversationServiceError("message text cannot be empty")
        conversation = self.store.get_conversation(conversation_id)
        user_message = self.store.append_message(conversation_id, "user", text)
        session = self._sessions.get(conversation_id)
        hydration_latency_ms = 0.0
        if session is None:
            messages = self.store.list_messages(conversation_id)
            visible_history = messages[:-1] if messages and messages[-1].id == user_message.id else messages
            runtime_context = dict(conversation.context or {})
            # Scope is checked from the conversation owner before this fetch;
            # the store has no global user-facing claim lookup.
            if conversation.owner_user_id:
                runtime_context["authenticated_user"] = self.store.get_authenticated_user_context(
                    conversation.owner_user_id)
                hydration_started = time.monotonic()
                runtime_context["durable_analytical_context"] = self.store.load_durable_context_for_user(
                    conversation_id, conversation.owner_user_id)
                hydration_latency_ms = (time.monotonic() - hydration_started) * 1000
            session = self.session_factory.create(conversation, visible_history, runtime_context=runtime_context)
            self._sessions[conversation_id] = session

        started = time.monotonic()
        result = session.ask(text)
        latency_ms = (time.monotonic() - started) * 1000
        assistant = self.store.append_message(
            conversation_id, "assistant", result.text, metadata=runtime_result_to_metadata(result, latency_ms, hydration_latency_ms)
        )
        if result.durable_memory:
            self.store.persist_analytical_turn(conversation_id, user_message.id, assistant.id, result.durable_memory)
        if conversation.title_origin == "default" and is_substantive_text(text):
            try:
                title = self.title_generator.generate(text, result.text)
                if title:
                    self.store.auto_title_conversation(conversation_id, title)
            except Exception:
                pass
        return assistant

    def send_message_for_user(self, conversation_id: str, user_id: str, text: str) -> Message:
        self.store.get_conversation_for_user(conversation_id, user_id)
        return self.send_message(conversation_id, text)

    def list_messages(self, conversation_id: str) -> list[Message]:
        return self.store.list_messages(conversation_id)

    def list_messages_for_user(self, conversation_id: str, user_id: str) -> list[Message]:
        return self.store.list_messages_for_user(conversation_id, user_id)

    def set_feedback(self, message_id: str, rating: str, note: str | None = None) -> Feedback:
        return self.store.set_feedback(message_id, rating, note)

    def set_feedback_for_user(self, message_id: str, user_id: str, rating: str, note: str | None = None) -> Feedback:
        return self.store.set_feedback_for_user(message_id, user_id, rating, note)

    def get_feedback(self, message_id: str) -> Feedback | None:
        return self.store.get_feedback(message_id)

    def report_feedback_for_user(
        self, user_id: str, conversation_id: str, anchor_message_id: str, comment: str,
        release_revision: str | None = None,
    ) -> FeedbackReport:
        """Out-of-band product action: no LLM call, no tool call, no new turn."""
        return self.store.create_feedback_report_for_user(
            user_id, conversation_id, anchor_message_id, comment, release_revision=release_revision
        )

    def list_feedback_reports(self, status: str | None = None, reporter_user_id: str | None = None) -> list[FeedbackReport]:
        return self.store.list_feedback_reports(status=status, reporter_user_id=reporter_user_id)

    def get_feedback_report(self, report_id: str) -> FeedbackReport:
        return self.store.get_feedback_report(report_id)

    def update_feedback_report_status(self, report_id: str, status: str) -> FeedbackReport:
        return self.store.update_feedback_report_status(report_id, status)


def runtime_result_to_metadata(result: AnalystSessionResult, latency_ms: float, hydration_latency_ms: float = 0.0) -> dict[str, Any]:
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
        "turn_metrics": {
            "total_turn_latency_ms": latency_ms,
            "llm_rounds": usage.calls,
            "llm_latency_ms": usage.llm_latency_ms if usage.llm_latency_ms is not None else usage.latency_ms,
            "tool_calls": len(result.tool_calls),
            "tool_latency_ms": sum(call.duration_ms or 0.0 for call in result.tool_calls),
            "sql_tool_latency_ms": sum((call.duration_ms or 0.0) for call in result.tool_calls if call.name == "run_sql"),
            "hydration_latency_ms": hydration_latency_ms,
            "hydrated_claim_count": result.hydrated_claim_count,
            "evidence_count": result.reused_evidence_count + result.fresh_evidence_count,
            "reused_evidence_count": result.reused_evidence_count,
            "fresh_evidence_count": result.fresh_evidence_count,
            **token_usage,
            **({"provider": usage.provider} if usage.provider else {}),
            **({"model": usage.model} if usage.model else {}),
        },
        **({"termination_reason": result.termination_reason} if result.termination_reason else {}),
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
