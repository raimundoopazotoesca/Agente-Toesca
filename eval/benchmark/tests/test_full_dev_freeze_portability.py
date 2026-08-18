"""Full Dev v1.1 freeze portability: the fingerprint must identify CONTENT, not
one working copy's line endings.

Background (see docs/toesca-analyst-full-dev-v1-1-freeze-portability-fix.md):
the original freeze hashed raw bytes, so it encoded the EOL state of the tree it
was computed in -- 50 case files in CRLF and one in 89 CRLF + 2 stray LF. Git
stores those files LF-pure, so no checkout could reproduce that byte pattern and
validate_full_dev() failed on every fresh clone.

These tests pin the property that fixes it: EOL representation is ignored,
everything else still counts.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.round_b.runner import (
    FULL_DEV_HASH_ALGORITHM,
    FULL_DEV_V1_1_CANONICAL_SHA,
    FULL_DEV_V1_1_LEGACY_BYTE_SHA,
    _canonical_file_hash,
    _file_hash,
    validate_full_dev,
)

_LOGICAL_LINES = ["id: tae-demo-001", "turns:", "  - question: cuanto es la vacancia", "    answer: 12.5"]


def _write(path: Path, text: str) -> Path:
    path.write_bytes(text.encode("utf-8"))
    return path


# --- Test A: LF vs CRLF ------------------------------------------------------

def test_lf_and_crlf_representations_hash_identically(tmp_path):
    lf = _write(tmp_path / "lf.yaml", "\n".join(_LOGICAL_LINES) + "\n")
    crlf = _write(tmp_path / "crlf.yaml", "\r\n".join(_LOGICAL_LINES) + "\r\n")

    assert lf.read_bytes() != crlf.read_bytes()          # genuinely different on disk
    assert _file_hash(lf) != _file_hash(crlf)            # the old byte hash could not tell them apart as equal
    assert _canonical_file_hash(lf) == _canonical_file_hash(crlf)


# --- Test B: mixed EOL, the exact bug class found ----------------------------

def test_mixed_eol_matches_its_lf_canonical_form(tmp_path):
    """CRLF / CRLF / LF / CRLF -- the shape tce-investigationmultidomain-001.yaml
    actually had in the tree that produced the legacy freeze."""
    mixed = _write(tmp_path / "mixed.yaml",
                   _LOGICAL_LINES[0] + "\r\n" + _LOGICAL_LINES[1] + "\r\n"
                   + _LOGICAL_LINES[2] + "\n" + _LOGICAL_LINES[3] + "\r\n")
    lf = _write(tmp_path / "lf.yaml", "\n".join(_LOGICAL_LINES) + "\n")
    crlf = _write(tmp_path / "crlf.yaml", "\r\n".join(_LOGICAL_LINES) + "\r\n")

    assert _canonical_file_hash(mixed) == _canonical_file_hash(lf) == _canonical_file_hash(crlf)
    # ...and this is precisely what the old algorithm got wrong: three distinct hashes
    assert len({_file_hash(mixed), _file_hash(lf), _file_hash(crlf)}) == 3


# --- Test C: real content changes are still detected -------------------------

@pytest.mark.parametrize("mutation", [
    ("12.5", "12.6"),           # a number
    ("vacancia", "vacancía"),   # one accented character
    ("tae-demo-001", "tae-demo-002"),  # an identifier
])
def test_content_changes_still_change_the_hash(tmp_path, mutation):
    old, new = mutation
    base = _write(tmp_path / "base.yaml", "\n".join(_LOGICAL_LINES) + "\n")
    changed = _write(tmp_path / "changed.yaml", ("\n".join(_LOGICAL_LINES) + "\n").replace(old, new))

    assert _canonical_file_hash(base) != _canonical_file_hash(changed)


def test_whitespace_that_is_not_a_line_ending_still_counts(tmp_path):
    """Canonicalization must be narrow: only CRLF -> LF, nothing else."""
    base = _write(tmp_path / "a.yaml", "id: x\nvalue: 1\n")
    trailing = _write(tmp_path / "b.yaml", "id: x \nvalue: 1\n")   # one trailing space
    bare_cr = _write(tmp_path / "c.yaml", "id: x\rvalue: 1\n")     # lone CR, not CRLF

    assert _canonical_file_hash(base) != _canonical_file_hash(trailing)
    assert _canonical_file_hash(base) != _canonical_file_hash(bare_cr)


# --- Test D + E: the real freeze validates, with the frozen shape ------------

def test_validate_full_dev_passes_from_a_plain_git_checkout():
    checked = validate_full_dev()
    assert checked["content_sha256"] == FULL_DEV_V1_1_CANONICAL_SHA
    assert checked["hash_algorithm"] == FULL_DEV_HASH_ALGORITHM == "sha256-lf-normalized-v1"


def test_freeze_shape_is_unchanged_by_the_migration():
    checked = validate_full_dev()
    assert (checked["case_count"], checked["turn_count"]) == (51, 79)
    assert (checked["tae_count"], checked["tce_count"]) == (34, 17)
    assert len(checked["ordered_case_ids"]) == 51
    assert sum(checked["turn_counts"].values()) == 79


def test_legacy_byte_fingerprint_is_preserved_as_evidence():
    """B24-B27 recorded the byte-level value; it stays reachable and distinct
    from the canonical one, so no report can silently conflate them."""
    assert FULL_DEV_V1_1_LEGACY_BYTE_SHA == "090fb1c91bcf34e64c09ad285ac1c133ab13d06c256b96ab4af0e6c4f6e6033c"
    assert FULL_DEV_V1_1_CANONICAL_SHA != FULL_DEV_V1_1_LEGACY_BYTE_SHA
    assert validate_full_dev()["legacy_byte_sha256"] == FULL_DEV_V1_1_LEGACY_BYTE_SHA


# --- Test F: Holdout isolation, established structurally ---------------------

def test_full_dev_canonicalization_cannot_reach_holdout():
    """Structural, not content-based: this asserts on source text and import
    graph only. No holdout case file is opened, listed or hashed anywhere here.

    Two independent reasons the Holdout freeze is out of reach:
      1. _canonical_file_hash is called from exactly one place, validate_full_dev,
         which is scoped to split="dev";
      2. the Holdout freeze machinery (compute_freeze_manifest.py) hashes with its
         own local helpers and imports nothing from eval.round_b.runner.
    """
    repo = Path(__file__).resolve().parents[3]
    runner_src = (repo / "eval/round_b/runner.py").read_text(encoding="utf-8")
    freeze_src = (repo / "eval/benchmark/compute_freeze_manifest.py").read_text(encoding="utf-8")

    # 1. single call site, and it is the dev-split validator
    assert runner_src.count("_canonical_file_hash(") == 2  # one def, one call
    assert 'load_cases(CASES_DIR, split="dev")' in runner_src

    # 2. the holdout freeze module does not import the runner at all
    assert "eval.round_b.runner" not in freeze_src
    assert "_canonical_file_hash" not in freeze_src
    assert "from eval.round_b" not in freeze_src

    # and the runner never selects the holdout split or path in code
    # (prose mentions in comments are fine; these are the constructs that would
    # actually reach holdout files)
    assert 'split="holdout"' not in runner_src
    assert "split='holdout'" not in runner_src
    assert "cases/holdout" not in runner_src
    assert "HOLDOUT" not in runner_src
