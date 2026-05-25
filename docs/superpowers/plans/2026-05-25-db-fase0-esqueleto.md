# DB Migration — Fase 0: Esqueleto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear el esqueleto de la base de datos del agente: schema versionado, migraciones, seeds de dimensiones y repos vacíos por dominio — sin tocar el flujo mensual actual.

**Architecture:** SQLite (reusando `memory/agente_toesca.db`), capa de acceso en `tools/db/` con repos por dominio. Migraciones SQL versionadas aplicadas idempotentemente al startup. Seeds desde catálogos hoy hardcoded en código.

**Tech Stack:** Python 3.12, `sqlite3` (stdlib), `pytest` para tests. Cero dependencias nuevas en producción.

**Referencia:** `docs/superpowers/specs/2026-05-25-db-migration-design.md` (secciones 3, 4, 5 — Fase 0).

---

## File Structure

```
tools/db/
  __init__.py
  connection.py          # _get_conn(), aplicar migraciones al import
  migrations/
    __init__.py
    001_init_dimensions.sql
    002_init_raw.sql
    003_init_facts.sql
    004_init_derived.sql
    005_init_audit.sql
    006_seed_dimensions.sql
  repo_fondo.py          # dim_fondo / dim_activo / dim_serie / dim_cuenta
  repo_rent_roll.py      # raw_rent_roll_line
  repo_eeff.py           # raw_eeff_line
  repo_flujo.py          # raw_flujo_line
  repo_er_activo.py      # raw_er_activo_line
  repo_fact.py           # fact_precio_cuota / fact_uf / fact_dividendo
  repo_kpi.py            # derived_kpi
  repo_audit.py          # ingest_run / publish_run
  errors.py              # excepciones tipadas

tests/
  conftest.py            # fixture tmp_db: instancia SQLite en archivo temporal
  db/
    __init__.py
    test_migrations.py
    test_seeds.py
    test_repo_fondo.py
    test_repo_rent_roll.py
    test_repo_eeff.py
    test_repo_flujo.py
    test_repo_er_activo.py
    test_repo_fact.py
    test_repo_kpi.py
    test_repo_audit.py
```

Cada repo tiene una sola responsabilidad: CRUD sobre su(s) tabla(s) + queries específicas. El resto del agente nunca toca `sqlite3` directamente.

---

## Task 1: Bootstrap — pytest y estructura de tests

**Files:**
- Create: `tests/__init__.py` (vacío)
- Create: `tests/db/__init__.py` (vacío)
- Create: `tests/conftest.py`
- Modify: `pyproject.toml` o crear `pytest.ini`

- [ ] **Step 1: Instalar pytest**

Run: `pip install pytest`
Expected: `Successfully installed pytest-X.Y.Z`

- [ ] **Step 2: Crear archivos `__init__.py` vacíos**

```bash
mkdir -p tests/db
type nul > tests/__init__.py
type nul > tests/db/__init__.py
```

(Windows: usar `type nul > file` o crear desde Python; en bash: `touch`.)

- [ ] **Step 3: Crear `pytest.ini` en la raíz**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 4: Crear `tests/conftest.py` con fixture `tmp_db`**

```python
"""Fixtures globales para tests."""
import os
import sqlite3
import tempfile

import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    """Path a un archivo SQLite temporal (no se aplica schema)."""
    return str(tmp_path / "test.db")


@pytest.fixture
def tmp_db(tmp_db_path):
    """Conexión SQLite a un archivo temporal con schema aplicado."""
    from tools.db.connection import apply_migrations, get_conn_for

    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    yield conn
    conn.close()
```

- [ ] **Step 5: Verificar que pytest descubre el directorio**

Run: `pytest --collect-only`
Expected: `collected 0 items` (sin errores, solo "no tests").

- [ ] **Step 6: Commit**

```bash
git add tests/__init__.py tests/db/__init__.py tests/conftest.py pytest.ini
git commit -m "test: bootstrap pytest + fixture tmp_db"
```

---

## Task 2: Capa de conexión + sistema de migraciones

**Files:**
- Create: `tools/db/__init__.py` (vacío)
- Create: `tools/db/connection.py`
- Create: `tools/db/migrations/__init__.py` (vacío)
- Create: `tools/db/migrations/001_init_dimensions.sql`
- Create: `tests/db/test_migrations.py`

- [ ] **Step 1: Escribir test de aplicación inicial de migraciones**

Crear `tests/db/test_migrations.py`:

```python
"""Tests del sistema de migraciones."""
import sqlite3

import pytest

from tools.db.connection import apply_migrations, get_conn_for, current_version


def test_apply_migrations_creates_schema_version_table(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    assert cur.fetchone() is not None


def test_apply_migrations_records_versions(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT version FROM schema_version ORDER BY version")
    versions = [row[0] for row in cur.fetchall()]
    assert versions == sorted(versions)
    assert 1 in versions  # 001_init_dimensions debe estar aplicado


def test_apply_migrations_is_idempotent(tmp_db_path):
    apply_migrations(tmp_db_path)
    v1 = current_version(tmp_db_path)
    apply_migrations(tmp_db_path)
    v2 = current_version(tmp_db_path)
    assert v1 == v2


def test_apply_migrations_creates_dim_tables(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cur.fetchall()}
    assert {"dim_fondo", "dim_activo", "dim_serie", "dim_cuenta"} <= tables
```

- [ ] **Step 2: Correr tests para confirmar que fallan por imports faltantes**

Run: `pytest tests/db/test_migrations.py -v`
Expected: `ImportError: cannot import name 'apply_migrations' from 'tools.db.connection'`

- [ ] **Step 3: Crear `tools/db/__init__.py` vacío y `tools/db/migrations/__init__.py` vacío**

```python
# tools/db/__init__.py
```

```python
# tools/db/migrations/__init__.py
```

- [ ] **Step 4: Implementar `tools/db/connection.py`**

```python
"""Conexión SQLite y aplicación de migraciones."""
import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "memory",
    "agente_toesca.db",
)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_conn_for(db_path: str) -> sqlite3.Connection:
    """Conexión a un .db específico, con foreign keys activadas."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def get_conn() -> sqlite3.Connection:
    """Conexión a la DB por defecto del agente."""
    return get_conn_for(DEFAULT_DB_PATH)


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()


def current_version(db_path: str) -> int:
    conn = get_conn_for(db_path)
    try:
        _ensure_schema_version_table(conn)
        cur = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        return cur.fetchone()[0]
    finally:
        conn.close()


def _discover_migrations() -> list[tuple[int, Path]]:
    """Devuelve [(version, path), …] ordenado por version."""
    out = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        name = path.stem  # ej. '001_init_dimensions'
        version_str = name.split("_", 1)[0]
        if not version_str.isdigit():
            continue
        out.append((int(version_str), path))
    return out


def apply_migrations(db_path: str) -> list[int]:
    """Aplica todas las migraciones pendientes. Devuelve lista de versions aplicadas."""
    conn = get_conn_for(db_path)
    applied = []
    try:
        _ensure_schema_version_table(conn)
        cur = conn.execute("SELECT version FROM schema_version")
        done = {row[0] for row in cur.fetchall()}

        for version, path in _discover_migrations():
            if version in done:
                continue
            sql = path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (version,)
            )
            conn.commit()
            applied.append(version)
    finally:
        conn.close()
    return applied
```

- [ ] **Step 5: Crear `tools/db/migrations/001_init_dimensions.sql`**

```sql
-- Dimensiones: catálogos estables del negocio.

CREATE TABLE dim_fondo (
    fondo_key          TEXT PRIMARY KEY,
    nombre             TEXT NOT NULL,
    sharepoint_folder  TEXT
);

CREATE TABLE dim_activo (
    activo_key  TEXT PRIMARY KEY,
    fondo_key   TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    nombre      TEXT NOT NULL,
    tipo        TEXT
);

CREATE TABLE dim_serie (
    nemotecnico  TEXT PRIMARY KEY,
    fondo_key    TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    serie        TEXT NOT NULL
);

CREATE TABLE dim_cuenta (
    codigo      TEXT PRIMARY KEY,
    nombre      TEXT NOT NULL,
    tipo_eeff   TEXT,
    signo       INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_dim_activo_fondo ON dim_activo(fondo_key);
CREATE INDEX idx_dim_serie_fondo  ON dim_serie(fondo_key);
```

- [ ] **Step 6: Correr tests para verificar que pasan**

Run: `pytest tests/db/test_migrations.py -v`
Expected: 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/db/__init__.py tools/db/connection.py tools/db/migrations/ tests/db/test_migrations.py
git commit -m "feat(db): conexión + sistema de migraciones + schema dimensions"
```

---

## Task 3: Migraciones raw, fact, derived, audit

**Files:**
- Create: `tools/db/migrations/002_init_raw.sql`
- Create: `tools/db/migrations/003_init_facts.sql`
- Create: `tools/db/migrations/004_init_derived.sql`
- Create: `tools/db/migrations/005_init_audit.sql`
- Modify: `tests/db/test_migrations.py` (agregar verificaciones)

- [ ] **Step 1: Extender test para verificar tablas raw/fact/derived/audit**

Agregar al final de `tests/db/test_migrations.py`:

```python
def test_apply_migrations_creates_raw_tables(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert {
        "raw_rent_roll_line",
        "raw_eeff_line",
        "raw_flujo_line",
        "raw_er_activo_line",
    } <= tables


def test_apply_migrations_creates_fact_tables(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert {"fact_precio_cuota", "fact_uf", "fact_dividendo"} <= tables


def test_apply_migrations_creates_derived_and_audit_tables(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert {"derived_kpi", "ingest_run", "publish_run"} <= tables


def test_raw_rent_roll_unique_file_hash_source_row(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    conn.execute("INSERT INTO dim_fondo(fondo_key, nombre) VALUES ('F1', 'F1')")
    conn.execute(
        "INSERT INTO dim_activo(activo_key, fondo_key, nombre) VALUES ('A1','F1','A1')"
    )
    conn.execute(
        """INSERT INTO raw_rent_roll_line(activo_key, periodo, file_hash, source_row)
           VALUES ('A1','2026-04','HASH1', 5)"""
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO raw_rent_roll_line(activo_key, periodo, file_hash, source_row)
               VALUES ('A1','2026-04','HASH1', 5)"""
        )
        conn.commit()
```

- [ ] **Step 2: Correr tests, verificar que fallan**

Run: `pytest tests/db/test_migrations.py -v`
Expected: los 4 nuevos tests FAIL con "no such table".

- [ ] **Step 3: Crear `tools/db/migrations/002_init_raw.sql`**

```sql
-- Capa raw: una fila por línea del documento del proveedor.

CREATE TABLE raw_rent_roll_line (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key      TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo         TEXT NOT NULL,
    unidad          TEXT,
    arrendatario    TEXT,
    m2              REAL,
    renta_uf        REAL,
    vencimiento     TEXT,
    extra_json      TEXT,
    source_file     TEXT,
    source_sheet    TEXT,
    source_row      INTEGER,
    file_hash       TEXT NOT NULL,
    ingest_run_id   INTEGER,
    loaded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at   TEXT,
    UNIQUE (file_hash, source_row)
);

CREATE INDEX idx_raw_rr_activo_periodo ON raw_rent_roll_line(activo_key, periodo);
CREATE INDEX idx_raw_rr_hash           ON raw_rent_roll_line(file_hash);

CREATE TABLE raw_eeff_line (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key       TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    periodo         TEXT NOT NULL,
    cuenta_codigo   TEXT REFERENCES dim_cuenta(codigo),
    cuenta_nombre   TEXT,
    monto_clp       REAL,
    monto_uf        REAL,
    source_file     TEXT,
    source_sheet    TEXT,
    source_row      INTEGER,
    file_hash       TEXT NOT NULL,
    ingest_run_id   INTEGER,
    loaded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at   TEXT,
    UNIQUE (file_hash, source_row)
);

CREATE INDEX idx_raw_eeff_fondo_periodo ON raw_eeff_line(fondo_key, periodo);

CREATE TABLE raw_flujo_line (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key      TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo         TEXT NOT NULL,
    cuenta_codigo   TEXT REFERENCES dim_cuenta(codigo),
    cuenta_nombre   TEXT,
    monto_clp       REAL,
    monto_uf        REAL,
    source_file     TEXT,
    source_sheet    TEXT,
    source_row      INTEGER,
    file_hash       TEXT NOT NULL,
    ingest_run_id   INTEGER,
    loaded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at   TEXT,
    UNIQUE (file_hash, source_row)
);

CREATE INDEX idx_raw_flujo_activo_periodo ON raw_flujo_line(activo_key, periodo);

CREATE TABLE raw_er_activo_line (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key      TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo         TEXT NOT NULL,
    cuenta_codigo   TEXT REFERENCES dim_cuenta(codigo),
    cuenta_nombre   TEXT,
    monto_clp       REAL,
    monto_uf        REAL,
    source_file     TEXT,
    source_sheet    TEXT,
    source_row      INTEGER,
    file_hash       TEXT NOT NULL,
    ingest_run_id   INTEGER,
    loaded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at   TEXT,
    UNIQUE (file_hash, source_row)
);

CREATE INDEX idx_raw_er_activo_periodo ON raw_er_activo_line(activo_key, periodo);
```

- [ ] **Step 4: Crear `tools/db/migrations/003_init_facts.sql`**

```sql
-- Facts: datos directos del mercado, fuente única.

CREATE TABLE fact_precio_cuota (
    nemotecnico  TEXT NOT NULL REFERENCES dim_serie(nemotecnico),
    fecha        TEXT NOT NULL,
    precio       REAL NOT NULL,
    fuente       TEXT,
    loaded_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (nemotecnico, fecha)
);

CREATE TABLE fact_uf (
    fecha      TEXT PRIMARY KEY,
    valor_clp  REAL NOT NULL,
    loaded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE fact_dividendo (
    nemotecnico  TEXT NOT NULL REFERENCES dim_serie(nemotecnico),
    fecha_pago   TEXT NOT NULL,
    monto        REAL NOT NULL,
    loaded_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (nemotecnico, fecha_pago)
);
```

- [ ] **Step 5: Crear `tools/db/migrations/004_init_derived.sql`**

```sql
-- Derived: KPIs calculados por el agente.

CREATE TABLE derived_kpi (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad_tipo    TEXT NOT NULL CHECK (entidad_tipo IN ('fondo','activo','serie')),
    entidad_key     TEXT NOT NULL,
    periodo         TEXT NOT NULL,
    kpi             TEXT NOT NULL,
    valor           REAL,
    unidad          TEXT,
    recipe          TEXT NOT NULL,
    ingest_run_id   INTEGER,
    computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (entidad_tipo, entidad_key, periodo, kpi, recipe)
);

CREATE INDEX idx_kpi_entidad     ON derived_kpi(entidad_tipo, entidad_key);
CREATE INDEX idx_kpi_periodo     ON derived_kpi(periodo);
CREATE INDEX idx_kpi_kpi         ON derived_kpi(kpi);
```

- [ ] **Step 6: Crear `tools/db/migrations/005_init_audit.sql`**

```sql
-- Audit: trazabilidad de cargas y publicaciones.

CREATE TABLE ingest_run (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tool          TEXT NOT NULL,
    source_file   TEXT,
    file_hash     TEXT,
    rows_in       INTEGER,
    rows_loaded   INTEGER,
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at      TEXT,
    status        TEXT NOT NULL DEFAULT 'started',
    error         TEXT
);

CREATE INDEX idx_ingest_run_hash ON ingest_run(file_hash);

CREATE TABLE publish_run (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tool            TEXT NOT NULL,
    target_excel    TEXT,
    target_sheet    TEXT,
    periodo         TEXT,
    rows_written    INTEGER,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at        TEXT,
    status          TEXT NOT NULL DEFAULT 'started',
    error           TEXT
);
```

- [ ] **Step 7: Correr tests, verificar que pasan**

Run: `pytest tests/db/test_migrations.py -v`
Expected: 7 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add tools/db/migrations/ tests/db/test_migrations.py
git commit -m "feat(db): migraciones raw/fact/derived/audit"
```

---

## Task 4: Seeds de dimensiones desde catálogos actuales

**Files:**
- Create: `tools/db/migrations/006_seed_dimensions.sql`
- Create: `tests/db/test_seeds.py`

**Contexto.** Los catálogos viven hoy en código:
- `dim_fondo`: tres fondos del CLAUDE.md (A&R Apoquindo, A&R PT, A&R Rentas).
- `dim_activo`: INMOSA, PT, Viña Centro, Mall Curicó, Apoquindo, Apo3001.
- `dim_serie`: CFITRIPT-E, CFITOERI1A, CFITOERI1C, CFITOERI1I.
- `dim_cuenta`: sembrar vacío en esta fase; se poblará a medida que cada ingest descubra códigos.

- [ ] **Step 1: Escribir tests de seeds**

Crear `tests/db/test_seeds.py`:

```python
"""Tests de los seeds de dimensiones."""
from tools.db.connection import apply_migrations, get_conn_for


def test_seed_fondos(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT fondo_key FROM dim_fondo ORDER BY fondo_key")
    keys = [row[0] for row in cur.fetchall()]
    assert keys == ["A&R Apoquindo", "A&R PT", "A&R Rentas"]


def test_seed_activos(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT activo_key, fondo_key FROM dim_activo ORDER BY activo_key")
    rows = cur.fetchall()
    keys = [r[0] for r in rows]
    assert set(keys) == {"INMOSA", "PT", "Viña Centro", "Mall Curicó", "Apoquindo", "Apo3001"}


def test_seed_series(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT nemotecnico, fondo_key, serie FROM dim_serie ORDER BY nemotecnico")
    rows = [tuple(r) for r in cur.fetchall()]
    assert ("CFITRIPT-E", "A&R PT", "Única") in rows
    assert ("CFITOERI1A", "A&R Rentas", "A") in rows
    assert ("CFITOERI1C", "A&R Rentas", "C") in rows
    assert ("CFITOERI1I", "A&R Rentas", "I") in rows


def test_seed_idempotent(tmp_db_path):
    apply_migrations(tmp_db_path)
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT COUNT(*) FROM dim_fondo")
    assert cur.fetchone()[0] == 3
```

- [ ] **Step 2: Correr tests, verificar que fallan**

Run: `pytest tests/db/test_seeds.py -v`
Expected: 4 tests FAIL ("got 0", "got []").

- [ ] **Step 3: Crear `tools/db/migrations/006_seed_dimensions.sql`**

```sql
-- Seeds de dimensiones desde catálogos hardcoded en código.
-- INSERT OR IGNORE para que la migración sea segura ante reaplicaciones manuales.

INSERT OR IGNORE INTO dim_fondo (fondo_key, nombre, sharepoint_folder) VALUES
  ('A&R Apoquindo', 'Toesca Rentas Inmobiliarias Apoquindo', 'Fondos\Rentas Apoquindo'),
  ('A&R PT',        'Toesca Rentas Inmobiliarias PT',        'Fondos\Rentas PT'),
  ('A&R Rentas',    'Toesca Rentas Inmobiliarias',           'Fondos\Rentas TRI');

INSERT OR IGNORE INTO dim_activo (activo_key, fondo_key, nombre, tipo) VALUES
  ('INMOSA',      'A&R Rentas',    'INMOSA',         'inmobiliario'),
  ('PT',          'A&R PT',        'Parque Titanium','oficina'),
  ('Viña Centro', 'A&R Rentas',    'Viña Centro',    'retail'),
  ('Mall Curicó', 'A&R Rentas',    'Mall Curicó',    'retail'),
  ('Apoquindo',   'A&R Apoquindo', 'Fondo Apoquindo','oficina'),
  ('Apo3001',     'A&R Apoquindo', 'Apoquindo 3001', 'oficina');

INSERT OR IGNORE INTO dim_serie (nemotecnico, fondo_key, serie) VALUES
  ('CFITRIPT-E', 'A&R PT',     'Única'),
  ('CFITOERI1A', 'A&R Rentas', 'A'),
  ('CFITOERI1C', 'A&R Rentas', 'C'),
  ('CFITOERI1I', 'A&R Rentas', 'I');
```

- [ ] **Step 4: Correr tests, verificar que pasan**

Run: `pytest tests/db/test_seeds.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db/migrations/006_seed_dimensions.sql tests/db/test_seeds.py
git commit -m "feat(db): seeds de fondos, activos y series"
```

---

## Task 5: `errors.py` — excepciones tipadas

**Files:**
- Create: `tools/db/errors.py`

- [ ] **Step 1: Crear `tools/db/errors.py`**

```python
"""Excepciones tipadas para la capa DB."""


class DBError(Exception):
    """Base para errores de la capa DB."""


class NotFoundError(DBError):
    """Entidad solicitada no existe."""


class DuplicateError(DBError):
    """Ya existe un registro con la misma clave única."""


class ValidationError(DBError):
    """Datos de entrada no pasaron validación."""
```

- [ ] **Step 2: Commit**

```bash
git add tools/db/errors.py
git commit -m "feat(db): excepciones tipadas"
```

---

## Task 6: `repo_fondo.py` — acceso a dimensiones

**Files:**
- Create: `tools/db/repo_fondo.py`
- Create: `tests/db/test_repo_fondo.py`

- [ ] **Step 1: Escribir tests del repo de dimensiones**

```python
"""Tests del repo de dimensiones (fondos, activos, series, cuentas)."""
import pytest

from tools.db import repo_fondo
from tools.db.errors import NotFoundError


def test_list_fondos(tmp_db):
    fondos = repo_fondo.list_fondos(tmp_db)
    keys = [f["fondo_key"] for f in fondos]
    assert keys == ["A&R Apoquindo", "A&R PT", "A&R Rentas"]


def test_get_fondo(tmp_db):
    f = repo_fondo.get_fondo(tmp_db, "A&R PT")
    assert f["nombre"] == "Toesca Rentas Inmobiliarias PT"


def test_get_fondo_not_found(tmp_db):
    with pytest.raises(NotFoundError):
        repo_fondo.get_fondo(tmp_db, "NO_EXISTE")


def test_list_activos_de_fondo(tmp_db):
    activos = repo_fondo.list_activos(tmp_db, fondo_key="A&R Rentas")
    keys = sorted(a["activo_key"] for a in activos)
    assert keys == ["INMOSA", "Mall Curicó", "Viña Centro"]


def test_list_series_de_fondo(tmp_db):
    series = repo_fondo.list_series(tmp_db, fondo_key="A&R Rentas")
    keys = sorted(s["nemotecnico"] for s in series)
    assert keys == ["CFITOERI1A", "CFITOERI1C", "CFITOERI1I"]


def test_upsert_cuenta(tmp_db):
    repo_fondo.upsert_cuenta(tmp_db, codigo="4-01-001", nombre="Ingresos arriendo", tipo_eeff="ER", signo=1)
    cur = tmp_db.execute("SELECT nombre, tipo_eeff, signo FROM dim_cuenta WHERE codigo=?", ("4-01-001",))
    row = cur.fetchone()
    assert row["nombre"] == "Ingresos arriendo"
    assert row["signo"] == 1


def test_upsert_cuenta_idempotente(tmp_db):
    repo_fondo.upsert_cuenta(tmp_db, codigo="4-01-001", nombre="V1", tipo_eeff="ER", signo=1)
    repo_fondo.upsert_cuenta(tmp_db, codigo="4-01-001", nombre="V2", tipo_eeff="ER", signo=1)
    cur = tmp_db.execute("SELECT COUNT(*) AS n, nombre FROM dim_cuenta WHERE codigo=?", ("4-01-001",))
    row = cur.fetchone()
    assert row["n"] == 1
    assert row["nombre"] == "V2"
```

- [ ] **Step 2: Correr tests, verificar que fallan**

Run: `pytest tests/db/test_repo_fondo.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'tools.db.repo_fondo'`.

- [ ] **Step 3: Implementar `tools/db/repo_fondo.py`**

```python
"""Repo de dimensiones: fondos, activos, series, cuentas."""
import sqlite3

from tools.db.errors import NotFoundError


def list_fondos(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM dim_fondo ORDER BY fondo_key")
    return cur.fetchall()


def get_fondo(conn: sqlite3.Connection, fondo_key: str) -> sqlite3.Row:
    cur = conn.execute("SELECT * FROM dim_fondo WHERE fondo_key=?", (fondo_key,))
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"Fondo no encontrado: {fondo_key}")
    return row


def list_activos(
    conn: sqlite3.Connection, fondo_key: str | None = None
) -> list[sqlite3.Row]:
    if fondo_key is None:
        cur = conn.execute("SELECT * FROM dim_activo ORDER BY activo_key")
    else:
        cur = conn.execute(
            "SELECT * FROM dim_activo WHERE fondo_key=? ORDER BY activo_key",
            (fondo_key,),
        )
    return cur.fetchall()


def get_activo(conn: sqlite3.Connection, activo_key: str) -> sqlite3.Row:
    cur = conn.execute("SELECT * FROM dim_activo WHERE activo_key=?", (activo_key,))
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"Activo no encontrado: {activo_key}")
    return row


def list_series(
    conn: sqlite3.Connection, fondo_key: str | None = None
) -> list[sqlite3.Row]:
    if fondo_key is None:
        cur = conn.execute("SELECT * FROM dim_serie ORDER BY nemotecnico")
    else:
        cur = conn.execute(
            "SELECT * FROM dim_serie WHERE fondo_key=? ORDER BY nemotecnico",
            (fondo_key,),
        )
    return cur.fetchall()


def get_serie(conn: sqlite3.Connection, nemotecnico: str) -> sqlite3.Row:
    cur = conn.execute("SELECT * FROM dim_serie WHERE nemotecnico=?", (nemotecnico,))
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"Serie no encontrada: {nemotecnico}")
    return row


def upsert_cuenta(
    conn: sqlite3.Connection,
    codigo: str,
    nombre: str,
    tipo_eeff: str | None = None,
    signo: int = 1,
) -> None:
    conn.execute(
        """INSERT INTO dim_cuenta (codigo, nombre, tipo_eeff, signo)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(codigo) DO UPDATE SET
             nombre = excluded.nombre,
             tipo_eeff = excluded.tipo_eeff,
             signo = excluded.signo""",
        (codigo, nombre, tipo_eeff, signo),
    )
    conn.commit()


def get_cuenta(conn: sqlite3.Connection, codigo: str) -> sqlite3.Row:
    cur = conn.execute("SELECT * FROM dim_cuenta WHERE codigo=?", (codigo,))
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"Cuenta no encontrada: {codigo}")
    return row
```

- [ ] **Step 4: Correr tests, verificar que pasan**

Run: `pytest tests/db/test_repo_fondo.py -v`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db/repo_fondo.py tests/db/test_repo_fondo.py
git commit -m "feat(db): repo_fondo — fondos/activos/series/cuentas"
```

---

## Task 7: `repo_audit.py` — ingest_run / publish_run

**Files:**
- Create: `tools/db/repo_audit.py`
- Create: `tests/db/test_repo_audit.py`

- [ ] **Step 1: Escribir tests**

```python
"""Tests del repo de audit."""
from tools.db import repo_audit


def test_start_and_finish_ingest_run(tmp_db):
    run_id = repo_audit.start_ingest_run(
        tmp_db, tool="ingest_rent_roll_jll", source_file="/x/rr.xlsx", file_hash="HASH1"
    )
    assert isinstance(run_id, int) and run_id > 0

    repo_audit.finish_ingest_run(
        tmp_db, run_id, rows_in=100, rows_loaded=98, status="ok"
    )
    row = tmp_db.execute(
        "SELECT rows_in, rows_loaded, status, ended_at FROM ingest_run WHERE id=?",
        (run_id,),
    ).fetchone()
    assert row["rows_in"] == 100
    assert row["rows_loaded"] == 98
    assert row["status"] == "ok"
    assert row["ended_at"] is not None


def test_fail_ingest_run(tmp_db):
    run_id = repo_audit.start_ingest_run(tmp_db, tool="t", source_file=None, file_hash=None)
    repo_audit.fail_ingest_run(tmp_db, run_id, error="boom")
    row = tmp_db.execute(
        "SELECT status, error FROM ingest_run WHERE id=?", (run_id,)
    ).fetchone()
    assert row["status"] == "failed"
    assert row["error"] == "boom"


def test_publish_run_lifecycle(tmp_db):
    run_id = repo_audit.start_publish_run(
        tmp_db,
        tool="publish_cdg_renta_pt",
        target_excel="/x/cdg.xlsx",
        target_sheet="A&R PT",
        periodo="2026-04",
    )
    repo_audit.finish_publish_run(tmp_db, run_id, rows_written=42, status="ok")
    row = tmp_db.execute(
        "SELECT rows_written, status FROM publish_run WHERE id=?", (run_id,)
    ).fetchone()
    assert row["rows_written"] == 42
    assert row["status"] == "ok"
```

- [ ] **Step 2: Correr tests, verificar que fallan**

Run: `pytest tests/db/test_repo_audit.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `tools/db/repo_audit.py`**

```python
"""Repo de audit: ingest_run / publish_run."""
import sqlite3


def start_ingest_run(
    conn: sqlite3.Connection,
    tool: str,
    source_file: str | None,
    file_hash: str | None,
) -> int:
    cur = conn.execute(
        """INSERT INTO ingest_run (tool, source_file, file_hash, status)
           VALUES (?, ?, ?, 'started')""",
        (tool, source_file, file_hash),
    )
    conn.commit()
    return cur.lastrowid


def finish_ingest_run(
    conn: sqlite3.Connection,
    run_id: int,
    rows_in: int,
    rows_loaded: int,
    status: str = "ok",
) -> None:
    conn.execute(
        """UPDATE ingest_run
              SET rows_in = ?, rows_loaded = ?, status = ?, ended_at = datetime('now')
            WHERE id = ?""",
        (rows_in, rows_loaded, status, run_id),
    )
    conn.commit()


def fail_ingest_run(conn: sqlite3.Connection, run_id: int, error: str) -> None:
    conn.execute(
        """UPDATE ingest_run
              SET status = 'failed', error = ?, ended_at = datetime('now')
            WHERE id = ?""",
        (error, run_id),
    )
    conn.commit()


def start_publish_run(
    conn: sqlite3.Connection,
    tool: str,
    target_excel: str,
    target_sheet: str,
    periodo: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO publish_run (tool, target_excel, target_sheet, periodo, status)
           VALUES (?, ?, ?, ?, 'started')""",
        (tool, target_excel, target_sheet, periodo),
    )
    conn.commit()
    return cur.lastrowid


def finish_publish_run(
    conn: sqlite3.Connection,
    run_id: int,
    rows_written: int,
    status: str = "ok",
) -> None:
    conn.execute(
        """UPDATE publish_run
              SET rows_written = ?, status = ?, ended_at = datetime('now')
            WHERE id = ?""",
        (rows_written, status, run_id),
    )
    conn.commit()


def fail_publish_run(conn: sqlite3.Connection, run_id: int, error: str) -> None:
    conn.execute(
        """UPDATE publish_run
              SET status = 'failed', error = ?, ended_at = datetime('now')
            WHERE id = ?""",
        (error, run_id),
    )
    conn.commit()
```

- [ ] **Step 4: Correr tests, verificar que pasan**

Run: `pytest tests/db/test_repo_audit.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db/repo_audit.py tests/db/test_repo_audit.py
git commit -m "feat(db): repo_audit — ingest_run/publish_run"
```

---

## Task 8: `repo_rent_roll.py`

**Files:**
- Create: `tools/db/repo_rent_roll.py`
- Create: `tests/db/test_repo_rent_roll.py`

**Contrato del repo (mismo patrón reusado en repo_eeff, repo_flujo, repo_er_activo):**
- `insert_lines(conn, lines: list[dict], ingest_run_id: int) -> int` — inserta líneas, devuelve cuántas insertadas. Las filas con `(file_hash, source_row)` ya existente se omiten (idempotencia).
- `mark_superseded(conn, file_hash: str)` — marca todas las filas con ese hash como reemplazadas.
- `list_by_periodo(conn, activo_key, periodo) -> list[Row]`.

- [ ] **Step 1: Escribir tests**

```python
"""Tests de repo_rent_roll."""
from tools.db import repo_audit, repo_rent_roll


def _seed_run(tmp_db):
    return repo_audit.start_ingest_run(
        tmp_db, tool="ingest_rent_roll_jll", source_file="/x/rr.xlsx", file_hash="HASH1"
    )


def test_insert_lines(tmp_db):
    run_id = _seed_run(tmp_db)
    n = repo_rent_roll.insert_lines(
        tmp_db,
        lines=[
            {
                "activo_key": "PT",
                "periodo": "2026-04",
                "unidad": "1001",
                "arrendatario": "Acme",
                "m2": 100.5,
                "renta_uf": 50.0,
                "vencimiento": "2027-12-31",
                "source_file": "/x/rr.xlsx",
                "source_sheet": "RR",
                "source_row": 5,
                "file_hash": "HASH1",
            }
        ],
        ingest_run_id=run_id,
    )
    assert n == 1


def test_insert_lines_idempotente(tmp_db):
    run_id = _seed_run(tmp_db)
    line = {
        "activo_key": "PT",
        "periodo": "2026-04",
        "source_row": 5,
        "file_hash": "HASH1",
    }
    assert repo_rent_roll.insert_lines(tmp_db, [line], run_id) == 1
    assert repo_rent_roll.insert_lines(tmp_db, [line], run_id) == 0


def test_list_by_periodo(tmp_db):
    run_id = _seed_run(tmp_db)
    repo_rent_roll.insert_lines(
        tmp_db,
        [
            {"activo_key": "PT", "periodo": "2026-04", "source_row": 1, "file_hash": "H1"},
            {"activo_key": "PT", "periodo": "2026-04", "source_row": 2, "file_hash": "H1"},
            {"activo_key": "PT", "periodo": "2026-03", "source_row": 1, "file_hash": "H2"},
        ],
        run_id,
    )
    rows = repo_rent_roll.list_by_periodo(tmp_db, activo_key="PT", periodo="2026-04")
    assert len(rows) == 2


def test_mark_superseded(tmp_db):
    run_id = _seed_run(tmp_db)
    repo_rent_roll.insert_lines(
        tmp_db,
        [{"activo_key": "PT", "periodo": "2026-04", "source_row": 1, "file_hash": "H1"}],
        run_id,
    )
    repo_rent_roll.mark_superseded(tmp_db, file_hash="H1")
    row = tmp_db.execute(
        "SELECT superseded_at FROM raw_rent_roll_line WHERE file_hash=?", ("H1",)
    ).fetchone()
    assert row["superseded_at"] is not None
```

- [ ] **Step 2: Correr tests, verificar que fallan**

Run: `pytest tests/db/test_repo_rent_roll.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `tools/db/repo_rent_roll.py`**

```python
"""Repo de raw_rent_roll_line."""
import sqlite3

_INSERT_COLS = [
    "activo_key", "periodo", "unidad", "arrendatario", "m2", "renta_uf",
    "vencimiento", "extra_json", "source_file", "source_sheet", "source_row",
    "file_hash", "ingest_run_id",
]


def insert_lines(
    conn: sqlite3.Connection,
    lines: list[dict],
    ingest_run_id: int,
) -> int:
    """Inserta líneas. Devuelve cuántas se insertaron (omite duplicados por (file_hash, source_row))."""
    cols_sql = ", ".join(_INSERT_COLS)
    placeholders = ", ".join(["?"] * len(_INSERT_COLS))
    sql = f"INSERT OR IGNORE INTO raw_rent_roll_line ({cols_sql}) VALUES ({placeholders})"

    inserted = 0
    for line in lines:
        values = tuple(
            ingest_run_id if c == "ingest_run_id" else line.get(c)
            for c in _INSERT_COLS
        )
        cur = conn.execute(sql, values)
        inserted += cur.rowcount if cur.rowcount > 0 else 0
    conn.commit()
    return inserted


def mark_superseded(conn: sqlite3.Connection, file_hash: str) -> None:
    conn.execute(
        """UPDATE raw_rent_roll_line
              SET superseded_at = datetime('now')
            WHERE file_hash = ? AND superseded_at IS NULL""",
        (file_hash,),
    )
    conn.commit()


def list_by_periodo(
    conn: sqlite3.Connection,
    activo_key: str,
    periodo: str,
    include_superseded: bool = False,
) -> list[sqlite3.Row]:
    if include_superseded:
        sql = """SELECT * FROM raw_rent_roll_line
                  WHERE activo_key=? AND periodo=?
                  ORDER BY source_row"""
    else:
        sql = """SELECT * FROM raw_rent_roll_line
                  WHERE activo_key=? AND periodo=? AND superseded_at IS NULL
                  ORDER BY source_row"""
    cur = conn.execute(sql, (activo_key, periodo))
    return cur.fetchall()
```

- [ ] **Step 4: Correr tests, verificar que pasan**

Run: `pytest tests/db/test_repo_rent_roll.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db/repo_rent_roll.py tests/db/test_repo_rent_roll.py
git commit -m "feat(db): repo_rent_roll — insert/list/mark_superseded"
```

---

## Task 9: `repo_eeff.py`

**Files:**
- Create: `tools/db/repo_eeff.py`
- Create: `tests/db/test_repo_eeff.py`

Mismo contrato que `repo_rent_roll`, sobre `raw_eeff_line`. La diferencia: la entidad es `fondo_key` (no `activo_key`) y las columnas son las contables.

- [ ] **Step 1: Escribir tests**

```python
"""Tests de repo_eeff."""
from tools.db import repo_audit, repo_eeff


def _seed_run(tmp_db):
    return repo_audit.start_ingest_run(
        tmp_db, tool="ingest_eeff_pdf", source_file="/x/eeff.pdf", file_hash="HX"
    )


def test_insert_and_list(tmp_db):
    run_id = _seed_run(tmp_db)
    n = repo_eeff.insert_lines(
        tmp_db,
        lines=[
            {
                "fondo_key": "A&R PT",
                "periodo": "2026-03",
                "cuenta_codigo": None,
                "cuenta_nombre": "Activos totales",
                "monto_clp": 1_000_000.0,
                "monto_uf": None,
                "source_file": "/x/eeff.pdf",
                "source_row": 12,
                "file_hash": "HX",
            }
        ],
        ingest_run_id=run_id,
    )
    assert n == 1

    rows = repo_eeff.list_by_periodo(tmp_db, fondo_key="A&R PT", periodo="2026-03")
    assert len(rows) == 1
    assert rows[0]["cuenta_nombre"] == "Activos totales"


def test_insert_idempotente(tmp_db):
    run_id = _seed_run(tmp_db)
    line = {"fondo_key": "A&R PT", "periodo": "2026-03", "source_row": 1, "file_hash": "HX"}
    assert repo_eeff.insert_lines(tmp_db, [line], run_id) == 1
    assert repo_eeff.insert_lines(tmp_db, [line], run_id) == 0


def test_mark_superseded(tmp_db):
    run_id = _seed_run(tmp_db)
    repo_eeff.insert_lines(
        tmp_db,
        [{"fondo_key": "A&R PT", "periodo": "2026-03", "source_row": 1, "file_hash": "HX"}],
        run_id,
    )
    repo_eeff.mark_superseded(tmp_db, file_hash="HX")
    rows = repo_eeff.list_by_periodo(tmp_db, fondo_key="A&R PT", periodo="2026-03")
    assert rows == []
```

- [ ] **Step 2: Correr tests, verificar que fallan**

Run: `pytest tests/db/test_repo_eeff.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `tools/db/repo_eeff.py`**

```python
"""Repo de raw_eeff_line."""
import sqlite3

_INSERT_COLS = [
    "fondo_key", "periodo", "cuenta_codigo", "cuenta_nombre",
    "monto_clp", "monto_uf",
    "source_file", "source_sheet", "source_row", "file_hash", "ingest_run_id",
]


def insert_lines(
    conn: sqlite3.Connection,
    lines: list[dict],
    ingest_run_id: int,
) -> int:
    cols_sql = ", ".join(_INSERT_COLS)
    placeholders = ", ".join(["?"] * len(_INSERT_COLS))
    sql = f"INSERT OR IGNORE INTO raw_eeff_line ({cols_sql}) VALUES ({placeholders})"
    inserted = 0
    for line in lines:
        values = tuple(
            ingest_run_id if c == "ingest_run_id" else line.get(c) for c in _INSERT_COLS
        )
        cur = conn.execute(sql, values)
        inserted += cur.rowcount if cur.rowcount > 0 else 0
    conn.commit()
    return inserted


def mark_superseded(conn: sqlite3.Connection, file_hash: str) -> None:
    conn.execute(
        """UPDATE raw_eeff_line
              SET superseded_at = datetime('now')
            WHERE file_hash = ? AND superseded_at IS NULL""",
        (file_hash,),
    )
    conn.commit()


def list_by_periodo(
    conn: sqlite3.Connection,
    fondo_key: str,
    periodo: str,
    include_superseded: bool = False,
) -> list[sqlite3.Row]:
    if include_superseded:
        sql = """SELECT * FROM raw_eeff_line
                  WHERE fondo_key=? AND periodo=?
                  ORDER BY source_row"""
    else:
        sql = """SELECT * FROM raw_eeff_line
                  WHERE fondo_key=? AND periodo=? AND superseded_at IS NULL
                  ORDER BY source_row"""
    cur = conn.execute(sql, (fondo_key, periodo))
    return cur.fetchall()
```

- [ ] **Step 4: Correr tests, verificar que pasan**

Run: `pytest tests/db/test_repo_eeff.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db/repo_eeff.py tests/db/test_repo_eeff.py
git commit -m "feat(db): repo_eeff — insert/list/mark_superseded"
```

---

## Task 10: `repo_flujo.py` y `repo_er_activo.py`

Estructura idéntica al `repo_rent_roll` (entidad = `activo_key`), pero sobre las tablas `raw_flujo_line` y `raw_er_activo_line` respectivamente, con columnas contables (`cuenta_codigo`, `cuenta_nombre`, `monto_clp`, `monto_uf`).

**Files:**
- Create: `tools/db/repo_flujo.py`
- Create: `tools/db/repo_er_activo.py`
- Create: `tests/db/test_repo_flujo.py`
- Create: `tests/db/test_repo_er_activo.py`

- [ ] **Step 1: Escribir tests de `repo_flujo`**

```python
"""Tests de repo_flujo."""
from tools.db import repo_audit, repo_flujo


def _run(tmp_db):
    return repo_audit.start_ingest_run(tmp_db, tool="t", source_file=None, file_hash="HF")


def test_insert_and_list(tmp_db):
    rid = _run(tmp_db)
    n = repo_flujo.insert_lines(
        tmp_db,
        [
            {
                "activo_key": "INMOSA",
                "periodo": "2026-04",
                "cuenta_codigo": None,
                "cuenta_nombre": "Ingresos",
                "monto_clp": 12345.0,
                "monto_uf": None,
                "source_file": "/x.xlsx",
                "source_sheet": "Flujo",
                "source_row": 7,
                "file_hash": "HF",
            }
        ],
        rid,
    )
    assert n == 1
    rows = repo_flujo.list_by_periodo(tmp_db, "INMOSA", "2026-04")
    assert len(rows) == 1


def test_idempotente(tmp_db):
    rid = _run(tmp_db)
    line = {"activo_key": "INMOSA", "periodo": "2026-04", "source_row": 1, "file_hash": "HF"}
    assert repo_flujo.insert_lines(tmp_db, [line], rid) == 1
    assert repo_flujo.insert_lines(tmp_db, [line], rid) == 0


def test_mark_superseded(tmp_db):
    rid = _run(tmp_db)
    repo_flujo.insert_lines(
        tmp_db,
        [{"activo_key": "INMOSA", "periodo": "2026-04", "source_row": 1, "file_hash": "HF"}],
        rid,
    )
    repo_flujo.mark_superseded(tmp_db, file_hash="HF")
    assert repo_flujo.list_by_periodo(tmp_db, "INMOSA", "2026-04") == []
```

- [ ] **Step 2: Implementar `tools/db/repo_flujo.py`**

```python
"""Repo de raw_flujo_line."""
import sqlite3

_INSERT_COLS = [
    "activo_key", "periodo", "cuenta_codigo", "cuenta_nombre",
    "monto_clp", "monto_uf",
    "source_file", "source_sheet", "source_row", "file_hash", "ingest_run_id",
]


def insert_lines(
    conn: sqlite3.Connection,
    lines: list[dict],
    ingest_run_id: int,
) -> int:
    cols_sql = ", ".join(_INSERT_COLS)
    placeholders = ", ".join(["?"] * len(_INSERT_COLS))
    sql = f"INSERT OR IGNORE INTO raw_flujo_line ({cols_sql}) VALUES ({placeholders})"
    inserted = 0
    for line in lines:
        values = tuple(
            ingest_run_id if c == "ingest_run_id" else line.get(c) for c in _INSERT_COLS
        )
        cur = conn.execute(sql, values)
        inserted += cur.rowcount if cur.rowcount > 0 else 0
    conn.commit()
    return inserted


def mark_superseded(conn: sqlite3.Connection, file_hash: str) -> None:
    conn.execute(
        """UPDATE raw_flujo_line
              SET superseded_at = datetime('now')
            WHERE file_hash = ? AND superseded_at IS NULL""",
        (file_hash,),
    )
    conn.commit()


def list_by_periodo(
    conn: sqlite3.Connection,
    activo_key: str,
    periodo: str,
    include_superseded: bool = False,
) -> list[sqlite3.Row]:
    if include_superseded:
        sql = """SELECT * FROM raw_flujo_line
                  WHERE activo_key=? AND periodo=?
                  ORDER BY source_row"""
    else:
        sql = """SELECT * FROM raw_flujo_line
                  WHERE activo_key=? AND periodo=? AND superseded_at IS NULL
                  ORDER BY source_row"""
    cur = conn.execute(sql, (activo_key, periodo))
    return cur.fetchall()
```

- [ ] **Step 3: Correr tests de flujo**

Run: `pytest tests/db/test_repo_flujo.py -v`
Expected: 3 tests PASS.

- [ ] **Step 4: Escribir tests de `repo_er_activo` (mismo patrón)**

```python
"""Tests de repo_er_activo."""
from tools.db import repo_audit, repo_er_activo


def _run(tmp_db):
    return repo_audit.start_ingest_run(tmp_db, tool="t", source_file=None, file_hash="HE")


def test_insert_and_list(tmp_db):
    rid = _run(tmp_db)
    n = repo_er_activo.insert_lines(
        tmp_db,
        [
            {
                "activo_key": "Viña Centro",
                "periodo": "2026-04",
                "cuenta_codigo": None,
                "cuenta_nombre": "Arriendos",
                "monto_clp": 50000.0,
                "monto_uf": None,
                "source_file": "/x.xlsx",
                "source_sheet": "ER",
                "source_row": 10,
                "file_hash": "HE",
            }
        ],
        rid,
    )
    assert n == 1
    rows = repo_er_activo.list_by_periodo(tmp_db, "Viña Centro", "2026-04")
    assert len(rows) == 1


def test_idempotente(tmp_db):
    rid = _run(tmp_db)
    line = {"activo_key": "Viña Centro", "periodo": "2026-04", "source_row": 1, "file_hash": "HE"}
    assert repo_er_activo.insert_lines(tmp_db, [line], rid) == 1
    assert repo_er_activo.insert_lines(tmp_db, [line], rid) == 0


def test_mark_superseded(tmp_db):
    rid = _run(tmp_db)
    repo_er_activo.insert_lines(
        tmp_db,
        [{"activo_key": "Viña Centro", "periodo": "2026-04", "source_row": 1, "file_hash": "HE"}],
        rid,
    )
    repo_er_activo.mark_superseded(tmp_db, file_hash="HE")
    assert repo_er_activo.list_by_periodo(tmp_db, "Viña Centro", "2026-04") == []
```

- [ ] **Step 5: Implementar `tools/db/repo_er_activo.py`**

```python
"""Repo de raw_er_activo_line."""
import sqlite3

_INSERT_COLS = [
    "activo_key", "periodo", "cuenta_codigo", "cuenta_nombre",
    "monto_clp", "monto_uf",
    "source_file", "source_sheet", "source_row", "file_hash", "ingest_run_id",
]


def insert_lines(
    conn: sqlite3.Connection,
    lines: list[dict],
    ingest_run_id: int,
) -> int:
    cols_sql = ", ".join(_INSERT_COLS)
    placeholders = ", ".join(["?"] * len(_INSERT_COLS))
    sql = f"INSERT OR IGNORE INTO raw_er_activo_line ({cols_sql}) VALUES ({placeholders})"
    inserted = 0
    for line in lines:
        values = tuple(
            ingest_run_id if c == "ingest_run_id" else line.get(c) for c in _INSERT_COLS
        )
        cur = conn.execute(sql, values)
        inserted += cur.rowcount if cur.rowcount > 0 else 0
    conn.commit()
    return inserted


def mark_superseded(conn: sqlite3.Connection, file_hash: str) -> None:
    conn.execute(
        """UPDATE raw_er_activo_line
              SET superseded_at = datetime('now')
            WHERE file_hash = ? AND superseded_at IS NULL""",
        (file_hash,),
    )
    conn.commit()


def list_by_periodo(
    conn: sqlite3.Connection,
    activo_key: str,
    periodo: str,
    include_superseded: bool = False,
) -> list[sqlite3.Row]:
    if include_superseded:
        sql = """SELECT * FROM raw_er_activo_line
                  WHERE activo_key=? AND periodo=?
                  ORDER BY source_row"""
    else:
        sql = """SELECT * FROM raw_er_activo_line
                  WHERE activo_key=? AND periodo=? AND superseded_at IS NULL
                  ORDER BY source_row"""
    cur = conn.execute(sql, (activo_key, periodo))
    return cur.fetchall()
```

- [ ] **Step 6: Correr tests, verificar que pasan**

Run: `pytest tests/db/test_repo_flujo.py tests/db/test_repo_er_activo.py -v`
Expected: 6 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/db/repo_flujo.py tools/db/repo_er_activo.py tests/db/test_repo_flujo.py tests/db/test_repo_er_activo.py
git commit -m "feat(db): repo_flujo + repo_er_activo"
```

---

## Task 11: `repo_fact.py` — precios, UF, dividendos

**Files:**
- Create: `tools/db/repo_fact.py`
- Create: `tests/db/test_repo_fact.py`

A diferencia de raw, los facts son upsert por clave natural (no hash), porque el mercado se actualiza puntualmente.

- [ ] **Step 1: Escribir tests**

```python
"""Tests de repo_fact."""
import pytest

from tools.db import repo_fact
from tools.db.errors import NotFoundError


def test_upsert_precio_cuota(tmp_db):
    repo_fact.upsert_precio(tmp_db, nemotecnico="CFITRIPT-E", fecha="2026-04-30", precio=1234.5, fuente="bolsa")
    row = repo_fact.get_precio(tmp_db, "CFITRIPT-E", "2026-04-30")
    assert row["precio"] == 1234.5


def test_upsert_precio_sobrescribe(tmp_db):
    repo_fact.upsert_precio(tmp_db, nemotecnico="CFITRIPT-E", fecha="2026-04-30", precio=1.0)
    repo_fact.upsert_precio(tmp_db, nemotecnico="CFITRIPT-E", fecha="2026-04-30", precio=2.0)
    row = repo_fact.get_precio(tmp_db, "CFITRIPT-E", "2026-04-30")
    assert row["precio"] == 2.0


def test_get_precio_not_found(tmp_db):
    with pytest.raises(NotFoundError):
        repo_fact.get_precio(tmp_db, "CFITRIPT-E", "1999-01-01")


def test_upsert_uf(tmp_db):
    repo_fact.upsert_uf(tmp_db, fecha="2026-04-30", valor_clp=37500.0)
    assert repo_fact.get_uf(tmp_db, "2026-04-30") == 37500.0


def test_get_uf_not_found(tmp_db):
    with pytest.raises(NotFoundError):
        repo_fact.get_uf(tmp_db, "1999-01-01")


def test_upsert_dividendo(tmp_db):
    repo_fact.upsert_dividendo(tmp_db, nemotecnico="CFITOERI1A", fecha_pago="2026-05-15", monto=42.5)
    rows = repo_fact.list_dividendos(tmp_db, "CFITOERI1A")
    assert len(rows) == 1
    assert rows[0]["monto"] == 42.5
```

- [ ] **Step 2: Correr tests, verificar que fallan**

Run: `pytest tests/db/test_repo_fact.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `tools/db/repo_fact.py`**

```python
"""Repo de hechos: precios de cuota, UF, dividendos."""
import sqlite3

from tools.db.errors import NotFoundError


def upsert_precio(
    conn: sqlite3.Connection,
    nemotecnico: str,
    fecha: str,
    precio: float,
    fuente: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO fact_precio_cuota (nemotecnico, fecha, precio, fuente)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(nemotecnico, fecha) DO UPDATE SET
             precio = excluded.precio,
             fuente = excluded.fuente,
             loaded_at = datetime('now')""",
        (nemotecnico, fecha, precio, fuente),
    )
    conn.commit()


def get_precio(conn: sqlite3.Connection, nemotecnico: str, fecha: str) -> sqlite3.Row:
    cur = conn.execute(
        "SELECT * FROM fact_precio_cuota WHERE nemotecnico=? AND fecha=?",
        (nemotecnico, fecha),
    )
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"Precio no encontrado: {nemotecnico} {fecha}")
    return row


def upsert_uf(conn: sqlite3.Connection, fecha: str, valor_clp: float) -> None:
    conn.execute(
        """INSERT INTO fact_uf (fecha, valor_clp)
           VALUES (?, ?)
           ON CONFLICT(fecha) DO UPDATE SET
             valor_clp = excluded.valor_clp,
             loaded_at = datetime('now')""",
        (fecha, valor_clp),
    )
    conn.commit()


def get_uf(conn: sqlite3.Connection, fecha: str) -> float:
    cur = conn.execute("SELECT valor_clp FROM fact_uf WHERE fecha=?", (fecha,))
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"UF no encontrada: {fecha}")
    return row["valor_clp"]


def upsert_dividendo(
    conn: sqlite3.Connection,
    nemotecnico: str,
    fecha_pago: str,
    monto: float,
) -> None:
    conn.execute(
        """INSERT INTO fact_dividendo (nemotecnico, fecha_pago, monto)
           VALUES (?, ?, ?)
           ON CONFLICT(nemotecnico, fecha_pago) DO UPDATE SET
             monto = excluded.monto,
             loaded_at = datetime('now')""",
        (nemotecnico, fecha_pago, monto),
    )
    conn.commit()


def list_dividendos(conn: sqlite3.Connection, nemotecnico: str) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM fact_dividendo WHERE nemotecnico=? ORDER BY fecha_pago",
        (nemotecnico,),
    )
    return cur.fetchall()
```

- [ ] **Step 4: Correr tests, verificar que pasan**

Run: `pytest tests/db/test_repo_fact.py -v`
Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db/repo_fact.py tests/db/test_repo_fact.py
git commit -m "feat(db): repo_fact — precios/UF/dividendos"
```

---

## Task 12: `repo_kpi.py` — derived_kpi (motor de dashboards)

**Files:**
- Create: `tools/db/repo_kpi.py`
- Create: `tests/db/test_repo_kpi.py`

Este repo es la base para los futuros dashboards. La tabla es larga (un KPI por fila); las queries pivotan.

- [ ] **Step 1: Escribir tests**

```python
"""Tests de repo_kpi."""
import pytest

from tools.db import repo_kpi
from tools.db.errors import NotFoundError


def test_upsert_kpi(tmp_db):
    repo_kpi.upsert(
        tmp_db,
        entidad_tipo="activo",
        entidad_key="PT",
        periodo="2026-04",
        kpi="NOI",
        valor=1_234_567.0,
        unidad="CLP",
        recipe="noi_v1",
    )
    val = repo_kpi.get(tmp_db, "activo", "PT", "2026-04", "NOI", "noi_v1")
    assert val == 1_234_567.0


def test_upsert_sobrescribe_misma_recipe(tmp_db):
    repo_kpi.upsert(tmp_db, "activo", "PT", "2026-04", "NOI", 1.0, "CLP", "noi_v1")
    repo_kpi.upsert(tmp_db, "activo", "PT", "2026-04", "NOI", 2.0, "CLP", "noi_v1")
    assert repo_kpi.get(tmp_db, "activo", "PT", "2026-04", "NOI", "noi_v1") == 2.0


def test_get_not_found(tmp_db):
    with pytest.raises(NotFoundError):
        repo_kpi.get(tmp_db, "activo", "PT", "2026-04", "NOI", "noi_v1")


def test_serie_temporal(tmp_db):
    for periodo, val in [("2026-01", 1.0), ("2026-02", 2.0), ("2026-03", 3.0)]:
        repo_kpi.upsert(tmp_db, "activo", "PT", periodo, "NOI", val, "CLP", "noi_v1")

    rows = repo_kpi.serie_temporal(tmp_db, "activo", "PT", "NOI")
    assert [(r["periodo"], r["valor"]) for r in rows] == [
        ("2026-01", 1.0),
        ("2026-02", 2.0),
        ("2026-03", 3.0),
    ]


def test_serie_temporal_filtra_rango(tmp_db):
    for periodo, val in [("2026-01", 1.0), ("2026-02", 2.0), ("2026-03", 3.0)]:
        repo_kpi.upsert(tmp_db, "activo", "PT", periodo, "NOI", val, "CLP", "noi_v1")
    rows = repo_kpi.serie_temporal(
        tmp_db, "activo", "PT", "NOI", desde="2026-02", hasta="2026-02"
    )
    assert [r["periodo"] for r in rows] == ["2026-02"]


def test_snapshot_periodo(tmp_db):
    repo_kpi.upsert(tmp_db, "activo", "PT", "2026-04", "NOI", 100.0, "CLP", "noi_v1")
    repo_kpi.upsert(tmp_db, "activo", "PT", "2026-04", "vacancia", 0.05, "%", "vac_v1")
    snap = repo_kpi.snapshot_periodo(tmp_db, "activo", "PT", "2026-04")
    kpis = {r["kpi"]: r["valor"] for r in snap}
    assert kpis == {"NOI": 100.0, "vacancia": 0.05}


def test_tipo_entidad_invalido(tmp_db):
    with pytest.raises(Exception):  # CHECK constraint
        repo_kpi.upsert(tmp_db, "BAD_TIPO", "X", "2026-04", "K", 1.0, "u", "r")
```

- [ ] **Step 2: Correr tests, verificar que fallan**

Run: `pytest tests/db/test_repo_kpi.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `tools/db/repo_kpi.py`**

```python
"""Repo de derived_kpi — KPIs calculados, en formato largo para dashboards."""
import sqlite3

from tools.db.errors import NotFoundError


def upsert(
    conn: sqlite3.Connection,
    entidad_tipo: str,
    entidad_key: str,
    periodo: str,
    kpi: str,
    valor: float,
    unidad: str | None,
    recipe: str,
    ingest_run_id: int | None = None,
) -> None:
    conn.execute(
        """INSERT INTO derived_kpi
             (entidad_tipo, entidad_key, periodo, kpi, valor, unidad, recipe, ingest_run_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(entidad_tipo, entidad_key, periodo, kpi, recipe) DO UPDATE SET
             valor = excluded.valor,
             unidad = excluded.unidad,
             ingest_run_id = excluded.ingest_run_id,
             computed_at = datetime('now')""",
        (entidad_tipo, entidad_key, periodo, kpi, valor, unidad, recipe, ingest_run_id),
    )
    conn.commit()


def get(
    conn: sqlite3.Connection,
    entidad_tipo: str,
    entidad_key: str,
    periodo: str,
    kpi: str,
    recipe: str,
) -> float:
    cur = conn.execute(
        """SELECT valor FROM derived_kpi
            WHERE entidad_tipo=? AND entidad_key=? AND periodo=? AND kpi=? AND recipe=?""",
        (entidad_tipo, entidad_key, periodo, kpi, recipe),
    )
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(
            f"KPI no encontrado: {entidad_tipo}/{entidad_key} {periodo} {kpi} ({recipe})"
        )
    return row["valor"]


def serie_temporal(
    conn: sqlite3.Connection,
    entidad_tipo: str,
    entidad_key: str,
    kpi: str,
    desde: str | None = None,
    hasta: str | None = None,
    recipe: str | None = None,
) -> list[sqlite3.Row]:
    """Devuelve [{periodo, valor, unidad, recipe}, …] ordenado por periodo."""
    sql = """SELECT periodo, valor, unidad, recipe
               FROM derived_kpi
              WHERE entidad_tipo=? AND entidad_key=? AND kpi=?"""
    params: list = [entidad_tipo, entidad_key, kpi]
    if desde is not None:
        sql += " AND periodo >= ?"
        params.append(desde)
    if hasta is not None:
        sql += " AND periodo <= ?"
        params.append(hasta)
    if recipe is not None:
        sql += " AND recipe = ?"
        params.append(recipe)
    sql += " ORDER BY periodo"
    cur = conn.execute(sql, params)
    return cur.fetchall()


def snapshot_periodo(
    conn: sqlite3.Connection,
    entidad_tipo: str,
    entidad_key: str,
    periodo: str,
) -> list[sqlite3.Row]:
    """Todos los KPIs de una entidad en un periodo dado."""
    cur = conn.execute(
        """SELECT kpi, valor, unidad, recipe
             FROM derived_kpi
            WHERE entidad_tipo=? AND entidad_key=? AND periodo=?
            ORDER BY kpi""",
        (entidad_tipo, entidad_key, periodo),
    )
    return cur.fetchall()
```

- [ ] **Step 4: Correr tests, verificar que pasan**

Run: `pytest tests/db/test_repo_kpi.py -v`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db/repo_kpi.py tests/db/test_repo_kpi.py
git commit -m "feat(db): repo_kpi — upsert/get/serie_temporal/snapshot"
```

---

## Task 13: Aplicar migraciones a la DB real del agente

**Files:**
- Modify: `tools/memory_tools.py` (importar y aplicar migraciones al cargar el módulo)
- Create: `memory/backups/.gitkeep`

Hasta aquí los tests corrieron sobre archivos `.db` temporales. Ahora aplicamos el schema al `memory/agente_toesca.db` real, dejando un backup previo.

- [ ] **Step 1: Crear directorio de backups**

```bash
mkdir -p memory/backups
type nul > memory/backups/.gitkeep
```

- [ ] **Step 2: Hacer backup manual de la DB actual**

```bash
copy memory\agente_toesca.db memory\backups\agente_toesca_pre_fase0.db
```

(O en PowerShell: `Copy-Item memory\agente_toesca.db memory\backups\agente_toesca_pre_fase0.db`.)

- [ ] **Step 3: Modificar `tools/memory_tools.py` para aplicar migraciones al cargar**

Después de la línea `DB_PATH = …` (línea 15), agregar:

```python
# Aplicar migraciones pendientes al cargar el módulo.
from tools.db.connection import apply_migrations as _apply_migrations
_apply_migrations(DB_PATH)
```

(Si en el futuro `_apply_migrations` se mueve a `tools.db.__init__`, ajustar el import. Por ahora vive en `connection.py`.)

- [ ] **Step 4: Verificar que las nuevas tablas están en la DB real**

```bash
python -c "import sqlite3; c=sqlite3.connect('memory/agente_toesca.db'); print(sorted(r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")))"
```

Expected: la lista incluye `dim_fondo`, `dim_activo`, `dim_serie`, `dim_cuenta`, `raw_*`, `fact_*`, `derived_kpi`, `ingest_run`, `publish_run`, `schema_version`, además de las preexistentes (`historial_chat`, `kpis`, `contexto`).

- [ ] **Step 5: Verificar que el flujo actual del agente no se rompe**

Run: `python -c "from tools.memory_tools import load_memory; print('OK' if isinstance(load_memory(), str) else 'FAIL')"`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add tools/memory_tools.py memory/backups/.gitkeep
git commit -m "feat(db): aplicar migraciones al cargar memory_tools + backup pre-fase0"
```

---

## Task 14: Suite completa verde + nota en wiki

**Files:**
- Modify: `wiki/log.md`
- Create o modify: `wiki/db.md`

- [ ] **Step 1: Correr toda la suite de tests**

Run: `pytest tests/db/ -v`
Expected: TODOS los tests PASS (≈ 35 tests).

- [ ] **Step 2: Agregar entrada al `wiki/log.md`**

Agregar al inicio del archivo (o en sección apropiada):

```markdown
## [2026-05-25] feature | DB Fase 0 — esqueleto

Se creó la base SQLite del agente:
- `tools/db/` con repos por dominio (fondo, rent_roll, eeff, flujo, er_activo, fact, kpi, audit)
- Schema versionado en `tools/db/migrations/` (5 migraciones + seeds de fondos/activos/series)
- Sistema de migraciones idempotente, aplicado automáticamente al cargar `memory_tools.py`
- 35 tests, todos verdes
- Backup pre-fase0 en `memory/backups/agente_toesca_pre_fase0.db`

Excels siguen siendo la verdad. DB está lista para Fase 1 (dual-write por dominio).
Ver `docs/superpowers/specs/2026-05-25-db-migration-design.md`.
```

- [ ] **Step 3: Crear `wiki/db.md` con el mapa rápido**

```markdown
# DB del agente

Archivo: `memory/agente_toesca.db` (SQLite).

## Schema

- **Dimensiones**: `dim_fondo`, `dim_activo`, `dim_serie`, `dim_cuenta`
- **Raw** (línea por línea del proveedor): `raw_rent_roll_line`, `raw_eeff_line`, `raw_flujo_line`, `raw_er_activo_line`
- **Facts**: `fact_precio_cuota`, `fact_uf`, `fact_dividendo`
- **Derived**: `derived_kpi` (formato largo, una fila por KPI)
- **Audit**: `ingest_run`, `publish_run`, `schema_version`

## Cómo acceder

Nunca con SQL crudo desde el resto del agente. Siempre vía repos en `tools/db/repo_*.py`.

```python
from tools.db.connection import get_conn
from tools.db import repo_kpi

with get_conn() as conn:
    series = repo_kpi.serie_temporal(conn, "activo", "PT", "NOI")
```

## Estado por fase

- Fase 0 (esqueleto): ✅ DONE (2026-05-25)
- Fase 1 (dual-write por dominio): pendiente
- Fase 2 (backfill histórico): pendiente
- Fase 3 (inversión del flujo): pendiente
- Fase 4 (query + dashboards): pendiente

Ver spec completo: `docs/superpowers/specs/2026-05-25-db-migration-design.md`.
```

- [ ] **Step 4: Commit y push del wiki**

```bash
git add wiki/log.md wiki/db.md
git commit -m "wiki: DB Fase 0 — esqueleto completado"
git push
```

---

## Self-Review

**Spec coverage check:**
- §2 Arquitectura macro → todas las tablas creadas en Tasks 2-4. Capa `tools/db/` montada (Tasks 5-12). Aplicación a la DB real (Task 13).
- §3 Modelo de datos → 4 capas migradas (dim → Task 2, raw → Task 3, fact → Task 3, derived → Task 3, audit → Task 3); seeds en Task 4.
- §4 Capa de tools → solo se construyeron repos (la capa que TODOS los `ingest_*/compute_*/publish_*/query_*` futuros van a usar). Esos roles superiores son materia de planes posteriores, fuera de Fase 0.
- §5 Fase 0 (Esqueleto) → cubierto íntegramente: schema, migraciones, repos, seeds, tests, sin tocar flujo actual. ✅
- §5 Fase 1+ → fuera de alcance de este plan; un plan por dominio se escribirá después.

**Placeholders:** Ninguno. Cada step tiene código completo o comando ejecutable concreto.

**Type consistency:** Verificado.
- `ingest_run_id` se acepta como int en todos los `insert_lines`. Coincide con `cur.lastrowid` (int) de `start_ingest_run`.
- `entidad_tipo` ∈ {'fondo','activo','serie'} reforzado por CHECK constraint (Task 3) y por la firma de `repo_kpi.upsert`.
- Claves de seeds (`A&R PT`, `PT`, `Viña Centro`, etc.) coinciden entre Task 4 (seeds) y Tasks 6-12 (tests que las usan).
- Nombres de funciones consistentes: `apply_migrations`, `get_conn_for`, `current_version`, `insert_lines`, `mark_superseded`, `list_by_periodo`, `upsert`, `get`, `serie_temporal`, `snapshot_periodo`, `start_ingest_run`, `finish_ingest_run`, `fail_ingest_run`, `start_publish_run`, `finish_publish_run`.
- `repo_fact` distingue: `get_precio` devuelve `Row`, `get_uf` devuelve `float`. Tests testean la diferencia explícitamente.

**Granularidad:** Cada step es una acción de 2-5 min (escribir test, correr, implementar, correr, commit).
