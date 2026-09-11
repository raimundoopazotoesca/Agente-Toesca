from pathlib import Path

from tools.reports.pt import PTViewProvider


DB = Path("memory/agente_toesca_v2.db")


def test_pt_view_returns_two_buildings_with_aggregate_metrics():
    report = PTViewProvider(DB).build(period="2026-06")

    assert report["schema_version"] == "pt_view_v1"
    assert report["context"]["period"] == "2026-06"
    assert [building["asset_key"] for building in report["buildings"]] == ["Torre A", "Boulevard"]
    assert [building["label"] for building in report["buildings"]] == ["Torre A", "Inmob. CdC"]
    for building in report["buildings"]:
        assert {"occupancy_pct", "vacancy_pct", "vacant_m2", "gla_m2", "rent_uf_m2"} <= set(building)
    # A diferencia de Apoquindos, PT no tiene silueta de edificio ni layout
    # de locales (nunca se trazó esa geometría para Torre A / Inmob. CdC).
    assert "floors" not in report["buildings"][0]
    assert "locals" not in report["buildings"][0]


def test_pt_view_does_not_fabricate_a_future_snapshot():
    report = PTViewProvider(DB).build(period="2026-08")

    assert report["context"]["requested_period"] == "2026-08"
    assert report["context"]["period"] == "2026-06"
    assert report["coverage"]["status"] == "partial"


def test_pt_view_includes_insights_per_scope():
    report = PTViewProvider(DB).build(period="2026-06")

    insights = report["insights"]
    assert set(insights) == {"consolidado", "Torre A", "Boulevard"}
    for scope in insights.values():
        assert {"label", "rubro_arrendatario", "tipo_activo", "vencimiento", "vacancia_historica", "arrendatarios"} <= set(scope)
        assert scope["rubro_arrendatario"]
        assert scope["tipo_activo"]
        assert {"anios", "por_anio_uf", "plazo_medio_anios"} <= set(scope["vencimiento"])
        assert scope["vencimiento"]["anios"]
        assert isinstance(scope["vacancia_historica"], list)
        assert scope["vacancia_historica"]
        assert {"periodo", "occupancy_pct"} <= set(scope["vacancia_historica"][0])


def test_pt_view_per_building_tipo_activo_sums_to_consolidado():
    report = PTViewProvider(DB).build(period="2026-06")

    insights = report["insights"]
    for tipo, total in insights["consolidado"]["tipo_activo"].items():
        suma = insights["Torre A"]["tipo_activo"].get(tipo, 0.0) + insights["Boulevard"]["tipo_activo"].get(tipo, 0.0)
        assert round(suma, 1) == total


def test_pt_view_includes_plano_local_100_with_live_occupancy():
    report = PTViewProvider(DB).build(period="2026-06")

    plano = report["plano_local_100"]
    assert plano["titulo"] == "Plano Local 100"
    assert plano["edificio"] == "Inmob. CdC"
    nombres = [piso["nombre"] for piso in plano["pisos"]]
    assert nombres == ["Piso -1", "Piso -2"]
    unidades = {loc["unidad"]: loc for piso in plano["pisos"] for loc in piso["locales"]}
    assert len(unidades) == 11
    for loc in unidades.values():
        assert len(loc["poligono"]) >= 3
        assert "vacante" in loc
    # 100-8 está vacante en el dato real (ver tools/db/rent_roll_stats.py::get_plano_locales).
    assert unidades["100-8"]["vacante"] is True
    assert unidades["100-1"]["vacante"] is False
    assert unidades["100-1"]["arrendatario"]
