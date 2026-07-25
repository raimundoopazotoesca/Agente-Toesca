"""Invariantes de negocio sobre la DB productiva.

A diferencia del resto de la suite (que corre sobre DBs temporales migradas
desde cero), estos tests leen `memory/agente_toesca_v2.db` para detectar
corrupción de datos real. Se omiten si la DB no está presente.

Motivación: los tests cubrían CRUD de repos pero no invariantes, así que
20.487 violaciones de FK y ~12.300 filas duplicadas convivieron sin señal.
"""
from __future__ import annotations

import os

import pytest

from tools.db.connection import DEFAULT_DB_PATH, get_conn_for
from tools.db.fondo_keys import fondo_canonico

pytestmark = pytest.mark.skipif(
    not os.path.exists(str(DEFAULT_DB_PATH)), reason="DB productiva no disponible"
)


@pytest.fixture(scope="module")
def con():
    c = get_conn_for(str(DEFAULT_DB_PATH))
    yield c
    c.close()


# ── Claves de fondo ──────────────────────────────────────────────────────────

TABLAS_CON_FONDO = (
    "raw_eeff_line",
    "raw_valor_cuota_contable",
    "raw_dividendo",
    "raw_caja",
    "raw_capital_suscrito",
    "raw_cuota_en_circulacion",
)


@pytest.mark.parametrize("tabla", TABLAS_CON_FONDO)
def test_una_sola_grafia_por_fondo(con, tabla):
    """Regresión de la migración 058: `APO` y `Apo` convivieron en
    raw_eeff_line (18.009 vs 3 filas), partiendo la historia de Apoquindo y
    violando la FK a dim_fondo. Cualquier escritura nueva debe usar la clave
    canónica."""
    claves = [r[0] for r in con.execute(f"SELECT DISTINCT fondo_key FROM {tabla}") if r[0]]
    colisiones = {}
    for k in claves:
        colisiones.setdefault(k.upper(), []).append(k)
    duplicadas = {u: v for u, v in colisiones.items() if len(v) > 1}
    assert not duplicadas, f"{tabla} tiene el mismo fondo con varias grafías: {duplicadas}"


@pytest.mark.parametrize("tabla", TABLAS_CON_FONDO)
def test_fondo_key_es_canonico(con, tabla):
    claves = [r[0] for r in con.execute(f"SELECT DISTINCT fondo_key FROM {tabla}") if r[0]]
    no_canonicos = [k for k in claves if k != fondo_canonico(k)]
    assert not no_canonicos, f"{tabla} usa alias en vez de la clave canónica: {no_canonicos}"


def test_fondos_existen_en_dim_fondo(con):
    faltantes = con.execute(
        "SELECT DISTINCT r.fondo_key FROM raw_eeff_line r "
        "LEFT JOIN dim_fondo d ON d.fondo_key = r.fondo_key "
        "WHERE d.fondo_key IS NULL"
    ).fetchall()
    assert not faltantes, f"fondo_key sin fila en dim_fondo: {faltantes}"


# ── Perímetro del portfolio ──────────────────────────────────────────────────

def test_no_hay_claves_legacy_de_fondo(con):
    """Los nombres viejos ('A&R PT', 'Rentas Apoquindo') no deben reaparecer."""
    legacy = con.execute(
        "SELECT DISTINCT fondo_key FROM raw_eeff_line WHERE fondo_key LIKE 'A&R%'"
    ).fetchall()
    assert not legacy, f"claves legacy presentes: {legacy}"


def test_machali_excluido_del_portfolio_vigente(con):
    """Strip Machalí se vendió en 2025-08 y está fuera del portfolio; no debe
    tener datos operacionales posteriores."""
    posteriores = con.execute(
        "SELECT COUNT(*) FROM raw_er_activo_line "
        "WHERE activo_key LIKE '%achal%' AND periodo > '2025-08' AND superseded_at IS NULL"
    ).fetchone()[0]
    assert posteriores == 0, f"{posteriores} filas de Machalí después de la venta"


def test_activos_referencian_un_fondo_existente(con):
    """La relación activo→fondo va por FK, nunca inferida del nombre. Apo3001
    se llama 'Apoquindo 3001' pero pertenece a TRI, no al fondo Apo."""
    huerfanos = con.execute(
        "SELECT a.activo_key, a.fondo_key FROM dim_activo a "
        "LEFT JOIN dim_fondo f ON f.fondo_key = a.fondo_key "
        "WHERE f.fondo_key IS NULL"
    ).fetchall()
    assert not huerfanos, f"activos con fondo inexistente: {huerfanos}"


def test_apo3001_pertenece_a_tri(con):
    fondo = con.execute(
        "SELECT fondo_key FROM dim_activo WHERE activo_key='Apo3001'"
    ).fetchone()
    assert fondo is not None, "Apo3001 no está en dim_activo"
    assert fondo[0] == "TRI", (
        "Apo3001 debe pertenecer a TRI: es un activo distinto del fondo Apoquindo "
        "y de los edificios Apo4501/Apo4700"
    )


# ── Rangos y coherencia ──────────────────────────────────────────────────────

def test_periodos_tienen_formato_yyyy_mm(con):
    malos = con.execute(
        "SELECT DISTINCT periodo FROM raw_eeff_line "
        "WHERE periodo NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'"
    ).fetchall()
    assert not malos, f"períodos con formato inválido: {malos}"


def test_no_hay_kpis_de_vacancia_fuera_de_rango(con):
    """m2_vacantes no puede ser negativo."""
    negativos = con.execute(
        "SELECT COUNT(*) FROM derived_kpi WHERE kpi='m2_vacantes' AND valor < 0"
    ).fetchone()[0]
    assert negativos == 0, f"{negativos} filas de m2_vacantes negativas"


def test_derived_kpi_entidad_tipo_valido(con):
    invalidos = con.execute(
        "SELECT DISTINCT entidad_tipo FROM derived_kpi "
        "WHERE entidad_tipo NOT IN ('fondo','activo','serie')"
    ).fetchall()
    assert not invalidos, f"entidad_tipo fuera del enum: {invalidos}"


def test_integridad_fisica_de_la_db(con):
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


# ── Deudas conocidas: se documentan como umbral, no como cero ────────────────

def test_violaciones_fk_no_empeoran(con):
    """La migración 058 bajó las violaciones de 20.487 a 2.478. Las restantes son
    `ingest_run_id` inválidos (2.378 de ellos con file-hashes de texto en una
    columna INTEGER), pendientes de reparación. Este test evita que crezcan."""
    violaciones = len(con.execute("PRAGMA foreign_key_check").fetchall())
    assert violaciones <= 2478, (
        f"las violaciones de FK subieron a {violaciones} (tope conocido: 2478)"
    )
