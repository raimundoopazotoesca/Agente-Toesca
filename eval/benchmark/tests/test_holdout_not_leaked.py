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

# Manifest fields that are metadata-only and non-semantic: they identify
# a case for governance (which batch, what structural level, review
# status) without revealing what it is *about*. Anything outside this set
# showing up in a case entry is a signal someone started copying
# case-level semantic content (or worse, question/ground-truth content)
# into the manifest that lives in the dev-facing repo.
#
# Deliberately excluded (must live only in the private repo's
# MANIFEST_FULL.yaml, never here): primary_behavior, secondary_behaviors,
# domain, entities, periods, metrics, source_tables,
# dev_case_checked_against, most_similar_dev_case, similarity_reason.
# These were present in an earlier version of this manifest and were
# removed after Batch 1 review precisely because they leak enough to
# reconstruct what a case tests.
_ALLOWED_MANIFEST_CASE_FIELDS = {
    "case_id",
    "split",
    "level",
    "category",
    "status",
    "batch",
}

# Any of these keys appearing ANYWHERE in the manifest (not just inside a
# case entry -- also top-level, or nested under some future summary block)
# is a leak signal. Union of case-level semantic fields and raw
# question/ground-truth content fields.
_FORBIDDEN_SEMANTIC_FIELDS = {
    "primary_behavior",
    "secondary_behaviors",
    "domain",
    "entities",
    "entity",
    "periods",
    "period",
    "metrics",
    "metric",
    "source_tables",
    "dev_case_checked_against",
    "most_similar_dev_case",
    "similarity_reason",
    "question",
    "sql",
    "required_facts",
    "forbidden_claims",
    "ground_truth_refs",
    "expected_behavior",
}


def _all_keys(node) -> set[str]:
    """Recursively collect every mapping key in a parsed YAML structure."""
    keys: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            keys.add(str(k))
            keys |= _all_keys(v)
    elif isinstance(node, list):
        for item in node:
            keys |= _all_keys(item)
    return keys


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


def test_manifest_case_entries_are_minimal():
    """Each case entry in HOLDOUT_MANIFEST.yaml carries only governance
    fields (case_id/split/level/category/status/batch). Anything else --
    including case-level semantic metadata like domain/entities/periods/
    metrics, not just raw question/sql content -- belongs in the private
    repo's MANIFEST_FULL.yaml, never here."""
    if not MANIFEST_PATH.exists():
        pytest.skip("HOLDOUT_MANIFEST.yaml not present yet")
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    for case in data.get("cases", []):
        unexpected = set(case) - _ALLOWED_MANIFEST_CASE_FIELDS
        assert not unexpected, f"{case.get('case_id')}: unexpected manifest fields {unexpected}"


def test_manifest_has_no_semantic_content_anywhere():
    """Whole-file scan, not just inside `cases:` entries. Guards against a
    future summary block, aggregate-by-entity table, or any other
    structure that reintroduces case-level semantic metadata into the
    dev-facing repo through a side door."""
    if not MANIFEST_PATH.exists():
        pytest.skip("HOLDOUT_MANIFEST.yaml not present yet")
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    found = _all_keys(data) & _FORBIDDEN_SEMANTIC_FIELDS
    assert not found, f"HOLDOUT_MANIFEST.yaml contains forbidden semantic/content keys: {found}"


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
