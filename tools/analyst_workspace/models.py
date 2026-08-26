"""Small value objects returned by the analyst workspace store."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def preferred_name(display_name: str) -> str:
    """Return the natural short name derived from an authoritative display name."""
    return " ".join(display_name.split()).split(" ", 1)[0]


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str
    context: dict[str, Any] | None
    archived_at: str | None
    owner_user_id: str | None = None
    title_origin: str = "default"


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
    user_id: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ProductUpdate:
    id: str
    title: str
    body: str
    cta_label: str | None
    cta_config: dict[str, Any] | None
    published_at: str | None
    active: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class FeedbackReport:
    id: str
    reporter_user_id: str
    reporter_display_name: str
    conversation_id: str
    anchor_message_id: str
    comment: str
    conversation_snapshot: list[dict[str, Any]]
    technical_context: dict[str, Any] | None
    status: str
    created_at: str
    updated_at: str
