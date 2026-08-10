"""In-memory conversation state, keyed by session_id, for the Flask process.

Lost on server restart by design (confirmed acceptable for daily internal
use — see docs/superpowers/specs/2026-08-10-analyst-agent-phase1-design.md).
"""
from __future__ import annotations

from typing import Any

_DEFAULTS: dict[str, Any] = {
    "last_metric": None,
    "last_entities": {},
    "last_period": None,
    "last_analysis_type": None,
}

_STATE: dict[str, dict[str, Any]] = {}


def get_state(session_id: str) -> dict[str, Any]:
    if session_id not in _STATE:
        return dict(_DEFAULTS)
    return dict(_STATE[session_id])


def update_state(session_id: str, **fields: Any) -> None:
    current = _STATE.setdefault(session_id, dict(_DEFAULTS))
    current.update(fields)


def clear_state(session_id: str) -> None:
    _STATE.pop(session_id, None)
