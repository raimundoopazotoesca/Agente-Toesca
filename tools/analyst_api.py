"""Stable HTTP-facing adapter for the pending analyst conversation service.

This module intentionally does not import or construct the A4 service.  The
Flask application supplies it through a lazy factory, allowing HTTP tests and
module imports to stay free of workspace, provider, and knowledge-DB effects.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol


class ConversationServiceProtocol(Protocol):
    """Conceptual boundary to be reconciled once A4's public API is final."""

    def create_conversation(self, *, title: str | None = None, context: dict[str, Any] | None = None) -> Any: ...
    def list_conversations(self, *, include_archived: bool = False) -> list[Any]: ...
    def get_conversation(self, conversation_id: str) -> Any: ...
    def rename_conversation(self, conversation_id: str, title: str) -> Any: ...
    def archive_conversation(self, conversation_id: str) -> Any: ...
    def send_message(self, conversation_id: str, text: str) -> Any: ...
    def set_feedback(self, message_id: str, rating: str, note: str | None = None) -> Any: ...


class AnalystApiError(Exception):
    """Base class for expected, safe-to-render analyst API errors."""


class AnalystNotFoundError(AnalystApiError):
    pass


class AnalystServiceUnavailableError(AnalystApiError):
    pass


class ConversationApiAdapter:
    """Contains the provisional A5-to-A4 method and serialization adaptation."""

    def __init__(self, service: ConversationServiceProtocol):
        self._service = service

    def create_conversation(self, *, title: str | None, context: dict[str, Any] | None) -> dict[str, Any]:
        return _conversation(self._call(self._service.create_conversation, title=title, context=context))

    def list_conversations(self, *, include_archived: bool) -> list[dict[str, Any]]:
        return [_conversation(item) for item in self._call(self._service.list_conversations, include_archived=include_archived)]

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        return _conversation(self._call(self._service.get_conversation, conversation_id))

    def update_conversation(self, conversation_id: str, *, title: str | None, archived: bool | None) -> dict[str, Any]:
        if title is not None:
            return _conversation(self._call(self._service.rename_conversation, conversation_id, title))
        if archived is True:
            return _conversation(self._call(self._service.archive_conversation, conversation_id))
        raise ValueError("provide a title or archived=true")

    def send_message(self, conversation_id: str, text: str) -> dict[str, Any]:
        """The only point tied to A4's eventual send-message return shape."""
        return _message(self._call(self._service.send_message, conversation_id, text))

    def set_feedback(self, message_id: str, rating: str, note: str | None) -> dict[str, Any]:
        return _feedback(self._call(self._service.set_feedback, message_id, rating, note))

    @staticmethod
    def _call(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except KeyError as exc:
            # A4 will replace this provisional convention with explicit types.
            raise AnalystNotFoundError from exc
        except Exception as exc:
            # A4's concrete runtime/provider errors are intentionally not part
            # of A5's provisional public contract yet.
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
