"""Unicidad de raw_er_activo_line con la clave correcta.

La clave es `(file_hash, source_row, periodo, activo_key)`. Expresa que una fila
de la planilla PUEDE repartirse entre varios activos, pero NO puede repetirse
para el mismo activo y período.

Las dos claves más simples que se consideraron antes son incorrectas:
  (file_hash, source_row)          → las planillas traen meses en columnas: una
                                     fila de origen genera una fila por período.
  (file_hash, source_row, periodo) → rechazaría el reparto 75/25 de las
                                     contribuciones de Apoquindo entre Apo4501 y
                                     Apo4700, que es deliberado.
"""
from __future__ import annotations

import sqlite3

import pytest

from tools.db.connection import apply_migrations, get_conn_for


@pytest.fixture
def con(tmp_db_path):
    apply_migrations(tmp_db_path)
    c = get_conn_for(tmp_db_path)
    c.executemany(
        "INSERT OR IGNORE INTO dim_activo (activo_key, fondo_key, nombre) VALUES (?,?,?)",
        [("Apo4501", "Apo", "Apoquindo 4501"), ("Apo4700", "Apo", "Apoquindo 4700")],
    )
    c.commit()
    yield c
    c.close()


def _insertar(c, *, activo, periodo, monto, source_row=29, file_hash="H1", nombre="Contribuciones"):
    c.execute(
        "INSERT INTO raw_er_activo_line "
        "(activo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, "
        " file_hash, source_row, seccion, es_operacional) "
        "VALUES (?,?,?,?,?,?,?,'GASTOS_OPERACION',1)",
        (activo, periodo, "APO_CONTRIB", nombre, monto, file_hash, source_row),
    )
    c.commit()


def test_una_fila_de_origen_puede_repartirse_entre_activos(con):
    """El split 75/25 de las contribuciones de Apoquindo debe seguir aceptándose:
    misma fila de origen y mismo período, distinto activo."""
    _insertar(con, activo="Apo4501", periodo="2019-01", monto=-997.09,
              nombre="Contribuciones (split 75% s/combinado, regla 2026-07-09)")
    _insertar(con, activo="Apo4700", periodo="2019-01", monto=-332.36,
              nombre="Contribuciones (split 25% s/combinado, regla 2026-07-09)")

    filas = con.execute(
        "SELECT activo_key, monto_clp FROM raw_er_activo_line "
        "WHERE file_hash='H1' AND source_row=29 AND periodo='2019-01' ORDER BY activo_key"
    ).fetchall()
    assert len(filas) == 2
    assert filas[0]["activo_key"] == "Apo4501"
    # La proporción del reparto documentada en la regla: 75/25 = 3
    assert round(filas[0]["monto_clp"] / filas[1]["monto_clp"], 2) == 3.0


def test_una_fila_de_origen_genera_una_fila_por_periodo(con):
    """Las planillas de ER traen los meses en columnas."""
    for mes in ("2019-01", "2019-02", "2019-03"):
        _insertar(con, activo="Apo4501", periodo=mes, monto=-997.09)

    n = con.execute(
        "SELECT COUNT(*) FROM raw_er_activo_line WHERE file_hash='H1' AND source_row=29"
    ).fetchone()[0]
    assert n == 3


def test_rechaza_la_misma_fila_para_el_mismo_activo_y_periodo(con):
    """Idempotencia: reingerir la misma fila de origen no puede duplicarla."""
    _insertar(con, activo="Apo4501", periodo="2019-01", monto=-997.09)
    with pytest.raises(sqlite3.IntegrityError):
        _insertar(con, activo="Apo4501", periodo="2019-01", monto=-997.09)


def test_insert_or_ignore_es_idempotente(con):
    """Con la restricción, el INSERT OR IGNORE de los repos por fin funciona."""
    sql = (
        "INSERT OR IGNORE INTO raw_er_activo_line "
        "(activo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, file_hash, source_row) "
        "VALUES ('Apo4501','2019-01','APO_CONTRIB','Contribuciones',-997.09,'H1',29)"
    )
    con.execute(sql)
    con.commit()
    con.execute(sql)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM raw_er_activo_line").fetchone()[0]
    assert n == 1, "el segundo INSERT OR IGNORE no debe duplicar"


def test_distinto_archivo_si_puede_repetir_la_combinacion(con):
    """Otro archivo (otro hash) es otra versión del dato: se permite y se resuelve
    con superseded_at, no con la restricción."""
    _insertar(con, activo="Apo4501", periodo="2019-01", monto=-997.09, file_hash="H1")
    _insertar(con, activo="Apo4501", periodo="2019-01", monto=-998.00, file_hash="H2")
    n = con.execute("SELECT COUNT(*) FROM raw_er_activo_line").fetchone()[0]
    assert n == 2
