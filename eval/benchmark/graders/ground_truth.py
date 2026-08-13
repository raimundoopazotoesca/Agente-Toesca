"""Resolve a case's `ground_truth_refs` by running the author's SQL against
the pinned snapshot.

Numbers are never hand-written into case files (see design doc section 6);
this is the one place that turns a named ref into an actual value, using a
*trusted* connection (guard=False -- this is benchmark authoring code, not
the system under test).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eval.benchmark.cases_loader import Case
from eval.benchmark.snapshot import SnapshotSandbox


class GroundTruthError(Exception):
    """A ground_truth_refs SQL statement did not resolve to a single value."""


@dataclass
class ResolvedFact:
    ref: str
    value: Any
    unit: str


def resolve_ground_truth(case: Case, sandbox: SnapshotSandbox) -> dict[str, ResolvedFact]:
    resolved: dict[str, ResolvedFact] = {}
    conn = sandbox.connect(guard=False)
    try:
        for ref, spec in case.ground_truth_refs.items():
            rows = conn.execute(spec["sql"]).fetchall()
            if len(rows) != 1 or len(rows[0]) != 1:
                raise GroundTruthError(
                    f"{case.id}: ground_truth_refs[{ref!r}] must resolve to exactly one "
                    f"row/column, got {len(rows)} rows"
                )
            resolved[ref] = ResolvedFact(ref=ref, value=rows[0][0], unit=spec["unit"])
    finally:
        conn.close()
    return resolved
