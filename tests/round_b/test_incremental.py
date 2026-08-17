import json

import pytest

from eval.round_b.incremental import IncrementalStore, IncompleteRequestError


def test_event_log_flushes_identity_and_links_outcome(tmp_path):
    store = IncrementalStore(tmp_path, "run")
    started = store.event("provider_request_started", "groq", "case", 0, 1, 0)
    received = store.event("provider_response_received", "groq", "case", 0, 1, 0, request_event_id=started["event_id"])
    rows = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert rows == [started, received]
    assert received["request_event_id"] == started["event_id"]


def test_unresolved_request_marks_case_aborted_without_retry(tmp_path):
    store = IncrementalStore(tmp_path, "run")
    store.event("provider_request_started", "groq", "case", 0, 1, 0)
    with pytest.raises(IncompleteRequestError):
        store.reconcile("groq", "case")
    assert store.checkpoint()["groq"]["case"] == "aborted"


def test_turn_append_and_atomic_checkpoint_keep_completed_case(tmp_path):
    store = IncrementalStore(tmp_path, "run")
    store.set_state("groq", "case", "running")
    store.turn({"case_id": "case", "turn_index": 0, "reasoning_content": "secret", "final_answer": "ok"})
    store.set_state("groq", "case", "completed")
    assert store.checkpoint()["groq"]["case"] == "completed"
    assert "secret" not in (tmp_path / "turns.jsonl").read_text()
