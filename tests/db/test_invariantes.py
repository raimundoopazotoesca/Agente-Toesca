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


# ── Catálogo de KPIs ─────────────────────────────────────────────────────────

def test_kpis_legacy_no_se_recalculan(con):
    """`ltc` y `dscr` no tienen metodología escrita ni consumidores. Se conservan
    sus valores históricos, pero el pipeline no debe producir filas nuevas: sin
    fórmula documentada, un recálculo sería inventar el número."""
    legacy = {r[0] for r in con.execute("SELECT kpi FROM dim_kpi WHERE estado='legacy'")}
    assert legacy, "el catálogo debe marcar al menos ltc y dscr como legacy"

    corte = "2026-07-24"  # fecha en que se marcaron
    for kpi in legacy:
        nuevas = con.execute(
            "SELECT COUNT(*) FROM derived_kpi WHERE kpi=? AND computed_at > ?", (kpi, corte)
        ).fetchone()[0]
        assert nuevas == 0, f"{kpi} es legacy y se recalculó {nuevas} veces"


def test_kpis_legacy_conservan_su_historia(con):
    """Legacy significa 'no recalcular', no 'borrar'."""
    for kpi in ("ltc", "dscr"):
        n = con.execute("SELECT COUNT(*) FROM derived_kpi WHERE kpi=?", (kpi,)).fetchone()[0]
        assert n > 0, f"se perdieron los valores históricos de {kpi}"


def test_catalogo_cubre_los_kpis_con_consumidores(con):
    """Todo KPI que alimente un output debe estar en el catálogo: si no, nadie
    sabe si su metodología está escrita ni si puede recalcularse."""
    del_factsheet = {
        "dy", "dy_amort", "ltv", "duration_deuda", "perfil_vencimiento",
        "leverage_financiero", "noi_mensual", "ingresos_mensual", "m2_vacantes",
    }
    catalogados = {r[0] for r in con.execute("SELECT kpi FROM dim_kpi")}
    assert del_factsheet <= catalogados, (
        f"KPIs usados por outputs sin entrada en dim_kpi: {del_factsheet - catalogados}"
    )


# ── Integridad referencial ───────────────────────────────────────────────────

def test_cero_violaciones_de_fk(con):
    """Exigencia dura, sin umbral.

    Recorrido: 20.487 violaciones → 2.478 (migración 058, consolidación de
    `fondo_key` APO→Apo) → **0** (migración 061, que devolvió el hash cruzado a
    `file_hash` y dejó `ingest_run_id` en NULL). El tope intermedio fue una
    protección temporal; el estado aceptable es cero.
    """
    violaciones = con.execute("PRAGMA foreign_key_check").fetchall()
    detalle = [f"{r[0]}→{r[2]}" for r in violaciones[:5]]
    assert not violaciones, (
        f"{len(violaciones)} violaciones de integridad referencial: {detalle}"
    )


def test_todas_las_filas_de_eeff_tienen_file_hash(con):
    """Sin `file_hash` una fila es inalcanzable para `mark_superseded()`: no se
    puede versionar ni corregir. Eran 2.484 filas antes de la migración 061."""
    sin_hash = con.execute(
        "SELECT COUNT(*) FROM raw_eeff_line WHERE file_hash IS NULL"
    ).fetchone()[0]
    assert sin_hash == 0, f"{sin_hash} filas de raw_eeff_line sin file_hash"


def test_lineage_status_usa_el_vocabulario_definido(con):
    """Las cargas sin corrida registrada se marcan explícitamente en vez de
    inventarles un `ingest_run` sintético."""
    valores = {
        r[0] for r in con.execute(
            "SELECT DISTINCT lineage_status FROM raw_eeff_line WHERE lineage_status IS NOT NULL"
        )
    }
    assert valores <= {"legacy_untracked", "manual_sin_archivo"}, (
        f"lineage_status fuera del vocabulario: {valores}"
    )


def test_seccion_usa_el_vocabulario_normalizado(con):
    valores = {
        r[0] for r in con.execute(
            "SELECT DISTINCT seccion FROM raw_eeff_line WHERE seccion IS NOT NULL"
        )
    }
    assert valores <= {"ESF", "ER", "EFE", "ECP", "NOTA", "OTRO", "METRICA_SERIE"}, (
        f"seccion fuera del vocabulario normalizado: {valores}"
    )


def test_metricas_de_serie_fuera_del_perimetro_contable(con):
    """Las filas `Serie X - ...` son métricas por serie, no cuentas: ya viven en
    `raw_valor_cuota_*` y `raw_cuota_en_circulacion`. Sumarlas como partidas
    contables sería doble conteo."""
    contables = con.execute(
        "SELECT COUNT(*) FROM raw_eeff_line "
        "WHERE seccion = 'METRICA_SERIE' AND cuenta_codigo_canonical IS NOT NULL"
    ).fetchone()[0]
    assert contables == 0, (
        f"{contables} métricas de serie tienen código de cuenta contable"
    )


def test_sin_metricas_de_serie_sin_clasificar(con):
    """Toda fila con nombre de métrica de serie debe estar marcada, para que no
    reaparezca en el trabajo de mapeo canónico ni en deduplicaciones."""
    sin_marcar = con.execute(
        "SELECT COUNT(*) FROM raw_eeff_line "
        "WHERE cuenta_nombre LIKE 'Serie %' AND cuenta_nombre LIKE '%-%' "
        "  AND cuenta_codigo_canonical IS NULL AND seccion IS NOT 'METRICA_SERIE'"
    ).fetchone()[0]
    assert sin_marcar == 0, f"{sin_marcar} métricas de serie sin clasificar"


# ── Validación humana (eje independiente del linaje) ─────────────────────────

def test_validacion_humana_esta_completa(con):
    """Si una fila se marcó como validada, debe constar quién y contra qué: una
    validación sin evidencia no es trazable (P3)."""
    incompletas = con.execute(
        "SELECT COUNT(*) FROM raw_eeff_line "
        "WHERE (validado_por IS NOT NULL OR validado_at IS NOT NULL "
        "       OR validacion_fuente IS NOT NULL) "
        "  AND (validado_por IS NULL OR validado_at IS NULL OR validacion_fuente IS NULL)"
    ).fetchone()[0]
    assert incompletas == 0, f"{incompletas} filas con validación incompleta"


def test_apo_2020_12_total_activo_cuadra(con):
    """Cifra confirmada por el usuario contra los EEFF (2026-07-24). La fila
    proviene de una carga manual sin archivo en el repositorio, así que se
    verifica su coherencia interna."""
    fila = con.execute(
        "SELECT monto_clp, validado_por FROM raw_eeff_line "
        "WHERE fondo_key='Apo' AND periodo='2020-12' "
        "  AND cuenta_codigo_canonical='ESF.total_activo' AND superseded_at IS NULL"
    ).fetchall()
    assert len(fila) == 1, "debe quedar exactamente una fila vigente de total_activo"
    assert fila[0]["monto_clp"] == 42_343_358_000
    assert fila[0]["validado_por"] == "usuario"

    partes = dict(con.execute(
        "SELECT cuenta_codigo_canonical, monto_clp FROM raw_eeff_line "
        "WHERE fondo_key='Apo' AND periodo='2020-12' AND superseded_at IS NULL "
        "  AND cuenta_codigo_canonical IN "
        "      ('ESF.total_activo_corriente','ESF.total_activo_no_corriente')"
    ).fetchall())
    assert len(partes) == 2, "cada subtotal debe quedar con una sola fila vigente"
    assert sum(partes.values()) == fila[0]["monto_clp"]
