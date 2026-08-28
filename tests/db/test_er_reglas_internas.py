"""Tests de las reglas internas de ER (migracion 087 + tools/db/er_reglas.py).

Contribuciones y seguros no los entrega JLL. La tabla guarda solo parametros; la
aritmetica vive en codigo. Estos tests fijan ambas mitades del contrato.
"""
import json

import pytest

from tools.db import er_reglas
from tools.db.connection import apply_migrations, get_conn_for


@pytest.fixture
def db(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    conn.execute(
        "INSERT OR IGNORE INTO dim_activo (activo_key, nombre, fondo_key) "
        "VALUES ('Torre A', 'Torre A', 'PT')"
    )
    # UF diaria del periodo de prueba (`fuente` es NOT NULL en raw_uf_diaria)
    conn.executemany(
        "INSERT OR IGNORE INTO raw_uf_diaria (fecha, valor, fuente) VALUES (?, ?, 'TEST')",
        [("2026-06-%02d" % d, 40000.0 + d) for d in range(1, 31)],
    )
    conn.commit()
    yield conn
    conn.close()


def test_semilla_de_la_migracion_esta_completa(db):
    filas = db.execute(
        "SELECT activo_key, cuenta_codigo, tipo FROM dim_er_regla_interna"
    ).fetchall()
    contribuciones = {
        (r["activo_key"], r["cuenta_codigo"])
        for r in filas if r["tipo"] == "formula_contribuciones"
    }
    assert contribuciones == {
        ("Apo4501", "APO_CONTRIB"),
        ("Apo4700", "APO_CONTRIB"),
        ("Apo3001", "APO3001_CONTRIB_SOBRETASA"),
        ("Boulevard", "PT_CONTRIB"),
        ("Torre A", "PT_CONTRIB"),
    }
    seguros = {
        (r["activo_key"], r["cuenta_codigo"])
        for r in filas if r["tipo"] == "monto_fijo_uf"
    }
    # Apo4501/4700 no tienen seguros internos; Apo3001 lo entrega JLL.
    assert seguros == {("Boulevard", "PT_SEG"), ("Torre A", "PT_SEG")}


def test_parametros_son_datos_no_expresiones(db):
    """La tabla nunca debe guardar algo evaluable como codigo."""
    for row in db.execute("SELECT parametros_json FROM dim_er_regla_interna"):
        params = json.loads(row["parametros_json"])
        assert isinstance(params, dict)
        for valor in params.values():
            assert isinstance(valor, (int, float, list, str))
            if isinstance(valor, str):
                # los unicos strings son enums de convencion, no formulas
                assert valor in {"dia_5", "fin_mes"}


def test_uf_dia_5_cae_de_vuelta_al_primer_dia_disponible(db):
    db.execute("DELETE FROM raw_uf_diaria WHERE fecha = '2026-06-05'")
    db.commit()
    # sin el dia 5, toma el primer dia disponible a partir del 5
    assert er_reglas.uf_del_periodo(db, "2026-06") == 40006.0


def test_uf_fin_de_mes(db):
    assert er_reglas.uf_del_periodo(db, "2026-06", er_reglas.UF_FIN_MES) == 40030.0


def test_sin_uf_falla_ruidosamente(db):
    with pytest.raises(er_reglas.ReglaError, match="No hay UF"):
        er_reglas.uf_del_periodo(db, "2019-01")


def test_contribuciones_aplica_factor_divisor_y_uf(db):
    uf = er_reglas.uf_del_periodo(db, "2026-06")
    reglas = [
        r for r in er_reglas.reglas_vigentes(db, "2026-06")
        if r.activo_key == "Torre A" and r.cuenta_codigo == "PT_CONTRIB"
    ]
    assert len(reglas) == 1
    esperado = 1.0 * (-110660042 + -39543299) / 3 / uf
    assert er_reglas.evaluar(db, reglas[0], "2026-06") == pytest.approx(esperado)


def test_split_apoquindo_suma_uno(db):
    """El avaluo combinado se reparte 75/25 entre Apo4501 y Apo4700."""
    reglas = {
        r.activo_key: r for r in er_reglas.reglas_vigentes(db, "2026-06")
        if r.cuenta_codigo == "APO_CONTRIB"
    }
    f4501 = json.loads(
        db.execute(
            "SELECT parametros_json FROM dim_er_regla_interna "
            " WHERE activo_key='Apo4501' AND cuenta_codigo='APO_CONTRIB'"
        ).fetchone()["parametros_json"]
    )
    f4700 = json.loads(
        db.execute(
            "SELECT parametros_json FROM dim_er_regla_interna "
            " WHERE activo_key='Apo4700' AND cuenta_codigo='APO_CONTRIB'"
        ).fetchone()["parametros_json"]
    )
    assert f4501["factor"] + f4700["factor"] == 1.0
    assert f4501["base_clp"] == f4700["base_clp"]
    assert set(reglas) >= {"Apo4501", "Apo4700"}


def test_monto_fijo_no_depende_de_la_uf(db):
    regla = [
        r for r in er_reglas.reglas_vigentes(db, "2026-06")
        if r.cuenta_codigo == "PT_SEG" and r.activo_key == "Torre A"
    ][0]
    assert er_reglas.evaluar(db, regla, "2026-06") == pytest.approx(
        -173.464166666667
    )


def test_evaluar_periodo_trae_la_version_usada(db):
    filas, errores = er_reglas.evaluar_periodo(db, "2026-06", ["Torre A"])
    assert filas
    assert errores == []
    for f in filas:
        assert f["origen"] == "regla_interna"
        assert isinstance(f["origen_regla_id"], int)


def test_modo_tolerante_aisla_la_regla_que_falla(db):
    """Sin UF, contribuciones no se puede evaluar pero seguros sí.

    Es lo que necesita la ingesta: una UF faltante no puede hacer perder datos
    crudos que ya son válidos.
    """
    db.execute("DELETE FROM raw_uf_diaria WHERE fecha LIKE '2026-06%'")
    db.commit()

    with pytest.raises(er_reglas.ReglaError):
        er_reglas.evaluar_periodo(db, "2026-06", ["Torre A"])

    filas, errores = er_reglas.evaluar_periodo(
        db, "2026-06", ["Torre A"], tolerante=True
    )
    assert [f["cuenta_codigo"] for f in filas] == ["PT_SEG"]
    assert [e["cuenta_codigo"] for e in errores] == ["PT_CONTRIB"]


def test_regla_nueva_no_modifica_la_anterior(db):
    """Versionar es insertar, nunca editar parametros_json."""
    original = db.execute(
        "SELECT id, parametros_json FROM dim_er_regla_interna "
        " WHERE activo_key='Torre A' AND cuenta_codigo='PT_SEG'"
    ).fetchone()

    db.execute(
        "UPDATE dim_er_regla_interna SET vigente_hasta='2026-06' WHERE id=?",
        (original["id"],),
    )
    db.execute(
        "INSERT INTO dim_er_regla_interna "
        " (activo_key, cuenta_codigo, tipo, parametros_json, version, vigente_desde) "
        " VALUES ('Torre A', 'PT_SEG', 'monto_fijo_uf', ?, 2, '2026-07')",
        (json.dumps({"monto_uf": -200.0}),),
    )
    db.commit()

    # la version 1 quedo intacta
    assert db.execute(
        "SELECT parametros_json FROM dim_er_regla_interna WHERE id=?",
        (original["id"],),
    ).fetchone()["parametros_json"] == original["parametros_json"]

    # y cada periodo resuelve a su version
    def seg(periodo):
        return [
            r for r in er_reglas.reglas_vigentes(db, periodo)
            if r.cuenta_codigo == "PT_SEG" and r.activo_key == "Torre A"
        ][0]

    assert seg("2026-06").version == 1
    assert seg("2026-07").version == 2
    assert er_reglas.evaluar(db, seg("2026-07"), "2026-07") == -200.0


def test_version_duplicada_es_rechazada(db):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO dim_er_regla_interna "
            " (activo_key, cuenta_codigo, tipo, parametros_json, version) "
            " VALUES ('Torre A', 'PT_SEG', 'monto_fijo_uf', '{\"monto_uf\": -1}', 1)"
        )


def test_tipo_desconocido_falla(db):
    regla = er_reglas.Regla(
        id=0, activo_key="Torre A", cuenta_codigo="X", tipo="magia",
        parametros={}, version=1, vigente_desde=None, vigente_hasta=None,
    )
    with pytest.raises(er_reglas.ReglaError, match="no soportado"):
        er_reglas.evaluar(db, regla, "2026-06")
