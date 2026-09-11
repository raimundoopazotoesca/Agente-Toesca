from pathlib import Path

from tools.reports.curico import CuricoViewProvider


DB = Path("memory/agente_toesca_v2.db")


def test_curico_view_returns_building_and_insights():
    report = CuricoViewProvider(DB).build()

    assert report["schema_version"] == "curico_view_v1"
    assert report["building"]["label"] == "Mall Curicó"
    assert {"occupancy_pct", "vacancy_pct", "vacant_m2", "gla_m2"} <= set(report["building"])

    insights = report["insights"]
    assert insights["rubro_arrendatario"]
    assert insights["tipo_activo"]
    assert insights["arrendatarios"]


def test_curico_view_does_not_fabricate_a_future_snapshot():
    report = CuricoViewProvider(DB).build(period="2099-01")

    assert report["context"]["requested_period"] == "2099-01"
    assert report["coverage"]["status"] == "partial"
