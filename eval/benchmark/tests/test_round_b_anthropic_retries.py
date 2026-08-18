"""Offline audit tests for B1_STANDARD Anthropic retry ownership."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters.base import Turn, Usage
from eval.benchmark.adapters.track_b_anthropic import TrackBAnthropic
from eval.benchmark.snapshot import SnapshotSandbox
from eval.round_b.incremental import IncrementalStore
from eval.round_b.runner import RoundBRunner, classify_execution_error


class _CapturingAnthropic:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FlakySession:
    def __init__(self, adapter, outcomes):
        self.adapter, self.outcomes = adapter, iter(outcomes)

    def ask(self, _message):
        self.adapter.request_observer("provider_request_started", 0, None)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            self.adapter.request_observer("provider_request_failed", 0, outcome)
            raise outcome
        self.adapter.request_observer("provider_response_received", 0, None)
        return Turn(text="respuesta", usage=Usage(provider="anthropic", model="claude-opus-5", calls=1))


class _FlakyAdapter:
    def __init__(self, outcomes):
        self.sandbox = SnapshotSandbox()
        self.outcomes = outcomes
        self.request_observer = None

    def new_session(self, _session_id):
        return _FlakySession(self, self.outcomes)


def _run_case(tmp_path, outcomes, provider="anthropic", model="claude-opus-5"):
    adapter = _FlakyAdapter(outcomes)
    runner = RoundBRunner(lambda *_: adapter, tmp_path, run_id="retry-offline")
    store = IncrementalStore(tmp_path, "retry-offline")
    runner.run_case(provider, model, "tae-l1-008", "unused", store)
    events = [json.loads(line) for line in store.events_path.read_text(encoding="utf-8").splitlines()]
    return store, events


def test_anthropic_sdk_disables_internal_retries(monkeypatch):
    monkeypatch.setattr("eval.benchmark.adapters.track_b_anthropic.Anthropic", _CapturingAnthropic)
    adapter = TrackBAnthropic(provider={"api_key": "offline", "model": "claude-opus-5"})
    assert adapter.client.kwargs["max_retries"] == 0


def test_success_uses_one_observable_attempt(tmp_path):
    _, events = _run_case(tmp_path, [Turn(text="unused")])
    assert [event["attempt_index"] for event in events if event["event_type"] == "provider_request_started"] == [0]


@pytest.mark.parametrize("message", ["529 overloaded", "500 server error", "429 rate limit", "network down", "timeout"])
def test_eligible_error_retries_once_with_observable_attempts(tmp_path, message):
    store, events = _run_case(tmp_path, [RuntimeError(message), Turn(text="unused")])
    starts = [event for event in events if event["event_type"] == "provider_request_started"]
    assert [event["attempt_index"] for event in starts] == [0, 1]
    assert store.checkpoint()["anthropic"]["tae-l1-008"] == "completed"


def test_non_eligible_400_is_not_retried(tmp_path):
    with pytest.raises(RuntimeError, match="400"):
        _run_case(tmp_path, [RuntimeError("400 invalid request")])
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [event["attempt_index"] for event in events if event["event_type"] == "provider_request_started"] == [0]


def test_second_529_aborts_after_two_observable_attempts(tmp_path):
    with pytest.raises(RuntimeError, match="529"):
        _run_case(tmp_path, [RuntimeError("529 overloaded"), RuntimeError("529 overloaded")])
    store = IncrementalStore(tmp_path, "retry-offline")
    events = [json.loads(line) for line in store.events_path.read_text(encoding="utf-8").splitlines()]
    assert [event["attempt_index"] for event in events if event["event_type"] == "provider_request_started"] == [0, 1]
    assert store.checkpoint()["anthropic"]["tae-l1-008"] == "aborted"


def test_direct_openai_retry_is_centralized_and_auditable(tmp_path):
    store, events = _run_case(tmp_path, [RuntimeError("429 rate limit"), Turn(text="unused")], "openai", "gpt-5.6-terra")
    assert [event["attempt_index"] for event in events if event["event_type"] == "provider_request_started"] == [0, 1]
    assert store.checkpoint()["openai"]["tae-l1-008"] == "completed"


def test_5xx_classification_is_provider_infrastructure():
    assert classify_execution_error(RuntimeError("529 overloaded")) == "provider_infra"
