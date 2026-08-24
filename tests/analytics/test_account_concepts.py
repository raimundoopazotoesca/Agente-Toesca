from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.analytics.account_concepts import AccountConceptCatalog, AccountQuery, AccountQueryExecutor, AccountQueryError
from tools.analyst_runtime.actions import AnalyticsAccountQueryAction
from tools.analyst_runtime.transport import ToolRequest
from tools.analyst_runtime.session import DEFAULT_INTERACTIVE_SYSTEM_PROMPT, _has_account_coverage_none
from tools.analyst_runtime.actions import ActionRegistry
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.transport import ModelResponse
from tools.analyst_runtime.session import OpenAIResponsesAnalystSession


@pytest.fixture
def account_db(tmp_path: Path) -> Path:
    path = tmp_path / "accounts.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE raw_er_activo_line (
        activo_key TEXT, periodo TEXT, cuenta_codigo TEXT, cuenta_nombre TEXT,
        monto_clp REAL, monto_uf REAL, superseded_at TEXT, source_file TEXT,
        source_sheet TEXT, source_row INTEGER, file_hash TEXT, ingest_run_id INTEGER
    )""")
    conn.executemany("INSERT INTO raw_er_activo_line VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        ("A", "2025-01", "NEG", "Seguro fuente negativa", -100, None, None, "er.xlsx", "A", 1, "h", 1),
        ("A", "2025-02", "POS", "Seguro fuente positiva", 200, None, None, "er.xlsx", "A", 2, "h", 1),
        ("A", "2025-03", "NEG", "Seguro fuente negativa", -300, None, None, "er.xlsx", "A", 3, "h", 1),
        ("A", "2025-03", "UNMAPPED", "Seguro sin validar", -99, None, None, "er.xlsx", "A", 4, "h", 1),
        ("A", "2025-02", "NEG", "Seguro reemplazado", -999, None, "2025-03-01", "er.xlsx", "A", 5, "h", 1),
        ("A", "2025-01", "SPLIT", "Cuenta compartida", -400, None, None, "er.xlsx", "A", 6, "h", 1),
    ])
    conn.commit(); conn.close()
    return path


def _catalog() -> AccountConceptCatalog:
    return AccountConceptCatalog.from_dict({"concepts": [
        {"concept_id": "insurance", "display_name": "Seguros", "aliases": ["seguro"], "basis": "accrued_pnl_expense", "nature": "flow", "units": ["clp"], "allowed_aggregations": ["sum"], "entity_types": ["asset"], "mappings": [
            {"code": "NEG", "concept_id": "insurance", "sign_rule": "expense_magnitude", "status": "mapped"},
            {"code": "POS", "concept_id": "insurance", "sign_rule": "expense_magnitude", "status": "mapped"},
            {"code": "UNMAPPED", "concept_id": "insurance", "status": "unmapped", "note": "requires validation"},
            {"code": "SPLIT", "concept_id": "insurance", "sign_rule": "expense_magnitude", "allocation": 0.25, "status": "mapped"},
        ]},
        {"concept_id": "balance_example", "display_name": "Saldo", "aliases": [], "basis": "unknown", "nature": "point_in_time", "units": ["clp"], "allowed_aggregations": [], "entity_types": ["asset"], "mappings": []},
    ]})


def test_account_query_normalizes_signs_applies_explicit_allocation_and_excludes_superseded(account_db: Path):
    result = AccountQueryExecutor(account_db, _catalog()).execute(AccountQuery("insurance", "A", "asset", "2025-01", "2025-03", "sum"))

    assert result.value == pytest.approx(700)  # 100 + 200 + 300 + (400 * 25%)
    assert result.coverage["status"] == "partial"
    assert result.coverage["unmapped_row_count"] == 1
    assert result.account_row_count == 4
    assert result.basis == "accrued_pnl_expense"


def test_account_query_alias_and_new_concept_are_metadata_only(account_db: Path):
    catalog = _catalog()

    assert catalog.resolve_alias("seguro").concept_id == "insurance"
    assert catalog.get("balance_example").concept_id == "balance_example"


def test_account_query_rejects_sum_for_non_flow(account_db: Path):
    with pytest.raises(AccountQueryError, match="not permitted"):
        AccountQueryExecutor(account_db, _catalog()).execute(AccountQuery("balance_example", "A", "asset", "2025-01", "2025-03", "sum"))


def test_account_query_has_no_runtime_like_matching(account_db: Path):
    executor = AccountQueryExecutor(account_db, _catalog())

    assert "LIKE" not in executor.governed_sql.upper()


def test_generic_account_action_emits_traceable_governed_evidence(account_db: Path):
    action = AnalyticsAccountQueryAction(account_db, catalog=_catalog())
    result = action.execute(ToolRequest("accounts", action.name, {
        "concept": "insurance", "entity": "A", "entity_type": "asset", "period": "2025-01", "period_end": "2025-03", "aggregation": "sum",
    }))

    assert result.ok is True
    assert result.evidence is not None
    assert result.evidence.coverage["status"] == "partial"
    assert result.evidence.semantic_contract["accounting_basis"] == "accrued_pnl_expense"
    assert result.evidence.facts[0]["value"] == pytest.approx(700)


def test_none_account_evidence_is_not_rendered_as_a_zero_or_dataset(account_db: Path):
    action = AnalyticsAccountQueryAction(account_db, catalog=_catalog())
    result = action.execute(ToolRequest("none", action.name, {
        "concept": "insurance", "entity": "missing", "entity_type": "asset", "period": "2025-01", "period_end": "2025-03", "aggregation": "sum",
    }))

    assert result.ok is True
    assert result.evidence is None
    assert '"value": null' in result.content


def test_none_account_trace_uses_unstructured_finalization_without_false_fact_binding():
    investigation = SimpleNamespace(tool_calls=[SimpleNamespace(name="analytics_account_query", trace={"coverage": {"status": "none"}})])

    assert _has_account_coverage_none(investigation) is True


def test_none_account_query_reaches_a_natural_final_answer_without_canonical_conflict(account_db: Path):
    action = AnalyticsAccountQueryAction(account_db, catalog=_catalog())

    class Transport:
        def __init__(self):
            self.responses = iter([
                ModelResponse("", [ToolRequest("none", action.name, {"concept": "insurance", "entity": "missing", "entity_type": "asset", "period": "2025-01", "period_end": "2025-03", "aggregation": "sum"})]),
                ModelResponse("No hay evidencia gobernada suficiente; esto no implica cero."),
            ])
        def complete(self, _request): return next(self.responses)

    session = OpenAIResponsesAnalystSession(AnalystLoop("sys", Transport(), ActionRegistry([action]), [action.tool_spec()]), presenter=None)
    result = session.ask("consulta")

    # Human Analytical Presentation v1: NONE answers use the account-concept
    # catalog display name and the generic period formatter, not raw
    # internal identifiers or "YYYY-MM..YYYY-MM" notation.
    assert result.text == (
        "No encontré evidencia de gasto en seguros para missing entre enero y marzo de 2025. "
        "Esto no implica que el gasto haya sido cero, sólo que no hay datos gobernados que lo respalden."
    )
    assert result.presentation_integrity_status == "not_configured"


def test_parent_none_composition_preserves_requested_scope():
    from tools.analyst_runtime.session import _account_no_evidence_text

    assert _account_no_evidence_text({"concept_id": "insurance", "entity": "Apo", "entity_type": "fund", "period": "2025-01..2025-12"}) == (
        "No encontré evidencia de gasto en seguros para Apo durante 2025. "
        "Esto no implica que el gasto haya sido cero, sólo que no hay datos gobernados que lo respalden."
    )


def test_account_capability_has_one_generic_discoverability_instruction():
    assert "analytics_account_query" in DEFAULT_INTERACTIVE_SYSTEM_PROMPT
    assert "seguros" not in DEFAULT_INTERACTIVE_SYSTEM_PROMPT.casefold()
