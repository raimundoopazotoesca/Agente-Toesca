from __future__ import annotations

import json

from tools.analyst_runtime.base import ToolCall
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


def test_ambiguous_entity_has_no_canonical_value_and_correct_method():
    outcome = resolution_from_entity_payload(
        {"status": "ambiguous", "candidates": [{"entity_key": "Apo"}]}, {}
    )
    assert outcome.canonical_value is None
    assert outcome.method == "entity_resolver"


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


def test_action_metadata_is_allowlisted_and_strips_unknown_or_hidden_fields():
    call = ToolCall(
        name="resolve_entity",
        args={"query": "Apoquindo 3001"},
        ok=True,
        duration_ms=1.0,
        trace={
            "resolution": {"status": "resolved", "canonical_value": "Apo3001"},
            "candidates": [{"entity_key": "Apo3001"}],
            "evidence_id": "ev-1",
            "status": "resolved",
            "prompt": "system prompt text that must never be persisted",
            "raw_items": [{"secret": "raw provider payload"}],
            "chain_of_thought": "internal reasoning",
            "reasoning": "internal reasoning too",
            "replay_state": {"provider_internal": "opaque"},
        },
    )
    result = AnalystSessionResult(text="respuesta", tool_calls=[call])
    trace = build_turn_trace(
        result, user_text="vacancia Apo3001", turn_id="turn-1",
        conversation_id="conversation-1", session_id="session-1",
    )
    action_metadata = trace["execution"]["tool_calls"][0]["metadata"]
    assert action_metadata["resolution"]["status"] == "resolved"
    assert action_metadata["candidates"] == [{"entity_key": "Apo3001"}]
    assert action_metadata["evidence_id"] == "ev-1"
    serialized = json.dumps(trace)
    for forbidden in ("prompt", "raw_items", "chain_of_thought", "reasoning", "replay_state"):
        assert forbidden not in serialized

