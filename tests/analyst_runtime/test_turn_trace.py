from __future__ import annotations

import json

from tools.analyst_runtime.resolution import resolution_from_entity_payload
from tools.analyst_runtime.turn_trace import build_turn_trace, reconstruct_turn
from tools.analyst_runtime.session import AnalystSessionResult


def test_low_confidence_is_unknown_without_losing_cause():
    outcome = resolution_from_entity_payload({"status": "low_confidence", "candidates": []}, {})
    assert outcome.status == "unknown"
    assert outcome.reason_code == "low_confidence"
    assert outcome.evidence["internal_status"] == "low_confidence"


def test_ambiguous_entity_keeps_candidates():
    outcome = resolution_from_entity_payload(
        {"status": "ambiguous", "candidates": [{"entity_key": "Apo"}]}, {}
    )
    assert outcome.status == "ambiguous"
    assert outcome.candidates == ({"entity_key": "Apo"},)


def test_trace_reconstructs_answer_and_has_no_hidden_reasoning():
    result = AnalystSessionResult(text="La vacancia fue 5%.")
    trace = build_turn_trace(
        result,
        user_text="vacancia TRI",
        turn_id="turn-1",
        conversation_id="conversation-1",
        session_id="session-1",
    )
    reconstructed = reconstruct_turn(trace)
    assert reconstructed.final_answer == result.text
    serialized = json.dumps(trace)
    for forbidden in ("chain_of_thought", "scratchpad", "raw_items"):
        assert forbidden not in serialized

