"""Logical anti-leak guard for the Holdout Set.

This is the SECOND layer only. The first, primary layer is physical: the
real holdout YAML (questions, forbidden_claims, ground_truth SQL) lives in
a separate, private git repository outside this working tree -- see
eval/benchmark/cases/holdout/README.md. This test cannot catch a leak of
content that was never in this repo to begin with; it catches the specific,
narrower failure modes below.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BENCHMARK_DIR.parents[1]
HOLDOUT_DIR = BENCHMARK_DIR / "cases" / "holdout"
MANIFEST_PATH = BENCHMARK_DIR / "HOLDOUT_MANIFEST.yaml"

# Files that could plausibly encode a real question/answer if someone
# copy-pasted a holdout case into "helping" the agent: prompts, few-shot
# banks, verified-query stores, synonym/entity-resolver config.
_LEAK_SURFACE_GLOBS = [
    "**/prompts/**/*.py",
    "**/prompts/**/*.yaml",
    "**/prompts/**/*.md",
    "**/few_shot*/**",
    "**/verified_quer*/**",
    "**/synonyms*.py",
    "**/synonyms*.yaml",
    "**/entity_resolver*.py",
]

# Manifest fields that are metadata-only. Anything outside this set showing
# up in a case entry is a signal someone started copying real content
# (question text, forbidden_claims, sql) into the manifest.
_ALLOWED_MANIFEST_CASE_FIELDS = {
    "case_id",
    "split",
    "level",
    "category",
    "primary_behavior",
    "secondary_behaviors",
    "domain",
    "entities",
    "periods",
    "metrics",
    "source_tables",
    "dev_case_checked_against",
    "most_similar_dev_case",
    "similarity_reason",
    "status",
    "batch",
}

_SUSPECT_MANIFEST_FIELDS = {"question", "sql", "required_facts", "forbidden_claims", "ground_truth_refs", "expected_behavior"}


def test_holdout_dirs_contain_no_case_files():
    """The in-repo holdout dirs are pointers, not content. Any *.yaml here
    (other than the README's sibling structure) means the physical
    isolation boundary was crossed."""
    for sub in ("tae", "tce"):
        d = HOLDOUT_DIR / sub
        assert d.is_dir(), f"expected {d} to exist as a placeholder directory"
        yaml_files = list(d.glob("*.yaml")) + list(d.glob("*.yml"))
        assert not yaml_files, (
            f"found real case files under {d}: {[p.name for p in yaml_files]} -- "
            "holdout case content must live in the private external repo, "
            "not in automation_agent. See cases/holdout/README.md."
        )


def _manifest_case_ids() -> list[str]:
    if not MANIFEST_PATH.exists():
        return []
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    return [c["case_id"] for c in data.get("cases", [])]


def test_manifest_has_no_question_or_ground_truth_content():
    """HOLDOUT_MANIFEST.yaml is metadata for auditing, never the case
    content itself (case.schema.json is deliberately not extended for
    this). A leaked question/sql here would defeat the physical
    isolation for anyone who only reads the main repo."""
    if not MANIFEST_PATH.exists():
        pytest.skip("HOLDOUT_MANIFEST.yaml not present yet")
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    for case in data.get("cases", []):
        unexpected = set(case) - _ALLOWED_MANIFEST_CASE_FIELDS
        assert not unexpected, f"{case.get('case_id')}: unexpected manifest fields {unexpected}"
        suspect = set(case) & _SUSPECT_MANIFEST_FIELDS
        assert not suspect, f"{case.get('case_id')}: manifest contains content fields {suspect}"


def test_no_holdout_case_ids_referenced_outside_manifest_and_docs():
    """A holdout case id showing up in a prompt/few-shot/synonyms file is
    the clearest possible leak signal: someone pasted a case (or its id,
    which is often enough to look it up) into tuning material."""
    ids = _manifest_case_ids()
    if not ids:
        pytest.skip("no holdout cases registered in the manifest yet")

    allowed_files = {MANIFEST_PATH, HOLDOUT_DIR / "README.md"}
    # documentation/design docs are allowed to name case ids as examples
    allowed_files |= set((BENCHMARK_DIR).glob("HOLDOUT_SET_V1_*.md"))
    allowed_files |= set((BENCHMARK_DIR / "results").glob("*.md")) if (BENCHMARK_DIR / "results").exists() else set()

    candidates: list[Path] = []
    for pattern in _LEAK_SURFACE_GLOBS:
        candidates.extend(REPO_ROOT.glob(pattern))

    offenders = []
    for path in candidates:
        if not path.is_file() or path in allowed_files:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for case_id in ids:
            if case_id in text:
                offenders.append((path, case_id))

    assert not offenders, f"holdout case ids leaked into tuning-surface files: {offenders}"
