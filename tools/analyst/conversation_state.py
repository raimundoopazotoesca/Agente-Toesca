"""In-memory conversation state, keyed by session_id, for the Flask process.

Lost on server restart by design (confirmed acceptable for daily internal
use — see docs/superpowers/specs/2026-08-10-analyst-agent-phase1-design.md).
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

_DEFAULTS: dict[str, Any] = {
    "last_metric": None,
    "last_entities": {},
    "last_period": None,
    "last_analysis_type": None,
}

# Cap on distinct session_id keys held in memory. Without a bound, a process
# that never restarts would grow _STATE forever (e.g. one key per malicious
# or unbounded conversation_id). Oldest entries are evicted first.
_MAX_SESSIONS = 500

_STATE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()


def get_state(session_id: str) -> dict[str, Any]:
    if session_id not in _STATE:
        return dict(_DEFAULTS)
    return dict(_STATE[session_id])


def update_state(session_id: str, **fields: Any) -> None:
    if session_id in _STATE:
        _STATE.move_to_end(session_id)
        current = _STATE[session_id]
    else:
        current = dict(_DEFAULTS)
        _STATE[session_id] = current
        if len(_STATE) > _MAX_SESSIONS:
            _STATE.popitem(last=False)
    current.update(fields)


def clear_state(session_id: str) -> None:
    _STATE.pop(session_id, None)
