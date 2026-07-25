"""Índices únicos parciales: una sola versión vigente, historial ilimitado.

Los índices únicos totales impedían reingerir un archivo tras supersederlo, y
`UNIQUE(..., superseded_at)` no sirve como alternativa: SQLite trata cada NULL
como distinto, así que deja convivir N filas vigentes con la misma clave. Las
cuatro tablas de parking usaban esa forma y su restricción era decorativa.

La forma correcta es `WHERE superseded_at IS NULL`.
"""
from __future__ import annotations

import sqlite3

import pytest

from tools.db.connection import apply_migrations, get_conn_for

# (tabla, columnas de la clave, valores base) — una por familia de restricción.
TABLAS = [
    (
        "raw_er_activo_line",
        ("file_hash", "source_row", "periodo", "activo_key"),
        {"file_hash": "H1", "source_row": 4, "periodo": "2026-01", "activo_key": "Apo4501",
         "cuenta_codigo": "APO_CONTRIB", "cuenta_nombre": "Contribuciones", "monto_clp": -100.0},
    ),
    (
        "raw_rent_roll_line",
        ("file_hash", "source_row"),
        {"file_hash": "H1", "source_row": 7, "periodo": "2026-05",
         "activo_key": "Apo4501", "unidad": "101", "arrendatario": "Acme"},
    ),
    (
        "raw_flujo_line",
        ("file_hash", "source_row", "periodo"),
        {"file_hash": "H1", "source_row": 3, "periodo": "2026-01",
         "activo_key": "Apo4501", "cuenta_nombre": "Ingresos", "monto_clp": 500.0},
    ),
    (
        "raw_parking_ingreso_line",
        ("activo_key", "periodo", "concepto_id"),
        {"activo_key": "Parking PT", "periodo": "2026-01", "concepto_id": 1,
         "monto_clp": 100.0, "file_hash": "H1"},
    ),
    (
        "raw_parking_ticket_line",
        ("activo_key", "fecha"),
        {"activo_key": "Parking PT", "fecha": "2026-01-15", "file_hash": "H1",
         "tickets": 10},
    ),
]


@pytest.fixture
def con(tmp_db_path):
    apply_migrations(tmp_db_path)
    c = get_conn_for(tmp_db_path)
    c.executemany(
        "INSERT OR IGNORE INTO dim_activo (activo_key, fondo_key, nombre) VALUES (?,?,?)",
        [("Apo4501", "Apo", "Apoquindo 4501"), ("Parking PT", "PT", "Parking PT")],
    )
    c.commit()
    yield c
    c.close()


def _insert(c, tabla, valores, **extra):
    datos = {**valores, **extra}
    cols = ", ".join(datos)
    marks = ", ".join("?" * len(datos))
    c.execute(f"INSERT INTO {tabla} ({cols}) VALUES ({marks})", tuple(datos.values()))
    c.commit()


def _supersede(c, tabla):
    c.execute(f"UPDATE {tabla} SET superseded_at = datetime('now') WHERE superseded_at IS NULL")
    c.commit()


@pytest.mark.parametrize("tabla,clave,base", TABLAS, ids=[t[0] for t in TABLAS])
def test_no_pueden_coexistir_dos_filas_vigentes(tabla, clave, base, con):
    _insert(con, tabla, base)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(con, tabla, base)


@pytest.mark.parametrize("tabla,clave,base", TABLAS, ids=[t[0] for t in TABLAS])
def test_una_superseded_y_una_vigente_conviven(tabla, clave, base, con):
    """Es el caso de la reingesta: se anula la versión anterior y entra la nueva."""
    _insert(con, tabla, base)
    _supersede(con, tabla)
    _insert(con, tabla, base)

    vivas = con.execute(f"SELECT COUNT(*) FROM {tabla} WHERE superseded_at IS NULL").fetchone()[0]
    total = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    assert vivas == 1
    assert total == 2, "la versión anterior debe conservarse para auditoría"


@pytest.mark.parametrize("tabla,clave,base", TABLAS, ids=[t[0] for t in TABLAS])
def test_varias_superseded_se_conservan(tabla, clave, base, con):
    """El historial no tiene tope: N versiones anuladas y una sola vigente."""
    for _ in range(3):
        _insert(con, tabla, base)
        _supersede(con, tabla)
    _insert(con, tabla, base)

    vivas = con.execute(f"SELECT COUNT(*) FROM {tabla} WHERE superseded_at IS NULL").fetchone()[0]
    total = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    assert vivas == 1
    assert total == 4


@pytest.mark.parametrize("tabla,clave,base", TABLAS, ids=[t[0] for t in TABLAS])
def test_reingesta_del_mismo_archivo_funciona_tras_superseder(tabla, clave, base, con):
    """Con índice único total esto fallaba: la fila superseded seguía ocupando la
    clave y obligaba a que el archivo corregido tuviera otro hash."""
    _insert(con, tabla, base)
    _supersede(con, tabla)
    _insert(con, tabla, base)  # mismo file_hash / misma clave
    _supersede(con, tabla)
    _insert(con, tabla, base)

    assert con.execute(
        f"SELECT COUNT(*) FROM {tabla} WHERE superseded_at IS NULL"
    ).fetchone()[0] == 1


def test_parking_ya_no_acepta_dos_vigentes_iguales(con):
    """Regresión directa: el UNIQUE inline de parking aceptaba estas dos filas."""
    sql = ("INSERT INTO raw_parking_ingreso_line "
           "(activo_key, periodo, concepto_id, monto_clp, file_hash) "
           "VALUES ('Parking PT','2026-01',1,?,'H')")
    con.execute(sql, (100,))
    con.commit()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(sql, (999,))
        con.commit()


def test_los_indices_son_parciales(con):
    """Si alguien los recrea sin el WHERE, la reingesta vuelve a romperse."""
    esperados = {
        "uq_er_activo_vivo", "uq_rent_roll_vivo", "uq_flujo_vivo",
        "uq_parking_ingreso_vivo", "uq_parking_gasto_vivo",
        "uq_parking_facturacion_vivo", "uq_parking_ticket_vivo",
    }
    filas = dict(con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND name LIKE 'uq_%vivo'"
    ).fetchall())
    assert esperados <= set(filas), f"faltan índices: {esperados - set(filas)}"
    for nombre, sql in filas.items():
        assert "superseded_at IS NULL" in sql, f"{nombre} no es parcial"
