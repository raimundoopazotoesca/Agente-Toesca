"""Deterministic percentile helper for small telemetry samples.

Uses the "nearest rank" method (no interpolation): for a sample of size
``n`` sorted ascending, the p-th percentile is the value at rank
``ceil(p / 100 * n)`` (1-indexed), clamped to ``[1, n]``. This is the same
method described in NIST/ISO references for percentiles over small,
discrete samples and avoids any dependency on numpy or other numeric
libraries.

Example: values = [10, 20, 30, 40] (n=4)
  p50 -> rank = ceil(0.50 * 4) = 2 -> sorted[1] = 20
  p90 -> rank = ceil(0.90 * 4) = 4 -> sorted[3] = 40
"""
from __future__ import annotations

import math


def nearest_rank_percentile(values: list[float], p: float) -> float | None:
    """Return the p-th percentile (0 <= p <= 100) of ``values`` via nearest rank.

    Returns ``None`` for an empty sample. Non-finite/None entries must be
    filtered out by the caller before calling this function -- it never
    treats a missing value as zero.
    """
    if not values:
        return None
    if not (0 <= p <= 100):
        raise ValueError("p must be between 0 and 100")
    ordered = sorted(values)
    n = len(ordered)
    rank = max(1, min(n, math.ceil((p / 100) * n)))
    return ordered[rank - 1]


def average(values: list[float]) -> float | None:
    """Return the arithmetic mean of ``values``, or ``None`` if empty."""
    if not values:
        return None
    return sum(values) / len(values)
