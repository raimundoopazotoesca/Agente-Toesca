"""A3.3: deterministic factual-trend validation.

Closes the A3.2 residual gap identified in the A3.3 Design Memo v2: a claim
can carry a correct value while the free prose around it asserts an
incorrect DIRECTION ("cayo" when the real values rose). A3.2's
coverage_guard already forbids raw digits and unbound qualitative
superlatives in free text; this module extends the same philosophy to a
closed set of single-entity trend verbs/adjectives.

Everything here is a pure function over already-validated data (bound
canonical facts, bound derived claims). No new evidence store, no new
claim class, no LLM, no NLP -- a fixed lexicon (regex) plus arithmetic
already computed by derived_claims.py.

V1 lexicon and rules were derived from real prose already present in this
repository's test fixtures and system-prompt examples (see the A3.3 Design
Memo v2 and its 21.1-21.4 closure) -- not invented in the abstract:
  - "mejoro"/"mejora"/"se recupero" are excluded because the product's own
    voice examples use "mejora" in hedged/speculative contexts
    (test_product_voice.py), not as a realized-change assertion.
  - "alto"/"bajo"/"alta"/"baja" are excluded: they describe LEVEL, not
    DIRECTION of change (test_coverage_guard.py's "vacancia alta" fixture).
  - The DOWN lexicon uses only conjugated verb forms, never the nominal
    stem "disminucion(es)", which names a distinct domain event
    (aporte/disminucion de capital) in real fixtures
    (test_fund_financial_session.py), not a metric trend.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from tools.analytics.humanize import _parse_period  # reuse, never reimplement

Direction = Literal["UP", "DOWN", "FLAT"]

# ---- V1 lexicon (exact, approved terms only; see module docstring) --------

TREND_LEXICON: dict[str, Direction] = {
    # UP
    "subió": "UP", "subieron": "UP", "aumentó": "UP", "aumentaron": "UP",
    "creció": "UP", "crecieron": "UP", "se incrementó": "UP", "incrementó": "UP",
    # DOWN
    "cayó": "DOWN", "cayeron": "DOWN", "bajó": "DOWN", "bajaron": "DOWN",
    "disminuyó": "DOWN", "disminuyeron": "DOWN", "decreció": "DOWN", "decrecieron": "DOWN",
    "retrocedió": "DOWN", "retrocedieron": "DOWN",
    # FLAT
    "se mantuvo": "FLAT", "se mantuvieron": "FLAT",
    "no tuvo cambios": "FLAT", "no tuvieron cambios": "FLAT",
    "permaneció estable": "FLAT", "permanecieron estables": "FLAT",
    "no varió": "FLAT", "no variaron": "FLAT",
}

# Compiled once, longest terms first so a multi-word term (e.g. "no tuvo
# cambios") is not shadowed by a shorter unrelated overlap. Word boundaries
# on both sides; case-insensitive (draft/final prose may capitalize at
# sentence start).
_TREND_TERMS_SORTED = sorted(TREND_LEXICON, key=len, reverse=True)
_TREND_TERM_RE = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(term) for term in _TREND_TERMS_SORTED) + r")(?!\w)",
    re.IGNORECASE,
)

# Derived-claim operations whose sign/magnitude grounds a real before/after
# relation. Deliberately distinct from coverage_guard.has_comparison_claim:
# percent_change IS included here (its sign is exactly a temporal
# direction), discount_premium is EXCLUDED (same-period book-vs-market
# relation, never a temporal trend -- see derived_claims.py).
TREND_GROUNDING_OPERATIONS = frozenset(
    {"difference", "percent_change", "percentage_point_difference", "ratio", "comparison"}
)

# ---- Clause segmentation (fixed delimiters, no NLP) ------------------------

_PRIMARY_SPLIT_RE = re.compile(r",|;|\bpero\b|\bmientras(?: que)?\b", re.IGNORECASE)
_AND_SPLIT_RE = re.compile(r"\by\b", re.IGNORECASE)


def split_clauses(text: str) -> list[str]:
    """Deterministic clause segmentation for trend-term scanning.

    First splits on ",", ";", "pero", "mientras"/"mientras que" (never
    breaks an enumeration like "Torre A, Boulevard y Parking PT" alone,
    since a plain listing carries no trend term). Only within a segment
    that already contains 2+ trend-term matches does " y " become an
    additional delimiter -- this is what lets "El NOI del Activo A subió y
    el del Activo B cayó" split into two independently-checkable clauses
    without also fracturing entity enumerations that have no trend verbs.
    """
    segments = [segment for segment in _PRIMARY_SPLIT_RE.split(text) if segment.strip()]
    clauses: list[str] = []
    for segment in segments:
        if len(_TREND_TERM_RE.findall(segment)) >= 2:
            clauses.extend(part for part in _AND_SPLIT_RE.split(segment) if part.strip())
        else:
            clauses.append(segment)
    return clauses


def find_trend_terms(clause: str) -> list[Direction]:
    """All lexicon matches in one clause, in order of appearance."""
    return [TREND_LEXICON[match.lower()] for match in _TREND_TERM_RE.findall(clause)]


@dataclass(frozen=True)
class ClauseTrendHit:
    clause: str
    direction: Direction


AMBIGUOUS = "AMBIGUOUS"


def extract_clause_trend_hits(text: str) -> list[ClauseTrendHit] | Literal["AMBIGUOUS"]:
    """One ClauseTrendHit per clause with exactly one distinct direction.

    A clause is not itself ambiguous just because a term repeats (e.g. "no
    tuvo cambios ni tuvo cambios" -- degenerate, still one direction). It IS
    ambiguous when two DIFFERENT directions appear in the very same clause
    (no delimiter separated them, so nothing tells us which value belongs
    to which verb) -- returns the AMBIGUOUS sentinel for the whole text in
    that case, so the caller fails closed rather than guessing.
    """
    hits: list[ClauseTrendHit] = []
    for clause in split_clauses(text):
        directions = find_trend_terms(clause)
        if not directions:
            continue
        distinct = set(directions)
        if len(distinct) > 1:
            return AMBIGUOUS
        hits.append(ClauseTrendHit(clause=clause, direction=next(iter(distinct))))
    return hits


# ---- Direction normalization (reuses raw values already computed) ---------


def resolve_direction(lhs_value: float, lhs_period: Any, rhs_value: float, rhs_period: Any) -> Direction | None:
    """UP/DOWN/FLAT from two raw values at two real periods.

    Independent of which operand the model labelled lhs/rhs (that is only a
    documented authoring convention, never enforced elsewhere) -- this
    canonicalizes by the periods' own chronological order, resolved via
    tools.analytics.humanize._parse_period (the same YYYY-MM shape check the
    rest of this codebase already uses for period formatting, never
    reimplemented here). YYYY-MM strings compare lexicographically ==
    chronologically once validated. Returns None when the periods are
    equal, or either fails the YYYY-MM shape -- not a temporal comparison,
    so not eligible as trend-grounding evidence at all.
    """
    lhs_p, rhs_p = str(lhs_period), str(rhs_period)
    if _parse_period(lhs_p) is None or _parse_period(rhs_p) is None or lhs_p == rhs_p:
        return None
    earlier_value, later_value = (lhs_value, rhs_value) if lhs_p < rhs_p else (rhs_value, lhs_value)
    if later_value > earlier_value:
        return "UP"
    if later_value < earlier_value:
        return "DOWN"
    return "FLAT"


def eligible_trend_direction(operation: str, lhs_fact: dict[str, Any], rhs_fact: dict[str, Any]) -> Direction | None:
    """The real UP/DOWN/FLAT a derived claim grounds, or None if it does not
    qualify as temporal trend-grounding evidence at all (wrong operation,
    cross-entity, cross-metric, or not genuinely temporal).

    Deliberately NOT the sign of DerivedClaim.value: that sign's meaning
    varies by operation (difference/comparison/ratio use lhs-earlier
    convention, percent_change uses the opposite), which is exactly the
    kind of per-operation special-casing this design avoids. Reads the raw
    lhs_value/rhs_value + real periods instead (see resolve_direction).
    """
    if operation not in TREND_GROUNDING_OPERATIONS:
        return None
    if lhs_fact.get("entity_id") != rhs_fact.get("entity_id"):
        return None
    if lhs_fact.get("metric_key") != rhs_fact.get("metric_key"):
        return None
    try:
        lhs_value, rhs_value = float(lhs_fact["value"]), float(rhs_fact["value"])
    except (KeyError, TypeError, ValueError):
        return None
    return resolve_direction(lhs_value, lhs_fact.get("period"), rhs_value, rhs_fact.get("period"))
