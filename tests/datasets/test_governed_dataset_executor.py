from pathlib import Path

import pytest

from tools.datasets.executor import (DatasetFilter, DatasetMeasure, DatasetQueryError,
                                     GovernedDatasetExecutor, GovernedDatasetQuery)


DB = Path("memory/agente_toesca_v2.db")


def query(**kwargs):
    base = dict(dataset="rent_roll", filters=(DatasetFilter("activo_key", "eq", "Apo3001"), DatasetFilter("periodo", "eq", "2026-06")), group_by=("arrendatario",), measures=(DatasetMeasure("gla_m2", "sum"),), order_by="gla_m2", descending=True, limit=5, share_of_total=True)
    base.update(kwargs)
    return GovernedDatasetQuery(**base)


def test_top_tenants_is_composed_from_catalog_dimensions_filters_measure_and_limit():
    result = GovernedDatasetExecutor(DB).execute(query())
    assert len(result.rows) == 5
    assert result.coverage["full_universe_scanned"] is True
    assert result.coverage["output_intentionally_limited"] is True
    assert all("share_of_total" in row for row in result.rows)


def test_multiple_filters_and_generic_grouping_work_without_question_handler():
    result = GovernedDatasetExecutor(DB).execute(query(filters=(DatasetFilter("activo_key", "eq", "Apo3001"), DatasetFilter("periodo", "eq", "2026-06"), DatasetFilter("occupancy_status", "eq", "occupied"), DatasetFilter("unit_category", "eq", "office")), group_by=("unit_category",), limit=None))
    assert result.rows[0]["unit_category"] == "office"
    assert result.rows[0]["gla_m2"] > 0


def test_undeclared_fields_and_invalid_aggregation_fail_closed():
    executor = GovernedDatasetExecutor(DB)
    with pytest.raises(DatasetQueryError): executor.execute(query(filters=(DatasetFilter("m2; DROP TABLE raw_rent_roll_line", "eq", 1),)))
    with pytest.raises(DatasetQueryError): executor.execute(query(measures=(DatasetMeasure("rent_rate_uf_m2", "sum"),)))


def test_source_classification_and_snapshot_expiry_are_governed_dimensions():
    result = GovernedDatasetExecutor(DB).execute(query(
        filters=(DatasetFilter("activo_key", "eq", "Apo3001"), DatasetFilter("periodo", "eq", "2026-06"),
                 DatasetFilter("expiry_year", "between", 2026, 2030)),
        group_by=("tenant_type", "expiry_year"), limit=None,
    ))
    assert result.rows
    assert result.contract["snapshot_semantics"] == "current_rent_roll_snapshot"
    assert all("tenant_type" in row and "expiry_year" in row for row in result.rows)


def test_two_declared_axes_pivot_a_measure_without_dimension_specific_handler():
    result = GovernedDatasetExecutor(DB).execute(query(
        group_by=(), row_axis="tenant_type", column_axis="occupancy_status", limit=None,
    ))
    assert result.contract["axes"] == {"row": "tenant_type", "column": "occupancy_status"}
    assert result.rows
    assert any("occupied__gla_m2" in row for row in result.rows)


def test_unit_and_tenant_contract_keeps_each_snapshot_lease_expiry_separate():
    result = GovernedDatasetExecutor(DB).execute(query(
        filters=(DatasetFilter("activo_key", "eq", "Torre A"), DatasetFilter("periodo", "eq", "2026-06"),
                 DatasetFilter("arrendatario", "eq", "Scotiabank Azul")),
        group_by=("unidad", "arrendatario", "vencimiento"),
        measures=(DatasetMeasure("gla_m2", "sum"), DatasetMeasure("rent_rate_uf_m2", "avg")),
        order_by="gla_m2", limit=None, share_of_total=False,
    ))
    assert len(result.rows) > 1
    assert all(row["arrendatario"] == "Scotiabank Azul" for row in result.rows)
    assert all("unidad" in row and "vencimiento" in row and "rent_rate_uf_m2" in row for row in result.rows)


def test_floor_uses_only_declared_asset_level_source_mappings_and_computes_vacancy_from_gla():
    result = GovernedDatasetExecutor(DB).execute(query(
        filters=(DatasetFilter("activo_key", "eq", "Apo4700"), DatasetFilter("periodo", "eq", "2026-06")),
        group_by=("floor",), measures=(DatasetMeasure("vacancy_pct", "ratio"), DatasetMeasure("gla_m2", "sum")),
        order_by="vacancy_pct", limit=None, share_of_total=False,
    ))
    assert result.rows
    assert all(row["floor"] is not None for row in result.rows)
    assert all(0 <= row["vacancy_pct"] <= 1 for row in result.rows)
    assert result.contract["dimension_coverage"]["floor"] == ["Apo3001", "Apo4501", "Apo4700"]


def test_floor_fails_closed_for_an_asset_without_declared_coverage():
    with pytest.raises(DatasetQueryError, match="floor is unsupported"):
        GovernedDatasetExecutor(DB).execute(query(
            filters=(DatasetFilter("activo_key", "eq", "Torre A"), DatasetFilter("periodo", "eq", "2026-06")),
            group_by=("floor",),
        ))


def test_floor_composes_with_unit_tenant_rate_and_snapshot_expiry():
    result = GovernedDatasetExecutor(DB).execute(query(
        filters=(DatasetFilter("activo_key", "eq", "Apo3001"), DatasetFilter("periodo", "eq", "2026-06"),
                 DatasetFilter("floor", "eq", "8")),
        group_by=("floor", "unidad", "arrendatario", "vencimiento"),
        measures=(DatasetMeasure("gla_m2", "sum"), DatasetMeasure("rent_rate_uf_m2", "avg")),
        order_by="gla_m2", limit=None, share_of_total=False,
    ))
    assert result.rows == ({"floor": "8", "unidad": "Piso 8", "arrendatario": "Help SpA",
                            "vencimiento": "2026-07-31", "gla_m2": pytest.approx(443.4),
                            "rent_rate_uf_m2": pytest.approx(0.49)},)
