"""Assertions that benchmark wiring produced every applicable verdict."""
from __future__ import annotations

from typing import Any

from eval.benchmark.graders.gates import ALL_CEILING, ALL_FATAL


class LivenessError(AssertionError):
    """A declared deterministic benchmark check was not exercised."""


_JUDGE_OWNED_GATES = {"F1", "C4", "C5"}


def assert_liveness(reports: list[dict[str, Any]]) -> None:
    """Ensure applicable deterministic gates have real boolean outcomes.

    Judge-owned gates intentionally remain pending (``None``) until a judge
    is invoked; this verifier never turns that pending state into a pass.
    """
    for index, report in enumerate(reports):
        gate_results = report.get("gate_results", {})
        correction_context = report.get("correction_context")
        applicable = set(ALL_FATAL + ALL_CEILING) - {"F5"} - _JUDGE_OWNED_GATES
        if correction_context is not None:
            applicable.add("F5")
        for gate in sorted(applicable):
            verdict = gate_results.get(gate)
            if not isinstance(verdict, bool):
                raise LivenessError(f"report {index}: applicable {gate} verdict must be boolean, got {verdict!r}")
