"""Unit tests for the A3.3 deterministic trend-direction module: lexicon
normalization, clause segmentation, and direction resolution. Integration
with coverage_guard's binding/fail-closed behavior is covered separately in
test_coverage_guard.py; the FinalPresenter drift check in
test_presentation.py."""
from __future__ import annotations

from tools.analyst_runtime.trend_assertions import (
    AMBIGUOUS,
    eligible_trend_direction,
    extract_clause_trend_hits,
    find_trend_terms,
    resolve_direction,
    split_clauses,
)


# ---- Lexicon normalization: synonyms within a direction, exclusions -------

def test_up_synonyms_all_normalize_to_up():
    for term in ("subió", "subieron", "aumentó", "aumentaron", "creció", "crecieron",
                 "se incrementó", "incrementó"):
        assert find_trend_terms(f"El NOI {term} este trimestre.") == ["UP"]


def test_down_synonyms_all_normalize_to_down():
    for term in ("cayó", "cayeron", "bajó", "bajaron", "disminuyó", "disminuyeron",
                 "decreció", "decrecieron", "retrocedió", "retrocedieron"):
        assert find_trend_terms(f"El NOI {term} este trimestre.") == ["DOWN"]


def test_flat_synonyms_all_normalize_to_flat():
    for term in ("se mantuvo", "se mantuvieron", "no tuvo cambios", "no tuvieron cambios",
                 "permaneció estable", "permanecieron estables", "no varió", "no variaron"):
        assert find_trend_terms(f"El NOI {term} este trimestre.") == ["FLAT"]


def test_excluded_terms_are_never_matched():
    # Real-code-evidenced exclusions (see A3.3 Design Memo v2 21.1 closure):
    # "mejora"/"mejoró" is used speculatively in the product's own voice
    # examples; "alto/bajo" is level, not direction; "disminuciones de
    # capital" is a distinct domain noun, not the conjugated trend verb.
    for text in (
        "Esto sugiere que una mejora en ellos podría mover materialmente el indicador.",
        "El dato apunta a una mejora, aunque la cobertura del período es parcial.",
        "Apo3001 tuvo vacancia alta este mes.",
        "No hay registro de disminuciones de capital de la serie A.",
        "El fondo se ve estable.",  # "estable" alone (no "permaneció"/"se mantuvo") is not lexicon
    ):
        assert find_trend_terms(text) == []


def test_word_boundary_prevents_substring_false_positive():
    # "bajó" must not match inside an unrelated longer word.
    assert find_trend_terms("trabajó horas extra") == []


# ---- Clause segmentation ---------------------------------------------------

def test_split_on_comma_and_pero():
    clauses = split_clauses("El NOI subió, pero la vacancia cayó.")
    assert len(clauses) == 2
    assert "subió" in clauses[0] and "cayó" in clauses[1]


def test_split_on_mientras_que():
    clauses = split_clauses("El NOI subió mientras que la vacancia cayó.")
    assert any("subió" in c for c in clauses) and any("cayó" in c for c in clauses)
    assert not any("subió" in c and "cayó" in c for c in clauses)


def test_and_split_only_applies_when_clause_has_2_plus_trend_terms():
    # Canonical brief example: single clause, two entities, two verbs -> " y "
    # becomes a delimiter because the segment has 2+ trend-term matches.
    clauses = split_clauses("El NOI del Activo A subió y el del Activo B cayó.")
    assert len(clauses) == 2


def test_enumeration_with_y_is_not_split_when_no_trend_terms():
    # Must NOT fracture a plain asset listing that has zero trend verbs.
    clauses = split_clauses("Torre A, Boulevard y Parking PT son los activos del fondo.")
    assert any("Boulevard y Parking PT" in c or "Boulevard" in c for c in clauses)


def test_single_clause_two_directions_is_ambiguous():
    # No delimiter (no comma/pero/mientras/" y ") separates two conflicting
    # verbs -- nothing tells us which value each belongs to.
    assert extract_clause_trend_hits("El NOI subió luego cayó en el mismo periodo.") == AMBIGUOUS


def test_repeated_same_direction_in_one_clause_is_not_ambiguous():
    hits = extract_clause_trend_hits("El NOI no tuvo cambios ni tuvo cambios relevantes.")
    assert hits != AMBIGUOUS
    assert len(hits) == 1
    assert hits[0].direction == "FLAT"


def test_no_trend_terms_yields_empty_hit_list():
    assert extract_clause_trend_hits("El fondo se ve estable.") == []


# ---- Direction resolution: chronological order, not lhs/rhs labels --------

def test_resolve_direction_up():
    assert resolve_direction(100.0, "2026-01", 120.0, "2026-02") == "UP"


def test_resolve_direction_down():
    assert resolve_direction(120.0, "2026-01", 100.0, "2026-02") == "DOWN"


def test_resolve_direction_flat_on_exact_equality():
    assert resolve_direction(100.0, "2026-01", 100.0, "2026-02") == "FLAT"


def test_resolve_direction_ignores_which_operand_is_labelled_lhs():
    # Model reversed lhs/rhs vs. the documented "earlier/later" convention --
    # resolution must still be correct because it keys off the PERIODS, not
    # the lhs/rhs labels.
    assert resolve_direction(120.0, "2026-02", 100.0, "2026-01") == "UP"


def test_resolve_direction_same_period_is_not_temporal():
    assert resolve_direction(100.0, "2026-01", 120.0, "2026-01") is None


def test_resolve_direction_invalid_period_shape_is_not_temporal():
    assert resolve_direction(100.0, "2026", 120.0, "2026-02") is None
    assert resolve_direction(100.0, None, 120.0, "2026-02") is None


def test_resolve_direction_handles_negative_values():
    # -50 -> -30 is a real increase.
    assert resolve_direction(-50.0, "2026-01", -30.0, "2026-02") == "UP"


# ---- eligible_trend_direction: operation/entity/metric eligibility --------

_LHS = {"entity_id": "A", "metric_key": "noi", "value": 100.0, "unit": "clp", "period": "2026-01"}
_RHS = {"entity_id": "A", "metric_key": "noi", "value": 120.0, "unit": "clp", "period": "2026-02"}


def test_eligible_direction_for_difference_operation():
    assert eligible_trend_direction("difference", _LHS, _RHS) == "UP"


def test_eligible_direction_for_percent_change_operation():
    assert eligible_trend_direction("percent_change", _LHS, _RHS) == "UP"


def test_eligible_direction_for_ratio_operation():
    assert eligible_trend_direction("ratio", _LHS, _RHS) == "UP"


def test_eligible_direction_for_comparison_operation():
    assert eligible_trend_direction("comparison", _LHS, _RHS) == "UP"


def test_discount_premium_is_never_trend_grounding():
    same_period_rhs = {**_RHS, "period": "2026-01"}
    assert eligible_trend_direction("discount_premium", _LHS, same_period_rhs) is None


def test_cross_entity_operands_are_not_trend_grounding():
    other_entity_rhs = {**_RHS, "entity_id": "B"}
    assert eligible_trend_direction("difference", _LHS, other_entity_rhs) is None


def test_cross_metric_operands_are_not_trend_grounding():
    other_metric_rhs = {**_RHS, "metric_key": "vacancia"}
    assert eligible_trend_direction("difference", _LHS, other_metric_rhs) is None


def test_same_period_operands_are_not_trend_grounding():
    same_period_rhs = {**_RHS, "period": "2026-01"}
    assert eligible_trend_direction("difference", _LHS, same_period_rhs) is None
