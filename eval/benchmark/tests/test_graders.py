from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters.base import Turn
from eval.benchmark.graders import gates
from eval.benchmark.graders.deterministic import score_turn
from eval.benchmark.graders.entities import (
    check_expected_entities,
    entity_mentioned,
    normalize_expected_entities,
    other_entities_mentioned,
    period_matches,
    periods_mentioned,
)
from eval.benchmark.graders.ground_truth import ResolvedFact
from eval.benchmark.graders.numbers import extract_numbers, has_numbers, value_in_text


# --- numbers -----------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("el NOI fue $1.234.567", [1234567.0]),
        ("dividend yield de 1.234,56", [1234.56]),
        ("plain 1234.56 english style", [1234.56]),
        ("vacancia 12,5%", [12.5]),
        ("dos numeros: 100 y 200", [100.0, 200.0]),
    ],
)
def test_extract_numbers_cl_and_plain(text, expected):
    assert extract_numbers(text) == expected


def test_value_in_text_within_pct_tolerance():
    assert value_in_text(1_000_000, "el NOI fue 1.005.000", tolerance_pct=1.0)
    assert not value_in_text(1_000_000, "el NOI fue 1.500.000", tolerance_pct=1.0)


def test_value_in_text_within_abs_tolerance():
    assert value_in_text(12.5, "vacancia 12,6%", tolerance_abs=0.2)
    assert not value_in_text(12.5, "vacancia 15%", tolerance_abs=0.2)


# --- entities ------------------------------------------------------------

def test_entity_mentioned_matches_alias_and_accent_insensitive():
    assert entity_mentioned("como viene Parque Titanium este mes", "fondo", "PT")
    assert entity_mentioned("la vacancia de Vina Centro", "activo", "Viña Centro")


def test_entity_mentioned_does_not_false_positive_on_substring():
    # "Apo" should not match inside "Apoquindo 4501" spuriously in a way that
    # breaks Apo-vs-Apo3001 disambiguation elsewhere -- word boundary check.
    assert not entity_mentioned("xApo4501x", "fondo", "Apo")


def test_other_entities_mentioned_flags_wrong_fondo():
    text = "el fondo Apo tiene una vacancia de 5%"
    hits = other_entities_mentioned(text, "fondo", "TRI")
    assert "Apo" in hits


def test_check_expected_entities_single_value():
    result = check_expected_entities("NOI de Vina Centro este mes", {"activo": "Viña Centro"})
    assert result == {"activo": {"Viña Centro": True}}


def test_normalize_expected_entities_accepts_str_or_list():
    assert normalize_expected_entities({"fondo": "PT"}) == {"fondo": ["PT"]}
    assert normalize_expected_entities({"fondo": ["PT", "Apo"]}) == {"fondo": ["PT", "Apo"]}
    assert normalize_expected_entities(None) == {}


def test_check_expected_entities_multi_value_per_type():
    result = check_expected_entities("el LTV de PT es alto", {"fondo": ["PT", "Apo"]})
    assert result == {"fondo": {"PT": True, "Apo": False}}


def test_has_numbers():
    assert has_numbers("el NOI fue 1.000.000")
    assert not has_numbers("¿Podrías especificar la métrica y el fondo?")


def test_period_extraction_iso_and_month_name():
    assert periods_mentioned("dato de 2026-06") == {"2026-06"}
    assert periods_mentioned("en junio de 2026 bajo la vacancia") == {"2026-06"}


def test_period_matches_range():
    assert period_matches("evolucion desde 2025-01", {"from": "2025-01", "to": "2026-06"})
    assert not period_matches("dato de 2024-01", {"from": "2025-01", "to": "2026-06"})
    assert period_matches("cualquier cosa", {}) is True


# --- gates: fatal ----------------------------------------------------------

def test_gate_f2_entity_confusion_triggers_on_wrong_fondo():
    turn = Turn(text="el fondo Apo tiene vacancia de 5%")
    check = gates.gate_f2_entity_confusion(turn, {"fondo": "TRI"})
    assert check.triggered is True
    assert check.kind == "fatal"


def test_gate_f2_passes_when_expected_entity_present():
    turn = Turn(text="TRI tiene vacancia de 5%")
    check = gates.gate_f2_entity_confusion(turn, {"fondo": "TRI"})
    assert check.triggered is False


def test_gate_f2_multi_entity_partial_mention_is_not_confusion():
    """Mentioning only one of two expected entities (PT, not Apo) is an
    incomplete comparison, not entity confusion -- completeness/
    conversational_quality penalize it, F2 must not fatal it."""
    turn = Turn(text="el LTV de PT es 81%")
    check = gates.gate_f2_entity_confusion(turn, {"fondo": ["PT", "Apo"]})
    assert check.triggered is False


def test_gate_f2_multi_entity_triggers_on_wholly_different_fondo():
    turn = Turn(text="el LTV de TRI es 61%")
    check = gates.gate_f2_entity_confusion(turn, {"fondo": ["PT", "Apo"]})
    assert check.triggered is True


def test_gate_f3_session_leak():
    turn = Turn(text="como vimos antes con Apo4501, la vacancia bajo")
    check = gates.gate_f3_session_leak(turn, other_session_markers=["Apo4501"])
    assert check.triggered is True


def test_gate_f4_unsafe_db_from_sandbox_violations():
    turn = Turn(text="ok", gate_violations=["action=DELETE"])
    assert gates.gate_f4_unsafe_db(turn).triggered is True
    assert gates.gate_f4_unsafe_db(Turn(text="ok")).triggered is False


def test_gate_f5_ignored_correction():
    turn = Turn(text="la vacancia de Vina Centro es 10%")
    check = gates.gate_f5_ignored_correction(
        turn,
        corrected_entities={"activo": "Mall Curicó"},
        previous_entities={"activo": "Viña Centro"},
    )
    assert check.triggered is True

    turn_ok = Turn(text="la vacancia de Mall Curico es 10%")
    check_ok = gates.gate_f5_ignored_correction(
        turn_ok,
        corrected_entities={"activo": "Mall Curicó"},
        previous_entities={"activo": "Viña Centro"},
    )
    assert check_ok.triggered is False


# --- gates: ceiling ----------------------------------------------------------

def test_gate_c1_wrong_primary_number():
    resolved = {"noi": ResolvedFact(ref="noi", value=1_000_000, unit="CLP")}
    required = [{"ref": "noi", "tolerance_pct": 1.0}]

    ok_turn = Turn(text="el NOI fue 1.000.500")
    assert gates.gate_c1_wrong_primary_number(ok_turn, "noi", required, resolved).triggered is False

    bad_turn = Turn(text="el NOI fue 2.000.000")
    check = gates.gate_c1_wrong_primary_number(bad_turn, "noi", required, resolved)
    assert check.triggered is True
    assert check.ceiling == 0.30


def test_gate_c1_does_not_trigger_on_clarification_with_no_numbers():
    """A response with zero numeric content (clarification/decline) is not
    'a wrong number' -- that's a different failure mode, left to
    clarification_judgment (judge, still unscored)."""
    resolved = {"noi": ResolvedFact(ref="noi", value=1_000_000, unit="CLP")}
    required = [{"ref": "noi", "tolerance_pct": 1.0}]
    turn = Turn(text="¿Podrías especificar el activo y el período?")
    check = gates.gate_c1_wrong_primary_number(turn, "noi", required, resolved)
    assert check.triggered is False
    assert check.ceiling is None


def test_gate_c2_does_not_trigger_on_clarification_with_no_numbers():
    resolved = {"noi": ResolvedFact(ref="noi", value=1_000_000, unit="CLP")}
    required = [{"ref": "noi", "tolerance_pct": 1.0}, {"ref": "gastos", "tolerance_pct": 1.0}]
    turn = Turn(text="No tengo ese dato disponible.")
    check = gates.gate_c2_wrong_secondary_number(turn, "noi", required, resolved)
    assert check.triggered is False


def test_gate_c2_wrong_secondary_number():
    resolved = {
        "noi": ResolvedFact(ref="noi", value=1_000_000, unit="CLP"),
        "gastos": ResolvedFact(ref="gastos", value=200_000, unit="CLP"),
    }
    required = [{"ref": "noi", "tolerance_pct": 1.0}, {"ref": "gastos", "tolerance_pct": 1.0}]
    turn = Turn(text="el NOI fue 1.000.000, gastos 999.999.999")
    check = gates.gate_c2_wrong_secondary_number(turn, "noi", required, resolved)
    assert check.triggered is True
    assert check.ceiling == 0.60


def test_gate_c3_wrong_period_without_declaration():
    turn = Turn(text="la vacancia fue 5% en 2024-01")
    check = gates.gate_c3_wrong_period(turn, {"exact": "2026-06"}, clarification_expected=False)
    assert check.triggered is True
    assert check.ceiling == 0.40


def test_gate_c3_wrong_period_ambiguous_when_clarification_acceptable():
    turn = Turn(text="no encontre el dato exacto")
    check = gates.gate_c3_wrong_period(turn, {"exact": "2026-06"}, clarification_expected=True)
    assert check.triggered is None


def test_gate_verdict_ceiling_is_minimum_of_triggered():
    verdict = gates.GateVerdict(checks=[
        gates.GateCheck("C1", "ceiling", triggered=True, ceiling=0.30),
        gates.GateCheck("C3", "ceiling", triggered=True, ceiling=0.40),
    ])
    assert verdict.ceiling == 0.30


def test_gate_verdict_no_cap_when_nothing_triggered():
    verdict = gates.GateVerdict(checks=[gates.GateCheck("C1", "ceiling", triggered=False)])
    assert verdict.ceiling == 1.0


# --- deterministic scorer, end to end ---------------------------------------

def test_score_turn_correct_answer_no_gates():
    turn = Turn(text="el NOI de Vina Centro en 2026-06 fue 1.000.000", queries=["SELECT ..."])
    turn_spec = {
        "question": "NOI de Vina Centro en junio 2026",
        "required_facts": [{"ref": "noi", "tolerance_pct": 1.0}],
        "primary_fact": "noi",
        "expected_entities": {"activo": "Viña Centro"},
        "expected_period": {"exact": "2026-06"},
    }
    resolved = {"noi": ResolvedFact(ref="noi", value=1_000_000, unit="CLP")}
    result = score_turn(turn, turn_spec, resolved)
    assert not result.is_fatal
    assert result.dimension_scores["factual_correctness"] == 1.0
    assert result.dimension_scores["completeness"] == 1.0
    assert result.dimension_scores["conversational_quality"] == 1.0
    assert "analytical_quality" in result.unscored_dimensions  # judge territory


def test_score_turn_wrong_primary_number_caps_score():
    turn = Turn(text="el NOI de Vina Centro en 2026-06 fue 9.999.999")
    turn_spec = {
        "question": "NOI de Vina Centro en junio 2026",
        "required_facts": [{"ref": "noi", "tolerance_pct": 1.0}],
        "primary_fact": "noi",
        "expected_entities": {"activo": "Viña Centro"},
    }
    resolved = {"noi": ResolvedFact(ref="noi", value=1_000_000, unit="CLP")}
    result = score_turn(turn, turn_spec, resolved)
    assert not result.is_fatal
    assert result.dimension_scores["factual_correctness"] == 0.0
    # conversational_quality (entity was right) is capped, not zeroed
    assert 0 < result.dimension_scores["conversational_quality"] <= 0.30


def test_score_turn_legitimate_clarification_is_not_penalized():
    """tae-l8-001 shape: clarification_expected=acceptable, no data source
    for the metric, Track A declines with a generic clarify. Must not score
    factual_correctness=0 or conversational_quality=0 for that -- both go
    unscored, leaving room for the (future) judge to decide if declining
    was the right call."""
    turn = Turn(text="¿Podrías especificar qué métrica te interesa y a qué fondo o activo te refieres?")
    turn_spec = {
        "question": "morosidad de Viña Centro este mes",
        "expected_entities": {"activo": "Viña Centro"},
        "clarification_expected": "acceptable",
    }
    result = score_turn(turn, turn_spec, resolved={})
    assert not result.is_fatal
    assert not result.gate_verdict.ceiling_triggered
    assert "factual_correctness" in result.unscored_dimensions
    assert "conversational_quality" in result.unscored_dimensions
    assert result.no_numeric_claim is True


def test_score_turn_same_shape_but_clarification_not_expected_is_still_penalized():
    """Same non-answer, but the case demands a direct answer
    (clarification_expected=false): conversational_quality is NOT suppressed
    -- the entity miss still counts against it."""
    turn = Turn(text="¿Podrías especificar qué métrica te interesa?")
    turn_spec = {
        "question": "vacancia de TRI en junio 2026",
        "expected_entities": {"fondo": "TRI"},
        "clarification_expected": False,
    }
    result = score_turn(turn, turn_spec, resolved={})
    assert result.dimension_scores["conversational_quality"] == 0.0


def test_score_turn_multi_entity_comparison_partial_credit():
    """tae-l2-001 shape: comparison expecting both PT and Apo mentioned.
    Answer only covers PT -- partial conversational_quality credit, not a
    fatal entity-confusion gate."""
    turn = Turn(text="el LTV de PT es 81,2%")
    turn_spec = {
        "question": "Compara el LTV de PT y Apo en junio de 2026",
        "expected_entities": {"fondo": ["PT", "Apo"]},
    }
    result = score_turn(turn, turn_spec, resolved={})
    assert not result.is_fatal
    assert result.dimension_scores["conversational_quality"] == 0.5


def test_score_turn_entity_confusion_is_fatal_and_zeroes_everything():
    turn = Turn(text="el fondo Apo tiene vacancia de 5%")
    turn_spec = {
        "question": "vacancia de TRI",
        "expected_entities": {"fondo": "TRI"},
    }
    result = score_turn(turn, turn_spec, resolved={})
    assert result.is_fatal
    assert all(v == 0.0 for v in result.dimension_scores.values())
    assert not result.unscored_dimensions
