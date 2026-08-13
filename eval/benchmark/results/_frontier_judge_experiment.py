"""Re-run the 8 already-graded (case_id, track) pairs from
judge_run_v1_2_calibration_2026-08-13.jsonl through the SAME rubric
(current HEAD, v1.2 post-C4-narrowing) and SAME judge implementation
(JUDGE_IMPL_VERSION 1.2.0), swapping ONLY the judge model/provider from
Mistral to a Gemini frontier model reached via the OpenAI-compatible
endpoint (same pattern as tools/db_chat.py in the main repo).

Diagnostic only. Does not touch rubric.yaml, judge.py, cases/, deterministic.py,
gates.py, or any human/ground-truth files.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(r"C:\Users\raimundo.opazo\automation_agent\.env")

import os
from openai import OpenAI

from eval.benchmark.adapters.base import Turn, ToolCall
from eval.benchmark.cases_loader import load_cases, CASES_DIR
from eval.benchmark.graders.ground_truth import resolve_ground_truth
from eval.benchmark.graders.deterministic import score_turn
from eval.benchmark.graders.judge_input import build_judge_input
from eval.benchmark.graders.judge import run_judge, JUDGE_IMPL_VERSION, load_rubric
from eval.benchmark.snapshot import SnapshotSandbox

RESULTS_DIR = Path(__file__).resolve().parent
BASELINE_JSONL = RESULTS_DIR / "judge_run_v1_2_calibration_2026-08-13.jsonl"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise SystemExit("GEMINI_API_KEY not found (loaded from main repo .env)")

_client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

CANDIDATE_MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
]


def probe_model(model: str) -> bool:
    try:
        resp = _client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "reply with OK"}],
            max_tokens=200,
        )
        content = resp.choices[0].message.content or ""
        print(f"  probe {model}: {content!r}")
        return "OK" in content.upper()
    except Exception as exc:  # noqa: BLE001
        print(f"  probe {model}: FAILED -- {type(exc).__name__}: {exc}")
        return False


def pick_model() -> str:
    for m in CANDIDATE_MODELS:
        if probe_model(m):
            return m
    raise SystemExit("No candidate Gemini model responded successfully.")


def chat_fn(model: str, messages: list[dict], temperature: float = 0.0, max_tokens: int = 3000):
    return _client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def load_baseline_records() -> list[dict]:
    recs = [json.loads(l) for l in BASELINE_JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in recs if r["classification"] == "attempted"]


def main() -> None:
    print("Rubric version (current HEAD):", load_rubric().get("rubric_version"))
    print("JUDGE_IMPL_VERSION:", JUDGE_IMPL_VERSION)

    model = pick_model()
    print("Using model:", model)

    records = load_baseline_records()
    print(f"{len(records)} attempted records to re-judge")

    cases_dev = {c.id: c for c in load_cases(CASES_DIR, split="dev")}
    cases_holdout = {c.id: c for c in load_cases(CASES_DIR, split="holdout")} if (CASES_DIR / "holdout").exists() else {}

    sandbox = SnapshotSandbox()
    sandbox.verify()

    out_path = RESULTS_DIR / f"judge_run_frontier_{model.replace('.', '-')}_calibration_2026-08-13.jsonl"
    out_records = []

    for rec in records:
        case_id = rec["case_id"]
        track = rec["track"]
        blind_label = rec["blind_label"]
        case = cases_dev.get(case_id) or cases_holdout.get(case_id)
        if case is None:
            raise SystemExit(f"case {case_id} not found in dev or holdout split")

        if len(case.turns) != 1:
            raise SystemExit(f"case {case_id} has {len(case.turns)} turns -- multi-turn matching not implemented, inspect manually")
        turn_spec = case.turns[0]

        resolved = resolve_ground_truth(case, sandbox)

        response_text = rec["response_text"]
        executed_sql = rec.get("executed_sql") or []
        sandbox.log.reset()
        turn = Turn(
            text=response_text,
            tool_calls=[ToolCall(name="sql", args={"sql": q}, ok=True) for q in executed_sql],
            queries=list(executed_sql),
        )

        det = score_turn(turn, turn_spec, resolved)
        det_summary = {
            "dimension_scores": dict(det.dimension_scores),
            "unscored_dimensions": sorted(det.unscored_dimensions),
        }
        baseline_det = rec.get("deterministic", {})
        det_match = (
            det_summary["dimension_scores"] == baseline_det.get("dimension_scores")
            and det_summary["unscored_dimensions"] == baseline_det.get("unscored_dimensions")
        )
        print(f"[{blind_label}] {case_id}/{track} deterministic match vs baseline: {det_match}")
        if not det_match:
            print("    baseline:", baseline_det)
            print("    recomputed:", det_summary)

        judge_input = build_judge_input(turn_spec, turn, resolved, det, sandbox)

        t0 = time.time()
        result = run_judge(judge_input, chat_fn=chat_fn, model=model)
        latency_ms = (time.time() - t0) * 1000

        out_rec = {
            "blind_label": blind_label,
            "case_id": case_id,
            "track": track,
            "classification": rec["classification"],
            "response_text": response_text,
            "executed_sql": executed_sql,
            "deterministic": det_summary,
            "deterministic_matches_baseline": det_match,
            "judge": {
                "provider": "gemini",
                "model": model,
                "rubric_version": result.rubric_version,
                "judge_impl_version": result.judge_impl_version,
                "judge_model": result.judge_model,
                "judge_failed": result.judge_failed,
                "failure_detail": result.failure_detail,
                "attempts": result.attempts,
                "latency_ms": latency_ms,
                "response_mode": result.response_mode,
                "dimension_scores": result.dimension_scores,
                "not_applicable": sorted(result.not_applicable),
                "dimension_details": result.dimension_details,
                "gates": result.gates,
            },
        }
        out_records.append(out_rec)
        print(f"  -> judge_failed={result.judge_failed} attempts={result.attempts} latency_ms={latency_ms:.0f}")

    with out_path.open("w", encoding="utf-8") as fh:
        for r in out_records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("Wrote", out_path)


if __name__ == "__main__":
    main()
