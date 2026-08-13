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
    assert "not_applicable policy" in text
    assert "HARD CEILING" in text
    assert "Not a quantity metric" in text


def test_rubric_prompt_separates_retrieval_failure_from_fabrication_and_causality():
    text = judge._render_rubric_text(judge.load_rubric())
    assert "retrieval failure" in text
    assert "wrong query" in text
    assert "causal relationship" in text
    assert "hedged hypothesis" in text


def test_rubric_prompt_scopes_clarification_judgment_to_the_initial_decision():
    text = judge._render_rubric_text(judge.load_rubric())
    assert "initial decision" in text
    assert "Do not lower clarification_judgment" in text


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


def test_judge_result_stamps_all_three_version_axes_independently():
    """rubric_version (from rubric.yaml), judge_impl_version (this module's
    own code version), and judge_model (whatever the caller passed) must
    all be recorded and must not collapse into one value -- they vary
    independently across calibration runs."""
    payload = json.dumps(_valid_payload())
    chat_fn = _fake_chat([payload])
    result = judge.run_judge(_minimal_input(), chat_fn, model="some-other-model")
    assert result.rubric_version == judge.load_rubric()["rubric_version"]
    assert result.judge_impl_version == judge.JUDGE_IMPL_VERSION
    assert result.judge_model == "some-other-model"
    # the three must be independently settable/distinguishable, not the same string
    assert len({result.rubric_version, result.judge_impl_version, result.judge_model}) == 3


def test_judge_result_stamps_versions_even_on_persistent_failure():
    """A judge_failed result still self-identifies which rubric/impl/model
    produced the failure -- version info isn't only for successes."""
    chat_fn = _fake_chat(["garbage", "still garbage", "nope"])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model", max_attempts=3)
    assert result.judge_failed is True
    assert result.rubric_version == judge.load_rubric()["rubric_version"]
    assert result.judge_model == "test-model"


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


def test_run_judge_scores_missing_required_tool_as_zero_not_na():
    payload = _valid_payload()
    judge_input = JudgeInput(
        question="¿Cuál es el NOI del activo?",
        expected_behavior=["reportar el NOI"],
        forbidden_claims=[],
        ground_truth={"noi": {"value": 100, "unit": "UF"}},
        response_text="No tengo el dato.",
        executed_sql=[],
        query_results=[],
        artifacts=[],
        tool_trace=[],
        deterministic={},
        tool_requirements=None,
        clarification_expected=False,
    )
    result = judge.run_judge(
        judge_input,
        _fake_chat([json.dumps(payload)]),
        model="test-model",
    )
    assert result.dimension_scores["tool_correctness"] == 0
    assert "tool_correctness" not in result.not_applicable


def test_run_judge_tool_correctness_override_does_not_fire_when_tools_were_used():
    """The deterministic safety net only corrects the 'no tools ever ran,
    yet data existed' shape. If tool calls did happen, whatever the judge
    said about not_applicable is left alone -- this isn't a general
    override of judge judgment, just the one fully-decidable case."""
    payload = _valid_payload()
    judge_input = JudgeInput(
        question="q", expected_behavior=[], forbidden_claims=[],
        ground_truth={"noi": {"value": 100, "unit": "UF"}},
        response_text="x", executed_sql=["SELECT 1"], query_results=[], artifacts=[],
        tool_trace=[], deterministic={}, tool_requirements=None, clarification_expected=None,
    )
    result = judge.run_judge(judge_input, _fake_chat([json.dumps(payload)]), model="test-model")
    assert "tool_correctness" in result.not_applicable
    assert "tool_correctness" not in result.dimension_scores


def test_run_judge_tool_correctness_override_does_not_fire_without_ground_truth():
    """No tools used AND no ground truth available -- genuinely nothing to
    query, so not_applicable is legitimate and must not be overridden."""
    payload = _valid_payload()
    judge_input = JudgeInput(
        question="q", expected_behavior=[], forbidden_claims=[], ground_truth={},
        response_text="x", executed_sql=[], query_results=[], artifacts=[],
        tool_trace=[], deterministic={}, tool_requirements=None, clarification_expected=None,
    )
    result = judge.run_judge(judge_input, _fake_chat([json.dumps(payload)]), model="test-model")
    assert "tool_correctness" in result.not_applicable
    assert "tool_correctness" not in result.dimension_scores


def test_rubric_f1_retrieval_failure_carveout_points_to_other_dimensions():
    """The F1-vs-retrieval-failure carve-out must redirect scoring to the
    dimensions that actually cover it, not just say 'not F1' and stop."""
    text = judge._render_rubric_text(judge.load_rubric())
    assert "tool_correctness" in text
    assert "investigation_quality" in text
    # the carve-out sentence itself, not just the dimension existing elsewhere
    assert "zero rows" in text or "returns zero rows" in text


def test_rubric_c4_covers_unproven_event_used_as_explanation():
    """C4 must fire on a hedged-sounding explanation that quietly leans on
    an event never established by any query -- not just on bare 'X caused
    Y' assertions."""
    text = judge._render_rubric_text(judge.load_rubric())
    assert "unproven event" in text


def test_rubric_c4_requires_both_conditional_framing_and_evidence_gap_for_exception():
    """Regression guard for the v1.2 -> v1.2-narrowed fix: a genuinely
    hedged hypothesis needs BOTH conditional wording ("podria", "posible")
    AND an explicit evidence-gap acknowledgment to count as legitimate
    hedging. Conditional wording alone, or an uncertain event mentioned in
    passing, must not be enough on its own to force C4 despite that
    combined signal -- this is a general instruction to the judge, not a
    per-case rule."""
    text = judge._render_rubric_text(judge.load_rubric())
    assert "BOTH" in text
    assert "evidence" in text.lower() and "insufficient" in text.lower()
    assert "full stop" in text or "override" in text


def test_rubric_f1_audit_names_all_four_claim_classifications():
    """The claim-evidence audit must give the judge an explicit procedure
    with all four buckets, not just the two named fabrication shapes --
    a claim that doesn't match pattern (a) or (b) verbatim still needs
    somewhere to land."""
    text = judge._render_rubric_text(judge.load_rubric())
    assert "directly supported" in text
    assert "reasonably inferred" in text
    assert "explicitly hypothetical" in text
    assert "unsupported" in text


def test_rubric_f1_audit_does_not_escalate_supported_facts():
    """A claim that a specific row/value in an executed query or ground
    truth actually states must land in the supported bucket, not be
    treated as a candidate for F1 -- the audit is not guilty-until-proven,
    it starts from what's actually in evidence."""
    text = " ".join(judge._render_rubric_text(judge.load_rubric()).split())
    assert "a specific row/value in an executed query result or the provided ground truth" in text


def test_rubric_f1_audit_flags_unsupported_transformation_as_fact():
    """Generalized version of fact transformation: a claim that goes
    beyond what's directly supported or reasonably inferred, and is
    presented as settled rather than flagged as inferred, is the general
    shape that triggers F1 -- independent of any specific case's wording."""
    text = " ".join(judge._render_rubric_text(judge.load_rubric()).split())
    assert "goes beyond what is directly supported or reasonably inferred" in text
    assert "not flagged as a hypothesis" in text


def test_rubric_f1_audit_does_not_escalate_qualified_hypothesis():
    """An explicitly hypothetical claim -- conditional wording, or an
    acknowledged evidence gap -- must not automatically become F1 just
    because the underlying topic is uncertain."""
    text = judge._render_rubric_text(judge.load_rubric())
    assert "explicitly hypothetical" in text
    assert "not F1 by virtue of being" in text


def test_rubric_f1_audit_covers_unsupported_causal_or_event_claim():
    """The audit must generalize beyond the two named shapes (external
    citation, fact transformation) to any unsupported claim asserted as
    fact -- including an unproven causal driver or event presented as
    though it happened, not just the two illustrated patterns."""
    text = judge._render_rubric_text(judge.load_rubric())
    assert "BOTH unsupported AND" in text
    assert "presented as established fact" in text


def test_rubric_c4_still_fires_on_unqualified_causal_conclusion():
    """The narrowing must not have swallowed the original, legitimate C4
    case: a causal claim stated as settled fact with no hedge at all."""
    text = judge._render_rubric_text(judge.load_rubric())
    assert "established fact" in text or "ESTABLISHED FACT" in text


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


def test_run_judge_tolerates_vestigial_empty_justification_on_untriggered_gate():
    """Some models emit justification/evidence as "" on a non-triggered
    gate or not_applicable dimension instead of omitting the key -- that's
    semantically complete (nothing to justify), so it should not count as
    invalid output. This is a harness-robustness fix, not a rubric change."""
    payload = _valid_payload()
    payload["gates"]["F1_fabrication"] = {"triggered": False, "justification": "", "evidence": "", "confidence": 0.9}
    chat_fn = _fake_chat([json.dumps(payload)])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model")
    assert not result.judge_failed
    assert result.gates["F1_fabrication"]["triggered"] is False


def test_run_judge_still_rejects_empty_justification_when_actually_required():
    """The tolerance above must not swallow a genuine violation -- an empty
    justification on a TRIGGERED gate is still invalid."""
    bad = _valid_payload()
    bad["gates"]["F1_fabrication"] = {"triggered": True, "justification": "", "evidence": "algo", "confidence": 0.9}
    chat_fn = _fake_chat([json.dumps(bad), json.dumps(_valid_payload())])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model")
    assert result.attempts == 2  # first rejected, second accepted


def test_run_judge_extracts_json_even_with_surrounding_prose():
    payload = _valid_payload()
    wrapped = f"Aqui esta mi analisis:\n```json\n{json.dumps(payload)}\n```\nListo."
    chat_fn = _fake_chat([wrapped])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model")
    assert not result.judge_failed


def test_run_judge_correction_message_is_actionable_not_a_schema_dump():
    """Regression guard for the live-run finding: jsonschema's default
    ValidationError message is a multi-paragraph schema dump, not
    something a retry prompt should hand back. The correction nudge must
    be a short, specific instruction."""
    bad = _valid_payload()
    bad["dimensions"]["grounding"]["evidence"] = ["punto uno", "punto dos"]  # list instead of string
    chat_fn = _fake_chat([json.dumps(bad), json.dumps(_valid_payload())])
    judge.run_judge(_minimal_input(), chat_fn, model="test-model")
    correction = chat_fn.calls[1][-1]["content"]
    assert "STRING" in correction or "string" in correction
    assert len(correction) < 500  # not a raw schema dump


def test_run_judge_gate_result_shape():
    payload = _valid_payload()
    payload["gates"]["C4_unsupported_causality"] = {
        "triggered": True, "justification": "asserts cause as fact", "evidence": "esto se debe a X", "confidence": 0.75,
    }
    chat_fn = _fake_chat([json.dumps(payload)])
    result = judge.run_judge(_minimal_input(), chat_fn, model="test-model")
    assert result.gates["C4_unsupported_causality"]["triggered"] is True
    assert result.gates["F1_fabrication"]["triggered"] is False
