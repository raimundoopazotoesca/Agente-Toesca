"""El baseline debe reproducir exactamente el esquema de producción.

Esta era la deuda de fondo del proyecto: la DB productiva se bootstrapeó desde
`schema_v2.sql` y las migraciones 2–22 se marcaron aplicadas sin ejecutarse, así
que una DB creada con `apply_migrations()` tenía un esquema **distinto** del de
producción. Los tests validaban un esquema que producción no tenía y viceversa
(p. ej. la FK `raw_eeff_line.cuenta_codigo -> dim_cuenta`, que en una DB nueva
hacía fallar toda ingesta con `cuenta_codigo`).
"""
from __future__ import annotations

import os

import pytest

from tools.db.connection import (
    BASELINE_VERSION,
    DEFAULT_DB_PATH,
    apply_migrations,
    get_conn_for,
)


def _inventario(path: str) -> dict:
    """Firma estructural del esquema: columnas, FKs, UNIQUEs, índices y vistas."""
    con = get_conn_for(path)
    try:
        out: dict = {}
        for nombre, tipo in con.execute(
            "SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ):
            if tipo == "table":
                cols = tuple(
                    (r[1], r[2], r[3], r[4])
                    for r in con.execute(f"PRAGMA table_info('{nombre}')")
                )
                fks = tuple(sorted(
                    (str(r[2]), str(r[3]), str(r[4]))
                    for r in con.execute(f"PRAGMA foreign_key_list('{nombre}')")
                ))
                uniques = tuple(sorted(
                    tuple(str(x[2]) for x in con.execute(f"PRAGMA index_info('{i[1]}')"))
                    for i in con.execute(f"PRAGMA index_list('{nombre}')") if i[2]
                ))
                out[("tabla", nombre)] = (cols, fks, uniques)
            elif tipo in ("index", "view"):
                out[(tipo, nombre)] = True
        return out
    finally:
        con.close()


@pytest.fixture(scope="module")
def db_nueva(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("baseline") / "nueva.db")
    apply_migrations(path)
    return path


def test_db_nueva_llega_a_la_ultima_version(db_nueva):
    con = get_conn_for(db_nueva)
    try:
        maxima = con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        n = con.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    finally:
        con.close()
    assert maxima >= BASELINE_VERSION
    assert n == maxima, "hay huecos en schema_version"


def test_baseline_no_deja_tablas_obsoletas(db_nueva):
    """`dim_cuenta` (reemplazada por dim_cuenta_eeff) y `publish_run` (nunca
    usada) se excluyeron del baseline a propósito."""
    con = get_conn_for(db_nueva)
    try:
        tablas = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    finally:
        con.close()
    assert "dim_cuenta" not in tablas
    assert "publish_run" not in tablas


def test_db_nueva_permite_ingesta_con_cuenta_codigo(db_nueva):
    """Regresión: la FK a `dim_cuenta` (vacía) hacía fallar toda ingesta con
    `cuenta_codigo` en una DB nueva, mientras que en producción funcionaba."""
    con = get_conn_for(db_nueva)
    try:
        con.execute(
            "INSERT INTO raw_eeff_line (fondo_key, periodo, cuenta_codigo, "
            "cuenta_nombre, monto_clp, file_hash) VALUES ('Apo','2026-03',"
            "'ESF.total_activo','Total activo',1,'h')"
        )
        con.commit()
        assert con.execute("SELECT COUNT(*) FROM raw_eeff_line").fetchone()[0] == 1
    finally:
        con.close()


def test_seeds_de_dimensiones_presentes(db_nueva):
    con = get_conn_for(db_nueva)
    try:
        fondos = {r[0] for r in con.execute("SELECT fondo_key FROM dim_fondo")}
        n_series = con.execute("SELECT COUNT(*) FROM dim_serie").fetchone()[0]
    finally:
        con.close()
    assert fondos == {"TRI", "PT", "Apo"}, "las claves de fondo deben ser las canónicas"
    assert n_series >= 5


@pytest.mark.skipif(
    not os.path.exists(str(DEFAULT_DB_PATH)), reason="DB productiva no disponible"
)
def test_esquema_identico_al_de_produccion(db_nueva):
    """El invariante central de F0.2. Si falla tras agregar una migración,
    regenera el baseline: python scripts/regenerar_baseline.py"""
    prod = _inventario(str(DEFAULT_DB_PATH))
    nueva = _inventario(db_nueva)

    solo_prod = sorted(set(prod) - set(nueva))
    solo_nueva = sorted(set(nueva) - set(prod))
    distintos = sorted(k for k in set(prod) & set(nueva) if prod[k] != nueva[k])

    assert not solo_prod, f"objetos que producción tiene y una DB nueva no: {solo_prod}"
    assert not solo_nueva, f"objetos que una DB nueva tiene y producción no: {solo_nueva}"
    assert not distintos, f"objetos con estructura distinta: {distintos}"


@pytest.mark.skipif(
    not os.path.exists(str(DEFAULT_DB_PATH)), reason="DB productiva no disponible"
)
def test_baseline_al_dia_respecto_de_produccion():
    """Si alguien agrega una migración y no regenera el baseline, este test lo
    detecta antes de que una DB nueva divergga en silencio."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    res = subprocess.run(
        [sys.executable, str(root / "scripts" / "regenerar_baseline.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert res.returncode == 0, res.stderr or res.stdout
