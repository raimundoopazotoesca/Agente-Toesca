"""Stable HTTP-facing adapter for the pending analyst conversation service.

This module intentionally does not import or construct the A4 service.  The
Flask application supplies it through a lazy factory, allowing HTTP tests and
module imports to stay free of workspace, provider, and knowledge-DB effects.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from openai import OpenAIError

from tools.analyst_workspace.conversation_service import ConversationServiceError
from tools.analyst_workspace.store import (
    ConversationNotFoundError,
    MessageNotFoundError,
    ValidationError,
    WorkspaceStoreError,
)


class ConversationServiceProtocol(Protocol):
    """The small HTTP-facing subset of the A4 ConversationService."""

    def create_conversation(self, *, title: str | None = None, context: dict[str, Any] | None = None, user_id: str) -> Any: ...
    def list_conversations_for_user(self, user_id: str, include_archived: bool = False) -> list[Any]: ...
    def get_conversation_for_user(self, conversation_id: str, user_id: str) -> Any: ...
    def list_messages_for_user(self, conversation_id: str, user_id: str) -> list[Any]: ...
    def rename_conversation_for_user(self, conversation_id: str, user_id: str, title: str) -> Any: ...
    def archive_conversation_for_user(self, conversation_id: str, user_id: str) -> Any: ...
    def unarchive_conversation_for_user(self, conversation_id: str, user_id: str) -> Any: ...
    def send_message_for_user(self, conversation_id: str, user_id: str, text: str) -> Any: ...
    def set_feedback_for_user(self, message_id: str, user_id: str, rating: str, note: str | None = None) -> Any: ...


class AnalystApiError(Exception):
    """Base class for expected, safe-to-render analyst API errors."""


class AnalystNotFoundError(AnalystApiError):
    pass


class AnalystValidationError(AnalystApiError):
    pass


class AnalystServiceUnavailableError(AnalystApiError):
    pass


class ConversationApiAdapter:
    """Translate the stable HTTP contract to the concrete A3/A4 service."""

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
        """The only point tied to A4's eventual send-message return shape."""
        return _message(self._call(self._service.send_message_for_user, conversation_id, user_id, text))

    def set_feedback(self, message_id: str, user_id: str, rating: str, note: str | None) -> dict[str, Any]:
        return _feedback(self._call(self._service.set_feedback_for_user, message_id, user_id, rating, note))

    @staticmethod
    def _call(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except (ConversationNotFoundError, MessageNotFoundError) as exc:
            raise AnalystNotFoundError from exc
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
