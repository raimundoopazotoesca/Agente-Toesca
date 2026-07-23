from __future__ import annotations

from datetime import date

from tools.db.estado_ingesta import (
    _shift_periodo,
    _periodo_en_curso,
    _periodo_cerrado,
)


def test_shift_periodo_forward_within_year():
    assert _shift_periodo("2026-01", 2) == "2026-03"


def test_shift_periodo_forward_across_year():
    assert _shift_periodo("2025-11", 3) == "2026-02"


def test_shift_periodo_backward_across_year():
    assert _shift_periodo("2026-01", -1) == "2025-12"


def test_periodo_en_curso_mensual():
    assert _periodo_en_curso(date(2026, 7, 23), "mensual") == "2026-07"


def test_periodo_en_curso_trimestral_mid_quarter():
    # Julio cae en el trimestre Jul-Sep, que termina en Septiembre
    assert _periodo_en_curso(date(2026, 7, 23), "trimestral") == "2026-09"


def test_periodo_en_curso_trimestral_first_month_of_quarter():
    # Enero cae en el trimestre Ene-Mar, que termina en Marzo
    assert _periodo_en_curso(date(2026, 1, 5), "trimestral") == "2026-03"


def test_periodo_cerrado_mensual():
    assert _periodo_cerrado("2026-07", "mensual") == "2026-06"


def test_periodo_cerrado_trimestral():
    assert _periodo_cerrado("2026-09", "trimestral") == "2026-06"


def test_periodo_cerrado_trimestral_year_wrap():
    assert _periodo_cerrado("2026-03", "trimestral") == "2025-12"


import pytest

from tools.db.connection import apply_migrations, get_conn_for
from tools.db.estado_ingesta import CONFIG, estado_tipo, estado_ingesta


@pytest.fixture
def con(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    yield conn
    conn.close()


def _insert_eeff(con, periodo, fondo):
    # dim_fondo solo tiene seed 'Apo'; la data real usa fondo_key 'APO'
    # (ver raw_eeff_line en produccion) — se agrega para que la FK no falle.
    con.execute("INSERT OR IGNORE INTO dim_fondo (fondo_key, nombre) VALUES (?, ?)", (fondo, fondo))
    con.execute("INSERT OR IGNORE INTO dim_cuenta (codigo, nombre) VALUES ('X.TEST', 'Test')")
    con.execute(
        "INSERT INTO raw_eeff_line (fondo_key, periodo, cuenta_codigo, monto_clp, file_hash) "
        "VALUES (?, ?, 'X.TEST', 1, ?)",
        (fondo, periodo, f"hash-{fondo}-{periodo}"),
    )
    con.commit()


def _insert_rentroll(con, periodo, activo_key="PT"):
    con.execute(
        "INSERT INTO raw_rent_roll_line (activo_key, periodo, unidad, file_hash) "
        "VALUES (?, ?, 'U1', ?)",
        (activo_key, periodo, f"hash-{activo_key}-{periodo}"),
    )
    con.commit()


def _insert_mercado(con, periodo):
    con.execute(
        "INSERT INTO raw_mercado_oficinas (periodo, proveedor, submercado, clase) "
        "VALUES (?, 'JLL', 'Las Condes', 'A')",
        (periodo,),
    )
    con.commit()


def test_config_tiene_los_3_tipos_del_menu():
    ids = {c["id"] for c in CONFIG}
    assert ids == {"eeff", "rentroll", "mercado"}


def test_estado_tipo_eeff_completo_y_al_dia(con):
    cfg = next(c for c in CONFIG if c["id"] == "eeff")
    hoy = date(2026, 7, 23)  # cerrado esperado: 2026-06
    for fondo in ("TRI", "PT", "APO"):
        _insert_eeff(con, "2026-06", fondo)
    resultado = estado_tipo(con, cfg, hoy)
    assert resultado["ultimo_ingestado"] == "2026-06"
    assert resultado["pendiente"] is None
    assert resultado["al_dia"] is True


def test_estado_tipo_eeff_incompleto_marca_pendiente(con):
    cfg = next(c for c in CONFIG if c["id"] == "eeff")
    hoy = date(2026, 7, 23)
    _insert_eeff(con, "2026-06", "TRI")
    _insert_eeff(con, "2026-06", "PT")
    # falta APO en 2026-06
    resultado = estado_tipo(con, cfg, hoy)
    assert resultado["pendiente"] == "2026-06"
    assert resultado["al_dia"] is False


def test_estado_tipo_rentroll_mensual_completo(con):
    cfg = next(c for c in CONFIG if c["id"] == "rentroll")
    hoy = date(2026, 7, 23)  # cerrado esperado: 2026-06
    for activo in ("PT", "Apoquindo", "Apo3001", "Viña Centro", "Mall Curicó"):
        _insert_rentroll(con, "2026-06", activo)
    resultado = estado_tipo(con, cfg, hoy)
    assert resultado["ultimo_ingestado"] == "2026-06"
    assert resultado["pendiente"] is None
    assert resultado["al_dia"] is True


def test_estado_tipo_rentroll_parcial_no_marca_al_dia(con):
    # Falta JLL (PT/Apoquindo/Apo3001): aunque Viña y Curicó estén, el período
    # completo debe seguir "pendiente" — no alcanza con que ingresen algunos.
    cfg = next(c for c in CONFIG if c["id"] == "rentroll")
    hoy = date(2026, 7, 23)  # cerrado esperado: 2026-06
    _insert_rentroll(con, "2026-06", "Viña Centro")
    _insert_rentroll(con, "2026-06", "Mall Curicó")
    resultado = estado_tipo(con, cfg, hoy)
    assert resultado["ultimo_ingestado"] is None
    assert resultado["pendiente"] == "2026-06"
    assert resultado["al_dia"] is False


def test_estado_tipo_mercado_timeline_ultimo_slot_en_curso(con):
    cfg = next(c for c in CONFIG if c["id"] == "mercado")
    hoy = date(2026, 7, 23)  # en curso: 2026-09, cerrado: 2026-06
    _insert_mercado(con, "2025-12")
    _insert_mercado(con, "2026-03")
    _insert_mercado(con, "2026-06")
    resultado = estado_tipo(con, cfg, hoy)
    assert resultado["al_dia"] is True
    timeline = resultado["timeline"]
    assert [t["periodo"] for t in timeline] == ["2025-12", "2026-03", "2026-06", "2026-09"]
    assert [t["estado"] for t in timeline] == ["ok", "ok", "ok", "na"]


def test_estado_ingesta_devuelve_los_3_tipos(con):
    resultado = estado_ingesta(con, hoy=date(2026, 7, 23))
    ids = {t["id"] for t in resultado["tipos"]}
    assert ids == {"eeff", "rentroll", "mercado"}


def test_eeff_sub_ingestas_por_fondo(con):
    cfg = next(c for c in CONFIG if c["id"] == "eeff")
    hoy = date(2026, 7, 23)  # cerrado esperado: 2026-06
    _insert_eeff(con, "2026-06", "TRI")
    _insert_eeff(con, "2026-06", "PT")
    # APO no ingestado en 2026-06
    resultado = estado_tipo(con, cfg, hoy)
    subs = {s["key"]: s for s in resultado["sub_ingestas"]}
    assert subs["TRI"]["al_dia"] is True
    assert subs["PT"]["al_dia"] is True
    assert subs["APO"]["al_dia"] is False
    assert subs["APO"]["pendiente"] == "2026-06"
    assert resultado["resumen"] == {"al_dia": 2, "total": 3}


def test_rentroll_sub_ingestas_por_proveedor(con):
    cfg = next(c for c in CONFIG if c["id"] == "rentroll")
    hoy = date(2026, 7, 23)  # cerrado esperado: 2026-06
    # JLL completo (3 activos)
    for activo in ("PT", "Apoquindo", "Apo3001"):
        _insert_rentroll(con, "2026-06", activo)
    # Tres A Viña incompleto (falta 2026-06)
    _insert_rentroll(con, "2026-05", "Viña Centro")
    # Tres A Curicó nunca ingestado

    resultado = estado_tipo(con, cfg, hoy)
    subs = {s["key"]: s for s in resultado["sub_ingestas"]}
    assert subs["jll"]["al_dia"] is True
    assert subs["tresa_vina"]["al_dia"] is False
    assert subs["tresa_vina"]["ultimo_ingestado"] == "2026-05"
    assert subs["tresa_curico"]["al_dia"] is False
    assert subs["tresa_curico"]["ultimo_ingestado"] is None
    assert resultado["resumen"] == {"al_dia": 1, "total": 3}


def test_mercado_no_tiene_sub_ingestas(con):
    cfg = next(c for c in CONFIG if c["id"] == "mercado")
    resultado = estado_tipo(con, cfg, date(2026, 7, 23))
    assert resultado["sub_ingestas"] == []
    assert resultado["resumen"] is None


from tools.db.estado_ingesta import timeline_rango


def _ventana(rango, offset):
    """Recorta del rango completo la ventana de ``n`` períodos para un offset dado
    — misma lógica de slicing que hace el frontend con el cache."""
    start = offset - rango["offset_min"]
    return rango["periodos"][start:start + rango["n"]]


def test_timeline_rango_devuelve_periodos_consecutivos(con):
    hoy = date(2026, 7, 23)  # en_curso=2026-09
    resultado = timeline_rango(con, "eeff", hoy, offset_min=-1, offset_max=1)
    periodos = [p["periodo"] for p in resultado["periodos"]]
    assert periodos == ["2025-09", "2025-12", "2026-03", "2026-06", "2026-09", "2026-12"]


def test_timeline_rango_ventana_offset_cero_coincide_con_estado_tipo(con):
    hoy = date(2026, 7, 23)
    _insert_eeff(con, "2026-06", "TRI")
    esperado = estado_tipo(con, next(c for c in CONFIG if c["id"] == "eeff"), hoy)["timeline"]
    rango = timeline_rango(con, "eeff", hoy, offset_min=-1, offset_max=1)
    assert _ventana(rango, 0) == esperado


def test_timeline_rango_ventana_offset_negativo(con):
    hoy = date(2026, 7, 23)
    rango = timeline_rango(con, "eeff", hoy, offset_min=-1, offset_max=1)
    ventana = [p["periodo"] for p in _ventana(rango, -1)]
    assert ventana == ["2025-09", "2025-12", "2026-03", "2026-06"]


def test_timeline_rango_ventana_offset_positivo_marca_futuro_na(con):
    hoy = date(2026, 7, 23)
    rango = timeline_rango(con, "eeff", hoy, offset_min=-1, offset_max=1)
    ventana = _ventana(rango, 1)
    assert [p["periodo"] for p in ventana] == ["2026-03", "2026-06", "2026-09", "2026-12"]
    # 2026-12 cae después de en_curso (2026-09): todavía no puede estar ingestado
    assert ventana[-1]["estado"] == "na"


def test_timeline_rango_incluye_sub_ingestas(con):
    hoy = date(2026, 7, 23)
    _insert_eeff(con, "2026-06", "TRI")
    rango = timeline_rango(con, "eeff", hoy, offset_min=-1, offset_max=1)
    subs = {s["key"]: s for s in rango["sub_ingestas"]}
    tri_ventana = _ventana({"periodos": subs["TRI"]["periodos"], "offset_min": rango["offset_min"], "n": rango["n"]}, 0)
    pt_ventana = _ventana({"periodos": subs["PT"]["periodos"], "offset_min": rango["offset_min"], "n": rango["n"]}, 0)
    assert tri_ventana[-2]["estado"] == "ok"  # 2026-06
    assert pt_ventana[-2]["estado"] == "miss"
