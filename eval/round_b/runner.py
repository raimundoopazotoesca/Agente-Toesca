"""Frozen Mini-Dev Round B execution; no qualitative judge or fallback."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from eval.benchmark.adapters.track_b_frontier import B1_STANDARD_PROFILES
from eval.benchmark.snapshot import load_lock

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "eval/round_b/mini_dev_v1.yaml"
PRICING = ROOT / "eval/round_b/pricing.yaml"
CANONICAL_SHA = "dc4d8912986ac99e9a08853d55fa19668220032e41a89944c05d1cfcc573b976"


def _canonical_hash(data: dict[str, Any]) -> str:
    content = {k: v for k, v in data.items() if k != "content_sha256"}
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_mini_dev(path: Path = MANIFEST) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    actual = _canonical_hash(data)
    if actual != CANONICAL_SHA or data.get("content_sha256") != CANONICAL_SHA:
        raise ValueError(f"Mini-Dev canonical hash mismatch: {actual}")
    return {"mini_dev_id": data["mini_dev_id"], "canonical_manifest_sha256": actual,
            "case_count": len(data["ordered_case_ids"]), "turn_count": sum(data["turn_counts"].values()),
            "ordered_case_ids": data["ordered_case_ids"], "snapshot_sha256": data["dev_freeze"]["snapshot_sha256"]}


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_run_manifest(code_commit_sha: str, execution_date: str) -> dict[str, Any]:
    mini = validate_mini_dev()
    lock = load_lock()
    return {"run_kind": "mini_dev", "mini_dev": mini, "code_commit_sha": code_commit_sha, "track": "B",
            "snapshot": lock, "system_prompt_sha256": _file_hash(ROOT / "eval/benchmark/adapters/track_b_frontier.py"),
            "tool_schema_sha256": _file_hash(ROOT / "eval/benchmark/adapters/track_b_frontier.py"),
            "inference_profile": "B1_STANDARD", "provider_configs": [p.__dict__ for p in B1_STANDARD_PROFILES],
            "max_model_tool_rounds": 5, "timeout_policy": "provider default", "retry_policy": "one: 429/5xx/network/timeout",
            "grader_versions": {"deterministic_py_sha256": _file_hash(ROOT / "eval/benchmark/graders/deterministic.py"),
                                "gates_py_sha256": _file_hash(ROOT / "eval/benchmark/graders/gates.py")},
            "judge_status": "not_scored_yet", "execution_date": execution_date}


def estimate_cost(provider: str, model: str, input_tokens: int | None, output_tokens: int | None, cached_tokens: int | None) -> dict[str, Any] | None:
    if input_tokens is None or output_tokens is None:
        return None
    prices = yaml.safe_load(PRICING.read_text(encoding="utf-8"))["providers"]
    row = next((p for p in prices if p["provider"] == provider and p["model"] == model), None)
    if not row or not isinstance(row["input_per_mtok"], (int, float)) or not isinstance(row["output_per_mtok"], (int, float)):
        return None
    amount = input_tokens / 1e6 * row["input_per_mtok"] + output_tokens / 1e6 * row["output_per_mtok"]
    if cached_tokens and isinstance(row.get("cached_input_per_mtok"), (int, float)):
        amount -= cached_tokens / 1e6 * row["input_per_mtok"]
        amount += cached_tokens / 1e6 * row["cached_input_per_mtok"]
    return {"currency": row["currency"], "amount": round(amount, 8)}


def committed_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
