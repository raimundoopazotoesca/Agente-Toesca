# Ingesta ER INMOSA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingestar `RAW/NOI INMOSA.xlsx` (SharePoint) → `raw_er_activo_line` para `activo_key='INMOSA'`, siguiendo el mismo patrón idempotente de `ingest_er_apoquindo.py`/`ingest_er_pt.py`, con validación de integridad contra la fila "NOI Mensual" de la fuente.

**Architecture:** Módulo `tools/db/ingest_er_inmosa.py` con parser ancla+offset (fila "INMOSA" como ancla, 9 filas de categorías fijas debajo, fila de header de fechas 2 filas arriba de la ancla), persistencia idempotente por `file_hash` reutilizando `repo_er_activo.py`/`repo_audit.py` sin cambios, validación obligatoria suma-de-componentes==NOI antes de persistir.

**Tech Stack:** Python 3.12, `openpyxl` (lectura xlsx), `sqlite3`, `pytest`. Reutiliza `tools/db/repo_er_activo.py` y `tools/db/repo_audit.py` tal cual (sin modificarlos).

## Global Constraints

- `activo_key='INMOSA'` fijo — no hay desglose por residencia individual.
- Montos ya vienen en UF con signo aplicado en la fuente — se guardan literal en `monto_clp` (misma convención que PT/Apo, sin re-firmar).
- Todas las categorías tienen `es_operacional=1` — NOI se deriva como `SUM(monto_clp)`, nunca se persiste.
- La fila "Ingresos por Arriendos" está duplicada en la fuente (subtotal visual) — solo la primera ocurrencia se persiste.
- Validación de integridad **obligatoria y bloqueante**: si `SUM(7 categorías) != NOI Mensual` (tolerancia `abs(delta) < 0.01`) para cualquier periodo, el ingest completo falla (todo o nada) — no se persiste ningún periodo de esa corrida.
- Idempotencia por `file_hash` (sha256), igual patrón que `ingest_er_apoquindo.py`: mismo hash → skip; hash distinto con filas activas previas del mismo `activo_key` → supersede + reinsert.
- Categoría con nombre no reconocido (typo/variante nueva no mapeada) → fallar explícitamente, nunca ignorar en silencio.
- `periodo` en formato `'YYYY-MM'` (truncar fecha de fin de mes).
- Reference spec: `docs/superpowers/specs/2026-07-14-inmosa-er-ingesta-design.md`.
- Estructura real verificada del archivo (`RAW/NOI INMOSA.xlsx`, hoja `Hoja1`): fila 3 = header de fechas (col B..CV, 2018-01 a 2026-03, 99 meses); fila 5 = ancla `"INMOSA"`; filas 6-14 = 9 filas de categoría (fila 7 duplicada de fila 6); fila 15 = `"NOI Mensual"` (control, no se persiste). Labels exactos con mojibake real: `"(-) Administraci�n"`, `"(-) Provision Reparaciones "` (espacio final), `"(-) Aseo, Mantenci�n y Otros"`.

---

## File Structure

- Create: `tools/db/ingest_er_inmosa.py` — parser + persistencia + CLI.
- Create: `tests/db/test_ingest_er_inmosa.py` — tests de parser, validación de integridad y persistencia.
- No se modifica `tools/db/repo_er_activo.py` ni `tools/db/repo_audit.py` (se reutilizan tal cual).

---

## Task 1: Parser de la planilla INMOSA (ancla + offsets fijos)

**Files:**
- Create: `tools/db/ingest_er_inmosa.py`
- Test: `tests/db/test_ingest_er_inmosa.py`

**Interfaces:**
- Produces: `parse_planilla(xlsx_path: str) -> list[dict]` — cada dict con claves `activo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf, seccion, es_operacional, source_file, source_sheet, source_row` (mismo shape que `ingest_er_apoquindo.parse_planilla`, consumido por `repo_er_activo.insert_lines` en Task 2).
- Produces: `_file_hash(path: str) -> str` (sha256 hex, idéntico patrón a `ingest_er_apoquindo._file_hash`).
- Produces: excepción `ValueError` con mensaje explícito si (a) no se encuentra la fila ancla `"INMOSA"`, (b) una fila de categoría no matchea el diccionario conocido, o (c) la validación de integridad falla para algún periodo.

- [ ] **Step 1: Escribir el fixture xlsx de test (constructor helper)**

```python
# tests/db/test_ingest_er_inmosa.py
"""Tests para tools.db.ingest_er_inmosa."""
from __future__ import annotations

import os
import sqlite3

import openpyxl
import pytest

from tools.db import ingest_er_inmosa as mod


# ── Fixture xlsx replicando la estructura real de RAW/NOI INMOSA.xlsx ──────
# Fila 3: header de fechas. Fila 4: vacía. Fila 5: ancla "INMOSA".
# Filas 6-14: 9 filas de categoría (fila 7 duplica fila 6). Fila 15: NOI Mensual.
# Valores reales de ene/feb/mar-2018 tomados del archivo fuente.

_PERIODOS = ["2018-01", "2018-02", "2018-03"]
_FECHAS = [
    __import__("datetime").datetime(2018, 1, 31),
    __import__("datetime").datetime(2018, 2, 28),
    __import__("datetime").datetime(2018, 3, 31),
]
_INGRESOS = [6440.0915337339, 6434.459445817043, 6437.583242252402]
_ADMIN = [-175, -175, -175]
_PROV_REP = [-35.82156799923614, -19.76057110904785, -69.61203164324844]
_NOI_ESPERADO = [6229.2699657346675, 6239.698874707995, 6192.971210609153]


def _build_fixture_xlsx(tmp_path, corrupt_noi: bool = False,
                         unknown_label: bool = False) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hoja1"

    # Fila 3: header de fechas (col B=2 en adelante)
    for j, f in enumerate(_FECHAS, start=2):
        ws.cell(row=3, column=j).value = f
    # Fila 4: vacía (implícito)
    # Fila 5: ancla
    ws.cell(row=5, column=1).value = "INMOSA"
    # Fila 6-7: Ingresos (duplicado)
    label_ingresos = "(+) Ingresos por Arriendos"
    ws.cell(row=6, column=1).value = label_ingresos
    ws.cell(row=7, column=1).value = label_ingresos
    for j, v in enumerate(_INGRESOS, start=2):
        ws.cell(row=6, column=j).value = v
        ws.cell(row=7, column=j).value = v
    # Fila 8: Contribuciones (vacía en este fixture, como en el ejemplo real)
    ws.cell(row=8, column=1).value = "(+) Contribuciones"
    # Fila 9: Administración (mojibake real)
    ws.cell(row=9, column=1).value = "unknown label xyz" if unknown_label else "(-) Administraci�n"
    for j, v in enumerate(_ADMIN, start=2):
        ws.cell(row=9, column=j).value = v
    # Fila 10: Provision Reparaciones (con espacio final real)
    ws.cell(row=10, column=1).value = "(-) Provision Reparaciones "
    for j, v in enumerate(_PROV_REP, start=2):
        ws.cell(row=10, column=j).value = v
    # Fila 11: Aseo, Mantención y Otros (mojibake, valores 0)
    ws.cell(row=11, column=1).value = "(-) Aseo, Mantenci�n y Otros"
    for j in range(2, 2 + len(_PERIODOS)):
        ws.cell(row=11, column=j).value = 0
    # Fila 12: Otros Gastos Operacionales (vacía)
    ws.cell(row=12, column=1).value = "(-) Otros Gastos Operacionales"
    # Fila 13: IVA (vacía)
    ws.cell(row=13, column=1).value = "(-) IVA"
    # Fila 14: Seguros (valores 0)
    ws.cell(row=14, column=1).value = "(-) Seguros"
    for j in range(2, 2 + len(_PERIODOS)):
        ws.cell(row=14, column=j).value = 0
    # Fila 15: NOI Mensual (control)
    ws.cell(row=15, column=1).value = "NOI Mensual"
    noi_vals = list(_NOI_ESPERADO)
    if corrupt_noi:
        noi_vals[0] += 1000  # rompe la validación de integridad a propósito
    for j, v in enumerate(noi_vals, start=2):
        ws.cell(row=15, column=j).value = v

    os.makedirs(tmp_path, exist_ok=True)
    path = os.path.join(tmp_path, "inmosa_fixture.xlsx")
    wb.save(path)
    return path


@pytest.fixture
def fixture_xlsx(tmp_path):
    return _build_fixture_xlsx(str(tmp_path))
```

- [ ] **Step 2: Correr los tests (aún no existen aserciones, solo confirmar que el fixture se construye sin error)**

Run: `python -c "from tests.db.test_ingest_er_inmosa import _build_fixture_xlsx; import tempfile; print(_build_fixture_xlsx(tempfile.mkdtemp()))"`
Expected: imprime una ruta a un `.xlsx` sin traceback.

- [ ] **Step 3: Escribir los tests de parsing (fallan — el módulo no existe todavía)**

Agregar al final de `tests/db/test_ingest_er_inmosa.py`:

```python
# ── Tests de parsing ─────────────────────────────────────────────────────

def test_parse_devuelve_21_filas(fixture_xlsx):
    # 7 categorías (sin la duplicada) × 3 meses = 21
    rows = mod.parse_planilla(fixture_xlsx)
    assert len(rows) == 21


def test_parse_activo_key_fijo_inmosa(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert all(r["activo_key"] == "INMOSA" for r in rows)


def test_parse_periodos_yyyy_mm(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert {r["periodo"] for r in rows} == set(_PERIODOS)


def test_parse_pseudo_codigos_completos(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    codigos = {r["cuenta_codigo"] for r in rows}
    esperados = {
        "INMOSA_ING_ARR", "INMOSA_CONTRIB", "INMOSA_ADM", "INMOSA_PROV_REP",
        "INMOSA_ASEO", "INMOSA_OTROS_GASTOS", "INMOSA_IVA", "INMOSA_SEG",
    }
    assert codigos == esperados


def test_parse_ingresos_no_duplicados(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    ing = [r for r in rows if r["cuenta_codigo"] == "INMOSA_ING_ARR"]
    assert len(ing) == 3  # una fila por periodo, no dos


def test_parse_todas_operacionales(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert all(r["es_operacional"] == 1 for r in rows)


def test_parse_noi_row_ignorada(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    # La fila "NOI Mensual" nunca debe generar una fila con cuenta_codigo
    # (no hay categoría mapeada para ese label — si apareciera, cat_meta
    # sería None y el parser fallaría en vez de emitir una fila silenciosa).
    assert all(r["cuenta_codigo"] is not None for r in rows)
    # Ningún monto individual persistido iguala el NOI total del periodo
    # (confirma que la fila de control no se coló como si fuera una categoría).
    montos = {round(r["monto_clp"], 4) for r in rows}
    assert not montos & {round(v, 4) for v in _NOI_ESPERADO}


def test_parse_valores_reales_ingresos(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    ing_by_periodo = {r["periodo"]: r["monto_clp"] for r in rows if r["cuenta_codigo"] == "INMOSA_ING_ARR"}
    for periodo, esperado in zip(_PERIODOS, _INGRESOS):
        assert abs(ing_by_periodo[periodo] - esperado) < 1e-6


def test_parse_contribuciones_puede_ser_negativa(tmp_path):
    """Contribuciones con valor negativo se clasifica igual como INGRESOS_OPERACION
    (la seccion no depende del signo del valor, solo del prefijo de la fuente)."""
    path = _build_fixture_xlsx(str(tmp_path))
    wb = openpyxl.load_workbook(path)
    ws = wb["Hoja1"]
    ws.cell(row=8, column=2).value = -1381.0  # Contribuciones ene-2018 negativa
    # Ajustar NOI de ese periodo para que la suma siga cuadrando
    ws.cell(row=15, column=2).value = _NOI_ESPERADO[0] + (-1381.0)
    wb.save(path)

    rows = mod.parse_planilla(path)
    contrib = [r for r in rows if r["cuenta_codigo"] == "INMOSA_CONTRIB" and r["periodo"] == "2018-01"]
    assert len(contrib) == 1
    assert contrib[0]["monto_clp"] == -1381.0
    assert contrib[0]["seccion"] == "INGRESOS_OPERACION"


def test_parse_categoria_desconocida_falla(tmp_path):
    path = _build_fixture_xlsx(str(tmp_path), unknown_label=True)
    with pytest.raises(ValueError, match=r"(?i)categor[ií]a"):
        mod.parse_planilla(path)


def test_parse_validacion_integridad_falla_si_no_cuadra(tmp_path):
    path = _build_fixture_xlsx(str(tmp_path), corrupt_noi=True)
    with pytest.raises(ValueError, match=r"(?i)noi"):
        mod.parse_planilla(path)


def test_parse_source_metadata(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert all(r["source_file"] == fixture_xlsx for r in rows)
    assert all(r["source_sheet"] == "Hoja1" for r in rows)
    assert all(isinstance(r["source_row"], int) and r["source_row"] > 0 for r in rows)


def test_file_hash_estable(fixture_xlsx):
    h1 = mod._file_hash(fixture_xlsx)
    h2 = mod._file_hash(fixture_xlsx)
    assert h1 == h2
    assert len(h1) == 64
```

- [ ] **Step 4: Correr los tests para verificar que fallan (módulo no existe)**

Run: `python -m pytest tests/db/test_ingest_er_inmosa.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'tools.db.ingest_er_inmosa'` (o `ImportError`).

- [ ] **Step 5: Implementar el módulo**

```python
# tools/db/ingest_er_inmosa.py
"""Ingesta ER INMOSA (fondo TRI) → raw_er_activo_line.

Lee la planilla xlsx 'RAW/NOI INMOSA.xlsx' (SharePoint) con formato
categoría×mes anclado en la etiqueta 'INMOSA', y persiste las líneas en
raw_er_activo_line. Idempotente por file_hash. NOI no se persiste — se
deriva como SUM(monto_clp) WHERE es_operacional=1.

activo_key fijo: 'INMOSA' (sin desglose por residencia individual).
Montos en UF, guardados en monto_clp por convención (mismo criterio que
ingest_er_apoquindo.py / ingest_er_pt.py).

Estructura confirmada (2026-07-14) sobre RAW/NOI INMOSA.xlsx, hoja 'Hoja1':
fila ancla 'INMOSA', 9 filas de categoría debajo (la 2a es "Ingresos por
Arriendos" duplicada — se descarta), fila 'NOI Mensual' de control.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Optional

import openpyxl


# ── Mapeo categoría planilla → pseudo-código + sección ──────────────────────
# Todas las categorías son operacionales (entran al NOI). Incluye la variante
# mojibake real observada en RAW/NOI INMOSA.xlsx (U+FFFD por tildes perdidas).
_CATEGORIAS: dict[str, dict] = {
    "ingresos por arriendos":        {"codigo": "INMOSA_ING_ARR",     "seccion": "INGRESOS_OPERACION"},
    "contribuciones":                {"codigo": "INMOSA_CONTRIB",     "seccion": "INGRESOS_OPERACION"},
    "administraci�n":           {"codigo": "INMOSA_ADM",         "seccion": "GASTOS_OPERACION"},
    "administracion":                {"codigo": "INMOSA_ADM",         "seccion": "GASTOS_OPERACION"},
    "administración":                {"codigo": "INMOSA_ADM",         "seccion": "GASTOS_OPERACION"},
    "provision reparaciones":        {"codigo": "INMOSA_PROV_REP",    "seccion": "GASTOS_OPERACION"},
    "provisión reparaciones":        {"codigo": "INMOSA_PROV_REP",    "seccion": "GASTOS_OPERACION"},
    "aseo, mantenci�n y otros": {"codigo": "INMOSA_ASEO",        "seccion": "GASTOS_OPERACION"},
    "aseo, mantencion y otros":      {"codigo": "INMOSA_ASEO",        "seccion": "GASTOS_OPERACION"},
    "aseo, mantención y otros":      {"codigo": "INMOSA_ASEO",        "seccion": "GASTOS_OPERACION"},
    "otros gastos operacionales":    {"codigo": "INMOSA_OTROS_GASTOS","seccion": "GASTOS_OPERACION"},
    "iva":                           {"codigo": "INMOSA_IVA",         "seccion": "GASTOS_OPERACION"},
    "seguros":                       {"codigo": "INMOSA_SEG",         "seccion": "GASTOS_OPERACION"},
}

_ANCLA = "inmosa"
_LABEL_NOI = "noi mensual"
_ACTIVO_KEY = "INMOSA"


def _norm(s) -> str:
    """Normaliza a lowercase, sin prefijo (+)/(-), sin espacios extra al
    inicio/fin ni duplicados internos. Preserva U+FFFD (mojibake) tal cual
    para permitir matchear ambas variantes (con y sin mojibake)."""
    if s is None:
        return ""
    txt = str(s).strip().lower()
    txt = re.sub(r"^\([+\-]\)\s*", "", txt)
    return re.sub(r"\s+", " ", txt).strip()


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_planilla(xlsx_path: str) -> list[dict]:
    """Lee la planilla INMOSA y devuelve filas listas para raw_er_activo_line.

    Layout esperado (ver docstring del módulo):
    - Fila ancla con label 'INMOSA' en columna A.
    - Fila de header de fechas 2 filas arriba de la ancla.
    - 9 filas de categoría inmediatamente debajo de la ancla (la 2a
      ocurrencia de "Ingresos por Arriendos" se descarta).
    - Fila 'NOI Mensual' al final del bloque — usada solo para validar
      integridad, nunca persistida.
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    sheet_name = ws.title
    all_rows = list(ws.iter_rows(values_only=False))
    wb.close()

    # 1) Ubicar fila ancla "INMOSA"
    ancla_idx = None
    for i, row in enumerate(all_rows):
        val = row[0].value if len(row) > 0 else None
        if _norm(val) == _ANCLA:
            ancla_idx = i
            break
    if ancla_idx is None:
        raise ValueError(f"No se encontró la fila ancla 'INMOSA' en {xlsx_path}")

    # 2) Fila de header de fechas: buscar hacia arriba desde la ancla la
    #    primera fila con >=3 celdas parseables como fecha.
    header_row_idx = None
    period_by_col: dict[int, str] = {}
    for i in range(ancla_idx - 1, -1, -1):
        row = all_rows[i]
        candidatos = {}
        for cell in row:
            v = cell.value
            if hasattr(v, "year") and hasattr(v, "month"):
                candidatos[cell.column] = f"{v.year:04d}-{v.month:02d}"
        if len(candidatos) >= 3:
            header_row_idx = i
            period_by_col = candidatos
            break
    if header_row_idx is None:
        raise ValueError(f"No se encontró fila de header con fechas antes de la ancla 'INMOSA' en {xlsx_path}")

    # 3) Recorrer filas debajo de la ancla hasta 'NOI Mensual'
    out: list[dict] = []
    seen_categorias: set[str] = set()
    noi_por_periodo: dict[str, float] = {}
    suma_por_periodo: dict[str, float] = {}
    noi_row_found = False

    for i in range(ancla_idx + 1, len(all_rows)):
        row = all_rows[i]
        raw_label = row[0].value if len(row) > 0 else None
        label = _norm(raw_label)
        if not label:
            continue
        if label == _LABEL_NOI:
            noi_row_found = True
            for col, periodo in period_by_col.items():
                cell = row[col - 1] if col - 1 < len(row) else None
                if cell is not None and cell.value is not None:
                    noi_por_periodo[periodo] = float(cell.value)
            break  # fin del bloque INMOSA

        if label in seen_categorias:
            continue  # fila duplicada (ej. "Ingresos por Arriendos" repetida)

        cat_meta = _CATEGORIAS.get(label)
        if cat_meta is None:
            raise ValueError(
                f"Categoría no reconocida en {xlsx_path}, fila {i + 1}: {raw_label!r}"
            )
        seen_categorias.add(label)

        for col, periodo in period_by_col.items():
            cell = row[col - 1] if col - 1 < len(row) else None
            monto = float(cell.value) if cell is not None and cell.value is not None else 0.0
            suma_por_periodo[periodo] = suma_por_periodo.get(periodo, 0.0) + monto
            out.append({
                "activo_key":     _ACTIVO_KEY,
                "periodo":        periodo,
                "cuenta_codigo":  cat_meta["codigo"],
                "cuenta_nombre":  str(raw_label).strip(),
                "monto_clp":      monto,
                "monto_uf":       None,
                "seccion":        cat_meta["seccion"],
                "es_operacional": 1,
                "source_file":    xlsx_path,
                "source_sheet":   sheet_name,
                "source_row":     i + 1,
            })

    if not noi_row_found:
        raise ValueError(f"No se encontró la fila 'NOI Mensual' en {xlsx_path}")

    # 4) Validación de integridad: suma de componentes == NOI Mensual
    for periodo, noi_esperado in noi_por_periodo.items():
        suma = suma_por_periodo.get(periodo, 0.0)
        delta = abs(suma - noi_esperado)
        if delta >= 0.01:
            raise ValueError(
                f"Validación de integridad falló en {xlsx_path}, periodo {periodo}: "
                f"suma de componentes={suma!r} != NOI Mensual={noi_esperado!r} (delta={delta!r})"
            )

    return out


# ── Persistencia ─────────────────────────────────────────────────────────

def persist(xlsx_path: str,
            conn: "sqlite3.Connection | None" = None) -> dict:
    """Ingesta idempotente de la planilla ER INMOSA en raw_er_activo_line.

    Comportamiento (idéntico a ingest_er_apoquindo.persist):
    - Si ya existen filas activas (superseded_at IS NULL) con el mismo
      file_hash → no hace nada, retorna status 'skipped_idempotent'.
    - Si existen filas activas de una ingesta anterior (activo_key='INMOSA',
      otro file_hash) → las marca superseded e inserta las nuevas
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

        lines = parse_planilla(xlsx_path)
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
            conn, tool="ingest_er_inmosa",
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
            noi[r["periodo"]] += r["monto_clp"]
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

- [ ] **Step 6: Correr los tests de parsing para verificar que pasan**

Run: `python -m pytest tests/db/test_ingest_er_inmosa.py -v -k "not persist"`
Expected: todos los tests de parsing (13 tests) **PASS**.

- [ ] **Step 7: Commit**

```bash
git add tools/db/ingest_er_inmosa.py tests/db/test_ingest_er_inmosa.py
git commit -m "feat(db): parser ER INMOSA con validacion de integridad NOI"
```

---

## Task 2: Persistencia idempotente + test de integración contra el archivo real

**Files:**
- Modify: `tests/db/test_ingest_er_inmosa.py` — agregar fixture de DB temporal y tests de persistencia (mismo patrón que `test_ingest_er_apoquindo.py`), más un test de integración de solo-lectura contra el archivo real.

**Interfaces:**
- Consumes: `parse_planilla()` y `_file_hash()` de Task 1; `repo_er_activo.insert_lines()`, `repo_er_activo.mark_superseded()`, `repo_audit.start_ingest_run()`, `repo_audit.finish_ingest_run()` (todos ya existentes, sin cambios).
- Produces: `persist(xlsx_path: str, conn=None) -> dict` con `{"status": ..., "rows": ..., "file_hash": ..., "ingest_run_id": ...}` (ya implementado en Task 1 Step 5 — este task solo lo cubre con tests).

- [ ] **Step 1: Escribir los tests de persistencia (fallan si algo del schema mínimo está mal declarado)**

Agregar al final de `tests/db/test_ingest_er_inmosa.py`:

```python
# ── Tests de persistencia ────────────────────────────────────────────────

@pytest.fixture
def db_conn(tmp_path):
    """DB en disco (tmp) con schema mínimo necesario."""
    db_path = os.path.join(str(tmp_path), "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
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
             VALUES ('INMOSA','TRI','INMOSA',0.43);
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
    """)
    conn.commit()
    yield conn
    conn.close()


def test_persist_inserta_21_filas(fixture_xlsx, db_conn):
    res = mod.persist(fixture_xlsx, conn=db_conn)
    assert res["status"] == "inserted"
    assert res["rows"] == 21
    n = db_conn.execute(
        "SELECT COUNT(*) FROM raw_er_activo_line WHERE superseded_at IS NULL"
    ).fetchone()[0]
    assert n == 21


def test_persist_idempotente_mismo_hash(fixture_xlsx, db_conn):
    mod.persist(fixture_xlsx, conn=db_conn)
    res2 = mod.persist(fixture_xlsx, conn=db_conn)
    assert res2["status"] == "skipped_idempotent"
    n = db_conn.execute(
        "SELECT COUNT(*) FROM raw_er_activo_line WHERE superseded_at IS NULL"
    ).fetchone()[0]
    assert n == 21  # no duplica


def test_persist_reingesta_supersede_previas(fixture_xlsx, tmp_path, db_conn):
    mod.persist(fixture_xlsx, conn=db_conn)
    fixture_xlsx_2 = _build_fixture_xlsx(str(tmp_path / "sub"))
    wb = openpyxl.load_workbook(fixture_xlsx_2)
    wb["Hoja1"].cell(row=5, column=1).value = "INMOSA "  # cambia contenido → cambia hash
    wb.save(fixture_xlsx_2)

    res = mod.persist(fixture_xlsx_2, conn=db_conn)
    assert res["status"] == "superseded_and_reinserted"
    total = db_conn.execute("SELECT COUNT(*) FROM raw_er_activo_line").fetchone()[0]
    activas = db_conn.execute(
        "SELECT COUNT(*) FROM raw_er_activo_line WHERE superseded_at IS NULL"
    ).fetchone()[0]
    assert activas == 21
    assert total - activas == 21


def test_noi_derivado_matchea_suma_esperada(fixture_xlsx, db_conn):
    mod.persist(fixture_xlsx, conn=db_conn)
    for periodo, esperado in zip(_PERIODOS, _NOI_ESPERADO):
        calc = db_conn.execute("""
            SELECT SUM(monto_clp) FROM raw_er_activo_line
             WHERE activo_key='INMOSA' AND periodo=?
               AND es_operacional=1 AND superseded_at IS NULL
        """, (periodo,)).fetchone()[0]
        assert abs(calc - esperado) < 0.01, f"{periodo}: {calc} != {esperado}"


def test_persist_falla_no_escribe_nada_si_integridad_no_cuadra(tmp_path, db_conn):
    """Si la validación de integridad falla, no debe quedar ninguna fila
    persistida (falla atómica antes de tocar la DB)."""
    path = _build_fixture_xlsx(str(tmp_path), corrupt_noi=True)
    with pytest.raises(ValueError, match=r"(?i)noi"):
        mod.persist(path, conn=db_conn)
    n = db_conn.execute("SELECT COUNT(*) FROM raw_er_activo_line").fetchone()[0]
    assert n == 0


# ── Test de integración de solo-lectura contra el archivo real ──────────
# Se salta automáticamente si el archivo no está disponible en este entorno
# (por ejemplo, en CI sin acceso a SharePoint local).

_REAL_XLSX = (
    r"C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos"
    r"\RAW\NOI INMOSA.xlsx"
)


@pytest.mark.skipif(not os.path.exists(_REAL_XLSX), reason="archivo real no disponible en este entorno")
def test_parse_archivo_real_no_lanza_y_cuadra_integridad(tmp_path):
    """Copia el archivo real a tmp_path (evita locks de OneDrive) y confirma
    que parse_planilla no lanza ValueError — es decir, la validación de
    integridad (SUM(componentes)==NOI Mensual) cuadra en las 99 columnas
    reales, no solo en el fixture sintético."""
    import shutil
    local_copy = os.path.join(str(tmp_path), "real.xlsx")
    shutil.copy(_REAL_XLSX, local_copy)

    rows = mod.parse_planilla(local_copy)
    assert len(rows) > 0
    periodos = {r["periodo"] for r in rows}
    assert "2018-01" in periodos
    assert "2026-03" in periodos
    assert len(periodos) == 99
```

- [ ] **Step 2: Correr todos los tests del módulo**

Run: `python -m pytest tests/db/test_ingest_er_inmosa.py -v`
Expected: todos los tests **PASS** (18 tests de parsing/persistencia + 1 de integración condicional, dependiendo de si `_REAL_XLSX` existe en este entorno — si no existe, aparece como `SKIPPED`, no `FAILED`).

- [ ] **Step 3: Correr la suite completa de `tests/db/` para descartar regresiones**

Run: `python -m pytest tests/db/ -q`
Expected: todos los tests previos siguen en verde + los nuevos de este módulo.

- [ ] **Step 4: Commit**

```bash
git add tests/db/test_ingest_er_inmosa.py
git commit -m "test(db): persistencia idempotente ER INMOSA + integracion contra archivo real"
```

---

## Task 3: Ingestar el archivo real a la DB de producción

**Files:**
- Modify: `memory/agente_toesca_v2.db` (ingesta real vía `persist()`) — archivo tracked en git (confirmado en el trabajo previo de migración 049), se commitea el resultado.

**Interfaces:**
- Consumes: `tools.db.ingest_er_inmosa.persist(xlsx_path, conn=None)` de Task 1/2, usando la conexión real vía `tools.db.connection.get_conn()`.

- [ ] **Step 1: Dry-run contra el archivo real para inspección visual**

```bash
python -m tools.db.ingest_er_inmosa "C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\RAW\NOI INMOSA.xlsx" --dry-run
```

Expected: imprime `Parsed 693 filas de ...` (99 periodos × 7 categorías) sin traceback, con el rango `periodos: 2018-01..2026-03 (99 meses)` y una muestra de NOI por periodo. Si lanza `ValueError` de integridad o categoría no reconocida, **detenerse** — no continuar a Step 2 hasta resolverlo (puede indicar que el archivo cambió desde la inspección inicial de este plan).

- [ ] **Step 2: Ingestar a la DB real**

```bash
python -c "
from tools.db.ingest_er_inmosa import persist
res = persist(r'C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\RAW\NOI INMOSA.xlsx')
print(res)
"
```

Expected: `{'status': 'inserted', 'rows': 693, 'file_hash': '...', 'ingest_run_id': N}`.

- [ ] **Step 3: Sanity queries manuales**

```bash
python -c "
import sqlite3
c = sqlite3.connect('memory/agente_toesca_v2.db')
c.row_factory = sqlite3.Row
print('total filas activas INMOSA:', c.execute(\"SELECT COUNT(*) FROM raw_er_activo_line WHERE activo_key='INMOSA' AND superseded_at IS NULL\").fetchone()[0])
print('periodos min/max:', c.execute(\"SELECT MIN(periodo), MAX(periodo) FROM raw_er_activo_line WHERE activo_key='INMOSA' AND superseded_at IS NULL\").fetchone())
print('NOI 2018-01:', c.execute(\"SELECT SUM(monto_clp) FROM raw_er_activo_line WHERE activo_key='INMOSA' AND periodo='2018-01' AND es_operacional=1 AND superseded_at IS NULL\").fetchone()[0])
print('NOI 2026-03:', c.execute(\"SELECT SUM(monto_clp) FROM raw_er_activo_line WHERE activo_key='INMOSA' AND periodo='2026-03' AND es_operacional=1 AND superseded_at IS NULL\").fetchone()[0])
"
```

Expected: `total filas activas INMOSA` = 693; `periodos min/max` = `('2018-01', '2026-03')`; NOI 2018-01 ≈ 6229.27 (mismo valor validado en la inspección manual del spec); NOI 2026-03 ≈ 6081 (visto en la inspección de columnas finales durante el brainstorming).

- [ ] **Step 4: Correr suite completa de tests para confirmar no-regresión**

Run: `python -m pytest tests/ -q`
Expected: todos los tests pasan (incluyendo el nuevo `test_parse_archivo_real_no_lanza_y_cuadra_integridad`, que ahora corre real en vez de skip, dado que el archivo existe en este entorno).

- [ ] **Step 5: Commit**

```bash
git add memory/agente_toesca_v2.db
git commit -m "data(er-inmosa): ingesta ER INMOSA 2018-01 a 2026-03 (99 meses, 693 filas)"
```

---

## Task 4: Documentación

**Files:**
- Modify: `wiki/db.md` — agregar INMOSA a la lista de fuentes ER ingestadas (junto a PT/Apo).
- Modify: `wiki/log.md` — entrada de la ingesta.
- Modify: `CLAUDE.md` — sección "Flujo mensual NOI-RCSD", agregar referencia a `ingest_er_inmosa.py` como fuente alternativa/complementaria si aplica (ver nota abajo).

**Interfaces:**
- Consumes: nada.
- Produces: documentación consultable en sesiones futuras.

- [ ] **Step 1: Actualizar wiki/db.md**

Agregar al final de la sección de fuentes ER (buscar dónde se documentó PT/Apo, o al final del archivo si no hay sección dedicada):

```markdown
## Ingesta ER INMOSA (fondo TRI)

Fuente: `RAW/NOI INMOSA.xlsx` (SharePoint), hoja `Hoja1`. Formato categoría×mes
anclado en la fila con label `"INMOSA"`. Módulo: `tools/db/ingest_er_inmosa.py`.

`activo_key='INMOSA'` fijo (sin desglose por residencia individual — INMOSA
engloba 6 residencias de adulto mayor como una sola entidad para efectos de
ER/NOI). Validación de integridad obligatoria: suma de las 7 categorías debe
cuadrar exacto contra la fila "NOI Mensual" de la fuente antes de persistir
(si no cuadra, el ingest falla completo, no persiste nada).

Rango histórico ingestado: 2018-01 a 2026-03 (99 meses).
```

- [ ] **Step 2: Actualizar wiki/log.md**

Agregar al final:

```markdown
## [2026-07-14] ingesta | ER INMOSA (fondo TRI) — 2018-01 a 2026-03

Primer activo pendiente del fondo TRI consolidado (de los 5: INMOSA, Sucden,
Viña Centro, Curicó, Apo3001), siguiendo la arquitectura de `raw_er_activo_line`
ya usada para PT/Apo. `activo_key='INMOSA'` fijo, 693 filas (99 periodos × 7
categorías), validación de integridad contra "NOI Mensual" de la fuente
verificada en 0 discrepancias sobre el histórico completo.
```

- [ ] **Step 3: Commit**

```bash
git add wiki/db.md wiki/log.md
git commit -m "wiki: documenta ingesta ER INMOSA"
git push
```

---

## Self-Review

**Spec coverage:**
- Parser ancla+offset, mapeo de categorías, manejo de fila duplicada → Task 1 ✓
- Validación de integridad obligatoria y bloqueante → Task 1 (parser) + Task 2 (test de que no persiste nada si falla) ✓
- Idempotencia por `file_hash`, supersede en reingesta → Task 2 ✓
- Test con valores reales de ene-mar 2018 → Task 1 ✓
- Test de categoría desconocida falla explícito → Task 1 ✓
- Test de Contribuciones negativa clasificada igual → Task 1 ✓
- Ingesta real + sanity checks → Task 3 ✓
- Documentación → Task 4 ✓
- Consolidación a nivel fondo TRI (`v_activo_fondo_efectivo`) → **fuera de scope** por diseño (spec lo indica explícitamente; se hará cuando estén todos los activos pendientes o si el usuario lo pide antes).
- Archivar el archivo RAW a su carpeta canónica → **fuera de scope** por diseño (spec lo indica explícitamente).

**Placeholder scan:** sin TBDs. Todo el código de parser, tests y comandos son completos y ejecutables. Los valores esperados (ingresos, NOI, deltas) son los reales verificados en la inspección del archivo, no inventados.

**Type consistency:** `parse_planilla()` devuelve el mismo shape de dict en Task 1 que el consumido por `repo_er_activo.insert_lines()` en Task 2 — mismas claves (`activo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf, seccion, es_operacional, source_file, source_sheet, source_row`) usadas consistentemente en todos los tests. `persist()` devuelve el mismo shape de resultado (`status/rows/file_hash/ingest_run_id`) usado en Task 2 y Task 3.
