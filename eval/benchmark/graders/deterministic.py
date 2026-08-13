"""Deterministic scoring layer: everything verifiable without a judge.

Runs first and cheaply. If a fatal gate triggers, the judge is never
called for that turn (design doc section 9) -- there's nothing for it to
rescue. Ceiling caps still allow judge dimensions to be scored, capped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from eval.benchmark.adapters.base import Turn
from eval.benchmark.graders import gates
from eval.benchmark.graders.entities import check_expected_entities, period_matches
from eval.benchmark.graders.ground_truth import ResolvedFact
from eval.benchmark.graders.numbers import has_numbers, value_in_text

DIMENSIONS = [
    "factual_correctness",
    "completeness",
    "tool_correctness",
    "analytical_quality",
    "grounding",
    "hallucination",
    "conversational_quality",
    "clarification_judgment",
    "investigation_quality",
    "output_usefulness",
]


@dataclass
class DeterministicResult:
    dimension_scores: dict[str, float] = field(default_factory=dict)
    unscored_dimensions: set[str] = field(default_factory=set)
    gate_verdict: gates.GateVerdict | None = None
    facts_found: list[str] = field(default_factory=list)
    facts_missing: list[str] = field(default_factory=list)
    entities_found: dict[str, dict[str, bool]] = field(default_factory=dict)
    period_ok: bool | None = None
    # True when the answer asserted zero numbers at all (e.g. a clarification
    # or decline). Bookkeeping only -- it is what lets C1/C2 and the entity/
    # period components of conversational_quality avoid penalizing a
    # legitimate non-answer, but it is NOT a verdict on whether declining was
    # the right call. That judgment stays with clarification_judgment (judge,
    # still unscored) -- see gates.py module docstring on F1/C4/C5.
    no_numeric_claim: bool = False

    @property
    def is_fatal(self) -> bool:
        return bool(self.gate_verdict and self.gate_verdict.is_fatal)


def _score_facts(turn: Turn, turn_spec: dict[str, Any], resolved: dict[str, ResolvedFact]) -> tuple[float, list[str], list[str]]:
    required = turn_spec.get("required_facts", [])
    acceptable = turn_spec.get("acceptable_facts", [])
    if not required and not acceptable:
        return 1.0, [], []

    found, missing = [], []
    for spec in required:
        ref = spec["ref"]
        fact = resolved.get(ref)
        ok = fact is not None and value_in_text(
            float(fact.value), turn.text,
            tolerance_pct=spec.get("tolerance_pct", 0.0),
            tolerance_abs=spec.get("tolerance_abs", 0.0),
        )
        (found if ok else missing).append(ref)

    bonus = 0
    for spec in acceptable:
        ref = spec["ref"]
        fact = resolved.get(ref)
        if fact is not None and value_in_text(
            float(fact.value), turn.text,
            tolerance_pct=spec.get("tolerance_pct", 0.0),
            tolerance_abs=spec.get("tolerance_abs", 0.0),
        ):
            bonus += 1

    required_score = (len(found) / len(required)) if required else 1.0
    acceptable_score = min(bonus / max(len(acceptable), 1), 1.0) if acceptable else 0.0
    completeness = required_score if not acceptable else 0.7 * required_score + 0.3 * acceptable_score
    return completeness, found, missing


def score_turn(
    turn: Turn,
    turn_spec: dict[str, Any],
    resolved: dict[str, ResolvedFact],
    session_markers: list[str] | None = None,
    correction_context: tuple[dict[str, str], dict[str, str]] | None = None,
) -> DeterministicResult:
    """Score one turn's deterministic dimensions and run the gates that
    don't need a judge. `correction_context` = (previous_entities,
    corrected_entities), passed only on the turn right after a correction.
    """
    result = DeterministicResult()
    result.no_numeric_claim = not has_numbers(turn.text)

    completeness, found, missing = _score_facts(turn, turn_spec, resolved)
    result.facts_found, result.facts_missing = found, missing
    result.dimension_scores["completeness"] = completeness

    required = turn_spec.get("required_facts", [])
    if required and not result.no_numeric_claim:
        result.dimension_scores["factual_correctness"] = len(found) / len(required)
    else:
        # No required_facts at all, OR the answer asserted no number -- in
        # the latter case correctness can't be judged (there is no claim to
        # be right or wrong about); completeness above already reflects that
        # the fact wasn't delivered.
        result.unscored_dimensions.add("factual_correctness")

    # A legitimate non-answer (clarification/decline where the case allows
    # it) must not be scored as if it failed to mention the right entity or
    # period -- neither was ever promised. Whether declining was the *right*
    # call is still clarification_judgment's job (judge, unscored below).
    clarification_expected = turn_spec.get("clarification_expected")
    non_answer = clarification_expected in (True, "acceptable") and result.no_numeric_claim

    expected_entities = turn_spec.get("expected_entities") or {}
    entity_score = None
    if expected_entities:
        result.entities_found = check_expected_entities(turn.text, expected_entities)
        if not non_answer:
            all_hits = [hit for ekeys in result.entities_found.values() for hit in ekeys.values()]
            entity_score = (sum(all_hits) / len(all_hits)) if all_hits else None

    expected_period = turn_spec.get("expected_period")
    period_ok = period_matches(turn.text, expected_period) if expected_period else None
    result.period_ok = period_ok
    period_component = None if non_answer else (1.0 if period_ok else (0.0 if period_ok is False else None))

    conv_components = [v for v in (entity_score, period_component) if v is not None]
    if conv_components:
        result.dimension_scores["conversational_quality"] = sum(conv_components) / len(conv_components)
    else:
        result.unscored_dimensions.add("conversational_quality")

    tool_req = turn_spec.get("tool_requirements")
    if tool_req:
        if not turn.queries and not turn.tool_calls:
            result.unscored_dimensions.add("tool_correctness")
        else:
            checks = []
            min_q = tool_req.get("min_distinct_queries")
            if min_q is not None:
                checks.append(len(set(turn.queries)) >= min_q)
            must_touch = tool_req.get("must_touch_tables")
            if must_touch:
                blob = " ".join(turn.queries).lower()
                checks.append(all(t.lower() in blob for t in must_touch))
            must_artifacts = tool_req.get("must_produce_artifacts")
            if must_artifacts:
                kinds = {a.kind for a in turn.artifacts}
                checks.append(all(k in kinds for k in must_artifacts))
            result.dimension_scores["tool_correctness"] = (sum(checks) / len(checks)) if checks else 1.0
    else:
        result.unscored_dimensions.add("tool_correctness")

    for dim in DIMENSIONS:
        if dim not in result.dimension_scores and dim not in result.unscored_dimensions:
            result.unscored_dimensions.add(dim)  # judge territory: analytical_quality, grounding,
            # hallucination, clarification_judgment, investigation_quality, output_usefulness

    checks = [
        gates.gate_f2_entity_confusion(turn, expected_entities),
        gates.gate_f3_session_leak(turn, session_markers or []),
        gates.gate_f4_unsafe_db(turn),
        gates.gate_c1_wrong_primary_number(turn, turn_spec.get("primary_fact"), required, resolved),
        gates.gate_c2_wrong_secondary_number(turn, turn_spec.get("primary_fact"), required, resolved),
        gates.gate_c3_wrong_period(turn, expected_period, turn_spec.get("clarification_expected")),
        gates.gate_c4_unsupported_causality(turn),
        gates.gate_c5_forbidden_claim(turn, turn_spec.get("forbidden_claims") or []),
        gates.gate_f1_fabrication(turn),
    ]
    if correction_context is not None:
        previous_entities, corrected_entities = correction_context
        checks.append(gates.gate_f5_ignored_correction(turn, corrected_entities, previous_entities))

    verdict = gates.GateVerdict(checks=checks)
    result.gate_verdict = verdict

    if verdict.is_fatal:
        for dim in DIMENSIONS:
            result.dimension_scores[dim] = 0.0
        result.unscored_dimensions.clear()
        return result

    ceiling = verdict.ceiling
    for dim, zeroed in ((d, d in verdict.zeroed_dimensions) for d in list(result.dimension_scores)):
        if zeroed:
            result.dimension_scores[dim] = 0.0
        elif ceiling < 1.0:
            result.dimension_scores[dim] = min(result.dimension_scores[dim], ceiling)

    return result
