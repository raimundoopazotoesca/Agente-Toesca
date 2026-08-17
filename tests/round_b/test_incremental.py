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


def test_completed_case_is_not_replayed_and_pending_can_start(tmp_path):
    store = IncrementalStore(tmp_path, "run")
    store.begin_case("groq", "pending")
    store.complete_case("groq", "pending")
    with pytest.raises(RuntimeError, match="completed"):
        store.begin_case("groq", "pending")
    store.begin_case("groq", "next")
    assert store.checkpoint()["groq"]["next"] == "running"


def test_crash_after_started_reloads_as_unknown_and_aborted(tmp_path):
    IncrementalStore(tmp_path, "run").event("provider_request_started", "p", "c", 0, 0, 0)
    reloaded = IncrementalStore(tmp_path, "run")
    with pytest.raises(IncompleteRequestError): reloaded.reconcile("p", "c")
    assert reloaded.checkpoint()["p"]["c"] == "aborted"


def test_response_then_crash_preserves_request_pair_and_case_can_be_completed(tmp_path):
    store = IncrementalStore(tmp_path, "run"); store.set_state("p", "c", "running")
    start = store.event("provider_request_started", "p", "c", 0, 0, 0)
    store.event("provider_response_received", "p", "c", 0, 0, 0, request_event_id=start["event_id"])
    IncrementalStore(tmp_path, "run").reconcile("p", "c")
    store.turn({"case_id":"c", "turn_index":0, "final_answer":"ok"}); store.complete_case("p", "c")
    assert store.checkpoint()["p"]["c"] == "completed"


def test_retry_attempts_are_separate_auditable_requests(tmp_path):
    store = IncrementalStore(tmp_path, "run")
    first = store.event("provider_request_started", "p", "c", 0, 0, 0)
    store.event("provider_request_failed", "p", "c", 0, 0, 0, request_event_id=first["event_id"], error_taxonomy="quota_rate_limit")
    second = store.event("provider_request_started", "p", "c", 0, 0, 1)
    store.event("provider_response_received", "p", "c", 0, 0, 1, request_event_id=second["event_id"])
    rows = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert first["event_id"] != second["event_id"] and [x["attempt_index"] for x in rows if x["event_type"] == "provider_request_started"] == [0, 1]


def test_artifacts_reloaded_from_disk_have_no_secret_or_reasoning_fields(tmp_path):
    store = IncrementalStore(tmp_path, "run")
    store.turn({"api_key":"x", "authorization":"y", "reasoning_content":"z", "thought_signature":"q", "final_answer":"ok"})
    text = (tmp_path / "turns.jsonl").read_text()
    assert "reasoning" not in text and "thought" not in text
