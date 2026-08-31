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
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.benchmark.adapters.base import BenchmarkAdapter
from eval.benchmark.adapters.track_a_structured import TrackAStructured
from eval.benchmark.adapters.track_b_anthropic import TrackBAnthropic
from eval.benchmark.adapters.track_b_frontier import TrackBFrontier
from eval.benchmark.adapters.track_b_openai_responses import TrackBOpenAIResponses
from eval.benchmark.cases_loader import CASES_DIR, Case, correction_context_for_turn, load_cases
from eval.benchmark.graders.deterministic import score_turn
from eval.benchmark.graders.ground_truth import resolve_ground_truth
from eval.benchmark.liveness import assert_liveness
from eval.benchmark.snapshot import load_lock
from eval.benchmark.adapters.provider_factory import provider_config_for_track


def build_adapter(track: str, sandbox: SnapshotSandbox, provider: str | None = None, model: str | None = None) -> BenchmarkAdapter:
    if track == "track_a_structured":
        if provider is not None or model is not None:
            raise ValueError("Track A does not accept --provider or --model")
        return TrackAStructured(sandbox=sandbox)
    config = provider_config_for_track(track, provider, model)
    config.pop("provider")
    if track == "track_b_openai_responses":
        return TrackBOpenAIResponses(sandbox=sandbox, provider=config)
    if track == "track_b_anthropic":
        return TrackBAnthropic(sandbox=sandbox, provider=config)
    return TrackBFrontier(sandbox=sandbox, provider=config)


def run_metadata(track: str, adapter: BenchmarkAdapter, provider: str | None, model: str | None) -> dict:
    porcelain = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    dirty_paths = [line[3:] for line in porcelain.splitlines()]
    resolved_provider = provider or {"track_b_openai_responses": "openai", "track_b_anthropic": "anthropic"}.get(track)
    return {"head_sha": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip(), "porcelain_status": porcelain,
            "worktree_clean": not dirty_paths, "dirty_paths": dirty_paths, "comparison_eligible": not dirty_paths,
            "requested_track": track, "resolved_track": adapter.name, "provider": resolved_provider, "model": model or getattr(adapter, "model", None), "snapshot": load_lock()}


def output_record(metadata: dict, case_id: str, turn_index: int, report: dict) -> dict:
    return metadata | {"case_id": case_id, "turn_index": turn_index, "usage": report.get("usage"), "deterministic_dimensions": report["dimension_scores"], "gate_results": report["gate_results"], "answer": report["text"]}
from eval.benchmark.snapshot import SnapshotSandbox


def run_case(adapter: BenchmarkAdapter, case: Case, sandbox: SnapshotSandbox) -> list[dict]:
    resolved = resolve_ground_truth(case, sandbox) if case.ground_truth_refs else {}
    session = adapter.new_session(f"bench-{case.id}")

    turn_reports = []
    for index, turn_spec in enumerate(case.turns):
        turn = session.ask(turn_spec["question"])
        correction_ctx = correction_context_for_turn(case, index)
        result = score_turn(turn, turn_spec, resolved, correction_context=correction_ctx)
        gate_results = {
            check.gate: check.triggered
            for check in (result.gate_verdict.checks if result.gate_verdict else [])
        }
        turn_reports.append(
            {
                "question": turn_spec["question"],
                "text": turn.text,
                "usage": turn.usage.__dict__,
                "dimension_scores": result.dimension_scores,
                "unscored": sorted(result.unscored_dimensions),
                "fatal": result.is_fatal,
                "correction_context": turn_spec.get("correction_context"),
                "gate_results": gate_results,
                "gate_hits": [c.gate for c in (result.gate_verdict.fatal_triggered + result.gate_verdict.ceiling_triggered)] if result.gate_verdict else [],
                "facts_missing": result.facts_missing,
            }
        )
    return turn_reports


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev", choices=["dev", "holdout"])
    parser.add_argument("--case", default=None, help="run a single case id")
    parser.add_argument("--track", default="track_a_structured", choices=["track_a_structured", "track_b_frontier", "track_b_openai_responses", "track_b_anthropic"])
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    sandbox = SnapshotSandbox()
    sandbox.verify()
    adapter = build_adapter(args.track, sandbox, args.provider, args.model)
    metadata = run_metadata(args.track, adapter, args.provider, args.model)

    cases = load_cases(CASES_DIR, split=args.split)
    if args.case:
        cases = [c for c in cases if c.id == args.case]

    print(f"Track: {adapter.name} | split: {args.split} | {len(cases)} cases")
    all_turn_reports = []
    for case in cases:
        print(f"\n=== {case.id} ({case.suite}) ===")
        case_reports = run_case(adapter, case, sandbox)
        all_turn_reports.extend(case_reports)
        if args.output:
            with args.output.open("a", encoding="utf-8") as fh:
                for index, report in enumerate(case_reports):
                    fh.write(json.dumps(output_record(metadata, case.id, index, report), ensure_ascii=False) + "\n")
        for i, turn_report in enumerate(case_reports):
            print(f"  turn {i}: {turn_report['question']!r}")
            print(f"    fatal={turn_report['fatal']} gates={turn_report['gate_hits']}")
            for dim, score in turn_report["dimension_scores"].items():
                print(f"    {dim}: {score:.2f}")
            if turn_report["unscored"]:
                print(f"    unscored (needs judge): {turn_report['unscored']}")
            if turn_report["facts_missing"]:
                print(f"    facts missing: {turn_report['facts_missing']}")
    assert_liveness(all_turn_reports)


if __name__ == "__main__":
    main()
