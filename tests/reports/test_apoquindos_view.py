from pathlib import Path

from tools.reports.apoquindos import ApoquindosViewProvider


DB = Path("memory/agente_toesca_v2.db")


def test_apoquindos_view_returns_two_buildings_with_observed_floor_layouts():
    report = ApoquindosViewProvider(DB).build(period="2026-06")

    assert report["schema_version"] == "apoquindos_view_v1"
    assert report["context"]["period"] == "2026-06"
    assert [building["asset_key"] for building in report["buildings"]] == ["Apo4501", "Apo4700"]
    assert all(building["floors"] for building in report["buildings"])
    assert {"floor", "occupancy_pct", "vacant_m2", "units"} <= set(report["buildings"][0]["floors"][0])
    assert {"local_status", "locals"} <= set(report["buildings"][0])
    assert report["buildings"][0]["local_status"]["status"] == "available"


def test_apoquindos_view_does_not_fabricate_a_future_snapshot():
    report = ApoquindosViewProvider(DB).build(period="2026-08")

    assert report["context"]["requested_period"] == "2026-08"
    assert report["context"]["period"] == "2026-06"
    assert report["coverage"]["status"] == "partial"


def test_apoquindos_view_includes_insights_per_scope():
    report = ApoquindosViewProvider(DB).build(period="2026-06")

    insights = report["insights"]
    assert set(insights) == {"consolidado", "Apo4501", "Apo4700"}
    for scope in insights.values():
        assert {"label", "rubro_arrendatario", "tipo_activo", "vencimiento", "vacancia_historica"} <= set(scope)
        assert scope["rubro_arrendatario"]
        assert scope["tipo_activo"]
        assert {"anios", "por_anio_uf", "plazo_medio_anios"} <= set(scope["vencimiento"])
        assert scope["vencimiento"]["anios"]
        assert isinstance(scope["vacancia_historica"], list)
        assert scope["vacancia_historica"]
        assert {"periodo", "occupancy_pct"} <= set(scope["vacancia_historica"][0])


def test_apoquindos_view_per_building_tipo_activo_sums_to_consolidado():
    report = ApoquindosViewProvider(DB).build(period="2026-06")

    insights = report["insights"]
    for tipo, total in insights["consolidado"]["tipo_activo"].items():
        suma = insights["Apo4501"]["tipo_activo"].get(tipo, 0.0) + insights["Apo4700"]["tipo_activo"].get(tipo, 0.0)
        assert round(suma, 1) == total
