from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.cases_loader import load_case
from eval.benchmark.graders.ground_truth import GroundTruthError, resolve_ground_truth
from eval.benchmark.snapshot import SnapshotSandbox


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


def _case(tmp_path: Path, sql: str):
    body = f"""
    id: tae-l1-001
    suite: analyst
    level: L1
    tier: L1
    split: dev
    turns:
      - question: "test"
        required_facts:
          - {{ref: n, tolerance_pct: 1.0}}
    ground_truth_refs:
      n:
        sql: "{sql}"
        unit: count
    """
    import textwrap
    path = tmp_path / "c.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return load_case(path)


def test_resolve_ground_truth_single_value(tmp_path, sandbox):
    case = _case(tmp_path, "SELECT COUNT(*) FROM dim_activo")
    resolved = resolve_ground_truth(case, sandbox)
    assert resolved["n"].value == 17
    assert resolved["n"].unit == "count"


def test_resolve_ground_truth_rejects_multi_row(tmp_path, sandbox):
    case = _case(tmp_path, "SELECT activo_key FROM dim_activo")
    with pytest.raises(GroundTruthError):
        resolve_ground_truth(case, sandbox)


def test_resolve_ground_truth_uses_trusted_unguarded_connection(tmp_path, sandbox):
    """Author SQL runs unguarded (it's benchmark code, not the SUT) but must
    still only ever read -- there is nothing here that writes."""
    sandbox.log.reset()
    case = _case(tmp_path, "SELECT COUNT(*) FROM dim_fondo")
    resolve_ground_truth(case, sandbox)
    assert not sandbox.log.violations
