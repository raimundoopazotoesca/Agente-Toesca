from pathlib import Path

from tools.reports.sucden import SucdenViewProvider


DB = Path("memory/agente_toesca_v2.db")


def test_sucden_view_returns_single_contract_no_charts():
    report = SucdenViewProvider(DB).build()

    assert report["schema_version"] == "sucden_view_v1"
    assert report["building"]["label"] == "Sucden"
    assert "insights" not in report
    contrato = report["contrato"]
    assert contrato["arrendatario"] == "Sucden"
    assert {"m2", "renta_uf", "vencimiento", "fecha_inicio"} <= set(contrato)
