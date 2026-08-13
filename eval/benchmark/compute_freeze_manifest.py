"""Compute the reproducibility identity block for a benchmark evaluation run.

Infra only: hashes the files that can silently change scoring behavior
(judge implementation, rubric, case schema, runner/adapter config) and
bundles them with the run-specific identity (code commit, model, inference
params, eval date) requested by HOLDOUT_SET_V1_FREEZE_SPEC.md.

Does not run any evaluation and does not touch holdout content -- it only
produces the identity block that a real run's report should carry.
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

HASHED_FILES = {
    "judge_py": BENCHMARK_DIR / "graders" / "judge.py",
    "rubric_yaml": BENCHMARK_DIR / "graders" / "rubric.yaml",
    "case_schema_json": BENCHMARK_DIR / "schema" / "case.schema.json",
    "runner_py": BENCHMARK_DIR / "runner.py",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, check=True, text=True
    ).stdout.strip()


def build_identity(
    *,
    evaluated_model: str,
    judge_model_resolved: str,
    eval_date: str,
    inference_params_evaluated: dict[str, Any] | None = None,
    inference_params_judge: dict[str, Any] | None = None,
    extra_adapter_files: list[Path] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    file_hashes = {name: _sha256_file(path) for name, path in HASHED_FILES.items()}
    for extra in extra_adapter_files or []:
        file_hashes[f"adapter:{extra.relative_to(REPO_ROOT).as_posix()}"] = _sha256_file(extra)

    snapshot_lock = json.loads((BENCHMARK_DIR / "snapshot.lock").read_text(encoding="utf-8"))

    return {
        "code_commit_sha": _git_head(),
        "snapshot_sha256": snapshot_lock["sha256"],
        "snapshot_source_commit": snapshot_lock["git_commit"],
        "benchmark_today": snapshot_lock["benchmark_today"],
        "file_hashes": file_hashes,
        "evaluated_model": evaluated_model,
        "judge_model_resolved": judge_model_resolved,
        "inference_params_evaluated": inference_params_evaluated or {},
        "inference_params_judge": inference_params_judge or {},
        "eval_date": eval_date,
        "notes": notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluated-model", required=True)
    parser.add_argument("--judge-model-resolved", required=True)
    parser.add_argument("--eval-date", required=True, help="YYYY-MM-DD, actual date the run happened")
    parser.add_argument("--notes", default="")
    parser.add_argument("--out", type=Path, default=None, help="write JSON here instead of stdout")
    args = parser.parse_args()

    identity = build_identity(
        evaluated_model=args.evaluated_model,
        judge_model_resolved=args.judge_model_resolved,
        eval_date=args.eval_date,
        notes=args.notes,
    )
    text = json.dumps(identity, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
