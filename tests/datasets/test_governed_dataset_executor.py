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
