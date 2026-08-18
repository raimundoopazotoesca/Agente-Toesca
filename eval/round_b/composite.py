"""Offline validation for a split Full Dev continuation composite."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.round_b.runner import validate_full_dev


MODEL_FACING_FIELDS = (
    "system_prompt_sha256", "tool_schema_sha256", "inference_profile",
    "max_model_tool_rounds", "retry_policy", "timeout_policy",
)

CURRENT_GRADER_SHA = "354d0209422ca679cef62816923205d5a5735874c06a6fc52c1418b30df5cb51"
CURRENT_GATES_SHA = "24a8acf210b5b1a3b31a931b632d53920ffda32fede19bc704c6953ea1a3cdf6"
ABORTED_B25_CASE = "tce-investigationanomaly-001"


def _checkpoint_cases(directory: Path, state: str) -> list[str]:
    checkpoint = json.loads((directory / "checkpoint.json").read_text(encoding="utf-8"))
    return [case_id for case_id, case_state in checkpoint.get("openai", {}).items() if case_state == state]


def derive_remaining_cases(completed_case_ids: list[str]) -> dict[str, Any]:
    freeze = validate_full_dev()
    completed = set(completed_case_ids)
    if len(completed) != len(completed_case_ids):
        raise ValueError("duplicate completed case id")
    unknown = completed - set(freeze["ordered_case_ids"])
    if unknown:
        raise ValueError(f"completed case outside Dev freeze: {sorted(unknown)}")
    ordered = [case_id for case_id in freeze["ordered_case_ids"] if case_id not in completed]
    return {
        "source_dev_fingerprint": freeze["content_sha256"],
        "ordered_case_ids": ordered,
        "turn_counts": {case_id: freeze["turn_counts"][case_id] for case_id in ordered},
        "case_count": len(ordered),
        "turn_count": sum(freeze["turn_counts"][case_id] for case_id in ordered),
    }


def derive_b26_remaining_cases(b24_dir: Path, b25_dir: Path) -> dict[str, Any]:
    """Derive B26 from completed checkpoints, never from partial B25 turns."""
    b24_completed = _checkpoint_cases(b24_dir, "completed")
    b25_completed = _checkpoint_cases(b25_dir, "completed")
    b25_aborted = _checkpoint_cases(b25_dir, "aborted")
    if b25_aborted != [ABORTED_B25_CASE]:
        raise ValueError(f"unexpected B25 aborted cases: {b25_aborted}")

    completed = b24_completed + b25_completed
    remaining = derive_remaining_cases(completed)
    if not remaining["ordered_case_ids"] or remaining["ordered_case_ids"][0] != ABORTED_B25_CASE:
        raise ValueError("B25 aborted case must restart in B26 from turn zero")
    freeze = validate_full_dev()
    return {
        **remaining,
        "sources": {
            "round-b-20260818-b24": {
                "case_count": len(b24_completed),
                "turn_count": sum(freeze["turn_counts"][case_id] for case_id in b24_completed),
            },
            "round-b-20260818-b25": {
                "case_count": len(b25_completed),
                "turn_count": sum(freeze["turn_counts"][case_id] for case_id in b25_completed),
            },
        },
        "excluded_b25_case_ids": b25_aborted,
    }


def _validate_current_grading(directory: Path, manifest: dict[str, Any]) -> None:
    versions = manifest["grader_versions"]
    if versions == {"deterministic_py_sha256": CURRENT_GRADER_SHA, "gates_py_sha256": CURRENT_GATES_SHA}:
        return
    artifact = directory / "deterministic_regrading_v2.json"
    if not artifact.exists():
        raise ValueError("missing current grader regrading artifact")
    regrading = json.loads(artifact.read_text(encoding="utf-8"))
    if (regrading.get("new_grader_sha256"), regrading.get("new_gates_sha256")) != (CURRENT_GRADER_SHA, CURRENT_GATES_SHA):
        raise ValueError("regrading artifact does not use current grader/gates")


def validate_composite(b24_dir: Path, b25_dir: Path) -> dict[str, Any]:
    """Validate a completed B24+B25 composite without contacting a model."""
    manifests = [json.loads((directory / "run_manifest.json").read_text(encoding="utf-8")) for directory in (b24_dir, b25_dir)]
    left, right = manifests
    if left["candidate"] != right["candidate"]:
        raise ValueError("provider/model mismatch")
    if left.get("model_facing_runtime_sha", left["code_commit_sha"]) != right.get("model_facing_runtime_sha", right["code_commit_sha"]):
        raise ValueError("model-facing runtime mismatch")
    for field in MODEL_FACING_FIELDS:
        if left[field] != right[field]:
            raise ValueError(f"model-facing contract mismatch: {field}")
    if left["snapshot"] != right["snapshot"]:
        raise ValueError("snapshot mismatch")

    freeze = validate_full_dev()
    all_rows = []
    for directory in (b24_dir, b25_dir):
        rows = [json.loads(line) for line in (directory / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
        all_rows.extend(rows)
    keys = [(row["case_id"], row["turn_index"]) for row in all_rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate turn in composite")
    expected = {(case_id, turn_index) for case_id in freeze["ordered_case_ids"] for turn_index in range(freeze["turn_counts"][case_id])}
    if set(keys) != expected:
        raise ValueError("composite has gaps or unexpected turns")
    return {"case_count": len({case_id for case_id, _ in keys}), "turn_count": len(keys), "candidate": left["candidate"]}


def validate_sol_full_dev_composite(b24_dir: Path, b25_dir: Path, b26_dir: Path) -> dict[str, Any]:
    """Validate the three-run Sol composite while excluding all partial B25 TCE rows."""
    directories = (b24_dir, b25_dir, b26_dir)
    manifests = [json.loads((directory / "run_manifest.json").read_text(encoding="utf-8")) for directory in directories]
    if any(manifest["candidate"] != {"provider": "openai", "model": "gpt-5.6-sol"} for manifest in manifests):
        raise ValueError("provider/model mismatch")
    reference = manifests[0]
    for manifest in manifests[1:]:
        if manifest.get("model_facing_runtime_sha", manifest["code_commit_sha"]) != reference.get("model_facing_runtime_sha", reference["code_commit_sha"]):
            raise ValueError("model-facing runtime mismatch")
        for field in MODEL_FACING_FIELDS:
            if manifest[field] != reference[field]:
                raise ValueError(f"model-facing contract mismatch: {field}")
        if manifest["snapshot"] != reference["snapshot"]:
            raise ValueError("snapshot mismatch")
    for directory, manifest in zip(directories, manifests):
        _validate_current_grading(directory, manifest)

    plan = derive_b26_remaining_cases(b24_dir, b25_dir)
    if _checkpoint_cases(b26_dir, "completed") != plan["ordered_case_ids"]:
        raise ValueError("B26 checkpoint does not complete the derived continuation")
    sources = {
        b24_dir: set(_checkpoint_cases(b24_dir, "completed")),
        b25_dir: set(_checkpoint_cases(b25_dir, "completed")),
        b26_dir: set(plan["ordered_case_ids"]),
    }
    all_rows = []
    for directory in directories:
        rows = [json.loads(line) for line in (directory / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
        selected = [row for row in rows if row["case_id"] in sources[directory]]
        if any(row.get("status") != "completed" for row in selected):
            raise ValueError("composite source has non-completed row")
        all_rows.extend(selected)
    if any(row["case_id"] == ABORTED_B25_CASE for row in all_rows if row["run_id"] == "round-b-20260818-b25"):
        raise ValueError("partial B25 TCE case leaked into composite")
    keys = [(row["case_id"], row["turn_index"]) for row in all_rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate turn in composite")
    freeze = validate_full_dev()
    expected = {(case_id, turn_index) for case_id in freeze["ordered_case_ids"] for turn_index in range(freeze["turn_counts"][case_id])}
    if set(keys) != expected:
        raise ValueError("composite has gaps or unexpected turns")
    origins = {case_id: directory.name for directory, case_ids in sources.items() for case_id in case_ids}
    if origins.get(ABORTED_B25_CASE) != b26_dir.name:
        raise ValueError("aborted B25 TCE case does not originate only in B26")
    return {"case_count": len(origins), "turn_count": len(keys), "candidate": reference["candidate"], "origins": origins}
