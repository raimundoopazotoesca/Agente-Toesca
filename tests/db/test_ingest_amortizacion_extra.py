from __future__ import annotations

from datetime import date

import pytest

from tools.db import ingest_amortizacion_extra as amort


def _seed_credito(con, credito_key="TEST_CRED", estado="VIGENTE"):
    con.execute(
        "INSERT INTO dim_credito (credito_key, activo_key, fondo_key, acreedor, estado) "
        "VALUES (?, 'ActivoTest', 'TRI', 'BancoTest', ?)",
        (credito_key, estado),
    )
    con.commit()


def _seed_saldo(con, credito_key, proyectados=(), historicos=()):
    for periodo, saldo in proyectados:
        con.execute(
            "INSERT INTO raw_saldo_deuda (credito_key, periodo, saldo_uf, is_proyeccion) "
            "VALUES (?, ?, ?, 1)",
            (credito_key, periodo, saldo),
        )
    for periodo, saldo in historicos:
        con.execute(
            "INSERT INTO raw_saldo_deuda (credito_key, periodo, saldo_uf, is_proyeccion) "
            "VALUES (?, ?, ?, 0)",
            (credito_key, periodo, saldo),
        )
    con.commit()


def test_commit_rechaza_credito_inexistente(tmp_db):
    with pytest.raises(ValueError, match="no existe"):
        amort.commit(tmp_db, "NO_EXISTE", "2026-08-15", 100.0)


def test_commit_rechaza_credito_pagado(tmp_db):
    _seed_credito(tmp_db, estado="PAGADO")
    with pytest.raises(ValueError, match="VIGENTE"):
        amort.commit(tmp_db, "TEST_CRED", "2026-08-15", 100.0)


def test_commit_rechaza_monto_no_positivo(tmp_db):
    _seed_credito(tmp_db)
    with pytest.raises(ValueError, match="monto"):
        amort.commit(tmp_db, "TEST_CRED", "2026-08-15", 0)


def test_commit_rechaza_fecha_invalida(tmp_db):
    _seed_credito(tmp_db)
    with pytest.raises(ValueError, match="[Ff]echa"):
        amort.commit(tmp_db, "TEST_CRED", "15-08-2026", 100.0)


def test_commit_ajusta_solo_saldo_proyectado_futuro_del_mismo_credito(tmp_db):
    _seed_credito(tmp_db, credito_key="TEST_CRED")
    _seed_saldo(
        tmp_db, "TEST_CRED",
        proyectados=[("2026-08", 1000.0), ("2026-09", 950.0)],
        historicos=[("2026-07", 1050.0)],
    )
    _seed_credito(tmp_db, credito_key="OTRO_CRED")
    _seed_saldo(tmp_db, "OTRO_CRED", proyectados=[("2026-08", 500.0)])

    result = amort.commit(tmp_db, "TEST_CRED", "2026-08-10", 100.0, nota="prepago test")

    assert result["status"] == "ok"
    assert result["periodo"] == "2026-08"
    assert result["periodos_ajustados"] == 2

    saldo_hist = tmp_db.execute(
        "SELECT saldo_uf FROM raw_saldo_deuda WHERE credito_key='TEST_CRED' AND periodo='2026-07'"
    ).fetchone()[0]
    assert saldo_hist == 1050.0  # historico intacto (is_proyeccion=0)

    saldo_ago = tmp_db.execute(
        "SELECT saldo_uf FROM raw_saldo_deuda WHERE credito_key='TEST_CRED' AND periodo='2026-08'"
    ).fetchone()[0]
    assert saldo_ago == 900.0  # 1000 - 100

    saldo_sep = tmp_db.execute(
        "SELECT saldo_uf FROM raw_saldo_deuda WHERE credito_key='TEST_CRED' AND periodo='2026-09'"
    ).fetchone()[0]
    assert saldo_sep == 850.0  # 950 - 100

    saldo_otro = tmp_db.execute(
        "SELECT saldo_uf FROM raw_saldo_deuda WHERE credito_key='OTRO_CRED' AND periodo='2026-08'"
    ).fetchone()[0]
    assert saldo_otro == 500.0  # otro credito no se toca

    evento = tmp_db.execute(
        "SELECT credito_key, fecha, periodo, monto_uf, nota FROM raw_amortizacion_extraordinaria "
        "WHERE credito_key='TEST_CRED'"
    ).fetchone()
    assert tuple(evento) == ("TEST_CRED", "2026-08-10", "2026-08", 100.0, "prepago test")


def test_historial_orden_descendente_por_fecha(tmp_db):
    _seed_credito(tmp_db)
    amort.commit(tmp_db, "TEST_CRED", "2026-06-01", 50.0, nota="primero")
    amort.commit(tmp_db, "TEST_CRED", "2026-08-01", 30.0, nota="segundo")

    eventos = amort.historial(tmp_db, "TEST_CRED")

    assert [e["nota"] for e in eventos] == ["segundo", "primero"]


def test_listar_creditos_solo_vigentes(tmp_db):
    _seed_credito(tmp_db, credito_key="V1", estado="VIGENTE")
    _seed_credito(tmp_db, credito_key="P1", estado="PAGADO")

    creditos = amort.listar_creditos(tmp_db)

    keys = {c["credito_key"] for c in creditos}
    assert "V1" in keys
    assert "P1" not in keys


def test_listar_creditos_usa_saldo_a_la_fecha_no_el_ultimo_proyectado(tmp_db):
    _seed_credito(tmp_db, credito_key="TEST_CRED")
    _seed_saldo(
        tmp_db, "TEST_CRED",
        proyectados=[("2026-09", 850.0), ("2040-12", 0.0)],
        historicos=[("2026-07", 1050.0), ("2026-08", 950.0)],
    )

    creditos = amort.listar_creditos(tmp_db, hoy=date(2026, 8, 20))

    cred = next(c for c in creditos if c["credito_key"] == "TEST_CRED")
    assert cred["saldo_uf"] == 950.0
    assert cred["saldo_periodo"] == "2026-08"


def test_listar_creditos_sin_saldo_devuelve_none(tmp_db):
    _seed_credito(tmp_db, credito_key="SIN_SALDO")

    creditos = amort.listar_creditos(tmp_db)

    cred = next(c for c in creditos if c["credito_key"] == "SIN_SALDO")
    assert cred["saldo_uf"] is None
