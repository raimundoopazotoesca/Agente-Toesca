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
