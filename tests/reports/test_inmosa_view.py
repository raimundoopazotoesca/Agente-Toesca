from pathlib import Path

from tools.reports.inmosa import InmosaViewProvider


DB = Path("memory/agente_toesca_v2.db")


def test_inmosa_view_returns_building_metrics_only():
    report = InmosaViewProvider(DB).build()

    assert report["schema_version"] == "inmosa_view_v1"
    assert report["building"]["label"] == "INMOSA"
    assert {"occupancy_pct", "vacancy_pct", "vacant_m2", "gla_m2"} <= set(report["building"])
    # Sin rent roll ingestado: no se fabrica composición/arrendatarios.
    assert report["detalle_disponible"] is False
    assert "insights" not in report
