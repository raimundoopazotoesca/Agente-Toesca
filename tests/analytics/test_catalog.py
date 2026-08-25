from pathlib import Path
import sqlite3

import pytest

from tools.analytics.catalog import CatalogValidationError, load_metric_catalog


def test_catalog_has_distinct_economic_identities():
    catalog = load_metric_catalog()

    assert catalog.version == 1
    assert {"noi_mensual_fondo", "ingresos_mensual_fondo"} <= set(catalog.metrics)
    fund = catalog.metrics["vacancia_pct_fondo"]
    physical = catalog.metrics["vacancia_fisica_pct_activo"]
    vacant_area = catalog.metrics["m2_vacantes"]
    assert (fund.entity_grain, fund.period_grain, fund.unit, fund.source_kind) == ("fund", "month", "pct_0_100", "canonical")
    assert (physical.entity_grain, physical.period_grain, physical.unit, physical.source_kind) == ("asset", "month", "ratio_0_1", "breakdown")
    assert (vacant_area.entity_grain, vacant_area.period_grain, vacant_area.unit, vacant_area.source_kind) == ("asset", "month", "m2", "breakdown")
    assert fund.aggregation == "non_additive"
    assert vacant_area.aggregation == "sum_compatible_scope"
    assert set(fund.related_metrics) == {"vacancia_fisica_pct_activo", "m2_vacantes"}
    assert fund.access.kind == "fallback_chain"
    assert fund.access.primary.kind == "derived_kpi"
    assert fund.access.fallback.kind == "rollup_ratio_view"
    assert physical.access.kind == "view_metric"
    assert fund.key != physical.key


def test_catalog_is_contract_only_without_values_or_entity_lists():
    catalog = load_metric_catalog()
    serialized = catalog.as_dict()

    serialized_text = repr(serialized).casefold()
    assert "'valor'" not in serialized_text
    assert "'tri'" not in serialized_text
    assert "'mall curicó'" not in serialized_text
    assert serialized["metrics"]["vacancia_pct_fondo"]["access"] == {
        "kind": "fallback_chain",
        "primary": {"kind": "derived_kpi", "entity_type": "fondo", "kpi": "vacancia_pct"},
        "fallback": {
            "kind": "rollup_ratio_view",
            "views": {"PT": "v_vacancia_pt_consolidado_tipo", "Apo": "v_vacancia_apoquindo_consolidado_tipo"},
            "numerator_column": "m2_vacantes", "denominator_column": "m2_gla",
            "exclude_column": "tipo_unidad", "exclude_value": "Estacionamiento",
            "dedupe_columns": ("tipo_unidad",), "precedence_column": "fuente",
            "precedence_order": ("rent_roll", "manual"),
        },
    }


def test_canonical_contract_matches_the_protected_tri_june_fact_read_only():
    catalog = load_metric_catalog()
    connection = sqlite3.connect("file:memory/agente_toesca_v2.db?mode=ro", uri=True)
    row = connection.execute(
        "SELECT valor, formula, ingest_run_id FROM derived_kpi "
        "WHERE entidad_tipo='fondo' AND entidad_key='TRI' AND periodo='2026-06' AND kpi='vacancia_pct'"
    ).fetchone()

    assert row == (5.945, "vacancia_ponderada_fondo_rentas_manual (fila 37, Vacancia histórica DB.xlsx)", 142)
    assert catalog.metrics["vacancia_pct_fondo"].methodology == "vacancia_ponderada_fondo_rentas_manual"


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("catalog_version: 1\nmetrics: []\n", "at least one"),
        ("catalog_version: 1\nmetrics:\n- key: duplicate\n- key: duplicate\n", "malformed"),
        ("catalog_version: 1\nmetrics:\n- key: only\n  display_name: Only\n  description: test\n  unit: pct_0_100\n  entity_grain: fund\n  period_grain: month\n  source_kind: canonical\n  aggregation: non_additive\n  allowed_dimensions: []\n  status: active\n  related_metrics: [missing]\n  methodology: test\n  access: {kind: derived_kpi, entity_type: fondo, kpi: vacancia_pct}\n", "unknown related"),
    ],
)
def test_catalog_fails_fast_for_invalid_contracts(tmp_path: Path, contents: str, message: str):
    path = tmp_path / "catalog.yaml"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(CatalogValidationError, match=message):
        load_metric_catalog(path)
