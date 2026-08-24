"""Golden tests for the single shared metric-value formatter."""
import pytest

from tools.analytics.catalog import CatalogValidationError, load_metric_catalog
from tools.analytics.formatting import render_fact, render_metric_value, render_named_fact


def test_ratio_metric_with_percent_display_unit_renders_as_percent():
    # 0.7115159 is the raw canonical LTV of Apo3001 for 2026-06.
    assert render_metric_value("ltv_activo", 0.7115159, "ratio_0_1") == "71.15%"
    assert render_metric_value("ltv_fondo", 0.6101647, "ratio_0_1") == "61.02%"
    assert render_metric_value("ltv_fondo", 0.8122455, "ratio_0_1") == "81.22%"


@pytest.mark.parametrize("wrong", ["0.7115%", "0.71%", "7115%", "71.15159%"])
def test_ratio_percent_rendering_is_never_one_of_the_classic_mistakes(wrong):
    assert render_metric_value("ltv_activo", 0.7115159, "ratio_0_1") != wrong


def test_percent_scale_metric_without_display_unit_is_unchanged():
    """Regression guard: vacancia_pct_fondo is already percent-scale, so its
    rendered value must stay byte-identical (no x100, no rounding)."""
    assert render_metric_value("vacancia_pct_fondo", 5.945, "pct_0_100") == "5.945%"


def test_other_units_get_human_suffixes_not_internal_codes():
    assert render_metric_value("m2_vacantes", 1200.0, "m2") == "1200.0 m2"
    assert render_metric_value("noi_mensual_activo", 10465.96, "clp") == "10465.96 CLP"
    assert "clp" not in render_metric_value("noi_mensual_activo", 1.0, "clp").casefold().replace(" clp", "")


def test_unknown_metric_key_falls_back_to_legacy_concatenation():
    assert render_metric_value("vacancia", 5.945, "%") == "5.945%"


def test_render_fact_and_named_fact_use_display_scale():
    fact = {"metric_key": "ltv_activo", "value": 0.7115159, "unit": "ratio_0_1",
            "entity_id": "Apo3001", "period": "2026-06"}
    assert render_fact(fact) == "71.15%"
    assert render_named_fact(fact) == "LTV por activo: 71.15%"
    assert "ratio_0_1" not in render_named_fact(fact)
    assert "ltv_activo" not in render_named_fact(fact)


def test_catalog_exposes_display_unit_and_new_units():
    catalog = load_metric_catalog()
    assert catalog.metrics["ltv_activo"].unit == "ratio_0_1"
    assert catalog.metrics["ltv_activo"].display_unit == "percent"
    assert catalog.metrics["ltv_fondo"].display_unit == "percent"
    assert catalog.metrics["noi_mensual_activo"].unit == "clp"
    assert catalog.metrics["noi_mensual_activo"].display_unit is None
    assert catalog.metrics["vacancia_pct_fondo"].display_unit is None


def test_catalog_rejects_incompatible_display_unit(tmp_path):
    source = (
        "catalog_version: 1\nmetrics:\n"
        "  - key: bad\n    display_name: Bad\n    description: d\n    unit: pct_0_100\n"
        "    display_unit: percent\n    entity_grain: fund\n    period_grain: month\n"
        "    source_kind: canonical\n    access: {kind: derived_kpi, entity_type: fondo, kpi: x}\n"
        "    aggregation: non_additive\n    allowed_dimensions: [fund, period]\n    status: active\n"
        "    related_metrics: []\n    methodology: m\n"
    )
    path = tmp_path / "bad.yaml"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(CatalogValidationError):
        load_metric_catalog(path)


def test_catalog_rejects_unknown_display_unit(tmp_path):
    source = (
        "catalog_version: 1\nmetrics:\n"
        "  - key: bad\n    display_name: Bad\n    description: d\n    unit: ratio_0_1\n"
        "    display_unit: basis_points\n    entity_grain: fund\n    period_grain: month\n"
        "    source_kind: canonical\n    access: {kind: derived_kpi, entity_type: fondo, kpi: x}\n"
        "    aggregation: non_additive\n    allowed_dimensions: [fund, period]\n    status: active\n"
        "    related_metrics: []\n    methodology: m\n"
    )
    path = tmp_path / "bad.yaml"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(CatalogValidationError):
        load_metric_catalog(path)


def test_asset_vacancy_is_a_ratio_and_renders_as_percent():
    """v_vacancia_activo.vacancia_pct is a 0-1 ratio, unlike the fund-level
    derived_kpi which is already percent-scale."""
    assert render_metric_value("vacancia_fisica_pct_activo", 0.3620316883059285, "ratio_0_1") == "36.20%"
    assert load_metric_catalog().metrics["vacancia_fisica_pct_activo"].display_unit == "percent"
