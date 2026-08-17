from pathlib import Path

from eval.round_b.runner import build_run_manifest, estimate_cost, validate_mini_dev
from eval.round_b.runner import RoundBRunner
from eval.round_b.incremental import IncrementalStore
from eval.benchmark.adapters.base import Turn, Usage
from eval.benchmark.snapshot import SnapshotSandbox


ROOT = Path(__file__).resolve().parents[2]


def test_validate_mini_dev_uses_canonical_content_identity_not_file_bytes():
    checked = validate_mini_dev(ROOT / "eval/round_b/mini_dev_v1.yaml")
    assert checked["canonical_manifest_sha256"] == "df8cd68c690266e770210e752ab8078ef8f3dc23b175e55abe97963a18d3558f"
    assert checked["case_count"] == 15
    assert checked["turn_count"] == 25


def test_manifest_pins_b1_and_committed_code_sha():
    manifest = build_run_manifest("run-a", "abc123", "2026-08-17")
    assert manifest["run_id"] == "run-a"
    assert manifest["track"] == "B"
    assert manifest["mini_dev"]["canonical_manifest_sha256"].startswith("df8cd68c")
    assert manifest["code_commit_sha"] == "abc123"
    assert manifest["inference_profile"] == "B1_STANDARD"
    assert manifest["judge_status"] == "not_scored_yet"


def test_manifest_run_id_changes_raw_serialized_identity():
    import hashlib, json
    a = build_run_manifest("run-a", "abc123", "2026-08-17")
    b = build_run_manifest("run-b", "abc123", "2026-08-17")
    assert hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest() != hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest()


def test_effective_tool_schema_hash_is_canonical_across_key_order():
    import hashlib, json
    left = {"b": 2, "a": {"y": 1, "x": 0}}
    right = {"a": {"x": 0, "y": 1}, "b": 2}
    digest = lambda x: hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest(left) == digest(right)


def test_cost_is_unknown_without_price_or_usage_and_known_for_groq():
    assert estimate_cost("nvidia", "z-ai/glm-5.2", 10, 2, 0) is None
    assert estimate_cost("groq", "openai/gpt-oss-120b", 1_000_000, 1_000_000, 0) == {"currency": "USD", "amount": 0.75}


def test_fireworks_candidate_uses_external_key_and_inference_base_url():
    from eval.round_b.runner import CANDIDATES
    assert CANDIDATES["fireworks"] == ("FIREWORKS_API_KEY", "https://api.fireworks.ai/inference/v1")


class _FakeSession:
    def __init__(self, adapter): self.adapter, self.questions = adapter, []
    def ask(self, question):
        self.questions.append(question)
        for kind in ("provider_request_started", "provider_response_received"):
            self.adapter.request_observer(kind, 0, None)
        return Turn(text="sin cifras", usage=Usage(provider="groq", model="openai/gpt-oss-120b", calls=1))


class _FakeAdapter:
    def __init__(self): self.sandbox, self.sessions, self.request_observer = SnapshotSandbox(), [], None
    def new_session(self, _):
        s = _FakeSession(self); self.sessions.append(s); return s


def test_runner_executes_tce_incrementally_with_one_session_and_auditable_events(tmp_path, monkeypatch):
    adapter = _FakeAdapter()
    runner = RoundBRunner(lambda *_: adapter, tmp_path, "no-new-run-id")
    monkeypatch.setattr("eval.round_b.runner.committed_head", lambda: "sha")
    runner.run_case("groq", "openai/gpt-oss-120b", "tce-ambiguity-001", "sha", IncrementalStore(tmp_path, "no-new-run-id"))
    assert len(adapter.sessions) == 1 and len(adapter.sessions[0].questions) == 2
    assert IncrementalStore(tmp_path, "no-new-run-id").checkpoint()["groq"]["tce-ambiguity-001"] == "completed"
    events = (tmp_path / "events.jsonl").read_text().splitlines()
    turns = (tmp_path / "turns.jsonl").read_text().splitlines()
    assert len(events) == 4 and len(turns) == 2
