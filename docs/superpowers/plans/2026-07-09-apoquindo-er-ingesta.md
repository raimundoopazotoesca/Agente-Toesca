# Ingesta ER Fondo Apoquindo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingerir líneas mensuales de ER de Apo4501 y Apo4700 desde una planilla xlsx local a `raw_er_activo_line`, con idempotencia por `file_hash` y fix del bug de participación fondo→activo.

**Architecture:** Nuevo script `tools/db/ingest_er_apoquindo.py` que reutiliza `repo_er_activo.insert_lines`/`mark_superseded` y `repo_audit` (ya existentes, usados por `ingest_er.py` de Curicó/Viña). Parser openpyxl con localización por keyword en col A + header por meses. Fix participación via migración SQL versionada.

**Tech Stack:** Python + openpyxl + SQLite. Sin dependencias nuevas.

## Global Constraints

- Path DB negocio: `memory/agente_toesca_v2.db`
- Formato `periodo`: `YYYY-MM` (string)
- `raw_er_activo_line`: `monto_clp` con signo contable ya aplicado (ingresos +, gastos −)
- Convención `superseded_at`: filas viejas se marcan, no se borran; queries downstream filtran `WHERE superseded_at IS NULL`
- Idempotencia: `file_hash` SHA-256 del xlsx; corrida con mismo hash es no-op
- Los 10 pseudo-códigos válidos: `APO_ING_ARR`, `APO_GC_VAC`, `APO_COM_CORR`, `APO_ADM`, `APO_PROV_REP`, `APO_BONOS_LEG`, `APO_CONSTRUCT`, `APO_IVA_NR`, `APO_CONTRIB`, `APO_SEG` — todos con `es_operacional=1`
- Solo dos `activo_key` válidos en este ingestor: `Apo4501`, `Apo4700`
- Tests corren con `python -m pytest tests/db/test_ingest_er_apoquindo.py -v`
- Commits: prefijo `feat(er-apo):` o `fix(er-apo):`; sin `--no-verify`

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `tools/db/migrations/047_fix_participacion_apo_activos.sql` | Corrige `dim_activo.participacion_fondo_activo` de Apo4501/Apo4700: 0.3 → 1.0 |
| `tools/db/ingest_er_apoquindo.py` | Parser + persistencia. Funciones puras `_file_hash`, `parse_planilla`, y CLI `main` |
| `tests/db/test_ingest_er_apoquindo.py` | Fixture xlsx en memoria + tests idempotencia, signos, NOI |
| `wiki/log.md` (modif.) | Entrada con fecha y descripción del cambio |
| `wiki/fondos/apoquindo.md` (modif. o creado) | Documentar fuente de ER local, categorías, comando de ingesta |

---

### Task 1: Migración SQL — fix participación fondo Apo → activos

**Files:**
- Create: `tools/db/migrations/047_fix_participacion_apo_activos.sql`

**Interfaces:**
- Consumes: `dim_activo` con `activo_key IN ('Apo4501','Apo4700')` y `participacion_fondo_activo = 0.3`
- Produces: mismos registros con `participacion_fondo_activo = 1.0`. Ningún consumidor de código depende del valor 0.3 (verificado por grep en step 1).

- [ ] **Step 1: Verificar que no hay código que dependa del valor 0.3**

Run:
```bash
grep -rn "0.3" --include="*.py" tools/ scripts/ dashboards/ | grep -iE "apo|participacion|4501|4700"
```
Expected: sin resultados relevantes (o solo comentarios). Si aparece código que hardcodea 0.3 para Apo, detener y abrir issue antes de continuar.

- [ ] **Step 2: Escribir migración SQL**

Create `tools/db/migrations/047_fix_participacion_apo_activos.sql`:

```sql
-- 047_fix_participacion_apo_activos.sql
-- Fix: dim_activo.participacion_fondo_activo para Apo4501/Apo4700 debe ser 1.0.
-- El fondo Apoquindo es dueño 100% de ambos activos. El 30% previo confundía la
-- relación fondo-fondo (TRI→Apo) con la relación fondo-activo.
UPDATE dim_activo
   SET participacion_fondo_activo = 1.0
 WHERE activo_key IN ('Apo4501','Apo4700')
   AND fondo_key = 'Apo';
```

- [ ] **Step 3: Aplicar migración a la DB**

Run:
```bash
python -c "
import sqlite3
c = sqlite3.connect('memory/agente_toesca_v2.db')
c.executescript(open('tools/db/migrations/047_fix_participacion_apo_activos.sql').read())
c.commit()
for r in c.execute(\"SELECT activo_key, participacion_fondo_activo FROM dim_activo WHERE activo_key IN ('Apo4501','Apo4700')\"):
    print(r)
"
```
Expected:
```
('Apo4501', 1.0)
('Apo4700', 1.0)
```

- [ ] **Step 4: Commit**

```bash
git add tools/db/migrations/047_fix_participacion_apo_activos.sql memory/agente_toesca_v2.db
git commit -m "fix(er-apo): participacion_fondo_activo=1.0 para Apo4501/Apo4700"
```

---

### Task 2: Parser puro `parse_planilla` con tests

**Files:**
- Create: `tools/db/ingest_er_apoquindo.py` (parcial: hash + parser, sin CLI ni persistencia)
- Create: `tests/db/test_ingest_er_apoquindo.py` (fixture + tests de parseo)

**Interfaces:**
- Produces:
  - `_file_hash(path: str) -> str` — SHA-256 hex
  - `parse_planilla(xlsx_path: str) -> list[dict]` — retorna lista de dicts con claves `activo_key`, `periodo`, `cuenta_codigo`, `cuenta_nombre`, `monto_clp`, `seccion`, `es_operacional`, `source_file`, `source_sheet`, `source_row`. No toca DB. Los 10 pseudo-códigos vienen de un mapa constante `_CATEGORIAS`.

- [ ] **Step 1: Crear esqueleto del módulo con constantes**

Create `tools/db/ingest_er_apoquindo.py`:

```python
"""Ingesta ER Fondo Apoquindo (Apo4501, Apo4700) → raw_er_activo_line.

Lee una planilla xlsx con formato de resumen por categoría (10 conceptos por
activo por mes) y persiste las líneas en raw_er_activo_line. Idempotente por
file_hash. NOI no se persiste — se deriva.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

import openpyxl


# ── Mapeo categoría planilla → pseudo-código + sección + signo ─────────────────
# Todas las categorías son operacionales (entran al NOI).
_CATEGORIAS: dict[str, dict] = {
    "ingresos por arriendos":                {"codigo": "APO_ING_ARR",   "seccion": "INGRESOS_OPERACION"},
    "gastos comunes/vacancia":               {"codigo": "APO_GC_VAC",    "seccion": "GASTOS_OPERACION"},
    "gastos comunes / vacancia":             {"codigo": "APO_GC_VAC",    "seccion": "GASTOS_OPERACION"},
    "comisión corredor":                     {"codigo": "APO_COM_CORR",  "seccion": "GASTOS_OPERACION"},
    "comision corredor":                     {"codigo": "APO_COM_CORR",  "seccion": "GASTOS_OPERACION"},
    "administración":                        {"codigo": "APO_ADM",       "seccion": "GASTOS_OPERACION"},
    "administracion":                        {"codigo": "APO_ADM",       "seccion": "GASTOS_OPERACION"},
    "provisión reparaciones":                {"codigo": "APO_PROV_REP",  "seccion": "GASTOS_OPERACION"},
    "provision reparaciones":                {"codigo": "APO_PROV_REP",  "seccion": "GASTOS_OPERACION"},
    "gastos bono + legales + otros":         {"codigo": "APO_BONOS_LEG", "seccion": "GASTOS_OPERACION"},
    "gastos bono+legales+otros":             {"codigo": "APO_BONOS_LEG", "seccion": "GASTOS_OPERACION"},
    "gastos constructores asociados":        {"codigo": "APO_CONSTRUCT", "seccion": "GASTOS_OPERACION"},
    "gastos constructores asociados (contabilidad)": {"codigo": "APO_CONSTRUCT", "seccion": "GASTOS_OPERACION"},
    "gastos iva no recuperado":              {"codigo": "APO_IVA_NR",    "seccion": "GASTOS_OPERACION"},
    "gastos iva no recuperado/otros gastos": {"codigo": "APO_IVA_NR",    "seccion": "GASTOS_OPERACION"},
    "contribuciones":                        {"codigo": "APO_CONTRIB",   "seccion": "GASTOS_OPERACION"},
    "seguros":                               {"codigo": "APO_SEG",       "seccion": "GASTOS_OPERACION"},
}

# activo_key por nombre de sub-fila en la planilla
_ACTIVOS = {"4501": "Apo4501", "4700": "Apo4700"}

# Fila etiqueta "NOI Mensual" — se ignora al parsear (NOI se deriva)
_IGNORE_LABELS = {"noi mensual", "fondo apoquindo"}


def _norm(s) -> str:
    """Normaliza a lowercase sin paréntesis inicial de signo ni espacios extra."""
    if s is None:
        return ""
    txt = str(s).strip().lower()
    # remover prefijo tipo "(-) " o "(+)"
    txt = re.sub(r"^\([+\-]\)\s*", "", txt)
    return re.sub(r"\s+", " ", txt).strip()


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 2: Escribir tests con fixture xlsx en memoria**

Create `tests/db/test_ingest_er_apoquindo.py`:

```python
"""Tests para tools.db.ingest_er_apoquindo."""
from __future__ import annotations

import os
import tempfile
from datetime import date

import openpyxl
import pytest

from tools.db import ingest_er_apoquindo as mod


# ── Fixture xlsx con 3 meses × 2 activos × 10 categorías ────────────────────

_MESES_HEADER = ["dic-24", "ene-25", "feb-25"]
_PERIODOS = ["2024-12", "2025-01", "2025-02"]

_CATS_ORDER = [
    ("(-) Ingresos por Arriendos",       "APO_ING_ARR",   +1),
    ("(-) Gastos Comunes/Vacancia",      "APO_GC_VAC",    -1),
    ("(-) Comisión Corredor",            "APO_COM_CORR",  -1),
    ("(-) Administración",               "APO_ADM",       -1),
    ("Provisión Reparaciones",           "APO_PROV_REP",  -1),
    ("(-) Gastos Bono + Legales + Otros","APO_BONOS_LEG", -1),
    ("(-) Gastos Constructores Asociados (Contabilidad)", "APO_CONSTRUCT", -1),
    ("(-) Gastos IVA no recuperado/Otros Gastos", "APO_IVA_NR", -1),
    ("(-) Contribuciones",               "APO_CONTRIB",   -1),
    ("(-) Seguros",                      "APO_SEG",       -1),
]


def _build_fixture_xlsx(tmp_path) -> str:
    """Construye un xlsx con el layout esperado y valores previsibles.

    monto_activo = mes_index * 1000 + cat_index * 100  (signo aplicado).
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Apo"
    # Fila 1: A vacío, luego meses
    ws.cell(row=1, column=1).value = "Fondo Apoquindo"
    for j, m in enumerate(_MESES_HEADER, start=2):
        ws.cell(row=1, column=j).value = m
    r = 2
    for cat_idx, (label, _, sign) in enumerate(_CATS_ORDER):
        ws.cell(row=r, column=1).value = label
        r += 1
        # Sub-fila 4700
        ws.cell(row=r, column=1).value = "Apoquindo 4700"
        for mi, _ in enumerate(_MESES_HEADER):
            ws.cell(row=r, column=2 + mi).value = sign * (mi * 1000 + cat_idx * 100 + 47)
        r += 1
        # Sub-fila 4501
        ws.cell(row=r, column=1).value = "Apoquindo 4501"
        for mi, _ in enumerate(_MESES_HEADER):
            ws.cell(row=r, column=2 + mi).value = sign * (mi * 1000 + cat_idx * 100 + 45)
        r += 1
    # Fila NOI Mensual (debe ignorarse)
    ws.cell(row=r, column=1).value = "NOI Mensual"
    for mi in range(len(_MESES_HEADER)):
        ws.cell(row=r, column=2 + mi).value = 99999
    path = os.path.join(tmp_path, "apo_fixture.xlsx")
    wb.save(path)
    return path


@pytest.fixture
def fixture_xlsx(tmp_path):
    return _build_fixture_xlsx(str(tmp_path))


# ── Tests ────────────────────────────────────────────────────────────────────

def test_parse_devuelve_60_filas(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    # 3 meses × 2 activos × 10 categorías
    assert len(rows) == 60


def test_parse_activo_keys(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    activos = {r["activo_key"] for r in rows}
    assert activos == {"Apo4501", "Apo4700"}


def test_parse_periodos_yyyy_mm(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    periodos = {r["periodo"] for r in rows}
    assert periodos == {"2024-12", "2025-01", "2025-02"}


def test_parse_pseudo_codigos_completos(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    codigos = {r["cuenta_codigo"] for r in rows}
    esperados = {
        "APO_ING_ARR", "APO_GC_VAC", "APO_COM_CORR", "APO_ADM", "APO_PROV_REP",
        "APO_BONOS_LEG", "APO_CONSTRUCT", "APO_IVA_NR", "APO_CONTRIB", "APO_SEG",
    }
    assert codigos == esperados


def test_parse_signos(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    # Ingresos por arriendos siempre >0
    ings = [r for r in rows if r["cuenta_codigo"] == "APO_ING_ARR"]
    assert all(r["monto_clp"] > 0 for r in ings)
    # Contribuciones (gasto) siempre <0
    contrib = [r for r in rows if r["cuenta_codigo"] == "APO_CONTRIB"]
    assert all(r["monto_clp"] < 0 for r in contrib)


def test_parse_todas_operacionales(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert all(r["es_operacional"] == 1 for r in rows)


def test_parse_noi_row_ignorada(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    # 99999 es el valor de la fila NOI del fixture; no debe aparecer
    assert not any(r["monto_clp"] == 99999 for r in rows)


def test_parse_source_metadata(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert all(r["source_file"] == fixture_xlsx for r in rows)
    assert all(r["source_sheet"] == "Apo" for r in rows)
    assert all(isinstance(r["source_row"], int) and r["source_row"] > 0 for r in rows)


def test_file_hash_estable(fixture_xlsx):
    h1 = mod._file_hash(fixture_xlsx)
    h2 = mod._file_hash(fixture_xlsx)
    assert h1 == h2
    assert len(h1) == 64
```

- [ ] **Step 3: Correr tests — deben fallar todos porque `parse_planilla` no existe aún**

Run: `python -m pytest tests/db/test_ingest_er_apoquindo.py -v`
Expected: 8 tests fallan con `AttributeError: module 'tools.db.ingest_er_apoquindo' has no attribute 'parse_planilla'`. `test_file_hash_estable` pasa (la función ya existe del Step 1).

- [ ] **Step 4: Implementar `parse_planilla`**

Append to `tools/db/ingest_er_apoquindo.py`:

```python
# ── Parser de la planilla ──────────────────────────────────────────────────────

_MES_ABBR = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _parse_periodo_header(cell_value) -> Optional[str]:
    """Convierte 'dic-24', 'ene-25', un date o datetime a 'YYYY-MM'."""
    if cell_value is None:
        return None
    # Si es datetime/date (openpyxl a veces convierte)
    if hasattr(cell_value, "year") and hasattr(cell_value, "month"):
        return f"{cell_value.year:04d}-{cell_value.month:02d}"
    s = str(cell_value).strip().lower()
    m = re.match(r"^([a-zñ]{3})[-/\s]+(\d{2,4})$", s)
    if not m:
        return None
    mes_txt, yy = m.group(1), m.group(2)
    mes = _MES_ABBR.get(mes_txt)
    if mes is None:
        return None
    year = int(yy)
    if year < 100:
        year += 2000
    return f"{year:04d}-{mes:02d}"


def _detectar_activo(cell_value) -> Optional[str]:
    """'Apoquindo 4501' → 'Apo4501'. Devuelve None si no matchea."""
    if cell_value is None:
        return None
    s = str(cell_value)
    for token, key in _ACTIVOS.items():
        if token in s:
            return key
    return None


def parse_planilla(xlsx_path: str) -> list[dict]:
    """Lee la planilla y devuelve filas listas para insertar en raw_er_activo_line.

    Layout esperado:
    - Col A: etiqueta (categoría o sub-fila activo)
    - Col B..: valores mensuales, con header de meses en la primera fila que
      tenga múltiples celdas parseables como mes.
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    sheet_name = ws.title
    all_rows = list(ws.iter_rows(values_only=False))
    wb.close()

    # 1) Detectar fila de header
    header_row_idx = None
    period_by_col: dict[int, str] = {}
    for i, row in enumerate(all_rows):
        candidatos = {}
        for cell in row:
            p = _parse_periodo_header(cell.value)
            if p:
                candidatos[cell.column] = p
        if len(candidatos) >= 3:
            header_row_idx = i
            period_by_col = candidatos
            break
    if header_row_idx is None:
        raise ValueError(f"No se encontró fila de header con meses en {xlsx_path}")

    # 2) Recorrer filas: cuando A matchea una categoría, la siguiente(s) fila(s)
    #    con activo dan los valores.
    out: list[dict] = []
    current_cat: Optional[dict] = None
    for i in range(header_row_idx + 1, len(all_rows)):
        row = all_rows[i]
        label_cell = row[0]
        label = _norm(label_cell.value)
        if not label:
            continue
        if label in _IGNORE_LABELS:
            current_cat = None
            continue
        # ¿Es una categoría?
        cat_meta = _CATEGORIAS.get(label)
        if cat_meta is not None:
            current_cat = cat_meta
            continue
        # ¿Es una sub-fila de activo bajo la categoría actual?
        activo_key = _detectar_activo(label_cell.value)
        if activo_key is None or current_cat is None:
            continue
        for col, periodo in period_by_col.items():
            # openpyxl usa 1-index; row es tupla ordenada por columna
            cell = next((c for c in row if c.column == col), None)
            if cell is None or cell.value is None:
                continue
            try:
                monto = float(cell.value)
            except (TypeError, ValueError):
                continue
            out.append({
                "activo_key":     activo_key,
                "periodo":        periodo,
                "cuenta_codigo":  current_cat["codigo"],
                "cuenta_nombre":  str(label_cell.value).strip(),
                "monto_clp":      monto,
                "monto_uf":       None,
                "seccion":        current_cat["seccion"],
                "es_operacional": 1,
                "source_file":    xlsx_path,
                "source_sheet":   sheet_name,
                "source_row":     i + 1,
            })
    return out
```

- [ ] **Step 5: Correr tests — deben pasar todos**

Run: `python -m pytest tests/db/test_ingest_er_apoquindo.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add tools/db/ingest_er_apoquindo.py tests/db/test_ingest_er_apoquindo.py
git commit -m "feat(er-apo): parser planilla ER Apoquindo con tests de fixture"
```

---

### Task 3: Persistencia idempotente + CLI

**Files:**
- Modify: `tools/db/ingest_er_apoquindo.py` (agregar `persist` + `main`)
- Modify: `tests/db/test_ingest_er_apoquindo.py` (agregar tests DB)

**Interfaces:**
- Consumes: `parse_planilla`, `_file_hash` de Task 2; `repo_er_activo.insert_lines`, `repo_er_activo.mark_superseded`, `repo_audit.start_run`, `repo_audit.finish_run`, `tools.db.connection.get_conn`.
- Produces:
  - `persist(xlsx_path: str, conn: sqlite3.Connection | None = None) -> dict` — retorna `{"status": "inserted"|"skipped_idempotent"|"superseded_and_reinserted", "rows": int, "file_hash": str, "ingest_run_id": int | None}`. Si `conn` es None, usa `get_conn()`.
  - CLI: `python -m tools.db.ingest_er_apoquindo <xlsx> [--dry-run]`

- [ ] **Step 1: Verificar API de `repo_audit`**

Run: `python -c "from tools.db import repo_audit; help(repo_audit.start_run); help(repo_audit.finish_run)"`
Expected: firma real. Ajustar el código del Step 3 si difiere. Si `repo_audit` no tiene esas funciones, mirar cómo `ingest_er.py` inserta en `ingest_run` y copiar el patrón (esperado: INSERT directo a `ingest_run` con `tool`, `source_file`, `file_hash`, `started_at`, `status`).

- [ ] **Step 2: Escribir tests de persistencia**

Append to `tests/db/test_ingest_er_apoquindo.py`:

```python
import sqlite3


@pytest.fixture
def db_conn(tmp_path):
    """DB in-memory con schema mínimo necesario."""
    db_path = os.path.join(tmp_path, "test.db")
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
             VALUES ('Apo4501','Apo','Apoquindo 4501',1.0),
                    ('Apo4700','Apo','Apoquindo 4700',1.0);
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


def test_persist_inserta_60_filas(fixture_xlsx, db_conn):
    res = mod.persist(fixture_xlsx, conn=db_conn)
    assert res["status"] == "inserted"
    assert res["rows"] == 60
    n = db_conn.execute(
        "SELECT COUNT(*) FROM raw_er_activo_line WHERE superseded_at IS NULL"
    ).fetchone()[0]
    assert n == 60


def test_persist_idempotente_mismo_hash(fixture_xlsx, db_conn):
    mod.persist(fixture_xlsx, conn=db_conn)
    res2 = mod.persist(fixture_xlsx, conn=db_conn)
    assert res2["status"] == "skipped_idempotent"
    n = db_conn.execute(
        "SELECT COUNT(*) FROM raw_er_activo_line WHERE superseded_at IS NULL"
    ).fetchone()[0]
    assert n == 60  # no duplica


def test_persist_reingesta_supersede_previas(fixture_xlsx, tmp_path, db_conn):
    mod.persist(fixture_xlsx, conn=db_conn)
    # Crear un xlsx con contenido distinto → hash distinto
    fixture_xlsx_2 = _build_fixture_xlsx(str(tmp_path / "sub"))
    # Modificar un valor para cambiar el hash
    import openpyxl as _ox
    wb = _ox.load_workbook(fixture_xlsx_2)
    wb.active.cell(row=1, column=1).value = "Fondo Apoquindo v2"
    wb.save(fixture_xlsx_2)

    res = mod.persist(fixture_xlsx_2, conn=db_conn)
    assert res["status"] == "superseded_and_reinserted"
    activos_total = db_conn.execute(
        "SELECT COUNT(*) FROM raw_er_activo_line"
    ).fetchone()[0]
    activas = db_conn.execute(
        "SELECT COUNT(*) FROM raw_er_activo_line WHERE superseded_at IS NULL"
    ).fetchone()[0]
    superseded = activos_total - activas
    assert activas == 60
    assert superseded == 60


def test_noi_calculado_matchea_suma(fixture_xlsx, db_conn):
    mod.persist(fixture_xlsx, conn=db_conn)
    # NOI 2025-01 Apo4501 según fixture: sum sobre 10 categorías, mi=1, base=45
    # Ingresos (cat_idx=0, sign=+1): 1*1000 + 0*100 + 45 = 1045
    # Gastos (cat_idx=1..9, sign=-1): sum_i -(1000 + i*100 + 45)
    esperado = 1045 + sum(-(1000 + i*100 + 45) for i in range(1, 10))
    calc = db_conn.execute("""
        SELECT SUM(monto_clp) FROM raw_er_activo_line
         WHERE activo_key='Apo4501' AND periodo='2025-01'
           AND es_operacional=1 AND superseded_at IS NULL
    """).fetchone()[0]
    assert abs(calc - esperado) < 0.01
```

- [ ] **Step 3: Correr tests — nuevos fallan porque `persist` no existe**

Run: `python -m pytest tests/db/test_ingest_er_apoquindo.py -v`
Expected: los 8 anteriores pasan; los 4 nuevos fallan con `AttributeError: ... 'persist'`.

- [ ] **Step 4: Implementar `persist` + CLI**

Append to `tools/db/ingest_er_apoquindo.py`:

```python
# ── Persistencia ───────────────────────────────────────────────────────────────

import sqlite3
from datetime import datetime


def _register_ingest_run(conn: sqlite3.Connection, source_file: str,
                          file_hash: str, rows_in: int) -> int:
    cur = conn.execute(
        """INSERT INTO ingest_run (tool, source_file, file_hash, rows_in,
                                    started_at, status)
             VALUES (?, ?, ?, ?, ?, 'running')""",
        ("ingest_er_apoquindo", source_file, file_hash, rows_in,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    return cur.lastrowid


def _finish_ingest_run(conn: sqlite3.Connection, run_id: int,
                        rows_loaded: int, status: str,
                        error: Optional[str] = None) -> None:
    conn.execute(
        """UPDATE ingest_run
              SET ended_at = ?, rows_loaded = ?, status = ?, error = ?
            WHERE id = ?""",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         rows_loaded, status, error, run_id),
    )
    conn.commit()


def persist(xlsx_path: str,
            conn: Optional[sqlite3.Connection] = None) -> dict:
    """Ingesta idempotente. Ver docstring del módulo."""
    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()

    try:
        file_hash = _file_hash(xlsx_path)

        # 1) Idempotencia: ¿ya corrimos con este hash y quedó en success?
        prev = conn.execute(
            """SELECT id FROM ingest_run
                WHERE tool = 'ingest_er_apoquindo'
                  AND file_hash = ? AND status = 'success'
                LIMIT 1""",
            (file_hash,),
        ).fetchone()
        if prev is not None:
            return {"status": "skipped_idempotent", "rows": 0,
                    "file_hash": file_hash, "ingest_run_id": None}

        # 2) Parsear
        lines = parse_planilla(xlsx_path)
        for line in lines:
            line["file_hash"] = file_hash

        # 3) ¿Existen filas previas de este ingestor (otro hash) para
        #    los mismos activos? Marcarlas superseded.
        any_previous = conn.execute(
            """SELECT COUNT(*) FROM raw_er_activo_line
                WHERE activo_key IN ('Apo4501','Apo4700')
                  AND cuenta_codigo LIKE 'APO\\_%' ESCAPE '\\'
                  AND superseded_at IS NULL""",
        ).fetchone()[0]

        if any_previous > 0:
            conn.execute(
                """UPDATE raw_er_activo_line
                      SET superseded_at = datetime('now')
                    WHERE activo_key IN ('Apo4501','Apo4700')
                      AND cuenta_codigo LIKE 'APO\\_%' ESCAPE '\\'
                      AND superseded_at IS NULL""",
            )
            conn.commit()
            status = "superseded_and_reinserted"
        else:
            status = "inserted"

        # 4) Registrar corrida e insertar
        run_id = _register_ingest_run(conn, xlsx_path, file_hash, len(lines))
        try:
            from tools.db import repo_er_activo
            inserted = repo_er_activo.insert_lines(conn, lines, run_id)
        except Exception:
            # Fallback inline si repo no está disponible (tests aislados)
            inserted = _insert_lines_inline(conn, lines, run_id)

        _finish_ingest_run(conn, run_id, inserted, "success")
        return {"status": status, "rows": inserted,
                "file_hash": file_hash, "ingest_run_id": run_id}
    finally:
        if owns_conn:
            conn.close()


def _insert_lines_inline(conn: sqlite3.Connection, lines: list[dict],
                          run_id: int) -> int:
    cols = ["activo_key", "periodo", "cuenta_codigo", "cuenta_nombre",
            "monto_clp", "monto_uf", "seccion", "es_operacional",
            "source_file", "source_sheet", "source_row", "file_hash",
            "ingest_run_id"]
    sql = f"INSERT INTO raw_er_activo_line ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})"
    n = 0
    for line in lines:
        vals = tuple(run_id if c == "ingest_run_id" else line.get(c) for c in cols)
        conn.execute(sql, vals)
        n += 1
    conn.commit()
    return n


# ── CLI ────────────────────────────────────────────────────────────────────────

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
        periodos = sorted({r['periodo'] for r in rows})
        activos = sorted({r['activo_key'] for r in rows})
        print(f"  periodos: {periodos}")
        print(f"  activos:  {activos}")
        # Mostrar NOI por activo/periodo
        from collections import defaultdict
        noi = defaultdict(float)
        for r in rows:
            noi[(r['activo_key'], r['periodo'])] += r['monto_clp']
        print("  NOI (M$):")
        for k in sorted(noi.keys()):
            print(f"    {k[0]} {k[1]}: {noi[k]:>15,.0f}")
        return 0

    res = persist(args.xlsx)
    print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Correr tests — todos deben pasar**

Run: `python -m pytest tests/db/test_ingest_er_apoquindo.py -v`
Expected: 12 passed.

- [ ] **Step 6: Verificar CLI --dry-run con el fixture**

Run:
```bash
python -c "
import tempfile, os, openpyxl
from tests.db.test_ingest_er_apoquindo import _build_fixture_xlsx
tmp = tempfile.mkdtemp()
p = _build_fixture_xlsx(tmp)
os.system(f'python -m tools.db.ingest_er_apoquindo {p} --dry-run')
"
```
Expected: imprime `Parsed 60 filas`, periodos `['2024-12','2025-01','2025-02']`, activos `['Apo4501','Apo4700']`, y una tabla de NOI de 6 líneas.

- [ ] **Step 7: Commit**

```bash
git add tools/db/ingest_er_apoquindo.py tests/db/test_ingest_er_apoquindo.py
git commit -m "feat(er-apo): persistencia idempotente y CLI --dry-run"
```

---

### Task 4: Ingerir planilla real + documentar

**Files:**
- Modify: `wiki/log.md`
- Modify o Create: `wiki/fondos/apoquindo.md`

**Interfaces:**
- Consumes: la planilla real (path lo entrega el usuario cuando arranca esta task).
- Produces: filas en DB de producción + documentación viva.

- [ ] **Step 1: Localizar la planilla real**

La planilla está en `SHAREPOINT_DIR/raw/NOI/` (según instrucción del usuario 2026-07-09). Buscarla:

```bash
python -c "
import os
base = os.path.join(os.environ.get('SHAREPOINT_DIR',''), 'raw', 'NOI')
for r,d,fs in os.walk(base):
    for f in fs:
        if f.lower().endswith('.xlsx') and ('apo' in f.lower() or '4501' in f or '4700' in f):
            print(os.path.join(r,f))
"
```
Si aparecen múltiples candidatos, pedir confirmación al usuario. **No continuar hasta tener el path definitivo.**

- [ ] **Step 2: Correr --dry-run contra la planilla real**

Run:
```bash
python -m tools.db.ingest_er_apoquindo "<path_planilla>" --dry-run
```
Expected: mostrar N meses × 2 activos × 10 categorías. Verificar visualmente que la tabla de NOI cuadra con la fila "NOI Mensual" de la planilla en al menos 3 meses (spot check dic-24, mar-25, jun-25 de la imagen: 12.901, 13.209, 14.680 respectivamente para Fondo Apoquindo total). Si no cuadra, debug el parser antes de escribir DB.

- [ ] **Step 3: Backup DB antes de escribir**

Run:
```bash
cp memory/agente_toesca_v2.db memory/agente_toesca_v2.db.bak_pre_apo_er
```

- [ ] **Step 4: Correr persistencia real**

Run:
```bash
python -m tools.db.ingest_er_apoquindo "<path_planilla>"
```
Expected: imprime `{'status': 'inserted', 'rows': N, 'file_hash': '...', 'ingest_run_id': N}`.

- [ ] **Step 5: Verificar en DB**

Run:
```bash
python -c "
import sqlite3
c = sqlite3.connect('memory/agente_toesca_v2.db')
print('--- Filas activas por activo ---')
for r in c.execute('''
    SELECT activo_key, COUNT(*), MIN(periodo), MAX(periodo)
      FROM raw_er_activo_line
     WHERE activo_key IN ('Apo4501','Apo4700') AND superseded_at IS NULL
     GROUP BY activo_key
'''): print(r)
print()
print('--- NOI Fondo Apo por periodo (últimos 6) ---')
for r in c.execute('''
    SELECT periodo, ROUND(SUM(monto_clp)/1000.0, 0) AS noi_MM_clp
      FROM raw_er_activo_line
     WHERE activo_key IN ('Apo4501','Apo4700')
       AND es_operacional=1 AND superseded_at IS NULL
     GROUP BY periodo
     ORDER BY periodo DESC LIMIT 6
'''): print(r)
"
```
Expected: cada activo con el N esperado de meses; NOI de junio-25 ≈ 14.680 M$ según la imagen. **Presentar el output al usuario para validación humana.**

- [ ] **Step 6: Actualizar wiki/log.md**

Append a `wiki/log.md`:

```markdown
## [2026-07-09] ingesta | ER Fondo Apoquindo (Apo4501, Apo4700) desde planilla local

- Fuente: `<path_planilla_relativo_a_SHAREPOINT_DIR>`
- Destino: `raw_er_activo_line` — pseudo-códigos `APO_*` (10 categorías por activo por mes)
- Periodos: `<YYYY-MM>` a `<YYYY-MM>` (`<N>` meses × 2 activos × 10 categorías = `<N*20>` filas)
- Fix incluido: `dim_activo.participacion_fondo_activo` = 1.0 para Apo4501/Apo4700 (antes 0.3, era relación fondo-fondo mal ubicada)
- Idempotencia: `file_hash` SHA-256. Re-ingestar el mismo xlsx es no-op; re-ingestar uno modificado marca las viejas `superseded_at` y escribe nuevas.
- NOI: derivado con `SUM(monto_clp) WHERE es_operacional=1 GROUP BY activo_key, periodo`. No se persiste.
- Consolidación fondo Apo: `SUM(noi_activo * participacion_fondo_activo)` con `fondo_key='Apo'` → suma directa (participación 1.0).
```

- [ ] **Step 7: Crear/actualizar wiki/fondos/apoquindo.md**

Escribir `wiki/fondos/apoquindo.md` (o parche si ya existe) con al menos:

```markdown
# Fondo Apoquindo

## Estructura

- Fondo paraguas TRI tiene **30%** del fondo Apoquindo (relación fondo-fondo).
- Fondo Apoquindo tiene **100%** de sus dos activos: Apo4501, Apo4700.
- Ambos activos en `dim_activo` con `participacion_fondo_activo = 1.0`.

## Estado de Resultado — fuente actual (2026-07)

Mientras no llegan APIs de JLL y Tres A, el ER mensual se ingesta desde una planilla
local en formato "resumen por categoría" (10 categorías por activo por mes).

- Ingestor: `tools/db/ingest_er_apoquindo.py`
- Comando: `python -m tools.db.ingest_er_apoquindo <xlsx> [--dry-run]`
- Tabla destino: `raw_er_activo_line`
- Pseudo-códigos: `APO_ING_ARR`, `APO_GC_VAC`, `APO_COM_CORR`, `APO_ADM`,
  `APO_PROV_REP`, `APO_BONOS_LEG`, `APO_CONSTRUCT`, `APO_IVA_NR`, `APO_CONTRIB`,
  `APO_SEG` — todos con `es_operacional=1`.

## Consultas útiles

NOI mensual por activo:
```sql
SELECT activo_key, periodo, SUM(monto_clp) AS noi_clp
  FROM raw_er_activo_line
 WHERE activo_key IN ('Apo4501','Apo4700')
   AND es_operacional=1 AND superseded_at IS NULL
 GROUP BY activo_key, periodo;
```

## Contribuciones futuras — pendiente (fuera de este plan)

Para meses sin dato en la planilla, la contribución total mensual acordada 2026-07-09 es
`(-165.941.575 - 62.167.695) / 3 = -76.036.423,33 CLP/mes` (constante). En UF: dividir por
UF del mes (`fact_uf`). Reparto: **Apo4700 = 25%**, **Apo4501 = 75%**.

Cuando llegue el primer mes sin dato, abrir un plan aparte para ingestor "forecast contribuciones Apo"
(o resolverlo on-the-fly en query). Referencia: sección Out-of-scope del spec.

NOI Fondo Apo consolidado:
```sql
SELECT r.periodo, SUM(r.monto_clp * a.participacion_fondo_activo) AS noi_fondo
  FROM raw_er_activo_line r
  JOIN dim_activo a ON a.activo_key = r.activo_key
 WHERE a.fondo_key = 'Apo'
   AND r.es_operacional = 1 AND r.superseded_at IS NULL
 GROUP BY r.periodo;
```
```

- [ ] **Step 8: Commit wiki + push**

```bash
git add wiki/log.md wiki/fondos/apoquindo.md
git commit -m "wiki: ER Fondo Apoquindo — ingesta local mientras no hay API"
git push
```

---

## Self-Review

**Spec coverage:**
- D1 (reutilizar `raw_er_activo_line`): Task 3, `persist` inserta directo → ✓
- D2 (10 pseudo-códigos): Task 2 `_CATEGORIAS`, tests validan → ✓
- D3 (signo contable): Task 2 tests `test_parse_signos` → ✓
- D4 (NOI derivado): Task 2 `test_parse_noi_row_ignorada`, Task 3 `test_noi_calculado_matchea_suma`, Task 4 verificación con `SUM(monto_clp) WHERE es_operacional=1` → ✓
- D5 (idempotencia): Task 3 tests `test_persist_idempotente_mismo_hash` y `test_persist_reingesta_supersede_previas` → ✓
- D6 (fix participación): Task 1 completo → ✓
- Verificación NOI real vs planilla (spec Verificación §3): Task 4 Step 2 y Step 5 → ✓
- Wiki update: Task 4 Steps 6-7 → ✓

**Placeholder scan:** ninguno.

**Type consistency:** `parse_planilla` retorna `list[dict]` con claves canónicas de `raw_er_activo_line`; `persist` consume esos dicts y agrega `file_hash` + `ingest_run_id`. Firmas coinciden entre tasks. `_CATEGORIAS` es la única fuente de pseudo-códigos.

Plan listo y guardado en [docs/superpowers/plans/2026-07-09-apoquindo-er-ingesta.md](docs/superpowers/plans/2026-07-09-apoquindo-er-ingesta.md).
