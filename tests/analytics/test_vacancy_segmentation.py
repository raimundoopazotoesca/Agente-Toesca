from pathlib import Path
import shutil
import sqlite3

import pytest

from tools.analytics.executor import AnalyticsExecutor, AnalyticsQueryRequest, SemanticQueryError
from tools.analyst_runtime.actions import AnalyticsLookupFundAction
from tools.analyst_runtime.coverage_guard import validate_and_render
from tools.analyst_runtime.transport import ToolRequest


DB = Path("memory/agente_toesca_v2.db")


def _query(*space_types, fund="Apo", asset=None, period="2026-06"):
    return AnalyticsQueryRequest(
        metric="vacancia_fisica_pct_segmentada_fondo" if asset is None else "vacancia_fisica_pct_segmentada_activo",
        funds=(fund,) if asset is None else (), assets=(asset,) if asset else (),
        period=period, space_types=space_types,
    )


def test_real_source_labels_map_to_canonical_space_types():
    executor = AnalyticsExecutor(DB)
    rows = [executor.execute(_query(space_type)).rows[0] for space_type in ("office", "retail", "storage")]
    assert {row.dimensions["space_type"] for row in rows} == {"office", "retail", "storage"}
    assert all(row.dimensions["measurement_unit"] == "m2" for row in rows)


def test_segmented_vacancy_uses_ratio_of_sums_for_compatible_types():
    executor = AnalyticsExecutor(DB)
    office = executor.execute(_query("office")).rows[0]
    retail = executor.execute(_query("retail")).rows[0]
    combined = executor.execute(_query("office", "retail")).rows[0]
    assert combined.value == pytest.approx(
        (office.provenance["numerator"] + retail.provenance["numerator"])
        / (office.provenance["denominator"] + retail.provenance["denominator"])
    )
    assert combined.dimensions["space_types"] == ("office", "retail")


def test_missing_requested_segment_is_none_not_zero():
    result = AnalyticsExecutor(DB).execute(_query("storage", fund="TRI", period="2026-06"))
    assert result.rows[0].value is None
    assert result.rows[0].dimensions["coverage"] == "none"


def test_incompatible_physical_units_fail_closed():
    executor = AnalyticsExecutor(DB)
    with pytest.raises(SemanticQueryError, match="incompatible physical units"):
        executor._validate_units({"office": "m2", "parking": "spaces"})


def test_same_entity_period_segmented_claims_bind_without_collision():
    action = AnalyticsLookupFundAction(DB)
    office = action.execute(ToolRequest("office", action.name, {
        "metric": "vacancia_fisica_pct_segmentada_fondo", "fund": "Apo", "period": "2026-06", "space_types": ["office"],
    }))
    retail = action.execute(ToolRequest("retail", action.name, {
        "metric": "vacancia_fisica_pct_segmentada_fondo", "fund": "Apo", "period": "2026-06", "space_types": ["retail"],
    }))
    assert office.ok and retail.ok and office.evidence and retail.evidence
    office_fact, retail_fact = office.evidence.facts[0], retail.evidence.facts[0]
    result = validate_and_render({
        "fragments": [{"type": "canonical_metric_ref", "claim_id": "office"}, {"type": "canonical_metric_ref", "claim_id": "retail"}],
        "canonical_metric_claims": [
            {"claim_id": "office", "evidence_id": "office", **office_fact},
            {"claim_id": "retail", "evidence_id": "retail", **retail_fact},
        ], "governed_dataset_claims": [], "derived_metric_claims": [], "table_claims": [],
    }, [office.evidence, retail.evidence], [], DB)
    assert result.valid


def test_governed_vacancy_view_normalizes_raw_parking_without_reclassifying_other(tmp_path):
    db = tmp_path / "vacancy.db"
    shutil.copy2(DB, db)
    from tools.db.connection import _discover_migrations, apply_migrations
    # Se aplican las migraciones pendientes en la copia y se comprueba que el
    # esquema quede en la cabeza. Antes esto fijaba `== []` y `== 84`, lo que
    # hacía fallar el test ante cualquier migración nueva sin que hubiera nada
    # roto: el número de versión es andamiaje, no lo que este test verifica.
    apply_migrations(str(db))
    head = max(version for version, _ in _discover_migrations())
    conn = sqlite3.connect(db)
    try:
        schema_version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert schema_version == head
        parking = conn.execute("SELECT tipo_unidad, m2_gla FROM v_vacancia_activo_tipo WHERE activo_key='Viña Centro' AND periodo='2026-05' AND tipo_unidad='Estacionamiento'").fetchone()
        other = conn.execute("SELECT COUNT(*) FROM v_vacancia_activo_tipo WHERE activo_key='Mall Curicó' AND periodo='2026-05' AND tipo_unidad='Otro'").fetchone()[0]
    finally:
        conn.close()
    assert parking == ("Estacionamiento", 1.0)
    assert other == 1
