from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters.base import Artifact, Turn, ToolCall
from eval.benchmark.graders import gates, judge
from eval.benchmark.graders.deterministic import DeterministicResult
from eval.benchmark.graders.judge_input import JudgeInput, build_judge_input
from eval.benchmark.snapshot import SnapshotSandbox


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


# --- rubric / schema -----------------------------------------------------

def test_rubric_has_all_seven_dimensions_with_five_anchors():
    rubric = judge.load_rubric()
    assert set(rubric["dimensions"]) == set(judge.DIMENSION_NAMES)
    for name, spec in rubric["dimensions"].items():
        assert set(spec["anchors"].keys()) == {0, 1, 2, 3, 4}, name
        for score, text in spec["anchors"].items():
            assert len(text.strip()) > 15, f"{name}[{score}] anchor too vague/short"


def test_rubric_has_all_three_gates_with_trigger_tests():
    rubric = judge.load_rubric()
    assert set(rubric["gates"]) == set(judge.GATE_NAMES)
    for name, spec in rubric["gates"].items():
        assert "definition" in spec
        assert "trigger_test" in spec
        assert any(k.startswith("explicitly_not") for k in spec)


def test_output_schema_is_valid_json_schema():
    jsonschema_mod = pytest.importorskip("jsonschema")
    jsonschema_mod.Draft7Validator.check_schema(judge.load_output_schema())


def test_rubric_text_renders_without_error():
    text = judge._render_rubric_text(judge.load_rubric())
    assert "analytical_quality" in text
    assert "F1_fabrication" in text


# --- classify_response (deterministic, pre-judge) -------------------------

def test_classify_infra_failure_takes_priority():
    assert judge.classify_response(Turn(text="anything"), "RateLimitError: 429") == "infra_failure"
    assert judge.classify_response(None, "boom") == "infra_failure"


def test_classify_empty_text_is_model_non_answer():
    assert judge.classify_response(Turn(text=""), None) == "model_non_answer"
    assert judge.classify_response(Turn(text="   "), None) == "model_non_answer"


def test_classify_nonempty_text_is_attempted():
    assert judge.classify_response(Turn(text="el NOI fue 100"), None) == "attempted"


# --- judge_input neutrality ------------------------------------------------

def _fake_deterministic_result() -> DeterministicResult:
    result = DeterministicResult()
    result.dimension_scores = {"completeness": 1.0, "factual_correctness": 1.0}
    result.unscored_dimensions = {"analytical_quality", "grounding"}
    result.facts_found = ["noi_x"]
    result.gate_verdict = gates.GateVerdict(checks=[
        gates.GateCheck("C1", gates.CEILING, triggered=False),
        gates.GateCheck("F1", gates.FATAL, triggered=None),
    ])
    return result


def test_judge_input_never_carries_track_identity_fields(sandbox):
    """Structural guarantee: JudgeInput has no field that could name a
    model/provider/track, and Turn.usage/Turn.raw are never read by the
    builder (only .text/.artifacts/.tool_calls/.queries are)."""
    field_names = {f for f in JudgeInput.__dataclass_fields__}
    forbidden = {"model", "provider", "track", "usage", "raw", "conversation_state", "intent"}
    assert not (field_names & forbidden)

    turn = Turn(
        text="el NOI fue 100",
        queries=["SELECT 1"],
        usage=__import__("eval.benchmark.adapters.base", fromlist=["Usage"]).Usage(provider="secret-provider", model="secret-model"),
        raw={"clarify": True, "internal_state": "should never leak"},
    )
    ji = build_judge_input({"question": "q"}, turn, {}, _fake_deterministic_result(), sandbox)
    rendered = json.dumps(ji.to_prompt_dict())
    assert "secret-provider" not in rendered
    assert "secret-model" not in rendered
    assert "internal_state" not in rendered


def test_judge_input_includes_required_neutral_fields(sandbox):
    turn = Turn(text="respuesta", queries=["SELECT COUNT(*) FROM dim_activo"])
    turn_spec = {
        "question": "cuantos activos",
        "expected_behavior": ["listar activos"],
        "forbidden_claims": ["no inventar"],
        "clarification_expected": False,
        "tool_requirements": {"min_distinct_queries": 1},
    }
    ji = build_judge_input(turn_spec, turn, {}, _fake_deterministic_result(), sandbox)
    d = ji.to_prompt_dict()
    assert d["question"] == "cuantos activos"
    assert d["expected_behavior"] == ["listar activos"]
    assert d["forbidden_claims"] == ["no inventar"]
    assert d["executed_sql"] == ["SELECT COUNT(*) FROM dim_activo"]
    assert d["query_results"][0]["columns"]  # replayed successfully
    assert d["deterministic_grader_results"]["unscored_dimensions"] == ["analytical_quality", "grounding"]
    assert "F1" in d["deterministic_grader_results"]["gates_pending_judge"]


def test_judge_input_replays_bad_query_as_error_not_crash(sandbox):
    turn = Turn(text="x", queries=["SELECT * FROM tabla_que_no_existe"])
    ji = build_judge_input({"question": "q"}, turn, {}, _fake_deterministic_result(), sandbox)
    assert "error" in ji.query_results[0]


def test_judge_input_dedupes_queries(sandbox):
    turn = Turn(text="x", queries=["SELECT 1", "SELECT 1", "SELECT 2"])
    ji = build_judge_input({"question": "q"}, turn, {}, _fake_deterministic_result(), sandbox)
    assert ji.executed_sql == ["SELECT 1", "SELECT 2"]


def test_judge_input_carries_artifacts_and_tool_trace(sandbox):
    turn = Turn(
        text="x",
        artifacts=[Artifact(kind="chart", payload='{"type":"line"}')],
        tool_calls=[ToolCall(name="run_sql", args={"query": "SELECT 1"}, ok=True, duration_ms=42.0)],
    )
    ji = build_judge_input({"question": "q"}, turn, {}, _fake_deterministic_result(), sandbox)
    assert ji.artifacts == [{"kind": "chart", "payload": '{"type":"line"}', "spec": {}}]
    assert ji.tool_trace == [{"args": {"query": "SELECT 1"}, "ok": True}]  # no duration_ms leaked


# --- run_judge: mocked LLM, deterministic/offline --------------------------

def _valid_payload(**overrides) -> dict:
    dim = {"not_applicable": False, "score": 3, "justification": "ok", "evidence": "quote", "confidence": 0.8}
    na = {"not_applicable": True, "confidence": 0.9}
    gate_off = {"triggered": False, "confidence": 0.9}
    payload = {
        "response_mode": "answered",
        "dimensions": {name: dict(dim) for name in judge.DIMENSION_NAMES},
        "gates": {name: dict(gate_off) for name in judge.GATE_NAMES},
    }
    payload["dimensions"]["tool_correctness"] = na
    payload.update(overrides)
    return payload


def _fake_chat(payload_sequence):
    calls = []

    def chat_fn(model, messages, **kwargs):
        calls.append(messages)
        idx = len(calls) - 1
        content = payload_sequence[idx]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    chat_fn.calls = calls
    return chat_fn


def _minimal_input() -> JudgeInput:
    return JudgeInput(
        question="q", expected_behavior=[], forbidden_claims=[], ground_truth={},
        response_text="x", executed_sql=[], query_results=[], artifacts=[], tool_trace=[],
        deterministic={}, tool_requirements=None, clarification_expected=None,
    )


def test_run_judge_valid_output_first_try():
    payload = json.dumps(_valid_payload())
    chat_fn = _fake_chat([payload])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model")
    assert not result.judge_failed
    assert result.attempts == 1
    assert result.response_mode == "answered"
    assert result.dimension_scores["analytical_quality"] == 3
    assert "tool_correctness" in result.not_applicable
    assert "tool_correctness" not in result.dimension_scores


def test_run_judge_retries_once_then_succeeds():
    chat_fn = _fake_chat(["not json at all", json.dumps(_valid_payload())])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model")
    assert not result.judge_failed
    assert result.attempts == 2
    # second call includes the correction nudge
    assert "invalida" in chat_fn.calls[1][-1]["content"]


def test_run_judge_never_converts_persistent_failure_into_a_score():
    chat_fn = _fake_chat(["garbage", "still garbage", "nope"])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model", max_attempts=3)
    assert result.judge_failed is True
    assert result.dimension_scores == {}
    assert result.attempts == 3
    assert result.failure_detail is not None


def test_run_judge_rejects_missing_required_fields_on_score():
    bad = _valid_payload()
    del bad["dimensions"]["grounding"]["evidence"]  # not_applicable=False but no evidence
    chat_fn = _fake_chat([json.dumps(bad), json.dumps(_valid_payload())])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model")
    assert result.attempts == 2  # first rejected, second accepted


def test_run_judge_gate_triggered_requires_justification():
    bad = _valid_payload()
    bad["gates"]["F1_fabrication"] = {"triggered": True, "confidence": 0.7}  # missing justification/evidence
    chat_fn = _fake_chat([json.dumps(bad), json.dumps(_valid_payload())])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model")
    assert result.attempts == 2


def test_run_judge_extracts_json_even_with_surrounding_prose():
    payload = _valid_payload()
    wrapped = f"Aqui esta mi analisis:\n```json\n{json.dumps(payload)}\n```\nListo."
    chat_fn = _fake_chat([wrapped])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model")
    assert not result.judge_failed


def test_run_judge_gate_result_shape():
    payload = _valid_payload()
    payload["gates"]["C4_unsupported_causality"] = {
        "triggered": True, "justification": "asserts cause as fact", "evidence": "esto se debe a X", "confidence": 0.75,
    }
    chat_fn = _fake_chat([json.dumps(payload)])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model")
    assert result.gates["C4_unsupported_causality"]["triggered"] is True
    assert result.gates["F1_fabrication"]["triggered"] is False
