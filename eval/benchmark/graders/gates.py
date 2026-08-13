"""Hard gates, split per design doc section 8 into:

  - fatal gates (F1-F5): the response isn't about what was asked, or its
    content doesn't come from data. Anull the case entirely.
  - ceiling caps (C1-C5): a real error, but the rest of the response can
    still be judged. Impose a score ceiling and zero the directly-affected
    dimension; everything else scores normally.

This module implements every gate that can be decided from data already on
the Turn (sandbox trace, resolved ground truth, catalog aliases) without a
judge call: F2, F3, F4, F5, C1, C2, C3. F1 (fabrication) and C4/C5
(unsupported causality, forbidden claims) need the rubric judge to read
intent, not just surface text -- see design doc section 9. Their check
functions exist here as the wiring point but return GateCheck(triggered=
None, ...) ("not decidable without a judge") rather than faking a verdict;
the runner treats None as "ask the judge", not as "pass".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eval.benchmark.adapters.base import Turn
from eval.benchmark.graders.entities import (
    check_expected_entities,
    other_entities_mentioned,
    period_matches,
)
from eval.benchmark.graders.ground_truth import ResolvedFact
from eval.benchmark.graders.numbers import value_in_text

FATAL = "fatal"
CEILING = "ceiling"


@dataclass
class GateCheck:
    gate: str
    kind: str  # fatal | ceiling
    triggered: bool | None  # None = not decidable deterministically (needs judge)
    detail: str = ""
    ceiling: float | None = None  # only meaningful when kind == "ceiling"
    zeroed_dimension: str | None = None


# ---------------------------------------------------------------------------
# Fatal gates
# ---------------------------------------------------------------------------

def gate_f1_fabrication(turn: Turn) -> GateCheck:
    return GateCheck("F1", FATAL, triggered=None, detail="requires rubric judge with query evidence")


def gate_f2_entity_confusion(turn: Turn, expected_entities: dict[str, str]) -> GateCheck:
    """Triggered when the answer is clearly about a *different* known entity
    of the same type than the one expected, and never mentions the expected
    one -- e.g. answering about the fund Apo when Apo3001 (which belongs to
    TRI) was asked about."""
    for etype, ekey in (expected_entities or {}).items():
        found = check_expected_entities(turn.text, {etype: ekey})[etype]
        if found:
            continue
        confused_with = other_entities_mentioned(turn.text, etype, ekey)
        if confused_with:
            return GateCheck(
                "F2", FATAL, triggered=True,
                detail=f"expected {etype}={ekey}, answer is about {etype}={sorted(confused_with)}",
            )
    return GateCheck("F2", FATAL, triggered=False)


def gate_f3_session_leak(turn: Turn, other_session_markers: list[str]) -> GateCheck:
    """`other_session_markers`: entity/fact strings that only exist in a
    different session's conversation. Any of them showing up here is a leak."""
    text_lower = (turn.text or "").lower()
    leaked = [m for m in other_session_markers if m and m.lower() in text_lower]
    if leaked:
        return GateCheck("F3", FATAL, triggered=True, detail=f"leaked markers: {leaked}")
    return GateCheck("F3", FATAL, triggered=False)


def gate_f4_unsafe_db(turn: Turn) -> GateCheck:
    if turn.gate_violations:
        return GateCheck("F4", FATAL, triggered=True, detail="; ".join(turn.gate_violations))
    return GateCheck("F4", FATAL, triggered=False)


def gate_f5_ignored_correction(turn: Turn, corrected_entities: dict[str, str], previous_entities: dict[str, str]) -> GateCheck:
    """After a user correction ("no, me referia a X"), the very next turn
    must be about the corrected entity, not the one being corrected away
    from. Only meaningful on the turn immediately following a correction;
    the runner is responsible for calling this only there."""
    still_on_old = any(
        check_expected_entities(turn.text, {etype: ekey})[etype]
        for etype, ekey in (previous_entities or {}).items()
        if previous_entities.get(etype) != corrected_entities.get(etype)
    )
    on_new = all(
        check_expected_entities(turn.text, {etype: ekey})[etype]
        for etype, ekey in (corrected_entities or {}).items()
    )
    if still_on_old and not on_new:
        return GateCheck("F5", FATAL, triggered=True, detail="answer stayed on the pre-correction entity")
    return GateCheck("F5", FATAL, triggered=False)


# ---------------------------------------------------------------------------
# Ceiling caps
# ---------------------------------------------------------------------------

def gate_c1_wrong_primary_number(
    turn: Turn, primary_fact: str | None, required_facts: list[dict[str, Any]], resolved: dict[str, ResolvedFact]
) -> GateCheck:
    if not primary_fact:
        return GateCheck("C1", CEILING, triggered=False)
    spec = next((f for f in required_facts if f["ref"] == primary_fact), None)
    if spec is None or primary_fact not in resolved:
        return GateCheck("C1", CEILING, triggered=None, detail="primary_fact not resolvable")
    fact = resolved[primary_fact]
    ok = value_in_text(
        float(fact.value), turn.text,
        tolerance_pct=spec.get("tolerance_pct", 0.0),
        tolerance_abs=spec.get("tolerance_abs", 0.0),
    )
    if ok:
        return GateCheck("C1", CEILING, triggered=False)
    return GateCheck(
        "C1", CEILING, triggered=True, ceiling=0.30, zeroed_dimension="factual_correctness",
        detail=f"primary fact {primary_fact}={fact.value} not found in answer within tolerance",
    )


def gate_c2_wrong_secondary_number(
    turn: Turn, primary_fact: str | None, required_facts: list[dict[str, Any]], resolved: dict[str, ResolvedFact]
) -> GateCheck:
    misses = []
    for spec in required_facts:
        ref = spec["ref"]
        if ref == primary_fact or ref not in resolved:
            continue
        fact = resolved[ref]
        ok = value_in_text(
            float(fact.value), turn.text,
            tolerance_pct=spec.get("tolerance_pct", 0.0),
            tolerance_abs=spec.get("tolerance_abs", 0.0),
        )
        if not ok:
            misses.append(ref)
    if misses:
        return GateCheck(
            "C2", CEILING, triggered=True, ceiling=0.60, zeroed_dimension=None,
            detail=f"secondary facts missing/out of tolerance: {misses}",
        )
    return GateCheck("C2", CEILING, triggered=False)


def gate_c3_wrong_period(turn: Turn, expected_period: dict[str, str] | None, clarification_expected) -> GateCheck:
    if not expected_period:
        return GateCheck("C3", CEILING, triggered=False)
    if period_matches(turn.text, expected_period):
        return GateCheck("C3", CEILING, triggered=False)
    # A declared substitution ("no hay dato de julio, muestro junio") is
    # correct behaviour, not an error -- but detecting the declaration
    # itself is a judge call, so a deterministic miss here is reported as
    # `None` (ambiguous) unless the case explicitly does not expect
    # clarification/declaration handling, in which case it's a clean miss.
    if clarification_expected in (True, "acceptable"):
        return GateCheck("C3", CEILING, triggered=None, detail="period missing; may be a declared substitution")
    return GateCheck("C3", CEILING, triggered=True, ceiling=0.40, detail="expected period not mentioned in answer")


def gate_c4_unsupported_causality(turn: Turn) -> GateCheck:
    return GateCheck("C4", CEILING, triggered=None, ceiling=0.50, zeroed_dimension="grounding",
                      detail="requires rubric judge with query evidence")


def gate_c5_forbidden_claim(turn: Turn, forbidden_claims: list[str]) -> GateCheck:
    if not forbidden_claims:
        return GateCheck("C5", CEILING, triggered=False)
    return GateCheck("C5", CEILING, triggered=None, ceiling=0.50,
                      detail=f"requires rubric judge to check against: {forbidden_claims}")


ALL_FATAL = ["F1", "F2", "F3", "F4", "F5"]
ALL_CEILING = ["C1", "C2", "C3", "C4", "C5"]


@dataclass
class GateVerdict:
    checks: list[GateCheck]

    @property
    def fatal_triggered(self) -> list[GateCheck]:
        return [c for c in self.checks if c.kind == FATAL and c.triggered]

    @property
    def ceiling_triggered(self) -> list[GateCheck]:
        return [c for c in self.checks if c.kind == CEILING and c.triggered]

    @property
    def pending_judge(self) -> list[GateCheck]:
        return [c for c in self.checks if c.triggered is None]

    @property
    def is_fatal(self) -> bool:
        return bool(self.fatal_triggered)

    @property
    def ceiling(self) -> float:
        """Minimum ceiling across triggered caps; 1.0 (no cap) if none."""
        caps = [c.ceiling for c in self.ceiling_triggered if c.ceiling is not None]
        return min(caps) if caps else 1.0

    @property
    def zeroed_dimensions(self) -> set[str]:
        return {c.zeroed_dimension for c in self.checks if c.triggered and c.zeroed_dimension}
