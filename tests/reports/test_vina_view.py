from pathlib import Path

from tools.reports.vina import VinaViewProvider


DB = Path("memory/agente_toesca_v2.db")


def test_vina_view_returns_building_and_insights():
    report = VinaViewProvider(DB).build()

    assert report["schema_version"] == "vina_view_v1"
    assert report["building"]["label"] == "Viña Centro"
    assert {"occupancy_pct", "vacancy_pct", "vacant_m2", "gla_m2"} <= set(report["building"])

    insights = report["insights"]
    assert insights["rubro_arrendatario"]
    assert insights["tipo_activo"]
    assert insights["arrendatarios"]
    assert {"anios", "por_anio_uf", "plazo_medio_anios"} <= set(insights["vencimiento"])


def test_vina_view_does_not_fabricate_a_future_snapshot():
    report = VinaViewProvider(DB).build(period="2099-01")

    assert report["context"]["requested_period"] == "2099-01"
    assert report["coverage"]["status"] == "partial"
    assert report["context"]["period"] is not None
