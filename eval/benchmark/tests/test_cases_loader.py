from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.cases_loader import (
    CASES_DIR,
    CaseValidationError,
    load_case,
    load_cases,
    load_schema,
)

VALID = """
id: tae-l1-001
suite: analyst
level: L1
tier: L1
split: dev
turns:
  - question: "NOI de Vina Centro en junio 2026"
    required_facts:
      - {ref: noi_vina_2026_06, tolerance_pct: 0.5}
    primary_fact: noi_vina_2026_06
    expected_entities: {activo: "Vina Centro"}
    expected_period: {exact: "2026-06"}
ground_truth_refs:
  noi_vina_2026_06:
    sql: "SELECT 1"
    unit: CLP
"""


def _write(tmp_path: Path, body: str, name: str = "case.yaml") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_valid_case_loads(tmp_path):
    case = load_case(_write(tmp_path, VALID))
    assert case.id == "tae-l1-001"
    assert case.tier == "L1"
    assert case.capability is None
    assert case.human_only is False


def test_unknown_field_rejected(tmp_path):
    body = VALID.replace("split: dev", "split: dev\nexpected_sql: SELECT 1")
    with pytest.raises(CaseValidationError, match="Additional properties|expected_sql"):
        load_case(_write(tmp_path, body))


def test_analyst_case_requires_level_and_tier(tmp_path):
    body = VALID.replace("level: L1\n", "")
    with pytest.raises(CaseValidationError, match="need a `level`"):
        load_case(_write(tmp_path, body))


def test_conversation_case_requires_category(tmp_path):
    body = VALID.replace("id: tae-l1-001", "id: tce-followup-001")
    body = body.replace("suite: analyst", "suite: conversation")
    body = body.replace("level: L1\ntier: L1\n", "")
    with pytest.raises(CaseValidationError, match="need a `category`"):
        load_case(_write(tmp_path, body))


def test_id_prefix_must_match_suite(tmp_path):
    body = VALID.replace("id: tae-l1-001", "id: tce-l1-001")
    with pytest.raises(CaseValidationError, match="does not match suite"):
        load_case(_write(tmp_path, body))


def test_dangling_fact_ref_rejected(tmp_path):
    body = VALID.replace("ref: noi_vina_2026_06, tolerance_pct: 0.5", "ref: no_existe")
    with pytest.raises(CaseValidationError, match="no entry in ground_truth_refs"):
        load_case(_write(tmp_path, body))


def test_primary_fact_must_be_required(tmp_path):
    body = VALID.replace("primary_fact: noi_vina_2026_06", "primary_fact: otro")
    with pytest.raises(CaseValidationError, match="not among required_facts"):
        load_case(_write(tmp_path, body))


def test_holdout_split_must_live_in_holdout_dir(tmp_path):
    body = VALID.replace("split: dev", "split: holdout")
    with pytest.raises(CaseValidationError, match="not under cases/holdout"):
        load_case(_write(tmp_path, body))


def test_duplicate_ids_rejected(tmp_path):
    _write(tmp_path, VALID, "a.yaml")
    _write(tmp_path, VALID, "b.yaml")
    with pytest.raises(CaseValidationError, match="duplicate case id"):
        load_cases(tmp_path)


def test_schema_is_valid_json_schema():
    import jsonschema

    jsonschema.Draft7Validator.check_schema(load_schema())


def test_repository_cases_all_valid():
    """The real corpus must always load. Empty is fine while it is being written."""
    cases = load_cases(CASES_DIR)
    assert isinstance(cases, list)
