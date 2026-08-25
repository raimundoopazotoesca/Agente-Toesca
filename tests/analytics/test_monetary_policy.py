from tools.analytics.formatting import render_fact
from tools.analytics.monetary import MonetaryConversionSpec, convert_monetary_value, requested_monetary_unit


def test_native_uf_is_the_global_default_without_mutating_the_fact():
    fact = {"metric_key": "noi", "value": 172868.06, "unit": "UF", "period": "2025"}

    assert render_fact(fact) == "172.868 UF"
    assert fact["unit"] == "UF"
    assert fact["value"] == 172868.06


def test_explicit_clp_override_uses_only_an_explicit_governed_contract():
    spec = MonetaryConversionSpec("UF", "CLP", "point_in_time", 35000.0, "raw_uf_diaria", "2025-01-31")

    converted = convert_monetary_value(2.0, spec)

    assert converted.value == 70000.0
    assert converted.unit == "CLP"
    assert converted.lineage["source"] == "raw_uf_diaria"


def test_true_clp_fact_converts_to_uf_only_with_a_safe_contract():
    fact = {"metric_key": "tax", "value": 70000.0, "unit": "CLP", "period": "2025-01",
            "presentation_conversion": {"from_unit": "CLP", "to_unit": "UF", "temporal_basis": "point_in_time",
                                        "reference_value": 35000.0, "source": "raw_uf_diaria", "reference_date": "2025-01-31"}}

    assert render_fact(fact) == "2 UF"


def test_unsafe_clp_fact_stays_native_instead_of_fabricating_uf():
    fact = {"metric_key": "tax", "value": 70000.0, "unit": "CLP", "period": "2025"}

    assert render_fact(fact) == "70.000 CLP"


def test_user_unit_intent_is_generic_and_does_not_touch_non_monetary_metrics():
    assert requested_monetary_unit("Muéstramelo en pesos") == "CLP"
    assert requested_monetary_unit("Muéstramelo en UF") == "UF"
    assert render_fact({"metric_key": "vacancia", "value": 5.945, "unit": "%"}) == "5,95%"
