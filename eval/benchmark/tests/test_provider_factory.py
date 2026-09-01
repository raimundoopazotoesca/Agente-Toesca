from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters.provider_factory import ProviderConfigurationError, provider_config_for_track
from eval.benchmark.runner import output_record, run_metadata


def test_native_tracks_derive_their_provider_without_redundant_flag(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline")

    assert provider_config_for_track("track_b_openai_responses", None, "gpt-test")["provider"] == "openai"
    assert provider_config_for_track("track_b_anthropic", None, "claude-test")["provider"] == "anthropic"


@pytest.mark.parametrize("track,provider,model", [
    ("track_b_frontier", None, "model"),
    ("track_b_frontier", "groq", None),
    ("track_b_openai_responses", "openai", "model"),
    ("track_b_anthropic", "openai", "model"),
])
def test_invalid_track_arguments_fail_before_provider_execution(track, provider, model):
    with pytest.raises(ProviderConfigurationError):
        provider_config_for_track(track, provider, model)


def test_output_record_has_reproducibility_and_deterministic_fields(monkeypatch):
    class Adapter:
        name = "track_b_frontier"
        model = "test-model"
    class Result:
        stdout = " M modified.py\n?? new.py\n"
    monkeypatch.setattr("eval.benchmark.runner.subprocess.run", lambda *args, **kwargs: Result())
    metadata = run_metadata("track_b_frontier", Adapter(), "groq", "test-model")
    record = output_record(metadata, "case", 0, {"usage": {"calls": 0}, "dimension_scores": {"completeness": 1.0}, "gate_results": {"F2": False}, "text": "ok"})
    assert metadata["worktree_clean"] is False
    assert metadata["comparison_eligible"] is False
    assert metadata["dirty_paths"] == ["modified.py", "new.py"]
    assert {"head_sha", "porcelain_status", "worktree_clean", "dirty_paths", "requested_track", "resolved_track", "provider", "model", "snapshot", "usage", "deterministic_dimensions", "gate_results"} <= set(record)


def test_clean_worktree_is_comparison_eligible(monkeypatch):
    class Adapter: name = "track_b_openai_responses"; model = "model"
    class Result: stdout = ""
    monkeypatch.setattr("eval.benchmark.runner.subprocess.run", lambda *args, **kwargs: Result())
    metadata = run_metadata("track_b_openai_responses", Adapter(), None, "model")
    assert metadata["provider"] == "openai"
    assert metadata["worktree_clean"] is True
    assert metadata["comparison_eligible"] is True
