import json

from tools.analyst.intent import extract_intent
from tools.analyst.conversation_state import clear_state, update_state


def _fake_llm(expected_json: str):
    def _call(prompt: str) -> str:
        return expected_json
    return _call


def test_extracts_metric_and_entity():
    clear_state("intent-test-1")
    llm_response = json.dumps({
        "metric": "vacancia_pct",
        "entities": {"activo": "Torre A"},
        "period": "2026-07",
        "comparison": None,
        "confidence": 0.9,
    })
    result = extract_intent("vacancia de Torre A en julio 2026", "intent-test-1", _fake_llm(llm_response))
    assert result.metric == "vacancia_pct"
    assert result.entities == {"activo": "Torre A"}
    assert result.confidence == 0.9
    assert result.needs_clarification is False


def test_low_confidence_triggers_clarification():
    clear_state("intent-test-2")
    llm_response = json.dumps({
        "metric": None, "entities": {}, "period": None, "comparison": None, "confidence": 0.2,
    })
    result = extract_intent("como viene esto?", "intent-test-2", _fake_llm(llm_response))
    assert result.needs_clarification is True


def test_follow_up_inherits_state():
    clear_state("intent-test-3")
    update_state("intent-test-3", last_metric="noi", last_entities={"fondo": "PT"}, last_period="2026-06")
    llm_response = json.dumps({
        "metric": None, "entities": {}, "period": "2025-06", "comparison": "same_period_last_year", "confidence": 0.85,
    })
    result = extract_intent("¿y el año pasado?", "intent-test-3", _fake_llm(llm_response))
    assert result.metric == "noi"
    assert result.entities == {"fondo": "PT"}
    assert result.period == "2025-06"


def test_invalid_llm_json_returns_low_confidence():
    clear_state("intent-test-4")
    result = extract_intent("pregunta rara", "intent-test-4", _fake_llm("no es json"))
    assert result.needs_clarification is True
    assert result.confidence == 0.0
