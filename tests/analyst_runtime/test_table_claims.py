"""Structured Analytical Table Outputs v1.

Tables are a new, optional ``table_claims`` array on the SynthesisEnvelope
(sibling to ``governed_dataset_claims``/``derived_metric_claims``). The model
only cites WHICH already-bound claim_ids belong to a table; coverage_guard
infers rows/columns/headers/order deterministically from those claims' own
entity_id/period/metric_key fields and renders a literal Markdown pipe table.
No table cell is ever LLM-authored text -- an unplaceable claim_id fails the
whole turn closed, exactly like every other guard in this module.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.analyst_runtime.coverage_guard import validate_and_render
from tools.analyst_runtime.transport import ToolEvidence


@pytest.fixture
def catalog_db(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dim_fondo (fondo_key TEXT, nombre TEXT)")
    conn.execute("CREATE TABLE dim_activo (activo_key TEXT, fondo_key TEXT, nombre TEXT)")
    conn.execute("CREATE TABLE dim_sociedad (sociedad_key TEXT, nombre TEXT)")
    conn.executemany("INSERT INTO dim_fondo VALUES (?, ?)", [("TRI", "TRI"), ("Apo", "Apoquindo")])
    conn.executemany("INSERT INTO dim_activo VALUES (?, ?, ?)", [
        ("Apo4501", "Apo", "Apoquindo 4501"), ("Apo4700", "Apo", "Apoquindo 4700"),
    ])
    conn.commit()
    conn.close()
    return path


def _fact(metric_key, value, unit, entity_id, period):
    return {"metric_key": metric_key, "value": value, "unit": unit, "entity_id": entity_id, "period": period}


def _canonical_evidence(evidence_id, fact):
    return ToolEvidence(evidence_id, "canonical_metric", facts=(fact,))


def _claim(claim_id, evidence_id, fact):
    return {"claim_id": claim_id, "evidence_id": evidence_id, **fact}


# ---- 1D ranking table: rows vary by entity, one shared metric/period ----

def test_ranking_table_sorts_by_value_desc_from_raw_claims_not_model_order(catalog_db):
    facts = {
        "c1": _fact("vacancia_pct", 7.84, "%", "Apo4501", "2026-06"),
        "c2": _fact("vacancia_pct", 22.91, "%", "Apo4700", "2026-06"),
    }
    evidence = [_canonical_evidence(eid, fact) for eid, fact in facts.items()]
    envelope = {
        "fragments": [{"type": "text", "text": "La vacancia por activo:"}],
        "canonical_metric_claims": [_claim(cid, cid, fact) for cid, fact in facts.items()],
        "governed_dataset_claims": [], "derived_metric_claims": [],
        # Model lists them in ASCENDING claim order (c1 lower value first);
        # order_by must override this with the real values, descending.
        "table_claims": [{"claim_id": "t1", "cell_claim_ids": ["c1", "c2"], "order_by": "value_desc"}],
    }
    result = validate_and_render(envelope, evidence, [], catalog_db)
    assert result.valid
    assert len(result.tables) == 1
    lines = result.tables[0].splitlines()
    assert lines[0].startswith("| Activo |")
    # Apo4700 (22,91%) must lead the ranking despite being cited second.
    assert "Apoquindo 4700" in lines[2] and "22,91%" in lines[2]
    assert "Apoquindo 4501" in lines[3] and "7,84%" in lines[3]


def test_ranking_table_ties_keep_stable_deterministic_order(catalog_db):
    facts = {
        "c1": _fact("vacancia_pct", 10.0, "%", "Apo4501", "2026-06"),
        "c2": _fact("vacancia_pct", 10.0, "%", "Apo4700", "2026-06"),
    }
    evidence = [_canonical_evidence(eid, fact) for eid, fact in facts.items()]
    envelope = {
        "fragments": [], "canonical_metric_claims": [_claim(cid, cid, fact) for cid, fact in facts.items()],
        "governed_dataset_claims": [], "derived_metric_claims": [],
        "table_claims": [{"claim_id": "t1", "cell_claim_ids": ["c1", "c2"], "order_by": "value_desc"}],
    }
    result = validate_and_render(envelope, evidence, [], catalog_db)
    assert result.valid
    lines = result.tables[0].splitlines()
    # Tie: no false greater-than inversion -- both rows render the same value.
    assert "10,00%" in lines[2] and "10,00%" in lines[3]


# ---- 2D table: metric rows x period columns, plus a derived "Cambio" column ----

def test_two_period_multi_metric_table_includes_derived_change_column(catalog_db):
    facts = {
        "vac25": _fact("vacancia_pct", 6.97, "%", "TRI", "2025-06"),
        "vac26": _fact("vacancia_pct", 5.95, "%", "TRI", "2026-06"),
        "ltv25": _fact("ltv", 40.0, "%", "TRI", "2025-06"),
        "ltv26": _fact("ltv", 38.0, "%", "TRI", "2026-06"),
    }
    evidence = [_canonical_evidence(eid, fact) for eid, fact in facts.items()]
    envelope = {
        "fragments": [{"type": "text", "text": "Comparativa TRI:"}],
        "canonical_metric_claims": [_claim(cid, cid, fact) for cid, fact in facts.items()],
        "governed_dataset_claims": [],
        "derived_metric_claims": [
            {"claim_id": "d1", "operation": "percentage_point_difference", "lhs_claim_id": "vac25", "rhs_claim_id": "vac26"},
            {"claim_id": "d2", "operation": "percentage_point_difference", "lhs_claim_id": "ltv25", "rhs_claim_id": "ltv26"},
        ],
        "table_claims": [{"claim_id": "t1",
                           "cell_claim_ids": ["vac25", "vac26", "ltv25", "ltv26", "d1", "d2"],
                           "order_by": None}],
    }
    result = validate_and_render(envelope, evidence, [], catalog_db)
    assert result.valid
    lines = result.tables[0].splitlines()
    header = lines[0]
    assert "Métrica" in header and "Cambio (pp)" in header
    assert any("6,97%" in line and "5,95%" in line and "1,02 pp" in line for line in lines)


# ---- NONE vs observed zero, and missing combos in a composition table ----

def test_composition_table_distinguishes_none_from_observed_zero(catalog_db):
    facts = {
        "c1": _fact("vacancia_pct", 0.0, "%", "Apo4501", "2026-06"),
        "c2": _fact("m2_vacantes", 1647.2, "m2", "Apo4700", "2026-06"),
    }
    evidence = [_canonical_evidence(eid, fact) for eid, fact in facts.items()]
    envelope = {
        "fragments": [], "canonical_metric_claims": [_claim(cid, cid, fact) for cid, fact in facts.items()],
        "governed_dataset_claims": [], "derived_metric_claims": [],
        "table_claims": [{"claim_id": "t1", "cell_claim_ids": ["c1", "c2"], "order_by": None}],
    }
    result = validate_and_render(envelope, evidence, [], catalog_db)
    assert result.valid
    table = result.tables[0]
    assert "0,00%" in table  # observed zero rendered normally, never blank/"-"
    assert "Sin dato" in table  # Apo4501 has no m2_vacantes cell, Apo4700 has no vacancia_pct cell
    assert table.count("Sin dato") == 2


# ---- Fact integrity: fail-closed cases ----

def test_unbound_cell_claim_id_fails_the_whole_turn_closed(catalog_db):
    fact = _fact("vacancia_pct", 11.49, "%", "Apo4501", "2026-06")
    envelope = {
        "fragments": [{"type": "canonical_metric_ref", "claim_id": "c1"}],
        "canonical_metric_claims": [_claim("c1", "e1", fact)],
        "governed_dataset_claims": [], "derived_metric_claims": [],
        # "ghost" references a claim_id nothing bound -- a table must never
        # silently drop this cell; it must fail closed like an unbound number.
        "table_claims": [{"claim_id": "t1", "cell_claim_ids": ["c1", "ghost"], "order_by": None}],
    }
    result = validate_and_render(envelope, [_canonical_evidence("e1", fact)], [], catalog_db)
    assert not result.valid


def test_scalar_single_cell_table_is_rejected_forces_prose(catalog_db):
    fact = _fact("vacancia_pct", 11.49, "%", "Apo4501", "2026-06")
    envelope = {
        "fragments": [{"type": "canonical_metric_ref", "claim_id": "c1"}],
        "canonical_metric_claims": [_claim("c1", "e1", fact)],
        "governed_dataset_claims": [], "derived_metric_claims": [],
        "table_claims": [{"claim_id": "t1", "cell_claim_ids": ["c1"], "order_by": None}],
    }
    result = validate_and_render(envelope, [_canonical_evidence("e1", fact)], [], catalog_db)
    assert not result.valid


def test_comparison_operation_cannot_be_placed_as_a_table_cell(catalog_db):
    facts = {
        "c1": _fact("vacancia_pct", 7.84, "%", "Apo4501", "2026-06"),
        "c2": _fact("vacancia_pct", 22.91, "%", "Apo4700", "2026-06"),
    }
    evidence = [_canonical_evidence(eid, fact) for eid, fact in facts.items()]
    envelope = {
        "fragments": [{"type": "canonical_metric_ref", "claim_id": "c1"}],
        "canonical_metric_claims": [_claim(cid, cid, fact) for cid, fact in facts.items()],
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "cmp", "operation": "comparison", "lhs_claim_id": "c1", "rhs_claim_id": "c2"}],
        "table_claims": [{"claim_id": "t1", "cell_claim_ids": ["c1", "c2", "cmp"], "order_by": None}],
    }
    result = validate_and_render(envelope, evidence, [], catalog_db)
    assert not result.valid


def test_no_table_claims_produces_no_tables(catalog_db):
    fact = _fact("vacancia_pct", 11.49, "%", "Apo4501", "2026-06")
    envelope = {
        "fragments": [{"type": "canonical_metric_ref", "claim_id": "c1"}],
        "canonical_metric_claims": [_claim("c1", "e1", fact)],
        "governed_dataset_claims": [], "derived_metric_claims": [], "table_claims": [],
    }
    result = validate_and_render(envelope, [_canonical_evidence("e1", fact)], [], catalog_db)
    assert result.valid
    assert result.tables == ()


def test_two_table_claims_citing_the_same_facts_render_once_not_twice(catalog_db):
    """A real QA run (CASE8: 'pon en una tabla...') produced the model citing
    the same two facts via two separate table_claims entries. Since rendering
    is a pure function of the underlying facts, both entries render
    byte-identical Markdown -- the second must be dropped rather than shown
    to the reader twice (spec: no duplication)."""
    facts = {
        "c1": _fact("vacancia_pct", 11.49, "%", "Apo", "2026-06"),
        "c2": _fact("vacancia_pct", 5.95, "%", "TRI", "2026-06"),
    }
    evidence = [_canonical_evidence(eid, fact) for eid, fact in facts.items()]
    envelope = {
        "fragments": [], "canonical_metric_claims": [_claim(cid, cid, fact) for cid, fact in facts.items()],
        "governed_dataset_claims": [], "derived_metric_claims": [],
        "table_claims": [
            {"claim_id": "t1", "cell_claim_ids": ["c1", "c2"], "order_by": None},
            {"claim_id": "t2", "cell_claim_ids": ["c1", "c2"], "order_by": None},
        ],
    }
    result = validate_and_render(envelope, evidence, [], catalog_db)
    assert result.valid
    assert len(result.tables) == 1
