# Mercado Comercio (CNC) — tabla del fact sheet TRI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el placeholder de la tabla "Variaciones Reales Acumuladas Total Locales RM (CNC)" en la página 3 del fact sheet TRI por datos reales, con carga histórica única desde un Excel y una vía de ingesta mensual manual (paste-text) hacia adelante.

**Architecture:** Nueva tabla `raw_mercado_comercio` (periodo, categoria, variación %) poblada por (a) un backfill único desde el Excel histórico del usuario y (b) un módulo de ingesta paste-text (`validate`/`commit`) expuesto vía 3 endpoints Flask en `scripts/ingesta_server.py` y un subtab nuevo "Supermercados" en `web/ingesta.html` (mismo patrón ya usado para `raw_mercado_bodegas`). `build_factsheet.py` lee la fila del período operacional vigente y la pinta en la tabla ya existente en el HTML (`#tbl-comercio-thead`/`#tbl-comercio-tbody`).

**Tech Stack:** Python 3.12, sqlite3, Flask, openpyxl, pytest — mismas herramientas que el resto de `tools/db/` e `ingesta_server.py`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-10-mercado-comercio-cnc-design.md`.
- `periodo` siempre `'YYYY-MM'` (string) — normativa global del proyecto (`CLAUDE.md`).
- `loaded_at` siempre `'YYYY-MM-DD HH:MM:SS'` (sin `T`) — usar `DEFAULT (datetime('now'))`.
- Filtrar siempre `WHERE superseded_at IS NULL` en `raw_mercado_comercio`.
- Sin columnas de fuente/URL/referencia en la tabla (confirmado con el usuario).
- La tabla del fact sheet muestra una sola fila (mes operacional vigente), no histórico.
- No exponer CLI en los módulos de `tools/db/` (los consume `ingesta_server.py`, mismo criterio que `ingest_mercado_bodegas.py`).
- Categorías fijas y su orden (idénticas string a string a `centros_comerciales.categorias` en `build_factsheet.py`):
  `"Total Comercio", "Vestuario", "Calzado", "Artefactos Eléctricos", "Línea Hogar", "Muebles", "Supermercados"`.
  En el Excel/PDF de origen la última categoría se llama **"Supermercado Tradicional"** — se debe mapear a `"Supermercados"` al ingestar/leer.

---

### Task 1: Migración `raw_mercado_comercio`

**Files:**
- Create: `tools/db/migrations/080_raw_mercado_comercio.sql`
- Test: `tests/db/test_migrations.py` (si existe un test genérico que aplica todas las migraciones y verifica schema_version — si no existe, verificar con `tests/db/test_ingest_mercado_bodegas.py` como referencia de cómo se testea `apply_migrations`)

**Interfaces:**
- Produces: tabla `raw_mercado_comercio(id, periodo, categoria, variacion_acumulada_pct, file_hash, source_row, ingest_run_id, loaded_at, superseded_at)`, usada por Task 2, Task 3 y Task 6.

- [ ] **Step 1: Crear el archivo de migración**

```sql
-- 080: mercado de comercio minorista RM (CNC, mensual) — variaciones reales
-- acumuladas por categoría. Alimenta la tabla "Variaciones Reales
-- Acumuladas Total Locales RM (CNC)" de la página 3 del fact sheet TRI
-- (S.page3.centros_comerciales). Sin columnas de fuente/URL: no se
-- necesitan para esta tabla (a diferencia de raw_mercado_bodegas).

CREATE TABLE raw_mercado_comercio (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo                 TEXT NOT NULL,   -- 'YYYY-MM'
    categoria               TEXT NOT NULL,   -- una de las 7 categorías fijas (ver build_factsheet.py)
    variacion_acumulada_pct REAL,            -- fracción: 0.007 = 0,7%
    file_hash               TEXT,
    source_row              INTEGER,
    ingest_run_id           INTEGER REFERENCES ingest_run(id),
    loaded_at               TEXT DEFAULT (datetime('now')),
    superseded_at           TEXT,
    UNIQUE(periodo, categoria, file_hash)
);

CREATE INDEX idx_mercado_comercio_periodo ON raw_mercado_comercio(periodo);
CREATE INDEX idx_mercado_comercio_lookup ON raw_mercado_comercio(periodo, categoria)
    WHERE superseded_at IS NULL;
```

- [ ] **Step 2: Verificar que la migración aplica sin errores**

Run: `python -c "from tools.db.connection import apply_migrations; apply_migrations(':memory:'); print('ok')"`

(Si `apply_migrations` no acepta `':memory:'`, usar un archivo temporal: `python -c "from tools.db.connection import apply_migrations; apply_migrations('scratch_test.db'); print('ok')"` y luego borrar `scratch_test.db`.)

Expected: imprime `ok` sin excepciones — confirma que el SQL es válido y no colisiona con migraciones previas.

- [ ] **Step 3: Commit**

```bash
git add tools/db/migrations/080_raw_mercado_comercio.sql
git commit -m "feat(db): agrega tabla raw_mercado_comercio (CNC, comercio minorista RM)"
```

---

### Task 2: Módulo de ingesta paste-text `tools/db/ingest_mercado_comercio.py`

**Files:**
- Create: `tools/db/ingest_mercado_comercio.py`
- Test: `tests/db/test_ingest_mercado_comercio.py`

**Interfaces:**
- Consumes: tabla `raw_mercado_comercio` (Task 1); `tools.db.connection.get_conn_for` (ya existe).
- Produces: `CATEGORIAS_ORDEN: tuple[str, ...]` (las 7 categorías, en orden), `parse_fila_comercio(texto: str) -> dict[str, float | None]`, `ValidationResult` (misma forma que en `ingest_mercado_bodegas.py`: `.ok`, `.errors`, `.warnings`, `.data`, `.to_dict()`), `validate(texto: str, periodo: str) -> ValidationResult`, `commit(texto: str, periodo: str) -> dict` (misma forma que bodegas: `{"status", "run_id", "filas_insertadas", "filas_superseded"}`). Usado por Task 4 (endpoints).

- [ ] **Step 1: Escribir el test de parseo (falla primero)**

```python
"""Tests para tools.db.ingest_mercado_comercio."""
from __future__ import annotations

import pytest

from tools.db import ingest_mercado_comercio as mod
from tools.db.connection import apply_migrations, get_conn_for

# Fila real: Junio 2026/2025 (última fila del Excel histórico del usuario).
# Orden: Total Comercio, Vestuario, Calzado, Artefactos Eléctricos,
# Línea Hogar, Muebles, Supermercado Tradicional.
TEXTO_JUN_2026 = "-0,9% 6,2% -3,0% -9,1% 0,2% -0,6% -1,2%"


def test_parse_fila_comercio_ok():
    fila = mod.parse_fila_comercio(TEXTO_JUN_2026)
    assert fila["Total Comercio"] == pytest.approx(-0.009)
    assert fila["Vestuario"] == pytest.approx(0.062)
    assert fila["Calzado"] == pytest.approx(-0.03)
    assert fila["Artefactos Eléctricos"] == pytest.approx(-0.091)
    assert fila["Línea Hogar"] == pytest.approx(0.002)
    assert fila["Muebles"] == pytest.approx(-0.006)
    assert fila["Supermercados"] == pytest.approx(-0.012)


def test_parse_fila_comercio_con_encabezado_y_guion():
    texto = (
        "Total Comercio Vestuario Calzado Artefactos Eléctricos Línea Hogar Muebles Supermercado Tradicional\n"
        "0,7% 4,0% -4,5% 0,3% 5,3% -3,6% -0,2%"
    )
    fila = mod.parse_fila_comercio(texto)
    assert fila["Total Comercio"] == pytest.approx(0.007)
    assert fila["Supermercados"] == pytest.approx(-0.002)


def test_parse_fila_comercio_valor_faltante_como_guion():
    texto = "0,7% 4,0% -4,5% 0,3% 5,3% - -0,2%"
    fila = mod.parse_fila_comercio(texto)
    assert fila["Muebles"] is None


def test_parse_fila_comercio_sin_fila_valida_retorna_none():
    assert mod.parse_fila_comercio("esto no es una tabla") is None
```

- [ ] **Step 2: Ejecutar los tests de parseo y verificar que fallan**

Run: `pytest tests/db/test_ingest_mercado_comercio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.db.ingest_mercado_comercio'`.

- [ ] **Step 3: Implementar el parseo**

```python
"""Ingesta de datos de mercado de comercio minorista RM (CNC, mensual)
desde texto copy-paste de la fila "Ventas del Comercio Acumuladas" del
PDF mensual de CNC.

Formato de entrada esperado: una línea con 7 valores en el orden fijo de
CATEGORIAS_ORDEN, separados por espacio/tab, "%" opcional, "-" como null:

    -0,9% 6,2% -3,0% -9,1% 0,2% -0,6% -1,2%

Se ignoran líneas de encabezado (cualquier línea que no tenga exactamente
7 tokens numéricos/"-").

No expone CLI; lo consume scripts/ingesta_server.py (Flask).
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"

sys.path.insert(0, str(ROOT))
from tools.db.connection import get_conn_for  # noqa: E402

# Orden fijo — idéntico a S.page3.centros_comerciales.categorias en
# build_factsheet.py. La fuente (Excel/PDF CNC) llama a la última columna
# "Supermercado Tradicional"; el fact sheet la muestra como "Supermercados".
CATEGORIAS_ORDEN = (
    "Total Comercio", "Vestuario", "Calzado", "Artefactos Eléctricos",
    "Línea Hogar", "Muebles", "Supermercados",
)


def _parse_num_cl(raw: str) -> float | None:
    """Convierte formato numérico chileno (con % opcional) a fracción, o
    None si es '-'.

    '0,7%'  -> 0.007   (coma = decimal, se descarta el %, se divide /100)
    '-0,9%' -> -0.009
    '-'     -> None
    """
    s = raw.strip().rstrip("%").strip()
    if s == "-":
        return None
    s = s.replace(".", "").replace(",", ".")
    return float(s) / 100.0


def _looks_like_valor(tok: str) -> bool:
    if tok == "-":
        return True
    s = tok.rstrip("%").replace(".", "").replace(",", ".")
    try:
        float(s)
        return True
    except ValueError:
        return False


def parse_fila_comercio(texto: str) -> dict[str, float | None] | None:
    """Busca, entre las líneas del texto pegado, la primera con exactamente
    7 tokens numéricos/"-" y la mapea a CATEGORIAS_ORDEN.

    Retorna None si ninguna línea calza.
    """
    for line in texto.strip().splitlines():
        tokens = line.split()
        if len(tokens) != len(CATEGORIAS_ORDEN):
            continue
        if not all(_looks_like_valor(t) for t in tokens):
            continue
        valores = [_parse_num_cl(t) for t in tokens]
        return dict(zip(CATEGORIAS_ORDEN, valores))
    return None
```

- [ ] **Step 4: Ejecutar los tests de parseo y verificar que pasan**

Run: `pytest tests/db/test_ingest_mercado_comercio.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Escribir los tests de validate/commit (falla primero)**

Agregar al mismo archivo de test:

```python
@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    monkeypatch.setattr(mod, "DB_PATH", db_path)
    return db_path


def test_validate_sin_periodo():
    result = mod.validate(TEXTO_JUN_2026, "")
    assert not result.ok
    assert any("período" in e.lower() for e in result.errors)


def test_validate_texto_invalido():
    result = mod.validate("esto no es una tabla", "2026-06")
    assert not result.ok
    assert any("fila válida" in e for e in result.errors)


def test_validate_ok(db):
    result = mod.validate(TEXTO_JUN_2026, "2026-06")
    assert result.ok
    assert result.data["periodo"] == "2026-06"
    assert len(result.data["fila"]) == 7


def test_commit_inserta_filas(db):
    result = mod.commit(TEXTO_JUN_2026, "2026-06")
    assert result["status"] == "ok"
    assert result["filas_insertadas"] == 7
    assert result["filas_superseded"] == 0

    con = get_conn_for(db)
    n = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_comercio WHERE periodo='2026-06' AND superseded_at IS NULL"
    ).fetchone()[0]
    supermercados = con.execute(
        "SELECT variacion_acumulada_pct FROM raw_mercado_comercio "
        "WHERE periodo='2026-06' AND categoria='Supermercados' AND superseded_at IS NULL"
    ).fetchone()[0]
    con.close()
    assert n == 7
    assert supermercados == pytest.approx(-0.012)


def test_commit_idempotente_mismo_texto(db):
    mod.commit(TEXTO_JUN_2026, "2026-06")
    result2 = mod.commit(TEXTO_JUN_2026, "2026-06")
    assert result2["status"] == "skipped_duplicate"
    assert result2["filas_insertadas"] == 0


def test_commit_reemplaza_periodo_con_texto_distinto(db):
    mod.commit(TEXTO_JUN_2026, "2026-06")
    texto_v2 = TEXTO_JUN_2026.replace("-1,2%", "-1,5%")
    result2 = mod.commit(texto_v2, "2026-06")
    assert result2["status"] == "ok"
    assert result2["filas_superseded"] == 7

    con = get_conn_for(db)
    vigentes = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_comercio WHERE periodo='2026-06' AND superseded_at IS NULL"
    ).fetchone()[0]
    con.close()
    assert vigentes == 7
```

- [ ] **Step 6: Ejecutar y verificar que fallan**

Run: `pytest tests/db/test_ingest_mercado_comercio.py -v -k "validate or commit"`
Expected: FAIL — `AttributeError: module 'tools.db.ingest_mercado_comercio' has no attribute 'validate'`.

- [ ] **Step 7: Implementar validate/commit**

Agregar al mismo archivo (`tools/db/ingest_mercado_comercio.py`):

```python
class ValidationResult:
    """Resultado de validación con errores, warnings y datos parseados."""
    def __init__(self):
        self.ok = True
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.data: dict = {}

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.ok = False

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, **self.data}


def validate(texto: str, periodo: str) -> ValidationResult:
    """Valida que el texto contenga una fila con las 7 categorías.

    Retorna ValidationResult con ok=True/False, errores, warnings, y datos parseados.
    """
    result = ValidationResult()

    if not periodo:
        result.add_error("Falta declarar el período (YYYY-MM) del informe.")
        return result
    if not texto.strip():
        result.add_error("Pega la fila de valores antes de validar.")
        return result

    fila = parse_fila_comercio(texto)
    if fila is None:
        result.add_error(
            "No se detectó una fila válida — revisa que el texto pegado tenga "
            "exactamente 7 valores numéricos o '-' (Total Comercio, Vestuario, "
            "Calzado, Artefactos Eléctricos, Línea Hogar, Muebles, Supermercados)."
        )
        return result

    for categoria, valor in fila.items():
        if valor is not None and abs(valor) > 1:
            result.add_error(f"{categoria}: valor fuera de rango razonable ({valor * 100:.1f}%)")

    if not result.ok:
        return result

    fhash = hashlib.sha256(f"{periodo}|{texto.strip()}".encode("utf-8")).hexdigest()

    con = get_conn_for(str(DB_PATH))
    try:
        n_existentes = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_comercio WHERE periodo=? AND superseded_at IS NULL",
            (periodo,),
        ).fetchone()[0]
        ya_mismo_hash = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_comercio WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
    finally:
        con.close()

    if n_existentes:
        result.warnings.append(
            f"Ya existen {n_existentes} fila(s) vigentes para {periodo}. "
            "Si confirmas, se marcarán como reemplazadas y se insertarán las nuevas."
        )

    result.data = {
        "periodo": periodo,
        "fila": fila,
        "file_hash": fhash,
        "ya_ingestado": bool(ya_mismo_hash),
    }
    return result


def commit(texto: str, periodo: str) -> dict:
    """Valida y persiste los datos en la DB.

    Retorna {"status": "ok"|"skipped_duplicate", "run_id": int|None,
             "filas_insertadas": int, "filas_superseded": int}.
    Lanza ValueError si la validación falla.
    """
    result = validate(texto, periodo)
    if not result.ok:
        raise ValueError("No se puede ingestar: " + "; ".join(result.errors))

    fila = result.data["fila"]
    fhash = result.data["file_hash"]

    con = get_conn_for(str(DB_PATH))
    try:
        existing_hash_count = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_comercio WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
        if existing_hash_count:
            return {"status": "skipped_duplicate", "run_id": None, "filas_insertadas": 0, "filas_superseded": 0}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = con.execute(
            """INSERT INTO ingest_run (tool, source_file, file_hash, started_at, status, periodo_declarado)
               VALUES (?,?,?,?,?,?)""",
            ("ingest_mercado_comercio", f"cnc_manual_{periodo}", fhash, now, "running", periodo),
        )
        run_id = cur.lastrowid

        cur2 = con.execute(
            """UPDATE raw_mercado_comercio SET superseded_at=?
               WHERE periodo=? AND superseded_at IS NULL""",
            (now, periodo),
        )
        filas_superseded = cur2.rowcount if cur2.rowcount > 0 else 0

        rows = [
            (periodo, categoria, valor, fhash, idx, run_id)
            for idx, (categoria, valor) in enumerate(fila.items())
        ]
        con.executemany(
            """INSERT INTO raw_mercado_comercio
               (periodo, categoria, variacion_acumulada_pct, file_hash, source_row, ingest_run_id)
               VALUES (?,?,?,?,?,?)""",
            rows,
        )

        con.execute(
            "UPDATE ingest_run SET status=?, ended_at=?, rows_in=?, rows_loaded=? WHERE id=?",
            ("ok", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(fila), len(rows), run_id),
        )
        con.commit()
        return {
            "status": "ok",
            "run_id": run_id,
            "filas_insertadas": len(rows),
            "filas_superseded": filas_superseded,
        }
    finally:
        con.close()
```

- [ ] **Step 8: Ejecutar todos los tests del módulo y verificar que pasan**

Run: `pytest tests/db/test_ingest_mercado_comercio.py -v`
Expected: todos PASS (11 tests).

- [ ] **Step 9: Commit**

```bash
git add tools/db/ingest_mercado_comercio.py tests/db/test_ingest_mercado_comercio.py
git commit -m "feat(db): ingesta paste-text mensual de mercado comercio (CNC)"
```

---

### Task 3: Backfill histórico desde el Excel del usuario

**Files:**
- Create: `tools/db/backfill_mercado_comercio.py`
- Test: `tests/db/test_backfill_mercado_comercio.py`

**Interfaces:**
- Consumes: tabla `raw_mercado_comercio` (Task 1); `CATEGORIAS_ORDEN` de `tools.db.ingest_mercado_comercio` (Task 2) para mantener el mismo orden/nombres de categoría.
- Produces: `backfill(xlsx_path: str, db_path: str | None = None) -> dict` con `{"status": "ok", "filas_insertadas": int, "periodos": list[str]}`. Se invoca desde CLI (`python -m tools.db.backfill_mercado_comercio <ruta.xlsx>`) — a diferencia de `ingest_mercado_comercio.py`, este SÍ es un script de un solo uso con CLI (mismo criterio que otros `backfill_*.py` en `tools/db/`).

- [ ] **Step 1: Escribir el test con un Excel fixture pequeño (falla primero)**

```python
"""Tests para tools.db.backfill_mercado_comercio."""
from __future__ import annotations

import openpyxl
import pytest

from tools.db import backfill_mercado_comercio as mod
from tools.db.connection import apply_migrations, get_conn_for


@pytest.fixture
def xlsx_fixture(tmp_path):
    """Excel mínimo con la misma estructura que el histórico real del
    usuario: encabezado en la fila 5, datos desde la fila 6, columnas
    Mes/Período acumulado/7 categorías/Fuente/Referencia."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Histórico publicado"
    ws.append(["CNC — Variaciones reales acumuladas | Total Locales RM"])
    ws.append(["nota"])
    ws.append(["nota 2"])
    ws.append([])
    ws.append([
        "Mes", "Período acumulado", "Total Comercio", "Vestuario", "Calzado",
        "Artefactos Eléctricos", "Línea Hogar", "Muebles",
        "Supermercado Tradicional", "Fuente CNC", "Referencia exacta",
    ])
    ws.append([
        "2025-03-01", "Mar. 2025/2024", 0.01, 0.047, -0.012, 0.065, 0.087,
        -0.017, -0.02, "https://example.com", "p. 4",
    ])
    ws.append([
        "2025-04-01", "Abr. 2025/2024", 0.018, 0.067, -0.01, 0.044, 0.089,
        -0.034, -0.008, "https://example.com", "p. 4",
    ])
    path = tmp_path / "cnc_fixture.xlsx"
    wb.save(path)
    return str(path)


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    return db_path


def test_backfill_inserta_18x7_filas(xlsx_fixture, db):
    result = mod.backfill(xlsx_fixture, db_path=db)
    assert result["status"] == "ok"
    assert result["filas_insertadas"] == 2 * 7
    assert result["periodos"] == ["2025-03", "2025-04"]

    con = get_conn_for(db)
    n = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_comercio WHERE superseded_at IS NULL"
    ).fetchone()[0]
    supermercados_mar = con.execute(
        "SELECT variacion_acumulada_pct FROM raw_mercado_comercio "
        "WHERE periodo='2025-03' AND categoria='Supermercados'"
    ).fetchone()[0]
    con.close()
    assert n == 14
    assert supermercados_mar == pytest.approx(-0.02)


def test_backfill_es_idempotente(xlsx_fixture, db):
    mod.backfill(xlsx_fixture, db_path=db)
    result2 = mod.backfill(xlsx_fixture, db_path=db)
    assert result2["filas_insertadas"] == 0

    con = get_conn_for(db)
    n = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_comercio WHERE superseded_at IS NULL"
    ).fetchone()[0]
    con.close()
    assert n == 14
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `pytest tests/db/test_backfill_mercado_comercio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.db.backfill_mercado_comercio'`.

- [ ] **Step 3: Implementar el backfill**

```python
"""Carga única del histórico de mercado de comercio minorista RM (CNC)
desde el Excel armado por el usuario (hoja "Histórico publicado").

Uso: python -m tools.db.backfill_mercado_comercio <ruta_al_xlsx>

Idempotente: usa hash del archivo completo como file_hash — reejecutar
con el mismo archivo no duplica filas.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"

sys.path.insert(0, str(ROOT))
from tools.db.connection import get_conn_for  # noqa: E402
from tools.db.ingest_mercado_comercio import CATEGORIAS_ORDEN  # noqa: E402

SHEET_NAME = "Histórico publicado"
HEADER_ROW = 5
FIRST_DATA_ROW = 6

# Nombre de columna en el Excel -> nombre de categoría en la DB (idéntico
# a CATEGORIAS_ORDEN salvo "Supermercado Tradicional" -> "Supermercados").
_COL_A_CATEGORIA = {
    "Total Comercio": "Total Comercio",
    "Vestuario": "Vestuario",
    "Calzado": "Calzado",
    "Artefactos Eléctricos": "Artefactos Eléctricos",
    "Línea Hogar": "Línea Hogar",
    "Muebles": "Muebles",
    "Supermercado Tradicional": "Supermercados",
}


def backfill(xlsx_path: str, db_path: str | None = None) -> dict:
    db_path = db_path or str(DEFAULT_DB_PATH)
    file_hash = hashlib.sha256(Path(xlsx_path).read_bytes()).hexdigest()

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb[SHEET_NAME]
    header = [c.value for c in ws[HEADER_ROW]]
    col_idx = {name: i for i, name in enumerate(header) if name in _COL_A_CATEGORIA}
    mes_idx = header.index("Mes")

    con = get_conn_for(db_path)
    try:
        ya_cargado = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_comercio WHERE file_hash=?", (file_hash,)
        ).fetchone()[0]
        if ya_cargado:
            return {"status": "skipped_duplicate", "filas_insertadas": 0, "periodos": []}

        rows_to_insert = []
        periodos = []
        source_row = 0
        for row in ws.iter_rows(min_row=FIRST_DATA_ROW, values_only=True):
            if row[mes_idx] is None:
                continue
            mes_val = row[mes_idx]
            periodo = mes_val.strftime("%Y-%m") if hasattr(mes_val, "strftime") else str(mes_val)[:7]
            periodos.append(periodo)
            for col_excel, categoria in _COL_A_CATEGORIA.items():
                valor = row[col_idx[col_excel]]
                rows_to_insert.append((periodo, categoria, valor, file_hash, source_row))
                source_row += 1

        con.executemany(
            """INSERT INTO raw_mercado_comercio
               (periodo, categoria, variacion_acumulada_pct, file_hash, source_row)
               VALUES (?,?,?,?,?)""",
            rows_to_insert,
        )
        con.commit()
        return {"status": "ok", "filas_insertadas": len(rows_to_insert), "periodos": periodos}
    finally:
        con.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python -m tools.db.backfill_mercado_comercio <ruta_al_xlsx>")
        sys.exit(1)
    resultado = backfill(sys.argv[1])
    print(resultado)
```

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `pytest tests/db/test_backfill_mercado_comercio.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db/backfill_mercado_comercio.py tests/db/test_backfill_mercado_comercio.py
git commit -m "feat(db): backfill histórico mercado comercio (CNC) desde Excel"
```

---

### Task 4: Endpoints Flask en `scripts/ingesta_server.py`

**Files:**
- Modify: `scripts/ingesta_server.py` (agregar import junto a la línea 45, y 3 endpoints nuevos junto a los de `/api/mercado/bodegas/*`)
- Test: `tests/test_ingesta_server_mercado_comercio.py`

**Interfaces:**
- Consumes: `tools.db.ingest_mercado_comercio.validate`/`commit` (Task 2); patrón `client` fixture con `tmp_db_path` ya usado en `tests/test_ingesta_server_mercado_bodegas.py`.
- Produces: `GET /api/mercado/comercio/periodo_check?periodo=YYYY-MM`, `POST /api/mercado/comercio/validate` `{texto, periodo}`, `POST /api/mercado/comercio/commit` `{texto, periodo}` — consumidos por Task 5 (frontend).

- [ ] **Step 1: Escribir el test de los endpoints (falla primero)**

```python
"""Tests de los endpoints /api/mercado/comercio/* de scripts/ingesta_server.py."""
from __future__ import annotations

import pytest

from tools.db.connection import apply_migrations
from tools.db import ingest_mercado_comercio

TEXTO_JUN_2026 = "-0,9% 6,2% -3,0% -9,1% 0,2% -0,6% -1,2%"


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(ingest_mercado_comercio, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        c.environ_base["HTTP_X_INGESTA_TOKEN"] = ingesta_server.API_TOKEN
        yield c


def test_periodo_check_no_ingestado(client):
    res = client.get("/api/mercado/comercio/periodo_check?periodo=2026-06")
    assert res.status_code == 200
    assert res.get_json()["ya_ingestado"] is False


def test_validate_endpoint_ok(client):
    res = client.post("/api/mercado/comercio/validate", json={
        "texto": TEXTO_JUN_2026, "periodo": "2026-06",
    })
    data = res.get_json()
    assert data["ok"] is True


def test_commit_endpoint_inserta_y_periodo_check_refleja(client):
    res = client.post("/api/mercado/comercio/commit", json={
        "texto": TEXTO_JUN_2026, "periodo": "2026-06",
    })
    data = res.get_json()
    assert data["ok"] is True
    assert data["filas_insertadas"] == 7

    res2 = client.get("/api/mercado/comercio/periodo_check?periodo=2026-06")
    assert res2.get_json()["ya_ingestado"] is True


def test_commit_endpoint_texto_invalido_retorna_400(client):
    res = client.post("/api/mercado/comercio/commit", json={
        "texto": "esto no es una tabla", "periodo": "2026-06",
    })
    assert res.status_code == 400
    assert res.get_json()["ok"] is False
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `pytest tests/test_ingesta_server_mercado_comercio.py -v`
Expected: FAIL — 404 en las rutas nuevas (no existen todavía).

- [ ] **Step 3: Agregar el import**

En `scripts/ingesta_server.py`, junto a la línea 45:

```python
from tools.db import ingest_mercado_comercio as mercado_comercio_core  # noqa: E402
```

- [ ] **Step 4: Agregar los 3 endpoints**

Justo después del bloque `@app.post("/api/mercado/bodegas/commit")` existente en `scripts/ingesta_server.py`:

```python
@app.get("/api/mercado/comercio/periodo_check")
def api_mercado_comercio_periodo_check():
    periodo = request.args.get("periodo", "")
    if not periodo:
        return jsonify({"ya_ingestado": False})
    con = get_conn_for(str(mercado_comercio_core.DB_PATH))
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_comercio "
            "WHERE periodo=? AND superseded_at IS NULL",
            (periodo,),
        ).fetchone()[0]
        return jsonify({"ya_ingestado": bool(n), "n_filas": n})
    finally:
        con.close()


@app.post("/api/mercado/comercio/validate")
def api_mercado_comercio_validate():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    result = mercado_comercio_core.validate(texto, periodo)
    return jsonify(result.to_dict())


@app.post("/api/mercado/comercio/commit")
def api_mercado_comercio_commit():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    try:
        summary = mercado_comercio_core.commit(texto, periodo)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    _rebuild_factsheet()
    return jsonify({"ok": True, **summary})
```

- [ ] **Step 5: Ejecutar y verificar que pasa**

Run: `pytest tests/test_ingesta_server_mercado_comercio.py -v`
Expected: 4 tests PASS.

- [ ] **Step 6: Correr toda la suite de tests de ingesta_server para descartar regresiones**

Run: `pytest tests/test_ingesta_server_mercado_bodegas.py tests/test_ingesta_server_mercado_comercio.py -v`
Expected: todos PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/ingesta_server.py tests/test_ingesta_server_mercado_comercio.py
git commit -m "feat(ingesta): endpoints /api/mercado/comercio/* (validate/commit/periodo_check)"
```

---

### Task 5: Subtab "Supermercados" en `web/ingesta.html`

**Files:**
- Modify: `web/ingesta.html` — HTML: agregar botón de subtab (junto a la línea 673) y panel (junto a la línea 782); JS: agregar bloque análogo al de bodegas (junto a la línea 2267) y registrar el nuevo subtab en el switch de subtabs (línea ~1247-1252) y en `_irAIngestar` (línea ~2602-2611).

**Interfaces:**
- Consumes: endpoints de Task 4 (`/api/mercado/comercio/periodo_check`, `/validate`, `/commit`); helpers ya existentes en el archivo: `setStatus(el, msg, kind)`, `fmt(v)`.
- Produces: UI funcional, sin test automatizado (verificación manual en Step 5).

- [ ] **Step 1: Agregar el botón de subtab**

En `web/ingesta.html`, modificar el bloque de subtabs (línea 671-674):

```html
    <div class="tabs" id="mercado-subtabs">
      <button class="er-subtab-btn active" data-mercadotab="oficinas">Oficinas</button>
      <button class="er-subtab-btn" data-mercadotab="bodegas">Bodegas</button>
      <button class="er-subtab-btn" data-mercadotab="comercio">Supermercados</button>
    </div>
```

- [ ] **Step 2: Agregar el panel HTML**

Justo después del `</div>` que cierra `#mercado-panel-bodegas` (línea 782), agregar:

```html
  <div id="mercado-panel-comercio" class="mercado-sub-panel hidden">

  <div class="step">
    <div class="step-title"><span class="step-num">1</span> Período</div>
    <div class="row">
      <label class="muted" for="mercadocom-periodo">Mes del informe:</label>
      <select id="mercadocom-periodo" style="width:160px">
        <option value="">Elige mes...</option>
      </select>
    </div>
    <div class="row" id="mercadocom-periodo-status-row" style="margin-top:6px"></div>
  </div>

  <div class="step">
    <div class="step-title"><span class="step-num">2</span> Busca el dato en el informe CNC y pégalo aquí</div>
    <ol class="instructions">
      <li>Busca en Google: <code>site:cnc.cl/wp-content/uploads/ "Ventas-Comercio-RM" "<span id="mercadocom-mes-busqueda">mes año</span>"</code></li>
      <li>Entra al PDF y busca el gráfico "Ventas del Comercio Acumuladas".</li>
      <li>Pega los 7 valores en una sola línea, en este orden: Total Comercio, Vestuario, Calzado, Artefactos Eléctricos, Línea Hogar, Muebles, Supermercados (usa "-" si algún valor no aparece).</li>
    </ol>
    <textarea id="mercadocom-input" placeholder="Ej: -0,9% 6,2% -3,0% -9,1% 0,2% -0,6% -1,2%"></textarea>
    <div class="row">
      <button id="btn-mercadocom-validate">Validar y previsualizar</button>
      <span id="mercadocom-validate-status" class="muted"></span>
    </div>

    <div id="mercadocom-preview" class="preview hidden">
      <div class="badges" id="mercadocom-badges"></div>
      <ul id="mercadocom-errors" class="msg-list err"></ul>
      <ul id="mercadocom-warnings" class="msg-list warn"></ul>

      <div id="mercadocom-section-tabla" class="hidden">
        <h3>Valores detectados</h3>
        <table>
          <thead><tr id="mercadocom-tabla-head"></tr></thead>
          <tbody><tr id="mercadocom-tabla-row"></tr></tbody>
        </table>
      </div>
    </div>

    <div class="row" style="margin-top:20px;">
      <button id="btn-mercadocom-confirm" disabled>Confirmar e ingestar</button>
      <span id="mercadocom-ingest-status" class="muted"></span>
    </div>
  </div>

  </div>
```

- [ ] **Step 3: Registrar el subtab en el switch existente**

En el bloque JS que maneja el click de subtabs (buscar `document.querySelectorAll('#mercado-subtabs .er-subtab-btn')` alrededor de la línea 1247), no requiere cambios — el selector genérico ya cubre el botón nuevo porque usa `.mercado-sub-panel` y `data-mercadotab`. Confirmar leyendo ese bloque y no duplicar lógica.

- [ ] **Step 4: Agregar el bloque JS de la subtab "comercio"**

Justo después de `populateMercadoBodegasSemestres(); checkMercadoBodPeriodoStatus();` (línea 2267-2268), agregar:

```javascript
let lastMercadoComTexto = null;
let lastMercadoComPeriodo = null;
let lastMercadoComValidationOk = false;

const MESES_LARGO_ES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];

function populateMercadoComercioMeses() {
  const now = new Date();
  const currentYear = now.getFullYear();
  const currentMonth = now.getMonth() + 1;
  for (let y = currentYear - 2; y <= currentYear + 1; y++) {
    for (let m = 1; m <= 12; m++) {
      const opt = document.createElement('option');
      const mm = String(m).padStart(2, '0');
      opt.value = `${y}-${mm}`;
      opt.textContent = `${MESES_LARGO_ES[m - 1].charAt(0).toUpperCase()}${MESES_LARGO_ES[m - 1].slice(1)} ${y}`;
      mercadoComPeriodo.appendChild(opt);
      if (y === currentYear && m === currentMonth) opt.selected = true;
    }
  }
}

function actualizarMercadoComBusqueda() {
  const periodo = mercadoComPeriodo.value;
  const el = document.getElementById('mercadocom-mes-busqueda');
  if (!periodo) { el.textContent = 'mes año'; return; }
  const [y, m] = periodo.split('-');
  const nombreMes = MESES_LARGO_ES[parseInt(m, 10) - 1];
  el.textContent = `${nombreMes.charAt(0).toUpperCase()}${nombreMes.slice(1)} ${y}`;
}

const mercadoComPeriodo = document.getElementById('mercadocom-periodo');
const mercadoComInput = document.getElementById('mercadocom-input');
const btnMercadoComValidate = document.getElementById('btn-mercadocom-validate');
const mercadoComValidateStatus = document.getElementById('mercadocom-validate-status');
const btnMercadoComConfirm = document.getElementById('btn-mercadocom-confirm');
const mercadoComIngestStatus = document.getElementById('mercadocom-ingest-status');
const mercadoComPeriodoStatusRow = document.getElementById('mercadocom-periodo-status-row');

async function checkMercadoComPeriodoStatus() {
  const periodo = mercadoComPeriodo.value;
  mercadoComPeriodoStatusRow.innerHTML = '';
  actualizarMercadoComBusqueda();
  if (!periodo) return;
  try {
    const res = await fetch(`/api/mercado/comercio/periodo_check?periodo=${periodo}`);
    const data = await res.json();
    if (data.ya_ingestado) {
      const el = document.createElement('span');
      el.className = 'badge';
      el.innerHTML = `<span class="dot warn"></span>${periodo} ya tiene datos vigentes — reingestar los reemplazará.`;
      mercadoComPeriodoStatusRow.appendChild(el);
    }
  } catch (e) { /* silencioso */ }
}
mercadoComPeriodo.addEventListener('change', checkMercadoComPeriodoStatus);

function resetMercadoComPreview() {
  document.getElementById('mercadocom-preview').classList.add('hidden');
  btnMercadoComConfirm.disabled = true;
  lastMercadoComValidationOk = false;
  setStatus(mercadoComValidateStatus);
  setStatus(mercadoComIngestStatus);
}
mercadoComInput.addEventListener('input', resetMercadoComPreview);
mercadoComPeriodo.addEventListener('change', resetMercadoComPreview);

const CATEGORIAS_COMERCIO = ['Total Comercio', 'Vestuario', 'Calzado', 'Artefactos Eléctricos', 'Línea Hogar', 'Muebles', 'Supermercados'];

function renderMercadoComPreview(data) {
  document.getElementById('mercadocom-preview').classList.remove('hidden');
  const badges = document.getElementById('mercadocom-badges');
  badges.innerHTML = '';
  const errUl = document.getElementById('mercadocom-errors');
  const warnUl = document.getElementById('mercadocom-warnings');
  errUl.innerHTML = '';
  warnUl.innerHTML = '';

  function addBadge(label, status) {
    const el = document.createElement('span');
    el.className = 'badge';
    el.innerHTML = `<span class="dot ${status}"></span>${label}`;
    badges.appendChild(el);
  }
  addBadge(data.ok ? 'Validación OK' : 'Validación con errores', data.ok ? 'ok' : 'err');
  (data.errors || []).forEach(e => {
    const li = document.createElement('li'); li.textContent = e; errUl.appendChild(li);
  });
  (data.warnings || []).forEach(w => {
    const li = document.createElement('li'); li.textContent = w; warnUl.appendChild(li);
  });

  if (data.ok && data.fila) {
    document.getElementById('mercadocom-section-tabla').classList.remove('hidden');
    document.getElementById('mercadocom-tabla-head').innerHTML =
      CATEGORIAS_COMERCIO.map(c => `<th>${c}</th>`).join('');
    document.getElementById('mercadocom-tabla-row').innerHTML =
      CATEGORIAS_COMERCIO.map(c => {
        const v = data.fila[c];
        return `<td class="num">${v === null || v === undefined ? '—' : (v * 100).toFixed(1) + '%'}</td>`;
      }).join('');
  } else {
    document.getElementById('mercadocom-section-tabla').classList.add('hidden');
  }

  lastMercadoComValidationOk = data.ok;
  btnMercadoComConfirm.disabled = !data.ok;
}

btnMercadoComValidate.addEventListener('click', async () => {
  const texto = mercadoComInput.value;
  const periodo = mercadoComPeriodo.value;
  if (!periodo) { mercadoComValidateStatus.textContent = 'Declara el período del informe.'; return; }
  setStatus(mercadoComValidateStatus, 'Validando y preparando previsualización...', 'loading');
  btnMercadoComValidate.disabled = true;
  btnMercadoComConfirm.disabled = true;
  try {
    const res = await fetch('/api/mercado/comercio/validate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({texto, periodo}),
    });
    const data = await res.json();
    lastMercadoComTexto = texto;
    lastMercadoComPeriodo = periodo;
    renderMercadoComPreview(data);
    setStatus(mercadoComValidateStatus, data.ok ? 'Previsualización lista.' : 'Revisa los errores de la previsualización.', data.ok ? 'success' : 'error');
  } catch (e) {
    setStatus(mercadoComValidateStatus, 'Error: ' + e.message, 'error');
  } finally {
    btnMercadoComValidate.disabled = false;
  }
});

btnMercadoComConfirm.addEventListener('click', async () => {
  if (!lastMercadoComValidationOk || lastMercadoComTexto !== mercadoComInput.value ||
      lastMercadoComPeriodo !== mercadoComPeriodo.value) {
    mercadoComIngestStatus.textContent = 'Los datos cambiaron desde la última validación — vuelve a validar.';
    return;
  }
  btnMercadoComConfirm.disabled = true;
  setStatus(mercadoComIngestStatus, 'Ingestando en la base de datos...', 'loading');
  try {
    const res = await fetch('/api/mercado/comercio/commit', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({texto: lastMercadoComTexto, periodo: lastMercadoComPeriodo}),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || 'error desconocido');
    if (data.status === 'skipped_duplicate') {
      setStatus(mercadoComIngestStatus, 'Este texto ya había sido ingestado antes — no se creó nada nuevo.', 'warn');
    } else {
      setStatus(mercadoComIngestStatus,
        `Listo: ${data.filas_insertadas} filas insertadas` +
        (data.filas_superseded ? `, ${data.filas_superseded} filas anteriores reemplazadas` : '') +
        ` (run #${data.run_id}).`,
        'success');
    }
  } catch (e) {
    setStatus(mercadoComIngestStatus, 'Error al ingestar: ' + e.message, 'error');
    btnMercadoComConfirm.disabled = false;
  }
});

populateMercadoComercioMeses();
checkMercadoComPeriodoStatus();
```

- [ ] **Step 5: Verificación manual en navegador**

Run: `python scripts/ingesta_server.py` (o el comando que use el proyecto para levantarlo — revisar `README`/`CLAUDE.md` si difiere), abrir `http://127.0.0.1:8765/ingesta` (o la ruta correspondiente), ir a la pestaña "Mercado" → subtab "Supermercados".

Expected: se ve el selector de mes, el texto de instrucciones con el mes/año dinámico, el textarea, y al pegar `-0,9% 6,2% -3,0% -9,1% 0,2% -0,6% -1,2%` con período `2026-06` y hacer clic en "Validar y previsualizar" aparece la fila con los 7 porcentajes formateados y el botón "Confirmar e ingestar" se habilita.

- [ ] **Step 6: Commit**

```bash
git add web/ingesta.html
git commit -m "feat(ingesta): UI subtab Supermercados para ingesta mensual mercado comercio (CNC)"
```

---

### Task 6: Wiring en `scripts/build_factsheet.py`

**Files:**
- Modify: `scripts/build_factsheet.py`
  - Agregar `_fetch_mercado_comercio` junto a `_fetch_bodegas_mercado` (línea ~916-947)
  - Wiring en `fetch_fondo` junto al bloque de bodegas (línea ~1179-1188) y en el `return` (línea ~1508-1511)
  - Reemplazo del render placeholder (líneas 7606-7611)
- Test: `tests/test_build_factsheet_mercado_comercio.py` (si existe una suite de tests para `build_factsheet.py` que testea funciones `_fetch_*` de forma aislada contra una DB temporal — seguir ese patrón; si no existe ningún test de este tipo para `build_factsheet.py`, crear uno mínimo para `_fetch_mercado_comercio` siguiendo el estilo de `tests/db/test_ingest_mercado_comercio.py`)

**Interfaces:**
- Consumes: tabla `raw_mercado_comercio` (Task 1), constante `CATEGORIAS_ORDEN` de `tools.db.ingest_mercado_comercio` (Task 2, para mantener el orden y no duplicarlo).
- Produces: `_fetch_mercado_comercio(db_path: str, periodo: str) -> dict[str, float | None] | None`; clave `F["mercado_comercio"]` en el dict que retorna `fetch_fondo`, consumida por el JS de render de la página 3.

- [ ] **Step 1: Escribir el test de `_fetch_mercado_comercio` (falla primero)**

```python
"""Test para _fetch_mercado_comercio en scripts/build_factsheet.py."""
from __future__ import annotations

import sqlite3

import pytest

from scripts.build_factsheet import _fetch_mercado_comercio
from tools.db.connection import apply_migrations
from tools.db import ingest_mercado_comercio


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    ingest_mercado_comercio.DB_PATH = db_path
    ingest_mercado_comercio.commit("-0,9% 6,2% -3,0% -9,1% 0,2% -0,6% -1,2%", "2026-06")
    return db_path


def test_fetch_mercado_comercio_periodo_existente(db):
    fila = _fetch_mercado_comercio(db, "2026-06")
    assert fila is not None
    assert fila["Total Comercio"] == pytest.approx(-0.009)
    assert fila["Supermercados"] == pytest.approx(-0.012)


def test_fetch_mercado_comercio_periodo_inexistente(db):
    assert _fetch_mercado_comercio(db, "2020-01") is None
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `pytest tests/test_build_factsheet_mercado_comercio.py -v`
Expected: FAIL — `ImportError: cannot import name '_fetch_mercado_comercio'`.

- [ ] **Step 3: Implementar `_fetch_mercado_comercio`**

En `scripts/build_factsheet.py`, agregar justo después de `_fetch_bodegas_mercado` (después de la línea 947):

```python
def _fetch_mercado_comercio(db_path: str, periodo: str) -> dict[str, float | None] | None:
    """Lee raw_mercado_comercio para el período exacto dado — sin fallback a
    período anterior (si no está ingestado, la tabla muestra placeholder,
    igual criterio que bodegas cuando no hay filas)."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """SELECT categoria, variacion_acumulada_pct
               FROM raw_mercado_comercio
               WHERE periodo = ? AND superseded_at IS NULL""",
            (periodo,),
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return None
    return {categoria: valor for categoria, valor in rows}
```

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `pytest tests/test_build_factsheet_mercado_comercio.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Wiring en `fetch_fondo`**

En `scripts/build_factsheet.py`, modificar el bloque de la línea 1164-1188:

```python
    mercado_por_periodo: dict[str, list[dict]] = {}
    oficinas_evolucion = None
    mercado_bodegas_por_periodo: dict[str, list[dict]] = {}
    bodegas_evolucion = None
    mercado_comercio_por_periodo: dict[str, dict[str, float | None]] = {}
    if (cfg.get("page4") or {}).get("submercado") or (cfg.get("page3") or {}).get("modo") == "mercado":
        periodos_disponibles = [
            r[0] for r in cur.execute(
                "SELECT DISTINCT periodo FROM raw_mercado_oficinas "
                "WHERE proveedor='JLL' AND superseded_at IS NULL ORDER BY periodo"
            )
        ]
        for periodo in periodos_disponibles:
            mercado_por_periodo[periodo] = _fetch_mercado_rows(str(DB), periodo)
        oficinas_evolucion = _fetch_oficinas_evolucion(str(DB))

        periodos_bodegas = [
            r[0] for r in cur.execute(
                "SELECT DISTINCT periodo FROM raw_mercado_bodegas WHERE superseded_at IS NULL ORDER BY periodo"
            )
        ]
        for periodo in periodos_bodegas:
            filas = _fetch_bodegas_mercado(str(DB), periodo)
            if filas is not None:
                mercado_bodegas_por_periodo[periodo] = filas
        bodegas_evolucion = _fetch_bodegas_evolucion(str(DB))

        periodos_comercio = [
            r[0] for r in cur.execute(
                "SELECT DISTINCT periodo FROM raw_mercado_comercio WHERE superseded_at IS NULL ORDER BY periodo"
            )
        ]
        for periodo in periodos_comercio:
            fila = _fetch_mercado_comercio(str(DB), periodo)
            if fila is not None:
                mercado_comercio_por_periodo[periodo] = fila
```

Y en el `return` de `fetch_fondo` (línea 1508-1511), agregar la nueva clave junto a las de bodegas:

```python
        "mercado_bodegas": mercado_bodegas_por_periodo,
        "bodegas_evolucion": bodegas_evolucion,
        "mercado_comercio": mercado_comercio_por_periodo,
```

- [ ] **Step 6: Reemplazar el render placeholder en el JS embebido**

En `scripts/build_factsheet.py`, reemplazar las líneas 7606-7611:

```javascript
    const cc = S.page3.centros_comerciales;
    document.getElementById("tbl-comercio-thead").innerHTML =
      "<th></th>" + cc.categorias.map(c => `<th>${c}</th>`).join("");
    document.getElementById("tbl-comercio-tbody").innerHTML =
      `<tr><td>${usadoOp ? mesEspanol(usadoOp) : "—"}</td>` +
      cc.categorias.map(() => '<td class="placeholder">—</td>').join("") + `</tr>`;
```

por:

```javascript
    const cc = S.page3.centros_comerciales;
    document.getElementById("tbl-comercio-thead").innerHTML =
      "<th></th>" + cc.categorias.map(c => `<th>${c}</th>`).join("");
    const comercioFila = usadoOp && F.mercado_comercio ? F.mercado_comercio[usadoOp] : null;
    const fmtComercio = (v) => {
      if (v === null || v === undefined) return '<span class="placeholder">—</span>';
      const pct = (v * 100).toFixed(1).replace(".", ",");
      return (v > 0 ? "+" : "") + pct + "%";
    };
    document.getElementById("tbl-comercio-tbody").innerHTML =
      `<tr><td>${usadoOp ? mesEspanol(usadoOp) : "—"}</td>` +
      cc.categorias.map(c => `<td>${comercioFila ? fmtComercio(comercioFila[c]) : '<span class="placeholder">—</span>'}</td>`).join("") + `</tr>`;
```

- [ ] **Step 7: Correr toda la suite de tests relacionados a build_factsheet para descartar regresiones**

Run: `pytest tests/test_build_factsheet_mercado_comercio.py -v` y, si existe, la suite general de `build_factsheet` (buscar `tests/test_build_factsheet*.py` con `Glob` antes de correrla).
Expected: todos PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/build_factsheet.py tests/test_build_factsheet_mercado_comercio.py
git commit -m "feat(factsheet): pinta tabla Mercado Comercio (CNC) desde raw_mercado_comercio"
```

---

### Task 7: Backfill real + regeneración del fact sheet TRI

**Files:**
- No crea archivos nuevos — ejecuta el script de Task 3 contra la DB real y regenera el fact sheet.

**Interfaces:**
- Consumes: `tools/db/backfill_mercado_comercio.py` (Task 3) contra `memory/agente_toesca_v2.db`; el script de build del fact sheet (buscar el comando exacto — probablemente `python scripts/build_factsheet.py` o vía `_rebuild_factsheet()` en `ingesta_server.py`; confirmar leyendo el `if __name__ == "__main__"` de `build_factsheet.py`).

- [ ] **Step 1: Ejecutar el backfill contra la DB real**

Run: `python -m tools.db.backfill_mercado_comercio "C:\Users\raimundo.opazo\Downloads\CNC_Historico_Variaciones_Reales_Acumuladas_RM_2025-2026.xlsx"`

Expected: imprime `{'status': 'ok', 'filas_insertadas': 126, 'periodos': [...18 períodos...]}`.

- [ ] **Step 2: Verificar en la DB real**

Run: `python -c "import sqlite3; con = sqlite3.connect('memory/agente_toesca_v2.db'); print(con.execute(\"SELECT periodo, categoria, variacion_acumulada_pct FROM raw_mercado_comercio WHERE periodo='2026-06' AND superseded_at IS NULL ORDER BY source_row\").fetchall()); con.close()"`

Expected: 7 filas para `2026-06`, con `Supermercados` = `-0.012` (coincide con la última fila del Excel del usuario, Jun. 2026/2025).

- [ ] **Step 3: Regenerar el fact sheet TRI y verificar visualmente**

Run: el comando de build habitual del proyecto (revisar `if __name__ == "__main__"` en `scripts/build_factsheet.py` para la sintaxis exacta — típicamente algo como `python scripts/build_factsheet.py`).

Abrir `http://127.0.0.1:8765/factsheet` (NO con doble clic sobre el archivo — `file://` no recibe el token de autenticación, ver `CLAUDE.md`), ir a la página 3 del fact sheet TRI, mes operacional junio 2026.

Expected: la tabla "Variaciones Reales Acumuladas Total Locales RM (CNC)" muestra la fila de junio 2026 con los 7 valores reales (Total Comercio -0,9%, Vestuario +6,2%, Calzado -3,0%, Artefactos Eléctricos -9,1%, Línea Hogar +0,2%, Muebles -0,6%, Supermercados -1,2%), en vez de placeholders.

- [ ] **Step 4: Commit (si el build genera un archivo versionado, p. ej. `factsheet.html`)**

```bash
git status
```

Si `factsheet.html` u otro artefacto de build aparece modificado, confirmar con el usuario si corresponde comitearlo (puede ser un artefacto no versionado — revisar `.gitignore` primero).

---

## Self-Review

**Spec coverage:**
- Schema `raw_mercado_comercio` sin fuente/URL/referencia → Task 1. ✓
- Backfill histórico del Excel del usuario → Task 3. ✓
- Ingesta paste-text mensual (sin fuente) → Task 2. ✓
- Endpoints Flask espejo de bodegas → Task 4. ✓
- Subtab "Supermercados" con instrucciones de búsqueda explícitas → Task 5. ✓
- Wiring en fact sheet, una sola fila (mes operacional vigente) → Task 6. ✓
- Ejecución real + verificación visual → Task 7. ✓
- Mapeo "Supermercado Tradicional" (Excel) → "Supermercados" (fact sheet) → explícito en Global Constraints, Task 2 (`CATEGORIAS_ORDEN`) y Task 3 (`_COL_A_CATEGORIA`). ✓

**Placeholder scan:** sin TBD/TODO; todos los pasos de código traen implementación completa, no descripciones.

**Type consistency:** `CATEGORIAS_ORDEN` se define una sola vez en `tools/db/ingest_mercado_comercio.py` (Task 2) y se reutiliza (import, no redefinición) en Task 3 y se referencia por nombre en Task 6 — evita que los 7 strings de categoría diverjan entre módulos. `_fetch_mercado_comercio` devuelve `dict[str, float | None] | None`, consistente entre Task 6 Step 1 (test) y Step 3 (implementación). `commit()`/`validate()` devuelven las mismas claves (`status`, `run_id`, `filas_insertadas`, `filas_superseded` / `ok`, `errors`, `warnings`, `data`) que sus pares en `ingest_mercado_bodegas.py`, consumidos igual por Task 4.
