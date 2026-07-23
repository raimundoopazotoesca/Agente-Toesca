from tools.db.ingest_parking_pt_mensual import _periodo_archivo, validate


def test_periodo_archivo_extrae_mes_desde_nombre_saba():
    assert _periodo_archivo("06-2026 Liquidacion Parque Titanium.xlsx") == "2026-06"


def test_validate_rechaza_periodo_posterior_al_mes_del_archivo():
    result = validate(b"", "06-2026 Liquidacion Parque Titanium.xlsx", "2026-07")

    assert not result.ok
    assert result.errors == [
        "El periodo seleccionado (2026-07) no puede ser posterior al mes del archivo (2026-06)."
    ]
