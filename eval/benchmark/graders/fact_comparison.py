"""Semantic-unit-aware comparisons for resolved benchmark facts."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from eval.benchmark.graders.ground_truth import ResolvedFact
from eval.benchmark.graders.numbers import value_in_text


_NUMERIC_UNITS = {"clp", "uf", "pct", "m2", "count", "ratio"}


def is_numeric_fact(fact: ResolvedFact) -> bool:
    return fact.unit.casefold() in _NUMERIC_UNITS


def text_fact_in_answer(value: Any, text: str) -> bool:
    def normalize(item: Any) -> str:
        item = unicodedata.normalize("NFKD", str(item)).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", item).strip().casefold()
    return normalize(value) in normalize(text)


def fact_in_answer(
    fact: ResolvedFact,
    text: str,
    *,
    tolerance_pct: float = 0.0,
    tolerance_abs: float = 0.0,
) -> bool:
    """Compare a fact according to its schema-declared semantic unit."""
    if fact.unit.casefold() == "date":
        value = str(fact.value)
        return bool(re.search(rf"(?<!\d){re.escape(value)}(?!\d)", text))
    if not is_numeric_fact(fact):
        return text_fact_in_answer(fact.value, text)
    return value_in_text(float(fact.value), text, tolerance_pct=tolerance_pct, tolerance_abs=tolerance_abs)
