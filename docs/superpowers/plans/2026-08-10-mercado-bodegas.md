# Mercado de Bodegas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingestar el informe semestral de mercado de bodegas (GPS Property, texto pegado) y el histórico de evolución vacancia/UF (carga única desde xlsx) en la DB, y reemplazar los placeholders de la página 3 del factsheet TRI (tabla por zona + gráfico evolución) con esos datos reales.

**Architecture:** Mismo patrón que "Mercado Oficinas" ya existente: tabla `raw_mercado_bodegas` (snapshot semestral, parser de texto + validate/commit idempotente por `file_hash`) + tabla `raw_mercado_bodegas_evolucion` (histórico, poblada una sola vez desde un xlsx que no se vuelve a tocar). Un tab consolidado "Mercado" en `web/ingesta.html` con sub-tabs Oficinas/Bodegas. `build_factsheet.py` lee ambas tablas y alimenta el `renderBodegasChart()` y la tabla `tbl-bodegas` que ya existen en el HTML/JS del factsheet.

**Tech Stack:** Python 3, sqlite3 (vía `tools.db.connection`), Flask (`scripts/ingesta_server.py`), openpyxl (solo para el backfill), HTML/JS vanilla embebido en `build_factsheet.py` y `web/ingesta.html`.

## Global Constraints

- Períodos en formato `YYYY-MM` (mes de cierre del semestre: `06` o `12`).
- Todo número parseado desde texto usa formato numérico chileno (`.`=miles, `,`=decimal); `"-"` → `None`.
- Toda tabla `raw_*` nueva lleva `file_hash` + `source_row` con `UNIQUE(file_hash, source_row)`, `ingest_run_id`, `loaded_at`, `superseded_at` — idempotencia y trazabilidad como el resto del proyecto (ver CLAUDE.md).
- El xlsx de evolución (`RAW/mercado bodegas db.xlsx`) es solo un input de una sola carga — el gráfico siempre lee de la DB, nunca del archivo en tiempo de build.
- No tocar `factsheet.html` a mano — todo cambio va en `HTML_TEMPLATE`/JS dentro de `scripts/build_factsheet.py`.
- Nombres de fondo: solo se usa TRI (`cfg["page3"]["modo"] == "mercado"` ya está acotado a TRI).

---

### Task 1: Migración de schema — `raw_mercado_bodegas` + `raw_mercado_bodegas_evolucion`

**Files:**
- Create: `tools/db/migrations/079_raw_mercado_bodegas.sql`
- Test: `tests/db/test_estado_ingesta.py` (verificar que no rompe; no requiere caso nuevo)

**Interfaces:**
- Produces: tablas `raw_mercado_bodegas(id, periodo, zona, clase, es_total, produccion_m2, inventario_final_m2, participacion_pct, vacancia_actual_m2, tasa_vacancia_pct, vacancia_anterior_m2, absorcion_m2, precio_uf_m2, precio_usd_m2, file_hash, source_row, ingest_run_id, loaded_at, superseded_at)` y `raw_mercado_bodegas_evolucion(id, semestre, anio, periodo_num, uf_m2, vacancia_pct, source_file, file_hash, loaded_at, superseded_at)`.

- [ ] **Step 1: Crear el archivo de migración**

```sql
-- 079: mercado de bodegas — snapshot semestral por zona (informe GPS
-- Property, texto pegado) + histórico semestral vacancia/UF (carga única
-- desde RAW/"mercado bodegas db.xlsx", ver
-- tools/db/backfill_mercado_bodegas_evolucion.py). Alimentan la tabla y el
-- gráfico "Mercado Bodegas" de la página 3 del fact sheet TRI.

CREATE TABLE raw_mercado_bodegas (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo               TEXT NOT NULL,   -- 'YYYY-MM', mes de cierre del semestre (06/12)
    zona                  TEXT NOT NULL,   -- 'Centro'|'Nor-Poniente'|'Norte'|'Poniente'|'Sur'|'Gran Santiago'
    clase                 TEXT,            -- 'A/B' (null para el total 'Gran Santiago')
    es_total              INTEGER DEFAULT 0,
    produccion_m2         REAL,
    inventario_final_m2   REAL,
    participacion_pct     REAL,            -- 4.6, no 0.046
    vacancia_actual_m2    REAL,
    tasa_vacancia_pct     REAL,
    vacancia_anterior_m2  REAL,
    absorcion_m2          REAL,
    precio_uf_m2          REAL,
    precio_usd_m2         REAL,
    file_hash             TEXT,
    source_row            INTEGER,
    ingest_run_id         INTEGER REFERENCES ingest_run(id),
    loaded_at             TEXT DEFAULT (datetime('now')),
    superseded_at         TEXT,
    UNIQUE(file_hash, source_row)
);

CREATE INDEX idx_mercado_bodegas_periodo ON raw_mercado_bodegas(periodo);
CREATE INDEX idx_mercado_bodegas_lookup ON raw_mercado_bodegas(periodo, zona)
    WHERE superseded_at IS NULL;

CREATE TABLE raw_mercado_bodegas_evolucion (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    semestre      TEXT NOT NULL,   -- '2S-2015', '1S-2016', ...
    anio          INTEGER NOT NULL,
    periodo_num   INTEGER NOT NULL,  -- 1|2
    uf_m2         REAL,
    vacancia_pct  REAL,            -- fracción, 0.0995 = 9.95%
    source_file   TEXT,
    file_hash     TEXT,
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT,
    UNIQUE(semestre, file_hash)
);

CREATE INDEX idx_mercado_bodegas_evolucion_semestre
    ON raw_mercado_bodegas_evolucion(semestre);
```

- [ ] **Step 2: Aplicar la migración a la DB real y verificar**

Run: `python -c "from tools.db.connection import apply_migrations, DEFAULT_DB_PATH; apply_migrations(DEFAULT_DB_PATH)"`
Expected: sin errores. Verificar con:
`python -c "import sqlite3; c=sqlite3.connect('memory/agente_toesca_v2.db'); print(c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'raw_mercado_bodegas%'\").fetchall())"`
Expected: `[('raw_mercado_bodegas',), ('raw_mercado_bodegas_evolucion',)]`

- [ ] **Step 3: Correr la suite de tests de DB para asegurar que no rompió nada**

Run: `python -m pytest tests/db/ -q`
Expected: PASS (mismo resultado que antes de la migración, sin nuevos failures)

- [ ] **Step 4: Commit**

```bash
git add tools/db/migrations/079_raw_mercado_bodegas.sql
git commit -m "feat(db): schema raw_mercado_bodegas + raw_mercado_bodegas_evolucion"
```

---

### Task 2: Parser + validate/commit — `tools/db/ingest_mercado_bodegas.py`

**Files:**
- Create: `tools/db/ingest_mercado_bodegas.py`
- Test: `tests/db/test_ingest_mercado_bodegas.py`

**Interfaces:**
- Consumes: `tools.db.connection.get_conn_for(db_path)` (ya existe).
- Produces:
  - `ZONAS_ESPERADAS: set[str]` = `{"Centro", "Nor-Poniente", "Norte", "Poniente", "Sur", "Gran Santiago"}`
  - `parse_tabla_bodegas(texto: str) -> list[dict]` — cada dict con claves `zona, clase, es_total, produccion_m2, inventario_final_m2, participacion_pct, vacancia_actual_m2, tasa_vacancia_pct, vacancia_anterior_m2, absorcion_m2, precio_uf_m2, precio_usd_m2`.
  - `validate(texto: str, periodo: str) -> ValidationResult` (misma clase `ValidationResult` que `ingest_mercado.py`, reimplementada localmente con mismos atributos `ok/errors/warnings/data/to_dict()`).
  - `commit(texto: str, periodo: str) -> dict` — retorna `{"status": "ok"|"skipped_duplicate", "run_id": int|None, "filas_insertadas": int, "filas_superseded": int}`.
  - `DB_PATH: Path`

- [ ] **Step 1: Escribir el test del parser (caso válido)**

```python
"""Tests para tools.db.ingest_mercado_bodegas."""
from __future__ import annotations

import pytest

from tools.db import ingest_mercado_bodegas as mod
from tools.db.connection import apply_migrations, get_conn_for

TEXTO_GPS_1S_2026 = """Zona Clase Producción Inventario
Final
Participación
de Mercado
Vacancia
Actual
Tasa de
Vacancia Actual
Vacancia
Anterior Absorción Precio Promedio
Arriendo
Precio Promedio
Arriendo
(m²) (m²) (%) (m²) (%) (m²) (m²) (UF/m2
) (US$/m2
)
Centro A/B - 289.789 4,6% 1.340 0,5% - -1.340 0,226 9,21
Nor-Poniente A/B - 1.308.661 20,6% 40.475 3,1% 48.739 8.264 0,161 6,55
Norte A/B 8.000 1.430.841 22,5% 44.049 3,1% 45.682 9.633 0,157 6,39
Poniente A/B - 2.452.838 38,6% 201.620 8,2% 228.978 27.358 0,154 6,26
Sur A/B 119.000 874.007 13,8% 117.718 13,5% 62.778 64.060 0,146 5,94
Gran Santiago 127.000 6.356.136 100% 405.201 6,37% 386.177 107.976 0,146 5,93"""


def test_parse_tabla_bodegas_ok():
    filas = mod.parse_tabla_bodegas(TEXTO_GPS_1S_2026)
    assert len(filas) == 6
    centro = next(f for f in filas if f["zona"] == "Centro")
    assert centro["clase"] == "A/B"
    assert centro["es_total"] == 0
    assert centro["produccion_m2"] is None
    assert centro["inventario_final_m2"] == 289789.0
    assert centro["participacion_pct"] == 4.6
    assert centro["vacancia_actual_m2"] == 1340.0
    assert centro["tasa_vacancia_pct"] == 0.5
    assert centro["vacancia_anterior_m2"] is None
    assert centro["absorcion_m2"] == -1340.0
    assert centro["precio_uf_m2"] == 0.226
    assert centro["precio_usd_m2"] == 9.21

    total = next(f for f in filas if f["zona"] == "Gran Santiago")
    assert total["es_total"] == 1
    assert total["clase"] is None
    assert total["produccion_m2"] == 127000.0
    assert total["tasa_vacancia_pct"] == 6.37


def test_parse_tabla_bodegas_zona_faltante():
    texto_incompleto = "\n".join(TEXTO_GPS_1S_2026.splitlines()[:-3])
    with pytest.raises(ValueError, match="Faltan"):
        mod.validate(texto_incompleto, "2026-06").ok  # noqa: usa validate, no parse directo
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/db/test_ingest_mercado_bodegas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.db.ingest_mercado_bodegas'`

- [ ] **Step 3: Implementar el parser**

```python
"""Ingesta de datos de mercado de bodegas (GPS Property, semestral) desde
texto copy-paste de la tabla del informe.

Formato de entrada esperado (una línea por zona, tokens separados por
espacio, "-" como null):

    Centro A/B - 289.789 4,6% 1.340 0,5% - -1.340 0,226 9,21

Columnas en orden: zona(+), clase, producción, inventario_final,
participación%, vacancia_actual, tasa_vacancia%, vacancia_anterior,
absorción, precio_uf, precio_usd. La fila "Gran Santiago" no lleva clase
(9 valores en vez de 10 tokens de datos) y es el total.

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

ZONAS_ESPERADAS = {"Centro", "Nor-Poniente", "Norte", "Poniente", "Sur", "Gran Santiago"}
ZONA_TOTAL = "Gran Santiago"

_METRIC_KEYS = (
    "produccion_m2", "inventario_final_m2", "participacion_pct",
    "vacancia_actual_m2", "tasa_vacancia_pct", "vacancia_anterior_m2",
    "absorcion_m2", "precio_uf_m2", "precio_usd_m2",
)

_CAMPOS_NO_NEGATIVOS = (
    "produccion_m2", "inventario_final_m2", "participacion_pct",
    "vacancia_actual_m2", "vacancia_anterior_m2", "precio_uf_m2", "precio_usd_m2",
)


def _parse_num_cl(raw: str) -> float | None:
    s = raw.strip().rstrip("%").strip()
    if s == "-":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    return float(s)


def _is_valor_token(tok: str) -> bool:
    return tok == "-" or _looks_numeric(tok)


def _looks_numeric(tok: str) -> bool:
    s = tok.rstrip("%")
    s = s.replace(".", "").replace(",", ".")
    try:
        float(s)
        return True
    except ValueError:
        return False


def parse_tabla_bodegas(texto: str) -> list[dict]:
    """Parsea el texto copy-paste de la tabla de mercado bodegas (GPS Property).

    Ignora líneas de encabezado (no calzan el patrón zona + 9 valores).
    """
    lines = [l.strip() for l in texto.strip().splitlines() if l.strip()]
    filas: list[dict] = []
    for line in lines:
        tokens = line.split()
        if len(tokens) < 10:
            continue
        # Última fila (Gran Santiago) no tiene columna "clase": 9 valores + zona(s).
        # Filas de zona sí tienen "clase" = "A/B": zona(s) + clase + 9 valores.
        valores_9 = tokens[-9:]
        if not all(_is_valor_token(t) for t in valores_9):
            continue
        resto = tokens[:-9]
        if resto and resto[-1] == "A/B":
            zona = " ".join(resto[:-1])
            clase = "A/B"
            es_total = 0
        else:
            zona = " ".join(resto)
            clase = None
            es_total = 1
        if zona not in ZONAS_ESPERADAS:
            continue
        valores = [_parse_num_cl(v) for v in valores_9]
        fila = {"zona": zona, "clase": clase, "es_total": es_total}
        fila.update(dict(zip(_METRIC_KEYS, valores)))
        filas.append(fila)
    return filas


class ValidationResult:
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
    result = ValidationResult()

    if not periodo:
        result.add_error("Falta declarar el período (YYYY-MM) del informe.")
        return result
    if not texto.strip():
        result.add_error("Pega el texto de la tabla antes de validar.")
        return result

    filas = parse_tabla_bodegas(texto)
    if not filas:
        result.add_error(
            "No se detectaron filas válidas — revisa que el texto pegado tenga el "
            "formato 'Zona [A/B] <9 valores numéricos o -> ' por línea."
        )
        return result

    zonas_encontradas = {f["zona"] for f in filas}
    faltantes = ZONAS_ESPERADAS - zonas_encontradas
    sobrantes = zonas_encontradas - ZONAS_ESPERADAS
    if faltantes:
        result.add_error(f"Faltan zonas: {sorted(faltantes)}")
    if sobrantes:
        result.add_error(f"Zonas no reconocidas: {sorted(sobrantes)}")

    for f in filas:
        tasa = f.get("tasa_vacancia_pct")
        if tasa is not None and not (0 <= tasa <= 100):
            result.add_error(f"{f['zona']}: tasa_vacancia_pct fuera de rango 0-100 ({tasa})")
        for campo in _CAMPOS_NO_NEGATIVOS:
            valor = f.get(campo)
            if valor is not None and valor < 0:
                result.add_error(f"{f['zona']}: {campo} negativo ({valor}) — valor inesperado")

    if not result.ok:
        return result

    fhash = hashlib.sha256(f"{periodo}|{texto.strip()}".encode("utf-8")).hexdigest()

    con = get_conn_for(str(DB_PATH))
    try:
        n_existentes = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_bodegas WHERE periodo=? AND superseded_at IS NULL",
            (periodo,),
        ).fetchone()[0]
        ya_mismo_hash = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_bodegas WHERE file_hash=?", (fhash,)
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
        "filas": filas,
        "n_filas": len(filas),
        "file_hash": fhash,
        "ya_ingestado": bool(ya_mismo_hash),
    }
    return result


def commit(texto: str, periodo: str) -> dict:
    result = validate(texto, periodo)
    if not result.ok:
        raise ValueError("No se puede ingestar: " + "; ".join(result.errors))

    filas = result.data["filas"]
    fhash = result.data["file_hash"]
    source_file = f"gps_manual_{periodo}"

    con = get_conn_for(str(DB_PATH))
    try:
        existing_hash_count = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_bodegas WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
        if existing_hash_count:
            return {"status": "skipped_duplicate", "run_id": None, "filas_insertadas": 0, "filas_superseded": 0}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = con.execute(
            """INSERT INTO ingest_run (tool, source_file, file_hash, started_at, status, periodo_declarado)
               VALUES (?,?,?,?,?,?)""",
            ("ingest_mercado_bodegas", source_file, fhash, now, "running", periodo),
        )
        run_id = cur.lastrowid

        cur2 = con.execute(
            """UPDATE raw_mercado_bodegas SET superseded_at=?
               WHERE periodo=? AND superseded_at IS NULL""",
            (now, periodo),
        )
        filas_superseded = cur2.rowcount if cur2.rowcount > 0 else 0

        rows = [
            (
                periodo, f["zona"], f["clase"], f["es_total"],
                f["produccion_m2"], f["inventario_final_m2"], f["participacion_pct"],
                f["vacancia_actual_m2"], f["tasa_vacancia_pct"], f["vacancia_anterior_m2"],
                f["absorcion_m2"], f["precio_uf_m2"], f["precio_usd_m2"],
                fhash, idx, run_id,
            )
            for idx, f in enumerate(filas)
        ]
        con.executemany(
            """INSERT INTO raw_mercado_bodegas
               (periodo, zona, clase, es_total, produccion_m2, inventario_final_m2,
                participacion_pct, vacancia_actual_m2, tasa_vacancia_pct,
                vacancia_anterior_m2, absorcion_m2, precio_uf_m2, precio_usd_m2,
                file_hash, source_row, ingest_run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )

        con.execute(
            "UPDATE ingest_run SET status=?, ended_at=?, rows_in=?, rows_loaded=? WHERE id=?",
            ("ok", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(filas), len(rows), run_id),
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

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/db/test_ingest_mercado_bodegas.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Agregar tests de idempotencia y commit**

Agregar al mismo archivo de test:

```python
@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    monkeypatch.setattr(mod, "DB_PATH", db_path)
    return db_path


def test_commit_inserta_filas(db):
    result = mod.commit(TEXTO_GPS_1S_2026, "2026-06")
    assert result["status"] == "ok"
    assert result["filas_insertadas"] == 6
    assert result["filas_superseded"] == 0

    con = get_conn_for(db)
    n = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_bodegas WHERE periodo='2026-06' AND superseded_at IS NULL"
    ).fetchone()[0]
    con.close()
    assert n == 6


def test_commit_idempotente_mismo_texto(db):
    mod.commit(TEXTO_GPS_1S_2026, "2026-06")
    result2 = mod.commit(TEXTO_GPS_1S_2026, "2026-06")
    assert result2["status"] == "skipped_duplicate"
    assert result2["filas_insertadas"] == 0


def test_commit_reemplaza_periodo_con_texto_distinto(db):
    mod.commit(TEXTO_GPS_1S_2026, "2026-06")
    texto_v2 = TEXTO_GPS_1S_2026.replace("289.789", "300.000")
    result2 = mod.commit(texto_v2, "2026-06")
    assert result2["status"] == "ok"
    assert result2["filas_superseded"] == 6

    con = get_conn_for(db)
    vigentes = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_bodegas WHERE periodo='2026-06' AND superseded_at IS NULL"
    ).fetchone()[0]
    con.close()
    assert vigentes == 6
```

Run: `python -m pytest tests/db/test_ingest_mercado_bodegas.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add tools/db/ingest_mercado_bodegas.py tests/db/test_ingest_mercado_bodegas.py
git commit -m "feat(db): parser + validate/commit para ingesta mercado bodegas"
```

---

### Task 3: Backfill único del histórico de evolución — `tools/db/backfill_mercado_bodegas_evolucion.py`

**Files:**
- Create: `tools/db/backfill_mercado_bodegas_evolucion.py`
- Test: `tests/db/test_backfill_mercado_bodegas_evolucion.py`

**Interfaces:**
- Consumes: `tools.db.connection.apply_migrations`, `get_conn_for`, `DEFAULT_DB_PATH` (ya existen, mismos imports que `ingest_mercado_oficinas_evolucion.py`).
- Produces: `ingest(xlsx_path: str, db_path: str = DEFAULT_DB_PATH, sheet: str = "Hoja1") -> int` (retorna cantidad de filas nuevas insertadas).

- [ ] **Step 1: Escribir el test con un xlsx fixture**

```python
"""Tests para tools.db.backfill_mercado_bodegas_evolucion."""
from __future__ import annotations

import openpyxl
import pytest

from tools.db import backfill_mercado_bodegas_evolucion as mod
from tools.db.connection import apply_migrations, get_conn_for


@pytest.fixture
def xlsx_fixture(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hoja1"
    ws["D3"] = "UF/m2"
    ws["E3"] = "Vacancia"
    filas = [
        ("2S-2015", 0.119, 0.0995),
        ("1S-2016", 0.118, 0.1228),
        ("2S-2016", 0.109, 0.0749),
    ]
    for i, (semestre, uf, vac) in enumerate(filas, start=4):
        ws[f"C{i}"] = semestre
        ws[f"D{i}"] = uf
        ws[f"E{i}"] = vac
    path = tmp_path / "mercado_bodegas.xlsx"
    wb.save(path)
    return str(path)


def test_ingest_inserta_filas(tmp_path, xlsx_fixture):
    db_path = str(tmp_path / "test.db")
    n = mod.ingest(xlsx_fixture, db_path=db_path)
    assert n == 3

    con = get_conn_for(db_path)
    rows = con.execute(
        "SELECT semestre, anio, periodo_num, uf_m2, vacancia_pct FROM raw_mercado_bodegas_evolucion "
        "WHERE superseded_at IS NULL ORDER BY anio, periodo_num"
    ).fetchall()
    con.close()
    assert rows == [
        ("2S-2015", 2015, 2, 0.119, 0.0995),
        ("1S-2016", 2016, 1, 0.118, 0.1228),
        ("2S-2016", 2016, 2, 0.109, 0.0749),
    ]


def test_ingest_idempotente(tmp_path, xlsx_fixture):
    db_path = str(tmp_path / "test.db")
    mod.ingest(xlsx_fixture, db_path=db_path)
    n2 = mod.ingest(xlsx_fixture, db_path=db_path)
    assert n2 == 0

    con = get_conn_for(db_path)
    total = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_bodegas_evolucion WHERE superseded_at IS NULL"
    ).fetchone()[0]
    con.close()
    assert total == 3
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/db/test_backfill_mercado_bodegas_evolucion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.db.backfill_mercado_bodegas_evolucion'`

- [ ] **Step 3: Implementar el script**

```python
"""Backfill de una sola corrida: histórico semestral vacancia/UF de Bodegas
desde SharePoint RAW/"mercado bodegas db.xlsx" -> raw_mercado_bodegas_evolucion.

Formato fuente (hoja única "Hoja1"): fila 3 = headers ('UF/m2' en col D,
'Vacancia' en col E), filas 4+ = semestre (col C, ej. '2S-2015'), UF/m² (col
D), vacancia como fracción (col E).

No expone CLI de producción — el archivo es histórico manual que no se
vuelve a actualizar; se corre una vez para poblar la DB y el gráfico del
fact sheet lee siempre de raw_mercado_bodegas_evolucion, nunca del xlsx.
Re-ejecutable de forma idempotente (UNIQUE(semestre, file_hash) +
superseded_at) por si el archivo se corrige a mano en el futuro.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.db.connection import apply_migrations, get_conn_for, DEFAULT_DB_PATH  # noqa: E402


def _anio_periodo_num(semestre: str) -> tuple[int, int]:
    # '2S-2015' -> (2015, 2), '1S-2026' -> (2026, 1)
    num, anio = semestre.split("-")
    return int(anio), int(num[0])


def ingest(xlsx_path: str, db_path: str = DEFAULT_DB_PATH, sheet: str = "Hoja1") -> int:
    import openpyxl

    apply_migrations(db_path)
    file_hash = hashlib.sha256(Path(xlsx_path).read_bytes()).hexdigest()

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))

    conn = get_conn_for(db_path)
    n_inserted = 0
    try:
        conn.execute(
            "UPDATE raw_mercado_bodegas_evolucion SET superseded_at = datetime('now') "
            "WHERE superseded_at IS NULL AND file_hash != ?",
            (file_hash,),
        )
        for row in rows[3:]:
            semestre = row[2]
            if semestre is None:
                continue
            uf_m2 = row[3]
            vacancia_pct = row[4]
            anio, periodo_num = _anio_periodo_num(str(semestre))
            existing = conn.execute(
                "SELECT id FROM raw_mercado_bodegas_evolucion "
                "WHERE semestre = ? AND superseded_at IS NULL",
                (semestre,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE raw_mercado_bodegas_evolucion "
                    "SET uf_m2=?, vacancia_pct=?, file_hash=?, source_file=? WHERE id=?",
                    (uf_m2, vacancia_pct, file_hash, str(xlsx_path), existing[0]),
                )
            else:
                conn.execute(
                    """INSERT INTO raw_mercado_bodegas_evolucion
                        (semestre, anio, periodo_num, uf_m2, vacancia_pct, source_file, file_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (semestre, anio, periodo_num, uf_m2, vacancia_pct, str(xlsx_path), file_hash),
                )
                n_inserted += 1
        conn.commit()
    finally:
        conn.close()
    return n_inserted


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else (
        r"C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos"
        r"\RAW\mercado bodegas db.xlsx"
    )
    n = ingest(path)
    print(f"OK -> {n} filas nuevas insertadas en raw_mercado_bodegas_evolucion")
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/db/test_backfill_mercado_bodegas_evolucion.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Correr el backfill real contra el archivo de SharePoint**

Run: `python -X utf8 -m tools.db.backfill_mercado_bodegas_evolucion`
Expected: `OK -> 24 filas nuevas insertadas en raw_mercado_bodegas_evolucion` (o el número real de semestres del archivo)

Verificar: `python -c "import sqlite3; c=sqlite3.connect('memory/agente_toesca_v2.db'); print(c.execute(\"SELECT semestre, uf_m2, vacancia_pct FROM raw_mercado_bodegas_evolucion WHERE superseded_at IS NULL ORDER BY anio, periodo_num LIMIT 3\").fetchall())"`
Expected: primeras filas con `2S-2015`, `0.119`, `0.0995`

- [ ] **Step 6: Commit**

```bash
git add tools/db/backfill_mercado_bodegas_evolucion.py tests/db/test_backfill_mercado_bodegas_evolucion.py
git commit -m "feat(db): backfill único histórico evolución vacancia/UF bodegas"
```

---

### Task 4: Endpoints Flask — `scripts/ingesta_server.py`

**Files:**
- Modify: `scripts/ingesta_server.py` (agregar imports + 3 rutas, cerca del bloque `/api/mercado/*` existente, línea ~515-555)
- Test: `tests/test_ingesta_server_mercado_bodegas.py`

**Interfaces:**
- Consumes: `tools.db.ingest_mercado_bodegas.validate(texto, periodo)`, `.commit(texto, periodo)`, `.DB_PATH` (Task 2); `_rebuild_factsheet()` (helper ya existente en `ingesta_server.py`).
- Produces: `GET /api/mercado/bodegas/periodo_check?periodo=YYYY-MM`, `POST /api/mercado/bodegas/validate`, `POST /api/mercado/bodegas/commit`.

- [ ] **Step 1: Escribir el test de los endpoints**

```python
"""Tests de los endpoints /api/mercado/bodegas/* de scripts/ingesta_server.py."""
from __future__ import annotations

import pytest

from tools.db.connection import apply_migrations
from tools.db import ingest_mercado_bodegas


@pytest.fixture
def texto_gps():
    from tests.db.test_ingest_mercado_bodegas import TEXTO_GPS_1S_2026
    return TEXTO_GPS_1S_2026


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(ingest_mercado_bodegas, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        c.environ_base["HTTP_X_INGESTA_TOKEN"] = ingesta_server.API_TOKEN
        yield c


def test_periodo_check_no_ingestado(client):
    res = client.get("/api/mercado/bodegas/periodo_check?periodo=2026-06")
    assert res.status_code == 200
    assert res.get_json()["ya_ingestado"] is False


def test_validate_endpoint_ok(client, texto_gps):
    res = client.post("/api/mercado/bodegas/validate", json={
        "texto": texto_gps, "periodo": "2026-06",
    })
    data = res.get_json()
    assert data["ok"] is True
    assert data["n_filas"] == 6


def test_commit_endpoint_inserta_y_periodo_check_refleja(client, texto_gps):
    res = client.post("/api/mercado/bodegas/commit", json={
        "texto": texto_gps, "periodo": "2026-06",
    })
    data = res.get_json()
    assert data["ok"] is True
    assert data["filas_insertadas"] == 6

    res2 = client.get("/api/mercado/bodegas/periodo_check?periodo=2026-06")
    assert res2.get_json()["ya_ingestado"] is True


def test_commit_endpoint_texto_invalido_retorna_400(client):
    res = client.post("/api/mercado/bodegas/commit", json={
        "texto": "esto no es una tabla", "periodo": "2026-06",
    })
    assert res.status_code == 400
    assert res.get_json()["ok"] is False
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_ingesta_server_mercado_bodegas.py -v`
Expected: FAIL — 404 en las rutas (no existen todavía)

- [ ] **Step 3: Agregar el import**

En `scripts/ingesta_server.py`, junto al import existente `from tools.db import ingest_mercado as mercado_core` (línea 44):

```python
from tools.db import ingest_mercado_bodegas as mercado_bodegas_core  # noqa: E402
```

- [ ] **Step 4: Agregar las 3 rutas**

Insertar después de la función `api_mercado_commit()` (línea ~554, antes de `@app.get("/api/parking/periodo_check")`):

```python
@app.get("/api/mercado/bodegas/periodo_check")
def api_mercado_bodegas_periodo_check():
    periodo = request.args.get("periodo", "")
    if not periodo:
        return jsonify({"ya_ingestado": False})
    con = get_conn_for(str(mercado_bodegas_core.DB_PATH))
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_bodegas "
            "WHERE periodo=? AND superseded_at IS NULL",
            (periodo,),
        ).fetchone()[0]
        return jsonify({"ya_ingestado": bool(n), "n_filas": n})
    finally:
        con.close()


@app.post("/api/mercado/bodegas/validate")
def api_mercado_bodegas_validate():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    result = mercado_bodegas_core.validate(texto, periodo)
    return jsonify(result.to_dict())


@app.post("/api/mercado/bodegas/commit")
def api_mercado_bodegas_commit():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    try:
        summary = mercado_bodegas_core.commit(texto, periodo)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    _rebuild_factsheet()
    return jsonify({"ok": True, **summary})
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_ingesta_server_mercado_bodegas.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Correr toda la suite de tests del servidor para asegurar que no rompió los endpoints existentes**

Run: `python -m pytest tests/test_ingesta_server_mercado.py tests/test_ingesta_server_mercado_bodegas.py -v`
Expected: PASS (todos)

- [ ] **Step 7: Commit**

```bash
git add scripts/ingesta_server.py tests/test_ingesta_server_mercado_bodegas.py
git commit -m "feat(server): endpoints /api/mercado/bodegas/* (validate/commit/periodo_check)"
```

---

### Task 5: `build_factsheet.py` — fetchers y wiring del JS embebido

**Files:**
- Modify: `scripts/build_factsheet.py`
  - Agregar `_fetch_bodegas_mercado()` y `_fetch_bodegas_evolucion()` cerca de `_fetch_oficinas_evolucion` (línea ~846-905)
  - Agregar el fetch a `fetch_fondo()` en el bloque `if (cfg.get("page4")...` (línea ~1096-1107) y agregar las 2 claves al `return` (línea ~1427-1428)
  - Reemplazar el bloque JS de bodegas (línea ~7390-7404) por lectura real
- Test: extender `tests/test_build_factsheet_mercado.py`

**Interfaces:**
- Consumes: tablas `raw_mercado_bodegas`, `raw_mercado_bodegas_evolucion` (Task 1/2/3); `cfg["bodegas"]["zonas"]` y `cfg["bodegas"]["total_nombre"]` (ya existen en `scripts/build_factsheet.py:203-206`).
- Produces:
  - `_fetch_bodegas_mercado(db_path: str, periodo: str) -> list[dict] | None` — filas ordenadas según `cfg["bodegas"]["zonas"]` + total al final, cada dict con `zona, produccion_m2, inventario_final_m2, tasa_vacancia_pct, precio_uf_m2, es_total`. `None` si no hay filas para ese período.
  - `_fetch_bodegas_evolucion(db_path: str) -> dict | None` — `{"semestres": [...], "uf_m2": [...], "vacancia_pct": [...]}` (vacancia ya en %, no fracción — `renderBodegasChart` espera `vacancia_pct` en la misma escala que sus `vacTicks` `[-1,4,9,14]`). `None` si la tabla está vacía.
  - `F.mercado_bodegas: dict[str, list[dict]]` (por período, mismo patrón que `F.mercado`) y `F.bodegas_evolucion: dict | None` en el diccionario que retorna `fetch_fondo()`.

- [ ] **Step 1: Escribir los tests de los fetchers**

Agregar a `tests/test_build_factsheet_mercado.py`:

```python
def test_fetch_bodegas_mercado_con_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        """INSERT INTO raw_mercado_bodegas
           (periodo, zona, clase, es_total, produccion_m2, inventario_final_m2,
            participacion_pct, vacancia_actual_m2, tasa_vacancia_pct,
            vacancia_anterior_m2, absorcion_m2, precio_uf_m2, precio_usd_m2,
            file_hash, source_row)
           VALUES ('2026-06','Centro','A/B',0,NULL,289789,4.6,1340,0.5,NULL,-1340,0.226,9.21,'H',0),
                  ('2026-06','Gran Santiago',NULL,1,127000,6356136,100,405201,6.37,386177,107976,0.146,5.93,'H',5)"""
    )
    con.commit()
    con.close()

    filas = bf._fetch_bodegas_mercado(db_path, "2026-06")
    assert filas is not None
    assert filas[0]["zona"] == "Centro"
    assert filas[0]["inventario_final_m2"] == 289789.0
    assert filas[0]["tasa_vacancia_pct"] == 0.5
    assert filas[-1]["zona"] == "Gran Santiago"
    assert filas[-1]["es_total"] is True


def test_fetch_bodegas_mercado_sin_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    assert bf._fetch_bodegas_mercado(db_path, "2026-06") is None


def test_fetch_bodegas_evolucion_con_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        """INSERT INTO raw_mercado_bodegas_evolucion (semestre, anio, periodo_num, uf_m2, vacancia_pct, file_hash)
           VALUES ('2S-2015', 2015, 2, 0.119, 0.0995, 'H'),
                  ('1S-2016', 2016, 1, 0.118, 0.1228, 'H')"""
    )
    con.commit()
    con.close()

    evo = bf._fetch_bodegas_evolucion(db_path)
    assert evo == {
        "semestres": ["2S-2015", "1S-2016"],
        "uf_m2": [0.119, 0.118],
        "vacancia_pct": [9.95, 12.28],
    }


def test_fetch_bodegas_evolucion_sin_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    assert bf._fetch_bodegas_evolucion(db_path) is None
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_build_factsheet_mercado.py -v`
Expected: FAIL — `AttributeError: module 'build_factsheet' has no attribute '_fetch_bodegas_mercado'`

- [ ] **Step 3: Implementar `_fetch_bodegas_mercado` y `_fetch_bodegas_evolucion`**

Insertar en `scripts/build_factsheet.py` justo antes de `def fetch_fondo(...)` (después de `_fetch_oficinas_evolucion`, línea ~905):

```python
_BODEGAS_ZONAS_ORDEN = ["Centro", "Nor-Poniente", "Norte", "Poniente", "Sur"]


def _fetch_bodegas_mercado(db_path: str, periodo: str) -> list[dict] | None:
    """Lee raw_mercado_bodegas para el período dado, ordenado por
    _BODEGAS_ZONAS_ORDEN con el total 'Gran Santiago' al final — mismo orden
    que usa la tabla tbl-bodegas de la página 3 del fact sheet TRI."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """SELECT zona, produccion_m2, inventario_final_m2, tasa_vacancia_pct,
                      precio_uf_m2, es_total
               FROM raw_mercado_bodegas
               WHERE periodo = ? AND superseded_at IS NULL""",
            (periodo,),
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return None
    por_zona = {r[0]: r for r in rows}
    ordenadas = [por_zona[z] for z in _BODEGAS_ZONAS_ORDEN if z in por_zona]
    if "Gran Santiago" in por_zona:
        ordenadas.append(por_zona["Gran Santiago"])
    return [
        {
            "zona": r[0],
            "produccion_m2": r[1],
            "inventario_final_m2": r[2],
            "tasa_vacancia_pct": r[3],
            "precio_uf_m2": r[4],
            "es_total": bool(r[5]),
        }
        for r in ordenadas
    ]


def _fetch_bodegas_evolucion(db_path: str) -> dict | None:
    """Lee raw_mercado_bodegas_evolucion (histórico semestral, carga única
    desde xlsx) y arma {semestres, uf_m2, vacancia_pct} para
    renderBodegasChart(). vacancia_pct se normaliza a porcentaje entero
    (9.95, no 0.0995) porque el gráfico espera esa escala."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """SELECT semestre, uf_m2, vacancia_pct
               FROM raw_mercado_bodegas_evolucion
               WHERE superseded_at IS NULL
               ORDER BY anio, periodo_num"""
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return None
    return {
        "semestres": [r[0] for r in rows],
        "uf_m2": [r[1] for r in rows],
        "vacancia_pct": [round(r[2] * 100, 4) if r[2] is not None else None for r in rows],
    }
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_build_factsheet_mercado.py -v`
Expected: PASS (todos, incluyendo los 4 nuevos)

- [ ] **Step 5: Enganchar los fetchers en `fetch_fondo()`**

En `scripts/build_factsheet.py`, dentro del bloque existente (línea ~1096-1107):

```python
    mercado_por_periodo: dict[str, list[dict]] = {}
    oficinas_evolucion = None
    mercado_bodegas_por_periodo: dict[str, list[dict]] = {}
    bodegas_evolucion = None
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
```

Y en el `return` de `fetch_fondo()` (línea ~1427-1428), agregar junto a `"oficinas_evolucion": oficinas_evolucion,`:

```python
        "mercado_bodegas": mercado_bodegas_por_periodo,
        "bodegas_evolucion": bodegas_evolucion,
```

- [ ] **Step 6: Reemplazar el bloque JS placeholder de bodegas**

En `scripts/build_factsheet.py`, reemplazar el bloque completo entre líneas ~7390-7404 (desde el comentario `// Bodegas: sin fuente en DB todavía` hasta el `chart-bodegas` placeholder):

```javascript
    // Bodegas: raw_mercado_bodegas (snapshot por zona) + raw_mercado_bodegas_evolucion
    // (histórico semestral, ver F.mercado_bodegas / F.bodegas_evolucion).
    const bodPeriodos = F.mercado_bodegas ? Object.keys(F.mercado_bodegas).sort() : [];
    const bodPeriodoActual = bodPeriodos.length ? bodPeriodos[bodPeriodos.length - 1] : null;
    const bodRows = bodPeriodoActual ? F.mercado_bodegas[bodPeriodoActual] : null;
    const bodP1 = document.getElementById("txt-mercado3-bodegas-1");
    const bodP2 = document.getElementById("txt-mercado3-bodegas-2");
    bodP1.textContent = "Pendiente: párrafo de vacancia/canon de arriendo (informe GPS Property) — sin fuente ingestada en la DB todavía.";
    bodP1.classList.add("placeholder");
    bodP2.textContent = "Pendiente: párrafo de producción y proyecciones (informe GPS Property).";
    bodP2.classList.add("placeholder");
    const fmtBod = (v, dec) => (v === null || v === undefined) ? null :
      v.toLocaleString("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec });
    const celdaBod = (v, esPct) => {
      if (v === null || v === undefined) return '<td class="placeholder">—</td>';
      const texto = esPct ? fmtBod(v, 1) + "%" : fmtBod(v, 0);
      return `<td>${texto}</td>`;
    };
    if (bodRows) {
      document.getElementById("tbl-bodegas-tbody").innerHTML = bodRows.map(r => {
        const cls = r.es_total ? ' class="row-total"' : '';
        return `<tr${cls}><td>${r.zona}</td>` +
          celdaBod(r.produccion_m2, false) + celdaBod(r.inventario_final_m2, false) +
          celdaBod(r.tasa_vacancia_pct, true) +
          `<td>${r.precio_uf_m2 !== null && r.precio_uf_m2 !== undefined ? r.precio_uf_m2.toLocaleString("es-CL", {minimumFractionDigits:3, maximumFractionDigits:3}) : '<span class="placeholder">—</span>'}</td>` +
          `</tr>`;
      }).join("");
    } else {
      document.getElementById("tbl-bodegas-tbody").innerHTML =
        bod.zonas.map(z => `<tr><td>${z}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`).join("")
        + `<tr class="row-total"><td>${bod.total_nombre}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`;
    }
    if (F.bodegas_evolucion) {
      renderBodegasChart("chart-bodegas", F.bodegas_evolucion);
    } else {
      document.getElementById("chart-bodegas").innerHTML =
        `<div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>`;
    }
```

Nota: la línea `const bod = S.page3.bodegas;` (justo antes del bloque original) se mantiene — sigue usándose en la rama `else` como fallback de zonas.

- [ ] **Step 7: Regenerar el factsheet y verificar visualmente**

Run: `python -X utf8 scripts/build_factsheet.py`
Expected: sin errores. Abrir `http://127.0.0.1:8765/factsheet` (servidor de ingesta corriendo) → TRI página 3 → sección Bodegas debe mostrar el gráfico de evolución con datos reales (línea de vacancia bajando de ~10% a ~6%, barras UF/m² entre 0.09-0.19) y la tabla con placeholders "—" en la tabla por zona (todavía sin snapshot GPS Property ingestado).

- [ ] **Step 8: Commit**

```bash
git add scripts/build_factsheet.py tests/test_build_factsheet_mercado.py
git commit -m "feat(factsheet): wiring gráfico evolución + tabla mercado bodegas TRI pág. 3"
```

---

### Task 6: UI de ingesta — tab "Mercado" consolidado con sub-tabs Oficinas/Bodegas

**Files:**
- Modify: `web/ingesta.html`
  - Renombrar botón de tab (línea 480)
  - Envolver contenido existente de `#tab-mercado` en sub-panel Oficinas + agregar sub-panel Bodegas (líneas 668-722)
  - Agregar CSS de sub-tabs si no reutiliza `.er-subtab-btn` (reutilizar, no crear nuevo)
  - Agregar JS del sub-panel Bodegas (después del bloque `populateMercadoTrimestres(); checkMercadoPeriodoStatus();`, línea ~2037-2039)
  - Agregar el listener de sub-tabs (junto al de `#er-subtabs`, línea ~1176-1183)

**Interfaces:**
- Consumes: `GET/POST /api/mercado/bodegas/*` (Task 4); helpers JS ya globales `fmt(n)`, `setStatus(el, text, state)` (definidos línea ~1187-1195).

- [ ] **Step 1: Renombrar el botón de tab**

En `web/ingesta.html:480`, cambiar:

```html
<button class="tab-btn" data-tab="mercado">Mercado Oficinas</button>
```

por:

```html
<button class="tab-btn" data-tab="mercado">Mercado</button>
```

- [ ] **Step 2: Envolver el contenido en sub-panel Oficinas y agregar sub-panel Bodegas**

Reemplazar el bloque completo `<div id="tab-mercado" class="tab-panel">...</div>` (líneas 668-722) por:

```html
<div id="tab-mercado" class="tab-panel">

  <div class="row" style="margin-bottom:14px;">
    <div class="tabs" id="mercado-subtabs">
      <button class="er-subtab-btn active" data-mercadotab="oficinas">Oficinas</button>
      <button class="er-subtab-btn" data-mercadotab="bodegas">Bodegas</button>
    </div>
  </div>

  <div id="mercado-panel-oficinas" class="er-activo-panel">

  <div class="step">
    <div class="step-title"><span class="step-num">1</span> Período y proveedor</div>
    <div class="row">
      <label class="muted" for="mercado-periodo">Período del informe (trimestral):</label>
      <select id="mercado-periodo" style="width:160px">
        <option value="">Elige trimestre...</option>
      </select>
      <label class="muted" for="mercado-proveedor">Proveedor:</label>
      <select id="mercado-proveedor" style="width:160px">
        <option value="JLL">JLL</option>
      </select>
    </div>
    <div class="row" id="mercado-periodo-status-row" style="margin-top:6px"></div>
  </div>

  <div class="step">
    <div class="step-title"><span class="step-num">2</span> Copia la tabla del PDF y pégala aquí</div>
    <ol class="instructions">
      <li>Abre el informe JLL del trimestre.</li>
      <li>Selecciona y copia la tabla de mercado de oficinas completa (encabezado + las 18 filas).</li>
      <li>Pega el texto tal cual en el cuadro de abajo.</li>
    </ol>
    <textarea id="mercado-input" placeholder="Pega aquí el texto copiado de la tabla del informe JLL..."></textarea>
    <div class="row">
      <button id="btn-mercado-validate">Validar y previsualizar</button>
      <span id="mercado-validate-status" class="muted"></span>
    </div>

    <div id="mercado-preview" class="preview hidden">
      <div class="badges" id="mercado-badges"></div>
      <ul id="mercado-errors" class="msg-list err"></ul>
      <ul id="mercado-warnings" class="msg-list warn"></ul>

      <div id="mercado-section-tabla" class="hidden">
        <h3>Filas detectadas</h3>
        <table>
          <thead><tr>
            <th>Submercado</th><th>Clase</th><th class="num">Inventario (m²)</th>
            <th class="num">Absorción U12M (m²)</th><th class="num">Vacancia (%)</th>
            <th class="num">Renta (UF/m²)</th><th class="num">En construcción (m²)</th>
          </tr></thead>
          <tbody id="mercado-tabla-body"></tbody>
        </table>
      </div>
    </div>

    <div class="row" style="margin-top:20px;">
      <button id="btn-mercado-confirm" disabled>Confirmar e ingestar</button>
      <span id="mercado-ingest-status" class="muted"></span>
    </div>
  </div>

  </div>

  <div id="mercado-panel-bodegas" class="er-activo-panel hidden">

  <div class="step">
    <div class="step-title"><span class="step-num">1</span> Período</div>
    <div class="row">
      <label class="muted" for="mercadobod-periodo">Período del informe (semestral):</label>
      <select id="mercadobod-periodo" style="width:160px">
        <option value="">Elige semestre...</option>
      </select>
    </div>
    <div class="row" id="mercadobod-periodo-status-row" style="margin-top:6px"></div>
  </div>

  <div class="step">
    <div class="step-title"><span class="step-num">2</span> Copia la tabla del informe y pégala aquí</div>
    <ol class="instructions">
      <li>Abre el informe GPS Property del semestre.</li>
      <li>Selecciona y copia la tabla de mercado de bodegas por zona (encabezado + las 6 filas: Centro, Nor-Poniente, Norte, Poniente, Sur, Gran Santiago).</li>
      <li>Pega el texto tal cual en el cuadro de abajo.</li>
    </ol>
    <textarea id="mercadobod-input" placeholder="Pega aquí el texto copiado de la tabla del informe GPS Property..."></textarea>
    <div class="row">
      <button id="btn-mercadobod-validate">Validar y previsualizar</button>
      <span id="mercadobod-validate-status" class="muted"></span>
    </div>

    <div id="mercadobod-preview" class="preview hidden">
      <div class="badges" id="mercadobod-badges"></div>
      <ul id="mercadobod-errors" class="msg-list err"></ul>
      <ul id="mercadobod-warnings" class="msg-list warn"></ul>

      <div id="mercadobod-section-tabla" class="hidden">
        <h3>Filas detectadas</h3>
        <table>
          <thead><tr>
            <th>Zona</th><th class="num">Producción (m²)</th><th class="num">Inventario Final (m²)</th>
            <th class="num">Tasa Vacancia (%)</th><th class="num">Precio (UF/m²)</th>
          </tr></thead>
          <tbody id="mercadobod-tabla-body"></tbody>
        </table>
      </div>
    </div>

    <div class="row" style="margin-top:20px;">
      <button id="btn-mercadobod-confirm" disabled>Confirmar e ingestar</button>
      <span id="mercadobod-ingest-status" class="muted"></span>
    </div>
  </div>

  </div>

</div>
```

- [ ] **Step 3: Agregar el listener de sub-tabs**

En `web/ingesta.html`, junto al listener existente de `#er-subtabs` (línea ~1176-1183), agregar:

```javascript
document.querySelectorAll('#mercado-subtabs .er-subtab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#mercado-subtabs .er-subtab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('#tab-mercado .er-activo-panel').forEach(p => p.classList.add('hidden'));
    btn.classList.add('active');
    document.getElementById('mercado-panel-' + btn.dataset.mercadotab).classList.remove('hidden');
  });
});
```

- [ ] **Step 4: Agregar el JS del sub-panel Bodegas**

Después de `populateMercadoTrimestres(); checkMercadoPeriodoStatus();` (línea ~2037-2039), agregar:

```javascript
let lastMercadoBodTexto = null;
let lastMercadoBodPeriodo = null;
let lastMercadoBodValidationOk = false;

function populateMercadoBodegasSemestres() {
  const now = new Date();
  const currentYear = now.getFullYear();
  const currentMonth = now.getMonth() + 1;
  const currentSemestre = currentMonth <= 6 ? '06' : '12';
  const selectedYear = currentMonth > 6 ? currentYear : currentYear;

  for (let y = currentYear - 2; y <= currentYear + 1; y++) {
    for (const m of ['06', '12']) {
      const opt = document.createElement('option');
      opt.value = `${y}-${m}`;
      opt.textContent = `${m === '06' ? '1S' : '2S'}-${y}`;
      mercadoBodPeriodo.appendChild(opt);
      if (y === selectedYear && m === currentSemestre) {
        opt.selected = true;
      }
    }
  }
}

const mercadoBodPeriodo = document.getElementById('mercadobod-periodo');
const mercadoBodInput = document.getElementById('mercadobod-input');
const btnMercadoBodValidate = document.getElementById('btn-mercadobod-validate');
const mercadoBodValidateStatus = document.getElementById('mercadobod-validate-status');
const btnMercadoBodConfirm = document.getElementById('btn-mercadobod-confirm');
const mercadoBodIngestStatus = document.getElementById('mercadobod-ingest-status');
const mercadoBodPeriodoStatusRow = document.getElementById('mercadobod-periodo-status-row');

async function checkMercadoBodPeriodoStatus() {
  const periodo = mercadoBodPeriodo.value;
  mercadoBodPeriodoStatusRow.innerHTML = '';
  if (!periodo) return;
  try {
    const res = await fetch(`/api/mercado/bodegas/periodo_check?periodo=${periodo}`);
    const data = await res.json();
    if (data.ya_ingestado) {
      const el = document.createElement('span');
      el.className = 'badge';
      el.innerHTML = `<span class="dot warn"></span>${periodo} ya tiene ${data.n_filas} fila(s) vigentes — reingestar las reemplazará.`;
      mercadoBodPeriodoStatusRow.appendChild(el);
    }
  } catch (e) { /* silencioso */ }
}
mercadoBodPeriodo.addEventListener('change', checkMercadoBodPeriodoStatus);

function resetMercadoBodPreview() {
  document.getElementById('mercadobod-preview').classList.add('hidden');
  btnMercadoBodConfirm.disabled = true;
  lastMercadoBodValidationOk = false;
  setStatus(mercadoBodValidateStatus);
  setStatus(mercadoBodIngestStatus);
}
mercadoBodInput.addEventListener('input', resetMercadoBodPreview);
mercadoBodPeriodo.addEventListener('change', resetMercadoBodPreview);

function renderMercadoBodPreview(data) {
  document.getElementById('mercadobod-preview').classList.remove('hidden');
  const badges = document.getElementById('mercadobod-badges');
  badges.innerHTML = '';
  const errUl = document.getElementById('mercadobod-errors');
  const warnUl = document.getElementById('mercadobod-warnings');
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

  const tablaBody = document.getElementById('mercadobod-tabla-body');
  tablaBody.innerHTML = '';
  if (data.ok && data.filas && data.filas.length) {
    document.getElementById('mercadobod-section-tabla').classList.remove('hidden');
    data.filas.forEach(f => {
      const tr = document.createElement('tr');
      if (f.es_total) tr.style.fontWeight = '700';
      tr.innerHTML = `<td>${f.zona}</td>` +
        `<td class="num">${fmt(f.produccion_m2)}</td><td class="num">${fmt(f.inventario_final_m2)}</td>` +
        `<td class="num">${fmt(f.tasa_vacancia_pct)}%</td><td class="num">${fmt(f.precio_uf_m2)}</td>`;
      tablaBody.appendChild(tr);
    });
  } else {
    document.getElementById('mercadobod-section-tabla').classList.add('hidden');
  }

  lastMercadoBodValidationOk = data.ok;
  btnMercadoBodConfirm.disabled = !data.ok;
}

btnMercadoBodValidate.addEventListener('click', async () => {
  const texto = mercadoBodInput.value;
  const periodo = mercadoBodPeriodo.value;
  if (!periodo) { mercadoBodValidateStatus.textContent = 'Declara el período del informe.'; return; }
  setStatus(mercadoBodValidateStatus, 'Validando y preparando previsualización...', 'loading');
  btnMercadoBodValidate.disabled = true;
  btnMercadoBodConfirm.disabled = true;
  try {
    const res = await fetch('/api/mercado/bodegas/validate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({texto, periodo}),
    });
    const data = await res.json();
    lastMercadoBodTexto = texto;
    lastMercadoBodPeriodo = periodo;
    renderMercadoBodPreview(data);
    setStatus(mercadoBodValidateStatus, data.ok ? 'Previsualización lista.' : 'Revisa los errores de la previsualización.', data.ok ? 'success' : 'error');
  } catch (e) {
    setStatus(mercadoBodValidateStatus, 'Error: ' + e.message, 'error');
  } finally {
    btnMercadoBodValidate.disabled = false;
  }
});

btnMercadoBodConfirm.addEventListener('click', async () => {
  if (!lastMercadoBodValidationOk || lastMercadoBodTexto !== mercadoBodInput.value ||
      lastMercadoBodPeriodo !== mercadoBodPeriodo.value) {
    mercadoBodIngestStatus.textContent = 'Los datos cambiaron desde la última validación — vuelve a validar.';
    return;
  }
  btnMercadoBodConfirm.disabled = true;
  setStatus(mercadoBodIngestStatus, 'Ingestando en la base de datos...', 'loading');
  try {
    const res = await fetch('/api/mercado/bodegas/commit', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({texto: lastMercadoBodTexto, periodo: lastMercadoBodPeriodo}),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || 'error desconocido');
    if (data.status === 'skipped_duplicate') {
      setStatus(mercadoBodIngestStatus, 'Este texto ya había sido ingestado antes — no se creó nada nuevo.', 'warn');
    } else {
      setStatus(mercadoBodIngestStatus,
        `Listo: ${data.filas_insertadas} filas insertadas` +
        (data.filas_superseded ? `, ${data.filas_superseded} filas anteriores reemplazadas` : '') +
        ` (run #${data.run_id}).`,
        'success');
    }
  } catch (e) {
    setStatus(mercadoBodIngestStatus, 'Error al ingestar: ' + e.message, 'error');
    btnMercadoBodConfirm.disabled = false;
  }
});

populateMercadoBodegasSemestres();
checkMercadoBodPeriodoStatus();
```

- [ ] **Step 5: Verificación manual en el navegador**

Run: `python -X utf8 scripts/ingesta_server.py` (en background) y abrir `http://127.0.0.1:8765/ingesta#mercado`.
Expected:
- Tab superior dice "Mercado" (no "Mercado Oficinas").
- Sub-tabs "Oficinas" (activo por defecto) / "Bodegas" debajo del tab.
- Click en "Bodegas" muestra el formulario semestral; pegar el texto de ejemplo del informe GPS Property, click "Validar y previsualizar" → preview con 6 filas, sin errores; click "Confirmar e ingestar" → mensaje de éxito.
- Volver a página TRI del factsheet (`/factsheet`) → tabla `tbl-bodegas` ahora muestra los valores reales en vez de "—".

- [ ] **Step 6: Commit**

```bash
git add web/ingesta.html
git commit -m "feat(ui): tab Mercado consolidado con sub-tabs Oficinas/Bodegas"
```

---

### Task 7: Suite completa + regresión

**Files:** ninguno nuevo — solo verificación.

- [ ] **Step 1: Correr toda la suite de tests**

Run: `python -m pytest tests/ -q`
Expected: PASS, 0 failures (incluye todos los tests nuevos de Tasks 1-6 y ningún test preexistente roto)

- [ ] **Step 2: Regenerar el factsheet completo**

Run: `python -X utf8 scripts/build_factsheet.py`
Expected: sin errores, sin warnings nuevos sobre `mercado_bodegas`/`bodegas_evolucion`

- [ ] **Step 3: Commit final si quedó algo pendiente**

```bash
git status
```

Si hay cambios sin commitear (p. ej. `factsheet.html` regenerado), confirmar con el usuario antes de commitear — es un artefacto generado, verificar si el repo lo trackea.
