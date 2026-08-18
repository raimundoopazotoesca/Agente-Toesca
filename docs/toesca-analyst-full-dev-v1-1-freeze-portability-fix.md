# Full Dev v1.1 — freeze portability fix

**Date:** 2026-08-18
**Scope:** fingerprint algorithm only. Not a new benchmark, not a new version of
the Dev set. The 51 cases / 79 turns are unchanged, byte for byte, modulo line
endings.

---

## Problem

`validate_full_dev()` raised `Full Dev v1.1 freeze mismatch` on a clean checkout
of the same commit that produced the freeze, blocking every Full Dev run before
any provider call.

## Cause

The fingerprint hashed each case file's **raw bytes**:

```python
def _file_hash(path): return hashlib.sha256(path.read_bytes()).hexdigest()
```

That makes the freeze a fingerprint of one *working copy*, not of the benchmark's
content. Line endings are a checkout-time representation (`core.autocrlf`,
editors, platform), not repository content, so the value cannot survive a clone.

### Evidence

The tree that produced the legacy freeze
(`.codex/worktrees/toesca-analyst-round-b`) held:

- 50 of 51 case files with uniform **CRLF**;
- `eval/benchmark/cases/tce/tce-investigationmultidomain-001.yaml` with **89 CRLF
  + 2 bare LF** (offsets 4596 and 4792, lines 79 and 83) — 5298 bytes.

Git stores that file **LF-pure**: 5209 bytes, 0 CRLF. So the legacy bytes are not
recoverable from the repository by any means:

| Representation | bytes of the mixed-EOL file | Full Dev fingerprint | = legacy freeze? |
|---|---|---|---|
| checkout as-is (LF) | 5209 | `f851385d1cdf424f97b68b5f388c38ae76f51f173c7493e2d851ac95a70fb7d0` | no |
| uniform CRLF | 5300 | `5e1b9327150f6a27a7263f743dd63bdfc9123b6a22af12bba5f4bded2038bdb5` | no |
| legacy worktree bytes | 5298 | `090fb1c91bcf34e64c09ad285ac1c133ab13d06c256b96ab4af0e6c4f6e6033c` | **yes** |

No `.gitattributes` / `.git/info/attributes` setting can produce "CRLF except two
specific lines in one file", so a local EOL policy could not have fixed it either.

### Content is identical

All 51 dev case files are **byte-identical between the two trees once CRLF is
collapsed to LF** (51/51 verified), with the same case IDs, the same suites
(34 analyst + 17 conversation) and the same 79 turns. There is no content drift.
The two trees are the same benchmark in two representations.

## Fix

Hash a canonical text representation instead of raw bytes:

```python
FULL_DEV_HASH_ALGORITHM = "sha256-lf-normalized-v1"

def _canonical_file_hash(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
```

Everything else about the fingerprint is unchanged: same per-case entry shape
(`case_id`, `suite`, `turn_count`, repo-relative posix `path`, `sha256`), same
ordering by path, same canonical JSON envelope
(`ensure_ascii=False, sort_keys=True, separators=(",", ":")`, UTF-8).

Only CRLF → LF is collapsed. A lone CR, a trailing space, a changed digit or a
changed accent all still change the hash — covered by tests.

### Fingerprints

| Name | Value |
|---|---|
| `FULL_DEV_V1_1_LEGACY_BYTE_SHA` | `090fb1c91bcf34e64c09ad285ac1c133ab13d06c256b96ab4af0e6c4f6e6033c` |
| `FULL_DEV_V1_1_CANONICAL_SHA` | `5c0e6d9b1e57cd2e08ebe535f7ff59fa63c9d4f3a22ae1933eb45df675a0cdb5` |
| `FULL_DEV_HASH_ALGORITHM` | `sha256-lf-normalized-v1` |

### Equivalence proof

The canonical algorithm was run against both trees before the new value was
pinned:

| Source | Canonical fingerprint |
|---|---|
| current git checkout | `5c0e6d9b1e57cd2e08ebe535f7ff59fa63c9d4f3a22ae1933eb45df675a0cdb5` |
| legacy freeze worktree (exact bytes) | `5c0e6d9b1e57cd2e08ebe535f7ff59fa63c9d4f3a22ae1933eb45df675a0cdb5` |

**Identical.** The legacy working tree and the current checkout are the same
benchmark under EOL canonicalization.

## Blast radius

`_file_hash` (raw bytes) is deliberately **kept and still used** for
`grader_versions.deterministic_py_sha256` and `grader_versions.gates_py_sha256`,
which are byte-level values recorded by B24–B27. Only `validate_full_dev()` uses
the canonical hash.

- **Mini-Dev** hashes parsed YAML (`_canonical_hash`) and was already
  EOL-invariant — untouched, still validates.
- **Holdout** freeze machinery (`eval/benchmark/compute_freeze_manifest.py`)
  hashes with its own local helpers and imports nothing from
  `eval.round_b.runner`, so this change cannot reach it. Asserted structurally in
  `test_full_dev_freeze_portability.py::test_full_dev_canonicalization_cannot_reach_holdout`,
  which reads source text and the import graph only. **No holdout case file was
  opened, listed, hashed or executed during this migration.**

Not modified: case YAMLs, graders, ground truth, snapshot, holdout, and the
B24–B27 result manifests.

## Reporting consequence

Historical and current manifests pin *different* fingerprints, and that is
correct — they must not be conflated:

- **B24–B27** recorded `dev_set.content_sha256 = 090fb1c9…` (legacy byte freeze).
- **Runs from this commit on** record `dev_set.content_sha256 = 5c0e6d9b…` plus
  `dev_set.hash_algorithm = "sha256-lf-normalized-v1"` and
  `dev_set.legacy_byte_sha256 = 090fb1c9…` for traceability.

An F4 vs B27 comparison is valid on the strength of the equivalence proof above,
not because the two fields match. Any report making that comparison should cite
this document.

## Rationale

Cross-checkout reproducibility. A freeze that only validates inside one
developer's working directory is not a freeze; it silently converts an
environment difference into a false content-drift alarm, and it would have
blocked every future run of the benchmark on any other machine.
