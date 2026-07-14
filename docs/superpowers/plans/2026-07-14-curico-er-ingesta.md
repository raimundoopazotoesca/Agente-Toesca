# Ingesta ER Mall Curicó Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingestar `RAW/NOI Curico.xlsx` (SharePoint) → `raw_er_activo_line` para `activo_key='Mall Curicó'`, siguiendo el mismo patrón que `ingest_er_vina.py` (código de cuenta por regex, NOI recalculado desde cuentas crudas), adaptado a las diferencias estructurales de esta planilla.

**Architecture:** Módulo `tools/db/ingest_er_curico.py` con parser por headers de sección en columna C (sin ancla de texto inicial — arranca en `INGRESOS_OPERACION` por defecto justo después de la fila de fechas, corta en la **primera** ocurrencia de "Total Operacional"), persistencia idempotente por `file_hash` reutilizando `repo_er_activo.py`/`repo_audit.py` sin cambios, validación de integridad estricta para Ingreso Explotación y blanda para Gastos de Administración y Ventas (la fuente subestima este subtotal por 3 cuentas huérfanas fuera de sus fórmulas de categoría).

**Tech Stack:** Python 3.12, `openpyxl` (lectura xlsx), `sqlite3`, `pytest`. Reutiliza `tools/db/repo_er_activo.py`, `tools/db/repo_audit.py` y `tools/db/repo_fact.py` (UF fin de mes) tal cual, sin modificarlos.

## Global Constraints

- `activo_key='Mall Curicó'` fijo (ya existe en `dim_activo`, coincide con filas previas en `raw_er_activo_line` de una ingesta antigua vía `noi_tools.actualizar_er_curico` que quedarán `superseded`).
- Código de cuenta extraído por regex `^(\d(?:-\d{1,3}){3})\s+(.+)$` sobre columna C (2, índice 0), igual que `ingest_er_vina.py` — no diccionario fijo de categorías.
- Secciones: `INGRESOS_OPERACION` (es_operacional=1, **sin header de texto** — es la sección por defecto desde el inicio del recorrido), `INGRESO_FUERA_EXPLOTACION` (es_operacional=0, header `"Ingreso Fuera De Explotacion"`), `GASTOS_OPERACION` (es_operacional=1, header `"Gastos de administración y ventas"`).
- El recorrido corta en la **primera** ocurrencia de `"Total Operacional"` (a diferencia de Viña, que usa la última — acá la Sección 1 de datos reales está arriba y el espejo en UF está abajo, orden inverso).
- Sección `"Resultado No Operacional"` **no se ingesta** — no la usa el NOI de referencia (fila 133 de la fuente).
- `monto_clp` = pesos crudos de la fuente, con signo ya aplicado. `monto_uf = monto_clp / UF de fin de mes` vía `fact_uf` de la DB — no la UF de la fila 3 de la propia planilla (mismo criterio que Viña).
- NOI derivado: `SUM(monto_uf) WHERE es_operacional=1` — se recalcula desde las cuentas hoja, **incluye 3 cuentas huérfanas** (`3-1-10-115`, `3-1-10-116`, `3-1-10-117`) que la fuente excluye de sus fórmulas de subtotal de categoría (confirmado por el usuario 2026-07-14). No se persiste como columna.
- Validación de integridad Ingreso Explotación: **estricta**, `abs(suma_cuentas - "Total Resultado Operación") < 2000 CLP`.
- Validación de integridad Gastos Admin y Ventas: **blanda**, `abs(suma_cuentas) >= abs("Total Gastos de administración y ventas") - 2000 CLP` — la suma calculada nunca puede ser menor en magnitud al subtotal de la fuente (que subestima por el gap de cuentas huérfanas), pero si cae por debajo indica un bug real de parseo.
- Si cualquier validación falla fuera de estos criterios, el ingest falla explícito (periodo + delta) y no persiste nada de esa corrida (todo o nada).
- Idempotencia por `file_hash` (sha256): mismo hash → skip; hash distinto con filas activas previas del mismo `activo_key` → supersede + reinsert.
- `periodo` en formato `'YYYY-MM'`.
- Reference spec: `docs/superpowers/specs/2026-07-14-curico-er-ingesta-design.md`.
- Estructura real verificada del archivo (`RAW/NOI Curico.xlsx`, hoja `Hoja1`, `A1:AK242`): fila 4 = header de fechas (col D..AK, 2023-08 a 2026-05, 34 meses); columna C = datos reales (columna B es residuo de plantilla vieja desalineada, se ignora); 44 cuentas hoja distintas (11 Ingreso Explotación, 29 Gastos Admin y Ventas, 4 Ingreso Fuera de Explotación) × 34 periodos = 1496 filas totales; NOI recalculado en UF: 2023-08 ≈ 454.45, 2026-05 ≈ 1005.47.

---

## File Structure

- Create: `tools/db/ingest_er_curico.py` — parser + persistencia + CLI.
- Create: `tests/db/test_ingest_er_curico.py` — tests de parser, validación de integridad y persistencia.
- No se modifica `tools/db/repo_er_activo.py`, `tools/db/repo_audit.py` ni `tools/db/repo_fact.py` (se reutilizan tal cual).

---

## Task 1: Parser de la planilla Curicó (headers de sección + regex de cuenta)

**Files:**
- Create: `tools/db/ingest_er_curico.py`
- Test: `tests/db/test_ingest_er_curico.py`

**Interfaces:**
- Produces: `parse_planilla(xlsx_path: str, conn: "sqlite3.Connection | None" = None) -> list[dict]` — cada dict con claves `activo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf, seccion, es_operacional, source_file, source_sheet, source_row` (mismo shape que `ingest_er_vina.parse_planilla`, consumido por `repo_er_activo.insert_lines` en Task 2).
- Produces: `_file_hash(path: str) -> str` (sha256 hex).
- Produces: `persist(xlsx_path: str, conn: "sqlite3.Connection | None" = None) -> dict` con `{"status": "inserted"|"skipped_idempotent"|"superseded_and_reinserted", "rows": int, "file_hash": str, "ingest_run_id": int|None}`.
- Produces: excepción `ValueError` con mensaje explícito si (a) no se encuentra la fila de fechas, (b) no se encuentra la fila `"Total Operacional"` (terminador), o (c) alguna validación de integridad falla.

- [ ] **Step 1: Escribir el fixture xlsx de test (constructor helper) y los tests de parsing**

```python
# tests/db/test_ingest_er_curico.py
"""Tests para tools.db.ingest_er_curico."""
from __future__ import annotations

import datetime
import os
import sqlite3

import openpyxl
import pytest

from tools.db import ingest_er_curico as mod


# ── Fixture xlsx replicando la estructura real de RAW/NOI Curico.xlsx ──────
# Fila 4: fechas en columnas D, E (2 periodos reales).
# Columna C = label/código de cuenta a partir de la fila 6 (justo después de
# la fila de fechas, SIN header de texto "Ingreso de Explotacion" — a
# diferencia de Viña, acá la sección INGRESOS_OPERACION es la de arranque
# por defecto).
#
# Estructura del fixture (filas):
#   4  fechas
#   6  leaf ingreso 1 (INGRESOS_OPERACION, sin header previo)
#   7  leaf ingreso 2
#   9  "Total Resultado Operación" (subtotal, cuadra exacto)
#  11  "Ingreso Fuera De Explotacion" (header)
#  12  leaf fuera de explotación
#  13  "Total Ingreso Fuera De Explotación"
#  15  "Gastos de administración y ventas" (header)
#  16  "MANTENCIÓN" (subcategoría, sin código -> se salta)
#  17  leaf gasto 1
#  18  leaf gasto huérfano (3-1-10-115, con valor real pero el subtotal de
#      la fila 19 NO lo incluye, replicando el bug real de la fuente)
#  19  "Total Gastos de administración y ventas" (= solo leaf gasto 1,
#      subestimado a propósito, igual que en el archivo real)
#  20  "Total Operacional" (terminador — PRIMERA ocurrencia)
#  25  "Ingreso Fuera De Explotacion" (repetida, simula la Sección 2 de
#      espejo en UF que está más abajo en el archivo real)
#  26  leaf fantasma (NO debe capturarse — está después del terminador)
#  27  "Total Operacional" (segunda ocurrencia, tampoco debe alcanzarse)

_DATA_COL_1 = 4  # D
_DATA_COL_2 = 5  # E
_PERIODOS = ["2025-01", "2025-02"]
_FECHAS = {_DATA_COL_1: datetime.datetime(2025, 1, 31), _DATA_COL_2: datetime.datetime(2025, 2, 28)}
_UF = {"2025-01-31": 37000.0, "2025-02-28": 37200.0}

_ING_1 = {_DATA_COL_1: 42_000_000.0, _DATA_COL_2: 43_000_000.0}
_ING_2 = {_DATA_COL_1: 10_000_000.0, _DATA_COL_2: 10_500_000.0}
_FUERA = {_DATA_COL_1: 1_000_000.0, _DATA_COL_2: 1_100_000.0}
_GASTO_1 = {_DATA_COL_1: -15_000_000.0, _DATA_COL_2: -16_000_000.0}
_GASTO_HUERFANO = {_DATA_COL_1: -2_000_000.0, _DATA_COL_2: -2_200_000.0}

_TOTAL_RESULTADO_OPERACION = {c: _ING_1[c] + _ING_2[c] for c in (_DATA_COL_1, _DATA_COL_2)}
_TOTAL_FUERA = dict(_FUERA)
# Subestimado a propósito: NO incluye _GASTO_HUERFANO (replica el bug real).
_TOTAL_GASTOS_ADMIN = dict(_GASTO_1)


def _build_fixture_xlsx(tmp_path,
                         corrupt_ingreso_explotacion=False,
                         corrupt_gastos_admin_por_debajo=False) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hoja1"

    for col, fecha in _FECHAS.items():
        ws.cell(row=4, column=col).value = fecha

    ws.cell(row=6, column=3).value = "4-1-01-100  ARRIENDO TIENDAS ANCLAS"
    for col, v in _ING_1.items():
        ws.cell(row=6, column=col).value = v
    ws.cell(row=7, column=3).value = "4-1-01-101  ARRIENDO TIENDAS MENORES"
    for col, v in _ING_2.items():
        ws.cell(row=7, column=col).value = v

    ws.cell(row=9, column=3).value = "Total Resultado Operación"
    tro_vals = dict(_TOTAL_RESULTADO_OPERACION)
    if corrupt_ingreso_explotacion:
        tro_vals = {c: v + 999_999 for c, v in tro_vals.items()}
    for col, v in tro_vals.items():
        ws.cell(row=9, column=col).value = v

    ws.cell(row=11, column=3).value = "Ingreso Fuera De Explotacion"
    ws.cell(row=12, column=3).value = "4-2-01-002  OTROS INGRESOS"
    for col, v in _FUERA.items():
        ws.cell(row=12, column=col).value = v
    ws.cell(row=13, column=3).value = "Total Ingreso Fuera De Explotación"
    for col, v in _TOTAL_FUERA.items():
        ws.cell(row=13, column=col).value = v

    ws.cell(row=15, column=3).value = "Gastos de administración y ventas"
    ws.cell(row=16, column=3).value = "MANTENCIÓN"  # subcategoría, sin código
    ws.cell(row=17, column=3).value = "3-1-10-102  FEE ADMINISTRATIVO (REMUNERACIONES)"
    for col, v in _GASTO_1.items():
        ws.cell(row=17, column=col).value = v
    ws.cell(row=18, column=3).value = "3-1-10-115  MANTENCION COBRO DIRECTO"
    for col, v in _GASTO_HUERFANO.items():
        ws.cell(row=18, column=col).value = v

    ws.cell(row=19, column=3).value = "Total Gastos de administración y ventas"
    tga_vals = dict(_TOTAL_GASTOS_ADMIN)
    if corrupt_gastos_admin_por_debajo:
        # La suma calculada por el parser (gasto1 + huérfano) queda por
        # debajo del subtotal "corregido" a propósito -> debe fallar.
        tga_vals = {c: v - 10_000_000.0 for c, v in _GASTO_1.items()}
        tga_vals = {c: v + abs(_GASTO_HUERFANO[c]) + 10_000_000.0 for c, v in tga_vals.items()}
    for col, v in tga_vals.items():
        ws.cell(row=19, column=col).value = v

    ws.cell(row=20, column=3).value = "Total Operacional"

    # Sección 2 (espejo, más abajo) — nunca debe procesarse.
    ws.cell(row=25, column=3).value = "Ingreso Fuera De Explotacion"
    ws.cell(row=26, column=3).value = "9-9-99-999  CUENTA FANTASMA SECCION 2"
    for col in (_DATA_COL_1, _DATA_COL_2):
        ws.cell(row=26, column=col).value = 999_999_999.0
    ws.cell(row=27, column=3).value = "Total Operacional"

    os.makedirs(tmp_path, exist_ok=True)
    path = os.path.join(tmp_path, "curico_fixture.xlsx")
    wb.save(path)
    return path


@pytest.fixture
def conn(tmp_path):
    """DB en disco (tmp) con schema mínimo necesario (mismo patrón que
    tests/db/test_ingest_er_vina.py)."""
    db_path = os.path.join(str(tmp_path), "test.db")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE ingest_run (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool TEXT, source_file TEXT, file_hash TEXT,
            rows_in INTEGER, rows_loaded INTEGER,
            started_at TEXT, ended_at TEXT, status TEXT, error TEXT
        );
        CREATE TABLE dim_activo (
            activo_key TEXT PRIMARY KEY, fondo_key TEXT, nombre TEXT,
            tipo TEXT, participacion_fondo_activo REAL, categoria TEXT, sociedad TEXT
        );
        INSERT INTO dim_activo (activo_key, fondo_key, nombre, participacion_fondo_activo)
             VALUES ('Mall Curicó','TRI','Mall Curicó',1.0);
        CREATE TABLE raw_er_activo_line (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activo_key TEXT NOT NULL REFERENCES dim_activo(activo_key),
            periodo TEXT NOT NULL,
            cuenta_codigo TEXT, cuenta_nombre TEXT,
            monto_clp REAL, monto_uf REAL,
            seccion TEXT, es_operacional INTEGER,
            source_file TEXT, source_sheet TEXT, source_row INTEGER,
            file_hash TEXT, ingest_run_id INTEGER REFERENCES ingest_run(id),
            loaded_at TEXT DEFAULT (datetime('now')),
            superseded_at TEXT
        );
        CREATE TABLE raw_uf_diaria (
            fecha TEXT PRIMARY KEY, valor REAL, fuente TEXT,
            loaded_at TEXT DEFAULT (datetime('now'))
        );
        CREATE VIEW fact_uf AS SELECT fecha, valor FROM raw_uf_diaria ORDER BY fecha;
    """)
    for fecha, valor in _UF.items():
        c.execute(
            "INSERT INTO raw_uf_diaria (fecha, valor, fuente) VALUES (?, ?, 'test')",
            (fecha, valor),
        )
    c.commit()
    yield c
    c.close()


@pytest.fixture
def fixture_xlsx(tmp_path):
    return _build_fixture_xlsx(str(tmp_path))


# ── Tests de parsing ─────────────────────────────────────────────────────

def test_parse_devuelve_5_cuentas_x_2_periodos(fixture_xlsx, conn):
    # 2 ingreso explotación + 1 fuera explotación + 2 gastos (incl. huérfana) = 5 cuentas x 2 periodos.
    rows = mod.parse_planilla(fixture_xlsx, conn=conn)
    assert len(rows) == 10


def test_parse_activo_key_fijo_curico(fixture_xlsx, conn):
    rows = mod.parse_planilla(fixture_xlsx, conn=conn)
    assert all(r["activo_key"] == "Mall Curicó" for r in rows)


def test_parse_periodos_yyyy_mm(fixture_xlsx, conn):
    rows = mod.parse_planilla(fixture_xlsx, conn=conn)
    assert {r["periodo"] for r in rows} == set(_PERIODOS)


def test_parse_codigos_de_cuenta_extraidos_por_regex(fixture_xlsx, conn):
    rows = mod.parse_planilla(fixture_xlsx, conn=conn)
    codigos = {r["cuenta_codigo"] for r in rows}
    assert codigos == {"4-1-01-100", "4-1-01-101", "4-2-01-002", "3-1-10-102", "3-1-10-115"}


def test_parse_ingresos_operacion_sin_header_explicito(fixture_xlsx, conn):
    rows = mod.parse_planilla(fixture_xlsx, conn=conn)
    by_codigo = {r["cuenta_codigo"]: r for r in rows if r["periodo"] == "2025-01"}
    assert by_codigo["4-1-01-100"]["seccion"] == "INGRESOS_OPERACION"
    assert by_codigo["4-1-01-100"]["es_operacional"] == 1


def test_parse_seccion_y_es_operacional(fixture_xlsx, conn):
    rows = mod.parse_planilla(fixture_xlsx, conn=conn)
    by_codigo = {r["cuenta_codigo"]: r for r in rows if r["periodo"] == "2025-01"}
    assert by_codigo["4-2-01-002"]["seccion"] == "INGRESO_FUERA_EXPLOTACION"
    assert by_codigo["4-2-01-002"]["es_operacional"] == 0
    assert by_codigo["3-1-10-102"]["seccion"] == "GASTOS_OPERACION"
    assert by_codigo["3-1-10-102"]["es_operacional"] == 1


def test_parse_monto_uf_usa_fact_uf(fixture_xlsx, conn):
    rows = mod.parse_planilla(fixture_xlsx, conn=conn)
    r = next(r for r in rows if r["cuenta_codigo"] == "4-1-01-100" and r["periodo"] == "2025-01")
    assert r["monto_clp"] == _ING_1[_DATA_COL_1]
    assert abs(r["monto_uf"] - _ING_1[_DATA_COL_1] / _UF["2025-01-31"]) < 1e-6


def test_parse_noi_incluye_cuenta_huerfana(fixture_xlsx, conn):
    """La cuenta 3-1-10-115 (huérfana, excluida del subtotal de la fuente)
    debe seguir sumando al NOI recalculado."""
    rows = mod.parse_planilla(fixture_xlsx, conn=conn)
    codigos_gastos = {r["cuenta_codigo"] for r in rows if r["seccion"] == "GASTOS_OPERACION"}
    assert "3-1-10-115" in codigos_gastos
    noi_2025_01 = sum(r["monto_uf"] for r in rows if r["periodo"] == "2025-01" and r["es_operacional"] == 1)
    esperado = (_ING_1[_DATA_COL_1] + _ING_2[_DATA_COL_1] + _GASTO_1[_DATA_COL_1] + _GASTO_HUERFANO[_DATA_COL_1]) / _UF["2025-01-31"]
    assert abs(noi_2025_01 - esperado) < 1e-6


def test_parse_noi_excluye_ingreso_fuera_de_explotacion(fixture_xlsx, conn):
    rows = mod.parse_planilla(fixture_xlsx, conn=conn)
    noi_2025_01 = sum(r["monto_uf"] for r in rows if r["periodo"] == "2025-01" and r["es_operacional"] == 1)
    esperado = (_ING_1[_DATA_COL_1] + _ING_2[_DATA_COL_1] + _GASTO_1[_DATA_COL_1] + _GASTO_HUERFANO[_DATA_COL_1]) / _UF["2025-01-31"]
    assert abs(noi_2025_01 - esperado) < 1e-6
    assert abs(noi_2025_01 - (esperado + _FUERA[_DATA_COL_1] / _UF["2025-01-31"])) > 1e-6


def test_parse_corta_en_primera_ocurrencia_de_total_operacional(fixture_xlsx, conn):
    rows = mod.parse_planilla(fixture_xlsx, conn=conn)
    codigos = {r["cuenta_codigo"] for r in rows}
    assert "9-9-99-999" not in codigos
    assert len({r["seccion"] for r in rows if r["cuenta_codigo"] == "4-2-01-002"}) == 1


def test_parse_valida_integridad_ingreso_explotacion_ok(fixture_xlsx, conn):
    # No debe lanzar: el fixture cuadra por construcción.
    mod.parse_planilla(fixture_xlsx, conn=conn)


def test_parse_falla_si_ingreso_explotacion_no_cuadra(tmp_path, conn):
    path = _build_fixture_xlsx(str(tmp_path), corrupt_ingreso_explotacion=True)
    with pytest.raises(ValueError, match="Validación de integridad"):
        mod.parse_planilla(path, conn=conn)


def test_parse_gastos_admin_permite_gap_de_huerfana_sin_fallar(fixture_xlsx, conn):
    # El fixture ya tiene el subtotal de fuente subestimado (no incluye la
    # huérfana) — la validación blanda debe pasar igual, no lanzar.
    mod.parse_planilla(fixture_xlsx, conn=conn)


def test_parse_falla_si_gastos_admin_cae_por_debajo_del_subtotal_fuente(tmp_path, conn):
    path = _build_fixture_xlsx(str(tmp_path), corrupt_gastos_admin_por_debajo=True)
    with pytest.raises(ValueError, match="Validación de integridad"):
        mod.parse_planilla(path, conn=conn)


# ── Tests de persistencia (idempotencia) ────────────────────────────────

def test_persist_inserta_filas(fixture_xlsx, conn):
    res = mod.persist(fixture_xlsx, conn=conn)
    assert res["status"] == "inserted"
    assert res["rows"] == 10


def test_persist_es_idempotente(fixture_xlsx, conn):
    mod.persist(fixture_xlsx, conn=conn)
    res2 = mod.persist(fixture_xlsx, conn=conn)
    assert res2["status"] == "skipped_idempotent"
    assert res2["rows"] == 0


def test_persist_supersede_en_reingesta_con_cambios(tmp_path, conn):
    path1 = _build_fixture_xlsx(str(tmp_path) + "_1")
    res1 = mod.persist(path1, conn=conn)
    assert res1["status"] == "inserted"

    wb = openpyxl.load_workbook(path1)
    ws = wb["Hoja1"]
    ws.cell(row=6, column=_DATA_COL_1).value = 50_000_000.0
    ws.cell(row=9, column=_DATA_COL_1).value = 50_000_000.0 + _ING_2[_DATA_COL_1]
    path2 = os.path.join(str(tmp_path), "curico_fixture_v2.xlsx")
    os.makedirs(str(tmp_path), exist_ok=True)
    wb.save(path2)

    res2 = mod.persist(path2, conn=conn)
    assert res2["status"] == "superseded_and_reinserted"

    activos = conn.execute(
        "SELECT COUNT(*) FROM raw_er_activo_line WHERE activo_key='Mall Curicó' AND superseded_at IS NULL"
    ).fetchone()[0]
    assert activos == 10
```

- [ ] **Step 2: Correr los tests para verificar que fallan (módulo no existe todavía)**

Run: `python -m pytest tests/db/test_ingest_er_curico.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'tools.db.ingest_er_curico'`.

- [ ] **Step 3: Implementar el módulo**

```python
# tools/db/ingest_er_curico.py
"""Ingesta ER Mall Curicó (activo, fondo TRI) → raw_er_activo_line.

Lee la planilla xlsx 'RAW/NOI Curico.xlsx' (SharePoint), hoja 'Hoja1', y
persiste cada cuenta contable individual en raw_er_activo_line. Idempotente
por file_hash.

Mismo enfoque que ingest_er_vina.py: el código de cuenta se extrae por
regex de la columna C (no diccionario fijo de categorías), y la sección
(INGRESOS_OPERACION / INGRESO_FUERA_EXPLOTACION / GASTOS_OPERACION) se
determina por los headers de sección que preceden a cada cuenta.

Diferencias clave vs. Viña:
  - No hay header de texto "Ingreso de Explotacion" en columna C (columna B
    tiene un residuo de plantilla vieja desalineada, se ignora). La sección
    INGRESOS_OPERACION es la de arranque por defecto, justo después de la
    fila de fechas.
  - La Sección 1 (datos reales) está ARRIBA del archivo y la Sección 2
    (espejo en UF) está ABAJO — orden inverso a Viña. El recorrido corta en
    la PRIMERA ocurrencia de "Total Operacional", no la última.
  - La sección "Resultado No Operacional" (financiero: leasing, intereses,
    variación UF) no se ingesta — no la usa el NOI de referencia (fila 133
    de la fuente).

monto_clp = pesos reales (fiel a la fuente, con signo aplicado). monto_uf =
monto_clp / UF de fin de mes (fact_uf de la DB, no la UF de la propia
planilla).

NOI (confirmado por el usuario 2026-07-14): SUM(monto_uf) WHERE
es_operacional=1, es decir Ingreso Explotación + Gastos de Administración y
Ventas, SIN Ingreso Fuera de Explotación — misma metodología que la fila
133 "Noi" de la fuente, pero recalculada desde las cuentas crudas: la
fuente tiene 3 cuentas huérfanas (3-1-10-115 Mantención Cobro Directo,
3-1-10-116 Mantención Activo, 3-1-10-117 Servicios Administrativos Activo)
que sus propias fórmulas de subtotal de categoría (MANTENCIÓN, SERVICIOS)
no incluyen — impacto real de hasta 5.7% del gasto en algunos meses. Este
parser las incluye igual, porque recorre todas las cuentas por código
dentro de cada sección sin depender de las fórmulas de la fuente.

Validación de integridad (por periodo, en pesos):
  - Ingreso Explotación: ESTRICTA. SUM(cuentas) == "Total Resultado
    Operación" (tolerancia 2000 CLP) — el rango de la fuente es contiguo,
    sin huecos conocidos.
  - Gastos de Administración y Ventas: BLANDA. abs(SUM(cuentas)) >=
    abs("Total Gastos de administración y ventas") - 2000 CLP — no puede
    ser estricta por el gap de cuentas huérfanas ya documentado, pero la
    suma calculada nunca puede ser MENOR en magnitud al subtotal de la
    fuente sin indicar un bug real de parseo.
"""
from __future__ import annotations

import calendar
import hashlib
import re
import sqlite3
from typing import Optional

import openpyxl


_ACTIVO_KEY = "Mall Curicó"

_ACCOUNT_RE = re.compile(r"^(\d(?:-\d{1,3}){3})\s+(.+)$")

_HEADER_FUERA_EXPLOTACION = re.compile(r"^ingreso fuera de explotacion$", re.I)
_HEADER_GASTOS_OPERACION = re.compile(r"^gastos de administraci.n y ventas$", re.I)
_SUBTOTAL_RESULTADO_OPERACION = re.compile(r"^total resultado operaci.n$", re.I)
_SUBTOTAL_GASTOS_ADMIN = re.compile(r"^total gastos de administraci.n y ventas$", re.I)
_TERMINATOR = re.compile(r"^total operacional$", re.I)

_ES_OPERACIONAL = {
    "INGRESOS_OPERACION": 1,
    "GASTOS_OPERACION": 1,
    "INGRESO_FUERA_EXPLOTACION": 0,
}


def _norm(s) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip())


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _uf_fin_mes(conn: sqlite3.Connection, periodo: str) -> float:
    from tools.db import repo_fact

    year, month = (int(x) for x in periodo.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    fecha = f"{year:04d}-{month:02d}-{last_day:02d}"
    return repo_fact.get_uf(conn, fecha)


def parse_planilla(xlsx_path: str, conn: "sqlite3.Connection | None" = None) -> list[dict]:
    """Lee la planilla ER Mall Curicó y devuelve filas para raw_er_activo_line.

    Requiere conexión a la DB para resolver la UF de fin de mes (fact_uf) por
    periodo, igual que ingest_er_vina.parse_planilla.
    """
    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()

    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        ws = wb.worksheets[0]
        sheet_name = ws.title
        all_rows = list(ws.iter_rows(values_only=False))
        wb.close()

        # 1) Fila de fechas: la fila con MÁS celdas tipo fecha de toda la hoja.
        header_row_idx = None
        period_by_col: dict[int, str] = {}
        best_count = 0
        for i, row in enumerate(all_rows):
            candidatos = {}
            for cell in row:
                v = cell.value
                if hasattr(v, "year") and hasattr(v, "month"):
                    candidatos[cell.column] = f"{v.year:04d}-{v.month:02d}"
            if len(candidatos) > best_count:
                best_count = len(candidatos)
                header_row_idx = i
                period_by_col = candidatos
        if header_row_idx is None or best_count == 0:
            raise ValueError(f"No se encontró fila de fechas en {xlsx_path}")

        # 2) Recorrer filas desde justo después de la fila de fechas. Sin
        #    header de texto para arrancar (a diferencia de Viña): la
        #    sección por defecto es INGRESOS_OPERACION.
        out: list[dict] = []
        current_seccion: str = "INGRESOS_OPERACION"
        suma_ingreso_explotacion: dict[str, float] = {}
        suma_gastos_admin: dict[str, float] = {}
        subtotal_ingreso_explotacion: dict[str, float] = {}
        subtotal_gastos_admin: dict[str, float] = {}
        terminador_encontrado = False

        for i in range(header_row_idx + 1, len(all_rows)):
            row = all_rows[i]
            raw_label = row[2].value if len(row) > 2 else None
            label = _norm(raw_label)
            if not label:
                continue

            if _TERMINATOR.match(label):
                terminador_encontrado = True
                break

            if _HEADER_FUERA_EXPLOTACION.match(label):
                current_seccion = "INGRESO_FUERA_EXPLOTACION"
                continue
            if _HEADER_GASTOS_OPERACION.match(label):
                current_seccion = "GASTOS_OPERACION"
                continue

            if _SUBTOTAL_RESULTADO_OPERACION.match(label):
                for col, periodo in period_by_col.items():
                    cell = row[col - 1] if col - 1 < len(row) else None
                    if cell is not None and cell.value is not None:
                        subtotal_ingreso_explotacion[periodo] = float(cell.value)
                continue

            if _SUBTOTAL_GASTOS_ADMIN.match(label):
                for col, periodo in period_by_col.items():
                    cell = row[col - 1] if col - 1 < len(row) else None
                    if cell is not None and cell.value is not None:
                        subtotal_gastos_admin[periodo] = float(cell.value)
                continue

            m = _ACCOUNT_RE.match(label)
            if not m:
                continue  # header de subcategoría (ej. "SEGURIDAD"), sin código de cuenta

            cuenta_codigo, cuenta_nombre = m.group(1), m.group(2).strip()
            es_operacional = _ES_OPERACIONAL[current_seccion]

            for col, periodo in period_by_col.items():
                cell = row[col - 1] if col - 1 < len(row) else None
                monto_clp = float(cell.value) if cell is not None and cell.value is not None else 0.0
                monto_uf = monto_clp / _uf_fin_mes(conn, periodo)

                if current_seccion == "INGRESOS_OPERACION":
                    suma_ingreso_explotacion[periodo] = suma_ingreso_explotacion.get(periodo, 0.0) + monto_clp
                elif current_seccion == "GASTOS_OPERACION":
                    suma_gastos_admin[periodo] = suma_gastos_admin.get(periodo, 0.0) + monto_clp

                out.append({
                    "activo_key":     _ACTIVO_KEY,
                    "periodo":        periodo,
                    "cuenta_codigo":  cuenta_codigo,
                    "cuenta_nombre":  cuenta_nombre,
                    "monto_clp":      monto_clp,
                    "monto_uf":       monto_uf,
                    "seccion":        current_seccion,
                    "es_operacional": es_operacional,
                    "source_file":    xlsx_path,
                    "source_sheet":   sheet_name,
                    "source_row":     i + 1,
                })

        if not terminador_encontrado:
            raise ValueError(f"No se encontró la fila 'Total Operacional' en {xlsx_path}")

        # 3) Validación de integridad.
        _TOLERANCIA_CLP = 2000.0
        for periodo, esperado in subtotal_ingreso_explotacion.items():
            real = suma_ingreso_explotacion.get(periodo, 0.0)
            if abs(real - esperado) >= _TOLERANCIA_CLP:
                raise ValueError(
                    f"Validación de integridad falló en {xlsx_path}, periodo {periodo}: "
                    f"suma Ingreso Explotación={real!r} != Total Resultado Operación={esperado!r}"
                )
        # Gastos Admin y Ventas: validación blanda (la fuente subestima por
        # 3 cuentas huérfanas fuera de los rangos SUM() de sus categorías,
        # confirmado por el usuario 2026-07-14). La suma calculada nunca
        # puede ser MENOR (en magnitud) al subtotal de la fuente.
        for periodo, esperado in subtotal_gastos_admin.items():
            real = suma_gastos_admin.get(periodo, 0.0)
            if abs(real) < abs(esperado) - _TOLERANCIA_CLP:
                raise ValueError(
                    f"Validación de integridad falló en {xlsx_path}, periodo {periodo}: "
                    f"suma Gastos Admin y Ventas={real!r} es menor (en magnitud) que "
                    f"Total Gastos de administración y ventas={esperado!r} de la fuente "
                    f"(posible cuenta no capturada por el parser)"
                )

        return out
    finally:
        if owns_conn:
            conn.close()


# ── Persistencia ─────────────────────────────────────────────────────────

def persist(xlsx_path: str,
            conn: "sqlite3.Connection | None" = None) -> dict:
    """Ingesta idempotente de la planilla ER Mall Curicó en raw_er_activo_line.

    Comportamiento idéntico a ingest_er_vina.persist:
    - Si ya existen filas activas (superseded_at IS NULL) con el mismo
      file_hash → no hace nada, retorna status 'skipped_idempotent'.
    - Si existen filas activas de una ingesta anterior (activo_key='Mall
      Curicó', otro file_hash) → las marca superseded e inserta las nuevas
      ('superseded_and_reinserted').
    - Si no hay filas previas → inserta directo ('inserted').
    """
    from tools.db import repo_audit, repo_er_activo

    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()

    try:
        file_hash = _file_hash(xlsx_path)

        prev = conn.execute(
            """SELECT 1 FROM raw_er_activo_line
                WHERE file_hash = ? AND superseded_at IS NULL
                LIMIT 1""",
            (file_hash,),
        ).fetchone()
        if prev is not None:
            return {"status": "skipped_idempotent", "rows": 0,
                    "file_hash": file_hash, "ingest_run_id": None}

        lines = parse_planilla(xlsx_path, conn=conn)
        for line in lines:
            line["file_hash"] = file_hash

        prev_hashes = conn.execute(
            """SELECT DISTINCT file_hash FROM raw_er_activo_line
                WHERE activo_key = ?
                  AND file_hash != ?
                  AND superseded_at IS NULL""",
            (_ACTIVO_KEY, file_hash),
        ).fetchall()

        if prev_hashes:
            for row in prev_hashes:
                repo_er_activo.mark_superseded(conn, file_hash=row[0])
            status = "superseded_and_reinserted"
        else:
            status = "inserted"

        run_id = repo_audit.start_ingest_run(
            conn, tool="ingest_er_curico",
            source_file=xlsx_path, file_hash=file_hash,
        )
        inserted = repo_er_activo.insert_lines(conn, lines, run_id)
        repo_audit.finish_ingest_run(
            conn, run_id, rows_in=len(lines), rows_loaded=inserted, status="ok",
        )

        return {"status": status, "rows": inserted,
                "file_hash": file_hash, "ingest_run_id": run_id}
    finally:
        if owns_conn:
            conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xlsx", help="Path a la planilla xlsx")
    ap.add_argument("--dry-run", action="store_true",
                     help="Parsea e imprime resumen, no escribe DB")
    args = ap.parse_args(argv)

    if args.dry_run:
        rows = parse_planilla(args.xlsx)
        print(f"Parsed {len(rows)} filas de {args.xlsx}")
        periodos = sorted({r["periodo"] for r in rows})
        print(f"  periodos: {periodos[0]}..{periodos[-1]} ({len(periodos)} meses)")
        from collections import defaultdict
        noi = defaultdict(float)
        for r in rows:
            if r["es_operacional"]:
                noi[r["periodo"]] += r["monto_uf"]
        print("  NOI (UF) por periodo (primeros y últimos 3):")
        for p in periodos[:3] + periodos[-3:]:
            print(f"    {p}: {noi[p]:>15,.2f}")
        return 0

    res = persist(args.xlsx)
    print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/db/test_ingest_er_curico.py -v`
Expected: todos los tests **PASS** (17 tests: 12 de parsing + 3 de persistencia).

- [ ] **Step 5: Commit**

```bash
git add tools/db/ingest_er_curico.py tests/db/test_ingest_er_curico.py
git commit -m "feat(db): parser ER Mall Curicó (fondo TRI), NOI recalculado incl. cuentas huérfanas"
```

---

## Task 2: Test de integración de solo-lectura contra el archivo real

**Files:**
- Modify: `tests/db/test_ingest_er_curico.py` — agregar test condicional contra el archivo real.

**Interfaces:**
- Consumes: `parse_planilla()` de Task 1.

- [ ] **Step 1: Agregar el test de integración**

Agregar al final de `tests/db/test_ingest_er_curico.py`:

```python
# ── Test de integración de solo-lectura contra el archivo real ──────────
# Se salta automáticamente si el archivo no está disponible en este entorno.

_REAL_XLSX = (
    r"C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos"
    r"\RAW\NOI Curico.xlsx"
)


@pytest.mark.skipif(not os.path.exists(_REAL_XLSX), reason="archivo real no disponible en este entorno")
def test_parse_archivo_real_no_lanza_y_cuadra_integridad(tmp_path):
    """Copia el archivo real a tmp_path (evita locks de OneDrive) y confirma
    que parse_planilla no lanza ValueError sobre el histórico completo
    (34 periodos, 44 cuentas, validación estricta de Ingreso Explotación y
    blanda de Gastos Admin y Ventas)."""
    import shutil
    local_copy = os.path.join(str(tmp_path), "real.xlsx")
    shutil.copy(_REAL_XLSX, local_copy)

    rows = mod.parse_planilla(local_copy)
    assert len(rows) == 1496
    periodos = {r["periodo"] for r in rows}
    assert periodos == {f"2023-{m:02d}" for m in range(8, 13)} | \
                        {f"2024-{m:02d}" for m in range(1, 13)} | \
                        {f"2025-{m:02d}" for m in range(1, 13)} | \
                        {f"2026-{m:02d}" for m in range(1, 6)}
    codigos = {r["cuenta_codigo"] for r in rows}
    assert {"3-1-10-115", "3-1-10-116", "3-1-10-117"} <= codigos
```

- [ ] **Step 2: Correr todos los tests del módulo**

Run: `python -m pytest tests/db/test_ingest_er_curico.py -v`
Expected: todos los tests **PASS** (17 tests de Task 1 + 1 de integración condicional — `SKIPPED` si `_REAL_XLSX` no existe en este entorno, `PASSED` si existe).

- [ ] **Step 3: Correr la suite completa de `tests/db/` para descartar regresiones**

Run: `python -m pytest tests/db/ -q`
Expected: todos los tests previos siguen en verde + los nuevos de este módulo.

- [ ] **Step 4: Commit**

```bash
git add tests/db/test_ingest_er_curico.py
git commit -m "test(db): integracion ER Mall Curico contra archivo real"
```

---

## Task 3: Ingestar el archivo real a la DB de producción

**Files:**
- Modify: `memory/agente_toesca_v2.db` (ingesta real vía `persist()`).

**Interfaces:**
- Consumes: `tools.db.ingest_er_curico.persist(xlsx_path, conn=None)` de Task 1, usando la conexión real vía `tools.db.connection.get_conn()`.

- [ ] **Step 1: Dry-run contra el archivo real para inspección visual**

```bash
python -m tools.db.ingest_er_curico "C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\RAW\NOI Curico.xlsx" --dry-run
```

Expected: imprime `Parsed 1496 filas de ...`, rango `periodos: 2023-08..2026-05 (34 meses)`, y una muestra de NOI por periodo (2023-08 ≈ 454.45 UF, 2026-05 ≈ 1005.47 UF). Si lanza `ValueError` de integridad o de terminador no encontrado, **detenerse** — puede indicar que el archivo cambió desde la inspección inicial de este plan.

- [ ] **Step 2: Ingestar a la DB real**

```bash
python -c "
from tools.db.ingest_er_curico import persist
res = persist(r'C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\RAW\NOI Curico.xlsx')
print(res)
"
```

Expected: `{'status': 'superseded_and_reinserted', 'rows': 1496, 'file_hash': '...', 'ingest_run_id': N}` (hay filas previas de `noi_tools.actualizar_er_curico` para `activo_key='Mall Curicó'` que quedan `superseded`).

- [ ] **Step 3: Sanity queries manuales**

```bash
python -c "
import sqlite3
c = sqlite3.connect('memory/agente_toesca_v2.db')
c.row_factory = sqlite3.Row
print('total filas activas Mall Curicó:', c.execute(\"SELECT COUNT(*) FROM raw_er_activo_line WHERE activo_key='Mall Curicó' AND superseded_at IS NULL\").fetchone()[0])
print('periodos min/max:', c.execute(\"SELECT MIN(periodo), MAX(periodo) FROM raw_er_activo_line WHERE activo_key='Mall Curicó' AND superseded_at IS NULL\").fetchone())
print('NOI UF 2023-08:', c.execute(\"SELECT SUM(monto_uf) FROM raw_er_activo_line WHERE activo_key='Mall Curicó' AND periodo='2023-08' AND es_operacional=1 AND superseded_at IS NULL\").fetchone()[0])
print('NOI UF 2026-05:', c.execute(\"SELECT SUM(monto_uf) FROM raw_er_activo_line WHERE activo_key='Mall Curicó' AND periodo='2026-05' AND es_operacional=1 AND superseded_at IS NULL\").fetchone()[0])
"
```

Expected: `total filas activas Mall Curicó` = 1496; `periodos min/max` = `('2023-08', '2026-05')`; NOI UF 2023-08 ≈ 454.45; NOI UF 2026-05 ≈ 1005.47 (valores validados en la inspección manual del spec).

- [ ] **Step 4: Correr suite completa de tests para confirmar no-regresión**

Run: `python -m pytest tests/ -q`
Expected: todos los tests pasan (incluyendo `test_parse_archivo_real_no_lanza_y_cuadra_integridad`, que ahora corre real en vez de skip).

- [ ] **Step 5: Commit**

```bash
git add memory/agente_toesca_v2.db
git commit -m "data(er-curico): ingesta ER Mall Curicó 2023-08 a 2026-05 (34 meses, 1496 filas)"
```

---

## Task 4: Documentación

**Files:**
- Modify: `wiki/db.md` — agregar sección "Ingesta ER Mall Curicó" (siguiendo el mismo formato que "Ingesta ER Viña Centro").
- Modify: `wiki/activos/mall-curico.md` — actualizar con la fuente canónica nueva (mismo patrón que se hizo con `wiki/activos/vina-centro.md`).
- Modify: `wiki/log.md` — entrada de la ingesta.

- [ ] **Step 1: Actualizar wiki/db.md**

Agregar al final del archivo (después de la sección "Ingesta ER Viña Centro"):

```markdown
## Ingesta ER Mall Curicó (activo, fondo TRI)

Fuente: `RAW/NOI Curico.xlsx` (SharePoint), hoja `Hoja1`. Módulo:
`tools/db/ingest_er_curico.py`. `activo_key='Mall Curicó'`.

Mismo enfoque que Viña Centro (código de cuenta por regex, NOI recalculado
desde cuentas crudas), con dos diferencias: no hay header de texto para
arrancar la sección de Ingreso Explotación (arranca por defecto justo
después de la fila de fechas), y el recorrido corta en la **primera**
ocurrencia de "Total Operacional" (la Sección 1 de datos reales está arriba
del archivo, el espejo en UF está abajo — orden inverso a Viña).

**Cuentas huérfanas**: 3 cuentas (`3-1-10-115` Mantención Cobro Directo,
`3-1-10-116` Mantención Activo, `3-1-10-117` Servicios Administrativos
Activo) están físicamente en el bloque de Gastos de Administración y
Ventas, pero las fórmulas `SUM()` de sus subcategorías (MANTENCIÓN,
SERVICIOS) no las incluyen — quedan fuera del NOI oficial de fila 133 de la
fuente. Impacto real hasta 5.7% del gasto en algunos meses. **Confirmado
por el usuario 2026-07-14**: el NOI en la DB las incluye (recalculado desde
las cuentas crudas, no reusa la fórmula de la fuente) — validación de
integridad de Gastos Admin y Ventas es blanda por este motivo (no puede
exigir igualdad exacta contra el subtotal de la fuente).

Sección "Resultado No Operacional" (financiero: leasing, intereses,
variación UF) no se ingesta — no la usa el NOI de referencia.

Rango histórico ingestado: 2023-08 a 2026-05 (34 meses, 1496 filas).

**Nota — reemplaza la ingesta anterior de `actualizar_er_curico`**: existía
una ingesta previa a `raw_er_activo_line` vía `noi_tools.actualizar_er_curico`
(dual-write desde el ER Curicó embebido en el CDG mensual). El `persist()`
de `ingest_er_curico` marcó esas filas como `superseded` al correr por
primera vez (mismo `activo_key`, distinto `file_hash`). **Pendiente**: si
`actualizar_er_curico` se sigue llamando en el flujo mensual del CDG, va a
volver a insertar filas y re-supersede la data limpia de este parser —
mismo pendiente que quedó abierto para Viña.
```

- [ ] **Step 2: Actualizar wiki/activos/mall-curico.md**

Agregar después de la sección "Datos básicos" (antes de "Fuente de datos"):

```markdown
## Fuente canónica en la DB (desde 2026-07-14)

`raw_er_activo_line`, `activo_key='Mall Curicó'`, vía `tools/db/ingest_er_curico.py`.
Fuente: `RAW/NOI Curico.xlsx` (SharePoint), no el CDG. Detalle completo del
diseño, la definición de NOI (incluye 3 cuentas huérfanas de la fuente) y la
validación de integridad en `wiki/db.md` → sección "Ingesta ER Mall Curicó".

**Nota**: existía una ingesta previa vía `actualizar_er_curico` (dual-write
desde el ER embebido en el CDG) que quedó `superseded`.
```

- [ ] **Step 3: Actualizar wiki/log.md**

Agregar al final:

```markdown
## [2026-07-14] ingesta | ER Mall Curicó (fondo TRI) — 2023-08 a 2026-05

Segundo activo de Tres Asociados consolidado en `raw_er_activo_line`
(después de Viña Centro), mismo enfoque de código de cuenta por regex y NOI
recalculado desde cuentas crudas. `activo_key='Mall Curicó'`, 1496 filas
(34 periodos × 44 cuentas). Diferencia clave encontrada: 3 cuentas
huérfanas en Gastos de Administración y Ventas que la fuente excluye de sus
propios subtotales de categoría (hasta 5.7% del gasto en algunos meses) —
confirmado con el usuario que el NOI en la DB las incluye, con validación
de integridad blanda para ese bloque.
```

- [ ] **Step 4: Commit y push**

```bash
git add wiki/db.md wiki/activos/mall-curico.md wiki/log.md
git commit -m "wiki: documenta ingesta ER Mall Curicó"
git push
```

---

## Self-Review

**Spec coverage:**
- Parser por headers de sección + regex de cuenta, sin ancla de texto inicial → Task 1 ✓
- Terminador en primera ocurrencia de "Total Operacional" → Task 1 (parser + test `test_parse_corta_en_primera_ocurrencia_de_total_operacional`) ✓
- Exclusión de "Resultado No Operacional" → Task 1 (el parser corta antes de llegar a esa sección) ✓
- NOI recalculado incluyendo cuentas huérfanas → Task 1 (`test_parse_noi_incluye_cuenta_huerfana`) ✓
- Validación estricta Ingreso Explotación / blanda Gastos Admin y Ventas → Task 1 (`test_parse_falla_si_ingreso_explotacion_no_cuadra`, `test_parse_gastos_admin_permite_gap_de_huerfana_sin_fallar`, `test_parse_falla_si_gastos_admin_cae_por_debajo_del_subtotal_fuente`) ✓
- Idempotencia y supersede → Task 1 (tests de persistencia) ✓
- Test de integración contra archivo real → Task 2 ✓
- Ingesta real + sanity checks → Task 3 ✓
- Documentación (wiki/db.md, wiki/activos/mall-curico.md, wiki/log.md) → Task 4 ✓

**Placeholder scan:** sin TBD/TODO, todo el código de cada step está completo (no hay "similar a Task N" ni fragmentos parciales).

**Type consistency:** `parse_planilla(xlsx_path, conn=None) -> list[dict]` y `persist(xlsx_path, conn=None) -> dict` usados consistentemente en Task 1/2/3; shape de dict (`activo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf, seccion, es_operacional, source_file, source_sheet, source_row`) igual en el parser y en los tests que lo consumen.
