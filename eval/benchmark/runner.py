"""Run the benchmark's dev-split cases against one adapter and print a
per-case, per-dimension report.

Deterministic-only for now: dimensions that need the rubric judge (see
graders/deterministic.py's DIMENSIONS list) are reported as `unscored`
rather than guessed at. That judge is a separate, not-yet-built piece
(design doc section 9, layer 2) -- this script gives real signal on
factual_correctness/completeness/conversational_quality/gates today
without waiting on it.

Usage:
    python -m eval.benchmark.runner                  # Track A, dev split
    python -m eval.benchmark.runner --split holdout   # only at a milestone
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.benchmark.adapters.base import BenchmarkAdapter
from eval.benchmark.adapters.track_a_structured import TrackAStructured
from eval.benchmark.cases_loader import CASES_DIR, Case, load_cases
from eval.benchmark.graders.deterministic import score_turn
from eval.benchmark.graders.ground_truth import resolve_ground_truth
from eval.benchmark.snapshot import SnapshotSandbox


def run_case(adapter: BenchmarkAdapter, case: Case, sandbox: SnapshotSandbox) -> list[dict]:
    resolved = resolve_ground_truth(case, sandbox) if case.ground_truth_refs else {}
    session = adapter.new_session(f"bench-{case.id}")

    turn_reports = []
    previous_entities: dict[str, str] = {}
    for turn_spec in case.turns:
        turn = session.ask(turn_spec["question"])
        correction_ctx = None  # wired up once TCE correction cases exist with a marker field
        result = score_turn(turn, turn_spec, resolved, correction_context=correction_ctx)
        turn_reports.append(
            {
                "question": turn_spec["question"],
                "text": turn.text,
                "dimension_scores": result.dimension_scores,
                "unscored": sorted(result.unscored_dimensions),
                "fatal": result.is_fatal,
                "gate_hits": [c.gate for c in (result.gate_verdict.fatal_triggered + result.gate_verdict.ceiling_triggered)] if result.gate_verdict else [],
                "facts_missing": result.facts_missing,
            }
        )
        previous_entities = turn_spec.get("expected_entities", previous_entities)
    return turn_reports


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev", choices=["dev", "holdout"])
    parser.add_argument("--case", default=None, help="run a single case id")
    args = parser.parse_args()

    sandbox = SnapshotSandbox()
    sandbox.verify()
    adapter = TrackAStructured(sandbox=sandbox)

    cases = load_cases(CASES_DIR, split=args.split)
    if args.case:
        cases = [c for c in cases if c.id == args.case]

    print(f"Track: {adapter.name} | split: {args.split} | {len(cases)} cases")
    for case in cases:
        print(f"\n=== {case.id} ({case.suite}) ===")
        for i, turn_report in enumerate(run_case(adapter, case, sandbox)):
            print(f"  turn {i}: {turn_report['question']!r}")
            print(f"    fatal={turn_report['fatal']} gates={turn_report['gate_hits']}")
            for dim, score in turn_report["dimension_scores"].items():
                print(f"    {dim}: {score:.2f}")
            if turn_report["unscored"]:
                print(f"    unscored (needs judge): {turn_report['unscored']}")
            if turn_report["facts_missing"]:
                print(f"    facts missing: {turn_report['facts_missing']}")


if __name__ == "__main__":
    main()
