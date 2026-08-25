"""Small value objects returned by the analyst workspace store."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str
    context: dict[str, Any] | None
    archived_at: str | None
    owner_user_id: str | None = None


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str
    metadata: dict[str, Any] | None


@dataclass(frozen=True)
class Feedback:
    id: str
    message_id: str
    rating: str
    note: str | None
    created_at: str
