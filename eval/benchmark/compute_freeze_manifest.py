"""Compute reproducibility identity blocks for the Holdout Set.

Two DELIBERATELY separate concerns -- see HOLDOUT_FREEZE_MANIFEST_SPEC.md
and EVALUATION_RUN_MANIFEST_SPEC.md for the full rationale:

- `build_holdout_freeze_manifest()`: identity of the holdout CONTENT
  (case count/ids, pinned snapshot, case schema hash, private repo
  commit). Independent of any model, judge, inference params or eval
  date. Produced once per content freeze, referenced by many runs.

- `build_evaluation_run_manifest()`: identity of ONE evaluation RUN
  (evaluated code/model, judge model resolved, judge/rubric/runner
  hashes, inference params, eval date). Must reference a holdout_id from
  a real freeze manifest; never recomputes holdout content identity.

Infra only -- neither function runs an evaluation or touches holdout case
content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

BENCHMARK_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARK_DIR.parents[1]

# Content-defining files: shape/scope of the holdout itself.
_CONTENT_HASHED_FILES = {
    "case_schema_json": BENCHMARK_DIR / "schema" / "case.schema.json",
}

# Scoring-engine files: can legitimately change between runs of the SAME
# frozen holdout (a judge fix, a rubric revision) -- these belong to the
# run manifest, not the freeze manifest.
_RUN_HASHED_FILES = {
    "judge_py": BENCHMARK_DIR / "graders" / "judge.py",
    "rubric_yaml": BENCHMARK_DIR / "graders" / "rubric.yaml",
    "runner_py": BENCHMARK_DIR / "runner.py",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _sha256_files_concat(paths: list[Path]) -> str:
    """Deterministic hash over multiple files: sorted by relative path,
    each entry as `relpath\n<bytes>`, so file identity and order both
    matter (renames/reorders change the hash, not just content edits)."""
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.as_posix()):
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\n")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_head(cwd: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, check=True, text=True
    ).stdout.strip()


def build_holdout_freeze_manifest(
    *,
    holdout_id: str,
    case_ids: list[str],
    tae_count: int,
    tce_count: int,
    turn_count: int,
    private_repo_dir: Path,
    frozen_at: str,
    human_signoff: str,
) -> dict[str, Any]:
    """Identity of the holdout CONTENT. No model/judge/inference/eval_date
    fields -- those belong to build_evaluation_run_manifest()."""
    snapshot_lock = json.loads((BENCHMARK_DIR / "snapshot.lock").read_text(encoding="utf-8"))
    case_files = sorted((private_repo_dir / "cases" / "holdout").rglob("*.yaml"))

    return {
        "holdout_id": holdout_id,
        "benchmark_version": snapshot_lock["benchmark_version"],
        "case_count": len(case_ids),
        "tae_count": tae_count,
        "tce_count": tce_count,
        "turn_count": turn_count,
        "case_ids": sorted(case_ids),
        "snapshot_sha256": snapshot_lock["sha256"],
        "snapshot_source_commit": snapshot_lock["git_commit"],
        "case_schema_sha256": _sha256_file(_CONTENT_HASHED_FILES["case_schema_json"]),
        "private_repo_commit_sha": _git_head(private_repo_dir),
        "private_repo_content_sha256": _sha256_files_concat(case_files),
        "frozen_at": frozen_at,
        "human_signoff": human_signoff,
    }


def build_evaluation_run_manifest(
    *,
    holdout_id: str,
    run_id: str,
    evaluated_model: str,
    judge_model_resolved: str,
    eval_date: str,
    purpose: str,
    tuning_contamination_flag: bool = False,
    contamination_notes: str = "",
    inference_params_evaluated: dict[str, Any] | None = None,
    inference_params_judge: dict[str, Any] | None = None,
    extra_adapter_files: list[Path] | None = None,
) -> dict[str, Any]:
    """Identity of ONE evaluation run. References holdout_id; never
    recomputes holdout content identity (snapshot/schema/case list --
    those are build_holdout_freeze_manifest()'s job)."""
    run_hashes = {name: _sha256_file(path) for name, path in _RUN_HASHED_FILES.items()}
    for extra in extra_adapter_files or []:
        run_hashes[f"adapter:{extra.relative_to(REPO_ROOT).as_posix()}"] = _sha256_file(extra)

    return {
        "holdout_id": holdout_id,
        "run_id": run_id,
        "code_commit_sha": _git_head(REPO_ROOT),
        "evaluated_model": evaluated_model,
        "judge_model_resolved": judge_model_resolved,
        "run_file_hashes": run_hashes,
        "inference_params_evaluated": inference_params_evaluated or {},
        "inference_params_judge": inference_params_judge or {},
        "eval_date": eval_date,
        "purpose": purpose,
        "tuning_contamination_flag": tuning_contamination_flag,
        "contamination_notes": contamination_notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    freeze_p = sub.add_parser("freeze", help="build a Holdout Freeze Manifest")
    freeze_p.add_argument("--holdout-id", required=True)
    freeze_p.add_argument("--private-repo-dir", type=Path, required=True)
    freeze_p.add_argument("--case-ids", required=True, help="comma-separated")
    freeze_p.add_argument("--tae-count", type=int, required=True)
    freeze_p.add_argument("--tce-count", type=int, required=True)
    freeze_p.add_argument("--turn-count", type=int, required=True)
    freeze_p.add_argument("--frozen-at", required=True, help="YYYY-MM-DD")
    freeze_p.add_argument("--human-signoff", required=True)
    freeze_p.add_argument("--out", type=Path, default=None)

    run_p = sub.add_parser("run", help="build an Evaluation Run Manifest")
    run_p.add_argument("--holdout-id", required=True)
    run_p.add_argument("--run-id", required=True)
    run_p.add_argument("--evaluated-model", required=True)
    run_p.add_argument("--judge-model-resolved", required=True)
    run_p.add_argument("--eval-date", required=True, help="YYYY-MM-DD")
    run_p.add_argument("--purpose", required=True)
    run_p.add_argument("--out", type=Path, default=None)

    args = parser.parse_args()

    if args.command == "freeze":
        identity = build_holdout_freeze_manifest(
            holdout_id=args.holdout_id,
            case_ids=[c.strip() for c in args.case_ids.split(",") if c.strip()],
            tae_count=args.tae_count,
            tce_count=args.tce_count,
            turn_count=args.turn_count,
            private_repo_dir=args.private_repo_dir,
            frozen_at=args.frozen_at,
            human_signoff=args.human_signoff,
        )
    else:
        identity = build_evaluation_run_manifest(
            holdout_id=args.holdout_id,
            run_id=args.run_id,
            evaluated_model=args.evaluated_model,
            judge_model_resolved=args.judge_model_resolved,
            eval_date=args.eval_date,
            purpose=args.purpose,
        )

    text = json.dumps(identity, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
