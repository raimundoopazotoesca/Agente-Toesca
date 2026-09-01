"""Stable HTTP-facing adapter for the analyst ConversationService.

This module intentionally does not import or construct the service.  The
Flask application supplies it through a lazy factory, allowing HTTP tests and
module imports to stay free of workspace, provider, and knowledge-DB effects.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from openai import OpenAIError

from tools.analyst_workspace.conversation_service import ConversationServiceError, TurnTracePersistenceError
from tools.analyst_workspace.store import (
    ConversationNotFoundError,
    FeedbackReportNotFoundError,
    MessageNotFoundError,
    ValidationError,
    WorkspaceStoreError,
)


class ConversationServiceProtocol(Protocol):
    """The small HTTP-facing subset of the ConversationService."""

    def create_conversation(self, *, title: str | None = None, context: dict[str, Any] | None = None, user_id: str) -> Any: ...
    def list_conversations_for_user(self, user_id: str, include_archived: bool = False) -> list[Any]: ...
    def get_conversation_for_user(self, conversation_id: str, user_id: str) -> Any: ...
    def list_messages_for_user(self, conversation_id: str, user_id: str) -> list[Any]: ...
    def rename_conversation_for_user(self, conversation_id: str, user_id: str, title: str) -> Any: ...
    def archive_conversation_for_user(self, conversation_id: str, user_id: str) -> Any: ...
    def unarchive_conversation_for_user(self, conversation_id: str, user_id: str) -> Any: ...
    def send_message_for_user(self, conversation_id: str, user_id: str, text: str) -> Any: ...
    def set_feedback_for_user(self, message_id: str, user_id: str, rating: str, note: str | None = None) -> Any: ...
    def clear_feedback_for_user(self, message_id: str, user_id: str) -> None: ...
    def get_feedback_for_user(self, message_id: str, user_id: str) -> Any: ...
    def list_feedback_for_conversation_for_user(self, conversation_id: str, user_id: str) -> dict[str, str]: ...
    def get_feedback_summary(self) -> dict[str, Any]: ...
    def list_recent_feedback(self, limit: int = 20) -> list[dict[str, Any]]: ...
    def report_feedback_for_user(
        self, user_id: str, conversation_id: str, anchor_message_id: str, comment: str,
        release_revision: str | None = None,
    ) -> Any: ...
    def list_feedback_reports(self, status: str | None = None, reporter_user_id: str | None = None) -> list[Any]: ...
    def get_feedback_report(self, report_id: str) -> Any: ...
    def update_feedback_report_status(self, report_id: str, status: str) -> Any: ...


class AnalystApiError(Exception):
    """Base class for expected, safe-to-render analyst API errors."""


class AnalystNotFoundError(AnalystApiError):
    pass


class AnalystValidationError(AnalystApiError):
    pass


class AnalystServiceUnavailableError(AnalystApiError):
    pass


class AnalystForbiddenError(AnalystApiError):
    pass


class AnalystTracePersistenceError(AnalystApiError):
    """The mandatory durable TurnTrace could not be written with its answer."""


class ConversationApiAdapter:
    """Translate the stable HTTP contract to the concrete ConversationService."""

    def __init__(self, service: ConversationServiceProtocol):
        self._service = service

    def create_conversation(self, user_id: str, *, title: str | None, context: dict[str, Any] | None) -> dict[str, Any]:
        return _conversation(self._call(self._service.create_conversation, title=title, context=context, user_id=user_id))

    def list_conversations(self, user_id: str, *, include_archived: bool) -> list[dict[str, Any]]:
        return [_conversation(item) for item in self._call(self._service.list_conversations_for_user, user_id, include_archived=include_archived)]

    def get_conversation(self, conversation_id: str, user_id: str) -> dict[str, Any]:
        return _conversation(self._call(self._service.get_conversation_for_user, conversation_id, user_id))

    def list_messages(self, conversation_id: str, user_id: str) -> list[dict[str, Any]]:
        return [_message(item) for item in self._call(self._service.list_messages_for_user, conversation_id, user_id)]

    def update_conversation(self, conversation_id: str, user_id: str, *, title: str | None, archived: bool | None) -> dict[str, Any]:
        if title is not None:
            return _conversation(self._call(self._service.rename_conversation_for_user, conversation_id, user_id, title))
        if archived is True:
            return _conversation(self._call(self._service.archive_conversation_for_user, conversation_id, user_id))
        if archived is False:
            return _conversation(self._call(self._service.unarchive_conversation_for_user, conversation_id, user_id))
        raise AnalystValidationError("provide a title or archived boolean")

    def send_message(self, conversation_id: str, user_id: str, text: str) -> dict[str, Any]:
        return _message(self._call(self._service.send_message_for_user, conversation_id, user_id, text))

    def set_feedback(self, message_id: str, user_id: str, rating: str, note: str | None) -> dict[str, Any]:
        return _feedback(self._call(self._service.set_feedback_for_user, message_id, user_id, rating, note))

    def clear_feedback(self, message_id: str, user_id: str) -> None:
        self._call(self._service.clear_feedback_for_user, message_id, user_id)

    def get_feedback(self, message_id: str, user_id: str) -> dict[str, Any] | None:
        result = self._call(self._service.get_feedback_for_user, message_id, user_id)
        return _feedback(result) if result is not None else None

    def list_conversation_feedback(self, conversation_id: str, user_id: str) -> dict[str, Any]:
        return self._call(self._service.list_feedback_for_conversation_for_user, conversation_id, user_id)

    def get_feedback_summary(self) -> dict[str, Any]:
        return self._call(self._service.get_feedback_summary)

    def list_recent_feedback(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._call(self._service.list_recent_feedback, limit=limit)

    def submit_feedback_report(
        self, user_id: str, conversation_id: str, anchor_message_id: str, comment: str,
        release_revision: str | None = None,
    ) -> dict[str, Any]:
        return _feedback_report(self._call(
            self._service.report_feedback_for_user, user_id, conversation_id, anchor_message_id, comment,
            release_revision=release_revision,
        ))

    def list_feedback_reports(self, *, status: str | None, reporter_user_id: str | None) -> list[dict[str, Any]]:
        return [
            _feedback_report_summary(item)
            for item in self._call(self._service.list_feedback_reports, status=status, reporter_user_id=reporter_user_id)
        ]

    def get_feedback_report(self, report_id: str) -> dict[str, Any]:
        return _feedback_report(self._call(self._service.get_feedback_report, report_id))

    def update_feedback_report_status(self, report_id: str, status: str) -> dict[str, Any]:
        return _feedback_report(self._call(self._service.update_feedback_report_status, report_id, status))

    @staticmethod
    def _call(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except (ConversationNotFoundError, MessageNotFoundError, FeedbackReportNotFoundError) as exc:
            raise AnalystNotFoundError from exc
        except TurnTracePersistenceError as exc:
            raise AnalystTracePersistenceError from exc
        except (ValidationError, ConversationServiceError) as exc:
            raise AnalystValidationError from exc
        except WorkspaceStoreError as exc:
            raise AnalystServiceUnavailableError from exc
        except (RuntimeError, OpenAIError) as exc:
            raise AnalystServiceUnavailableError from exc


def get_adapter(factory: Callable[[], ConversationServiceProtocol] | None) -> ConversationApiAdapter:
    if factory is None:
        raise AnalystServiceUnavailableError
    try:
        return ConversationApiAdapter(factory())
    except AnalystApiError:
        raise
    except Exception as exc:
        raise AnalystServiceUnavailableError from exc


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value[name]
    return getattr(value, name)


def _conversation(value: Any) -> dict[str, Any]:
    return {name: _field(value, name) for name in ("id", "title", "created_at", "updated_at", "context", "archived_at")}


def _message(value: Any) -> dict[str, Any]:
    return {name: _field(value, name) for name in ("id", "conversation_id", "role", "content", "created_at", "metadata")}


def _feedback(value: Any) -> dict[str, Any]:
    return {name: _field(value, name) for name in ("rating", "note")}


def _feedback_report(value: Any) -> dict[str, Any]:
    return {
        name: _field(value, name)
        for name in (
            "id", "reporter_user_id", "reporter_display_name", "conversation_id", "anchor_message_id",
            "comment", "conversation_snapshot", "technical_context", "status", "created_at", "updated_at",
        )
    }


def _feedback_report_summary(value: Any) -> dict[str, Any]:
    comment = _field(value, "comment")
    preview = comment if len(comment) <= 140 else comment[:140] + "…"
    return {
        name: _field(value, name)
        for name in ("id", "reporter_user_id", "reporter_display_name", "status", "created_at", "updated_at")
    } | {"comment_preview": preview}
