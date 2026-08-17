from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import yaml

from eval.benchmark.cases_loader import CASES_DIR, load_cases


ROUND_B_DIR = Path(__file__).resolve().parents[2] / "eval" / "round_b"
MANIFEST_PATH = ROUND_B_DIR / "mini_dev_v1.yaml"

EXPECTED_IDS = [
    "tae-l1-008",
    "tae-l2-003",
    "tae-l3-004",
    "tae-l4-003",
    "tae-l4-004",
    "tae-l5-004",
    "tae-l5-006",
    "tae-l6-001",
    "tae-l8-001",
    "tae-l8-002",
    "tce-ambiguity-001",
    "tce-entitycorrection-001",
    "tce-decisionchallenge-001",
    "tce-investigationmultidomain-001",
    "tce-investigationdrilldown-001",
]


def _load_manifest() -> dict:
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


def _content_hash(manifest: dict) -> str:
    content = {key: value for key, value in manifest.items() if key != "content_sha256"}
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_mini_dev_freeze_has_the_approved_stable_case_order():
    manifest = _load_manifest()
    assert manifest["ordered_case_ids"] == EXPECTED_IDS
    assert len(manifest["ordered_case_ids"]) == 15
    assert len(set(manifest["ordered_case_ids"])) == 15


def test_mini_dev_freeze_references_only_existing_dev_cases_and_25_turns():
    manifest = _load_manifest()
    cases = {case.id: case for case in load_cases(CASES_DIR)}
    selected = [cases[case_id] for case_id in manifest["ordered_case_ids"]]

    assert all(case.raw["split"] == "dev" for case in selected)
    assert sum(len(case.raw["turns"]) for case in selected) == 25
    assert manifest["turn_counts"] == {case.id: len(case.raw["turns"]) for case in selected}


def test_mini_dev_manifest_hash_is_reproducible_and_does_not_copy_case_content():
    manifest = _load_manifest()
    assert manifest["content_sha256"] == _content_hash(manifest)

    serialized = json.dumps(manifest, ensure_ascii=False).lower()
    forbidden_case_content = ("question", "ground_truth", "sql", "forbidden_claim", "expected_behavior")
    assert not any(field in serialized for field in forbidden_case_content)


def test_freeze_does_not_include_worktree_changes_to_dev_cases():
    changed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", "eval/benchmark/cases/tae", "eval/benchmark/cases/tce"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert changed == []
