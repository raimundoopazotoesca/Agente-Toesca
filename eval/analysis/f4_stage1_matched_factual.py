"""Offline, read-only diagnostic: matched-denominator factual_correctness between
B27 (Track B baseline) and F4 Stage 1. Makes no provider calls, touches no result
file, imports nothing from Holdout.

The official reported numbers (B27=0.6431 n=51, F4=0.5439 n=66) are NOT
recomputed or replaced here -- they come from run_case()'s own score_turn() and
stay authoritative. This script only explains WHY the denominator moved, by
matching turns 1:1 on (case_id, turn_index) and splitting into matched /
newly-scored / lost-scored.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
B27 = ROOT / "eval/benchmark/results/round-b/round-b-20260818-b27/turns.jsonl"
F4S1 = ROOT / "eval/benchmark/results/round-b/round-b-f4s1-terra/turns.jsonl"


def load(path: Path) -> dict[tuple[str, int], dict]:
    return {(r["case_id"], r["turn_index"]): r for r in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines())}


def factual(row: dict) -> float | None:
    return (row.get("deterministic_grading") or {}).get("dimension_scores", {}).get("factual_correctness")


def main() -> None:
    b27, f4 = load(B27), load(F4S1)
    assert set(b27) == set(f4), "turn key sets differ between runs -- not directly comparable"

    matched, newly_scored, lost_scored = [], [], []
    for key in sorted(b27):
        bf, ff = factual(b27[key]), factual(f4[key])
        if bf is not None and ff is not None:
            matched.append((key, bf, ff))
        elif bf is None and ff is not None:
            newly_scored.append((key, ff))
        elif bf is not None and ff is None:
            lost_scored.append((key, bf))

    print("=== A. MATCHED FACTUAL ===")
    print(f"n = {len(matched)}")
    b_mean = statistics.mean(m[1] for m in matched)
    f_mean = statistics.mean(m[2] for m in matched)
    print(f"mean B27 = {b_mean:.4f}")
    print(f"mean F4  = {f_mean:.4f}")
    print(f"delta    = {f_mean - b_mean:+.4f}")
    print("per-turn (case turn: B27 -> F4):")
    for (case_id, turn_idx), bf, ff in matched:
        marker = "" if abs(bf - ff) < 1e-9 else ("  <-- DOWN" if ff < bf else "  <-- UP")
        print(f"  {case_id} turn{turn_idx}: {bf:.2f} -> {ff:.2f}{marker}")

    print("\n=== B. NEWLY SCORED (unscored in B27, scored in F4) ===")
    print(f"n = {len(newly_scored)}")
    if newly_scored:
        vals = [v for _, v in newly_scored]
        print(f"mean = {statistics.mean(vals):.4f}")
        dist = {v: sum(1 for x in vals if x == v) for v in sorted(set(vals))}
        print(f"distribution = {dist}")
        print("ids:")
        for (case_id, turn_idx), v in newly_scored:
            print(f"  {case_id} turn{turn_idx}: {v:.2f}")

    print("\n=== C. LOST SCORED (scored in B27, unscored in F4) ===")
    print(f"n = {len(lost_scored)}")
    for (case_id, turn_idx), v in lost_scored:
        print(f"  {case_id} turn{turn_idx}: was {v:.2f} in B27")

    print("\n=== D. OFFICIAL REPORTED (unchanged, for reference only) ===")
    print("B27 = 0.6431 n=51")
    print("F4  = 0.5439 n=66")
    print(f"(sanity: matched n={len(matched)} + newly_scored n={len(newly_scored)} = {len(matched)+len(newly_scored)}; official F4 n=66)")
    print(f"(sanity: matched n={len(matched)} + lost_scored n={len(lost_scored)} = {len(matched)+len(lost_scored)}; official B27 n=51)")


if __name__ == "__main__":
    main()
