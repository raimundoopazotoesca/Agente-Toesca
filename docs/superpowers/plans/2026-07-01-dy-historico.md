# DY Histórico en derived_kpi — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persistir Dividend Yield (contable y bursátil) para todas las series de fondos Toesca, todos los meses desde inicio, con backfill histórico y recipe versionado.

**Architecture:** Migración 033 agrega columna `variante` a `derived_kpi` y reemplaza la UNIQUE constraint para separar contable/bursátil. Script `compute_kpis_series.py` computa DY en CLP (UF cancela) para cada serie × mes desde inicio, upserteando en `derived_kpi`. El skill `real-estate-finance-expert` se actualiza para reflejar que `dy_v1` está validado.

**Tech Stack:** Python 3.10+, SQLite (agente_toesca_v2.db), `tools.db.repo_kpi`, `tools.db.connection.apply_migrations`

## Global Constraints

- DB path: `memory/agente_toesca_v2.db`
- Migraciones SQL en: `tools/db/migrations/`; el runner (`connection.apply_migrations`) las aplica ordenadas por prefijo numérico
- Fórmula canónica DY: `sum(monto_clp_cuota where fecha_pago ∈ (t-12m, t]) / precio_clp(t)` — trabajar en CLP (UF cancela)
- Precio bursátil: `raw_valor_cuota_bursatil_line` (primario) → `raw_valor_cuota_contable_line tipo='bursatil'` (fallback)
- Precio contable: `raw_valor_cuota_contable_line tipo='contable'`, último disponible con `fecha <= t`
- Filtros dividendos: `tipo='dividendo'`, `superseded_at IS NULL`, `monto_clp_cuota IS NOT NULL`
- Recipe: `dy_v1` (no cambiar salvo que cambie la fórmula)
- Variante: `'contable'` | `'bursatil'` | `NULL` (KPIs sin distinción)
- Series:

| nemotecnico | fondo | inicio | bursatil |
|---|---|---|---|
| CFITOERI1A | TRI | 2018-03 | Sí |
| CFITOERI1C | TRI | 2018-03 | Sí |
| CFITOERI1I | TRI | 2018-03 | Sí |
| CFITRIPT-E | PT | 2018-03 | Sí |
| APO-UNICA | Apo | 2019-03 | No |

---

## File Map

| Acción | Archivo |
|---|---|
| CREATE | `tools/db/migrations/033_add_variante_derived_kpi.sql` |
| MODIFY | `tools/db/repo_kpi.py` — agregar `variante` a `upsert` y `get` |
| CREATE | `scripts/compute_kpis_series.py` — script principal backfill/incremental |
| MODIFY | `C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\references\persistence-recipes.md` |
| MODIFY | `C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\references\indicadores-retorno.md` |

---

## Task 1: Migración 033 + actualización repo_kpi

**Objetivo:** Agregar columna `variante` a `derived_kpi` y cambiar UNIQUE constraint de `(entity, period, kpi, recipe)` a `(entity, period, kpi, variante)`. Actualizar `repo_kpi.upsert` para incluir variante.

**Files:**
- Create: `tools/db/migrations/033_add_variante_derived_kpi.sql`
- Modify: `tools/db/repo_kpi.py`

**Interfaces:**
- Produces: `repo_kpi.upsert(conn, entidad_tipo, entidad_key, periodo, kpi, valor, unidad, recipe, ingest_run_id=None, variante=None)` — nueva firma
- Produces: `repo_kpi.get(conn, entidad_tipo, entidad_key, periodo, kpi, recipe=None, variante=None)` — nueva firma

---

- [ ] **Step 1: Crear migración SQL**

Crear `tools/db/migrations/033_add_variante_derived_kpi.sql`:

```sql
-- Migration 033: agregar variante a derived_kpi y cambiar UNIQUE constraint.
-- variante='contable'|'bursatil' para KPIs con doble precio; NULL para el resto.
-- Nuevo PK lógico: (entidad_tipo, entidad_key, periodo, kpi, variante).

ALTER TABLE derived_kpi ADD COLUMN variante TEXT DEFAULT NULL;

DROP INDEX IF EXISTS idx_kpi_entidad;
DROP INDEX IF EXISTS idx_kpi_periodo;
DROP INDEX IF EXISTS idx_kpi_kpi;

DROP TABLE IF EXISTS derived_kpi_new;

CREATE TABLE derived_kpi_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad_tipo    TEXT NOT NULL CHECK (entidad_tipo IN ('fondo','activo','serie')),
    entidad_key     TEXT NOT NULL,
    periodo         TEXT NOT NULL,
    kpi             TEXT NOT NULL,
    variante        TEXT DEFAULT NULL,
    valor           REAL,
    unidad          TEXT,
    recipe          TEXT NOT NULL,
    ingest_run_id   INTEGER,
    computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (entidad_tipo, entidad_key, periodo, kpi, variante)
);

INSERT OR REPLACE INTO derived_kpi_new
    (id, entidad_tipo, entidad_key, periodo, kpi, variante,
     valor, unidad, recipe, ingest_run_id, computed_at)
SELECT  id, entidad_tipo, entidad_key, periodo, kpi, variante,
        valor, unidad, recipe, ingest_run_id, computed_at
FROM derived_kpi;

DROP TABLE derived_kpi;
ALTER TABLE derived_kpi_new RENAME TO derived_kpi;

CREATE INDEX idx_kpi_entidad ON derived_kpi(entidad_tipo, entidad_key);
CREATE INDEX idx_kpi_periodo ON derived_kpi(periodo);
CREATE INDEX idx_kpi_kpi     ON derived_kpi(kpi);
```

- [ ] **Step 2: Aplicar la migración**

```bash
python - <<'EOF'
from tools.db.connection import apply_migrations, DEFAULT_DB_PATH
applied = apply_migrations(DEFAULT_DB_PATH)
print("Applied:", applied)
EOF
```

Salida esperada: `Applied: [33]`

- [ ] **Step 3: Verificar schema**

```bash
python - <<'EOF'
import sqlite3
conn = sqlite3.connect('memory/agente_toesca_v2.db')
cur = conn.execute("SELECT sql FROM sqlite_master WHERE name='derived_kpi'")
print(cur.fetchone()[0])
cur2 = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='derived_kpi'")
print([r[0] for r in cur2.fetchall()])
conn.close()
EOF
```

Salida esperada: schema con columna `variante` y UNIQUE en `(entidad_tipo, entidad_key, periodo, kpi, variante)`.

- [ ] **Step 4: Actualizar repo_kpi.py**

Reemplazar el contenido de `tools/db/repo_kpi.py`:

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
    variante: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO derived_kpi
             (entidad_tipo, entidad_key, periodo, kpi, variante, valor, unidad, recipe, ingest_run_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(entidad_tipo, entidad_key, periodo, kpi, variante) DO UPDATE SET
             valor         = excluded.valor,
             unidad        = excluded.unidad,
             recipe        = excluded.recipe,
             ingest_run_id = excluded.ingest_run_id,
             computed_at   = datetime('now')""",
        (entidad_tipo, entidad_key, periodo, kpi, variante, valor, unidad, recipe, ingest_run_id),
    )
    conn.commit()


def get(
    conn: sqlite3.Connection,
    entidad_tipo: str,
    entidad_key: str,
    periodo: str,
    kpi: str,
    recipe: str | None = None,
    variante: str | None = None,
) -> float:
    sql = """SELECT valor FROM derived_kpi
              WHERE entidad_tipo=? AND entidad_key=? AND periodo=? AND kpi=?
                AND variante IS ?"""
    params: list = [entidad_tipo, entidad_key, periodo, kpi, variante]
    if recipe is not None:
        sql += " AND recipe = ?"
        params.append(recipe)
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(
            f"KPI no encontrado: {entidad_tipo}/{entidad_key} {periodo} {kpi} variante={variante}"
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
    variante: str | None = None,
) -> list[sqlite3.Row]:
    sql = """SELECT periodo, valor, unidad, recipe, variante
               FROM derived_kpi
              WHERE entidad_tipo=? AND entidad_key=? AND kpi=?
                AND variante IS ?"""
    params: list = [entidad_tipo, entidad_key, kpi, variante]
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
    cur = conn.execute(
        """SELECT kpi, variante, valor, unidad, recipe
             FROM derived_kpi
            WHERE entidad_tipo=? AND entidad_key=? AND periodo=?
            ORDER BY kpi, variante""",
        (entidad_tipo, entidad_key, periodo),
    )
    return cur.fetchall()
```

- [ ] **Step 5: Verificar que el upsert viejo (sin variante) sigue funcionando**

```bash
python - <<'EOF'
import sqlite3
from tools.db.connection import get_conn
from tools.db import repo_kpi

conn = get_conn()
# Upsert sin variante (backward compat — variante=NULL)
repo_kpi.upsert(conn, 'serie', 'TEST-NEMO', '2026-01', 'test_kpi', 99.9, 'pct', 'test_v1')
val = repo_kpi.get(conn, 'serie', 'TEST-NEMO', '2026-01', 'test_kpi')
assert val == 99.9, f"Expected 99.9, got {val}"

# Upsert con variante (nuevo comportamiento)
repo_kpi.upsert(conn, 'serie', 'TEST-NEMO', '2026-01', 'dy', 4.13, 'pct', 'dy_v1', variante='bursatil')
repo_kpi.upsert(conn, 'serie', 'TEST-NEMO', '2026-01', 'dy', 2.15, 'pct', 'dy_v1', variante='contable')
v_burs = repo_kpi.get(conn, 'serie', 'TEST-NEMO', '2026-01', 'dy', variante='bursatil')
v_cont = repo_kpi.get(conn, 'serie', 'TEST-NEMO', '2026-01', 'dy', variante='contable')
assert v_burs == 4.13 and v_cont == 2.15, f"Got {v_burs}, {v_cont}"

# Limpiar
conn.execute("DELETE FROM derived_kpi WHERE entidad_key='TEST-NEMO'")
conn.commit()
conn.close()
print("OK — repo_kpi compatible con variante")
EOF
```

Salida esperada: `OK — repo_kpi compatible con variante`

- [ ] **Step 6: Commit**

```bash
git add tools/db/migrations/033_add_variante_derived_kpi.sql tools/db/repo_kpi.py
git commit -m "feat(db): migration 033 variante en derived_kpi + repo_kpi actualizado"
```

---

## Task 2: Script compute_kpis_series.py

**Objetivo:** Script que computa DY (contable + bursátil) para todas las series en cualquier rango de meses y persiste en `derived_kpi` con recipe `dy_v1`.

**Files:**
- Create: `scripts/compute_kpis_series.py`

**Interfaces:**
- Consumes: `repo_kpi.upsert(conn, ..., variante='contable'|'bursatil')` — Task 1
- Consumes: `tools.db.connection.get_conn()` — existente
- CLI: `python scripts/compute_kpis_series.py --kpi dy [--modo backfill|incremental] [--desde YYYY-MM] [--hasta YYYY-MM]`

---

- [ ] **Step 1: Crear scripts/compute_kpis_series.py**

```python
"""Compute and persist financial KPIs for all fund series.

Usage:
  python scripts/compute_kpis_series.py --kpi dy --modo backfill
  python scripts/compute_kpis_series.py --kpi dy
  python scripts/compute_kpis_series.py --kpi dy --desde 2024-01 --hasta 2026-03
"""
import argparse
import calendar
import sqlite3
import sys
from datetime import date
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.db.connection import get_conn
from tools.db import repo_kpi

RECIPE = "dy_v1"
UNIT = "ratio"  # 0.0413 = 4.13%

SERIES_CONFIG = {
    "CFITOERI1A": {"fondo": "TRI", "inicio": "2018-03", "bursatil": True},
    "CFITOERI1C": {"fondo": "TRI", "inicio": "2018-03", "bursatil": True},
    "CFITOERI1I": {"fondo": "TRI", "inicio": "2018-03", "bursatil": True},
    "CFITRIPT-E": {"fondo": "PT",  "inicio": "2018-03", "bursatil": True},
    "APO-UNICA":  {"fondo": "Apo", "inicio": "2019-03", "bursatil": False},
}


def _last_day(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _subtract_12m(t: date) -> date:
    """Mismo día, un año antes. Clamps al último día del mes si hace falta."""
    y = t.year - 1
    max_d = calendar.monthrange(y, t.month)[1]
    return date(y, t.month, min(t.day, max_d))


def _months_range(desde: str, hasta: str):
    """Yield (periodo 'YYYY-MM', last_day date) for each month in [desde, hasta]."""
    y, m = map(int, desde.split("-"))
    hy, hm = map(int, hasta.split("-"))
    while (y, m) <= (hy, hm):
        yield f"{y:04d}-{m:02d}", _last_day(y, m)
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _prev_month() -> str:
    """Último mes completo: ayer-ish."""
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def _get_divs_clp(conn: sqlite3.Connection, nemo: str, desde: date, hasta: date) -> float:
    """Suma monto_clp_cuota de dividendos en (desde, hasta]. 0.0 si no hay."""
    cur = conn.execute(
        """SELECT COALESCE(SUM(monto_clp_cuota), 0.0)
             FROM raw_dividendo_line
            WHERE superseded_at IS NULL
              AND tipo = 'dividendo'
              AND nemotecnico = ?
              AND fecha_pago > ? AND fecha_pago <= ?
              AND monto_clp_cuota IS NOT NULL""",
        (nemo, desde.isoformat(), hasta.isoformat()),
    )
    return cur.fetchone()[0]


def _get_precio_contable_clp(conn: sqlite3.Connection, nemo: str, t: date) -> float | None:
    """Último precio contable en CLP con fecha <= t."""
    cur = conn.execute(
        """SELECT precio_clp FROM raw_valor_cuota_contable_line
            WHERE nemotecnico = ? AND tipo = 'contable' AND fecha <= ?
            ORDER BY fecha DESC LIMIT 1""",
        (nemo, t.isoformat()),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def _get_precio_bursatil_clp(conn: sqlite3.Connection, nemo: str, t: date) -> float | None:
    """Precio bursátil en CLP con fecha <= t.
    Fuente primaria: raw_valor_cuota_bursatil_line (LarrainVial).
    Fallback: raw_valor_cuota_contable_line tipo='bursatil'.
    """
    cur = conn.execute(
        """SELECT precio_clp FROM raw_valor_cuota_bursatil_line
            WHERE nemotecnico = ? AND fecha <= ?
            ORDER BY fecha DESC LIMIT 1""",
        (nemo, t.isoformat()),
    )
    row = cur.fetchone()
    if row and row[0]:
        return row[0]
    # Fallback
    cur = conn.execute(
        """SELECT precio_clp FROM raw_valor_cuota_contable_line
            WHERE nemotecnico = ? AND tipo = 'bursatil' AND fecha <= ?
            ORDER BY fecha DESC LIMIT 1""",
        (nemo, t.isoformat()),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def _compute_dy(conn: sqlite3.Connection, nemo: str, t: date, variante: str) -> float | None:
    """DY = sum_divs_clp(t-12m, t] / precio_clp(t). None si falta precio."""
    t_12m = _subtract_12m(t)
    divs = _get_divs_clp(conn, nemo, t_12m, t)
    if variante == "contable":
        precio = _get_precio_contable_clp(conn, nemo, t)
    else:
        precio = _get_precio_bursatil_clp(conn, nemo, t)
    if precio is None or precio == 0:
        return None
    return divs / precio


def run_dy(conn: sqlite3.Connection, desde: str, hasta: str) -> None:
    total = 0
    skipped = 0
    for nemo, cfg in SERIES_CONFIG.items():
        inicio = cfg["inicio"]
        # No calcular antes del inicio del fondo
        desde_efectivo = max(desde, inicio)
        if desde_efectivo > hasta:
            continue
        for periodo, t in _months_range(desde_efectivo, hasta):
            for variante in (["contable", "bursatil"] if cfg["bursatil"] else ["contable"]):
                dy = _compute_dy(conn, nemo, t, variante)
                if dy is None:
                    skipped += 1
                    continue
                repo_kpi.upsert(
                    conn,
                    entidad_tipo="serie",
                    entidad_key=nemo,
                    periodo=periodo,
                    kpi="dy",
                    valor=dy,
                    unidad=UNIT,
                    recipe=RECIPE,
                    variante=variante,
                )
                total += 1
    print(f"Persistidos: {total} | Sin precio (skip): {skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute KPIs for fund series.")
    parser.add_argument("--kpi", required=True, choices=["dy"], help="KPI a calcular")
    parser.add_argument("--modo", choices=["backfill", "incremental"], default="incremental")
    parser.add_argument("--desde", help="Mes inicio YYYY-MM (override)")
    parser.add_argument("--hasta", help="Mes fin YYYY-MM (override, default=último mes completo)")
    args = parser.parse_args()

    hasta = args.hasta or _prev_month()

    if args.desde:
        desde = args.desde
    elif args.modo == "backfill":
        desde = "2017-01"  # anterior al inicio más antiguo → se filtra por serie
    else:
        desde = hasta  # incremental: solo mes actual

    print(f"KPI={args.kpi}  modo={args.modo}  desde={desde}  hasta={hasta}")
    conn = get_conn()
    try:
        if args.kpi == "dy":
            run_dy(conn, desde, hasta)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test — un solo mes conocido**

```bash
python scripts/compute_kpis_series.py --kpi dy --desde 2026-03 --hasta 2026-03
```

Salida esperada:
```
KPI=dy  modo=incremental  desde=2026-03  hasta=2026-03
Persistidos: 9 | Sin precio (skip): ...
```
(9 = 4 series × 2 variantes + 1 APO-UNICA × 1 contable = 9)

- [ ] **Step 3: Verificar valores contra referencia**

```bash
python - <<'EOF'
import sqlite3
conn = sqlite3.connect('memory/agente_toesca_v2.db')
conn.row_factory = sqlite3.Row
cur = conn.execute(
    """SELECT entidad_key, variante, ROUND(valor*100, 2) as dy_pct
         FROM derived_kpi
        WHERE kpi='dy' AND periodo='2026-03'
        ORDER BY entidad_key, variante"""
)
for r in cur.fetchall():
    print(f"  {r['entidad_key']:15s} {r['variante']:9s} {r['dy_pct']:.2f}%")
conn.close()
EOF
```

Salida esperada (validada contra CDG MAR-2026):
```
  APO-UNICA       contable  0.00%
  CFITRIPT-E      bursatil  11.94%
  CFITRIPT-E      contable  10.19%
  CFITOERI1A      bursatil  4.13%
  CFITOERI1A      contable  2.15%
  CFITOERI1C      bursatil  4.64%
  CFITOERI1C      contable  2.38%
  CFITOERI1I      bursatil  2.75%
  CFITOERI1I      contable  2.47%
```

> Si algún valor difiere en más de 0.05%, revisar la fuente de precio (`raw_valor_cuota_contable_line` vs `raw_valor_cuota_bursatil_line`) y el rango de dividendos.

- [ ] **Step 4: Backfill histórico completo**

```bash
python scripts/compute_kpis_series.py --kpi dy --modo backfill
```

Debe terminar sin error. El conteo de `Persistidos` esperado es ~ 500–800 filas (depende de cobertura de precios históricos).

- [ ] **Step 5: Verificar cobertura histórica**

```bash
python - <<'EOF'
import sqlite3
conn = sqlite3.connect('memory/agente_toesca_v2.db')
conn.row_factory = sqlite3.Row
cur = conn.execute(
    """SELECT entidad_key, variante, MIN(periodo) as desde, MAX(periodo) as hasta, COUNT(*) as n
         FROM derived_kpi
        WHERE kpi='dy' AND recipe='dy_v1'
        GROUP BY entidad_key, variante
        ORDER BY entidad_key, variante"""
)
for r in cur.fetchall():
    print(f"  {r['entidad_key']:15s} {r['variante']:9s}  {r['desde']} → {r['hasta']}  ({r['n']} meses)")
conn.close()
EOF
```

Verificar que TRI cubre desde 2018-03 o antes (según datos disponibles) y Apo desde 2019-03.

- [ ] **Step 6: Commit**

```bash
git add scripts/compute_kpis_series.py
git commit -m "feat: compute_kpis_series.py — backfill DY contable/bursatil todas las series"
```

---

## Task 3: Actualizar skill real-estate-finance-expert

**Objetivo:** Registrar `dy` con recipe `dy_v1` como validado en el skill, y documentar la regla de fuente bursátil.

**Files:**
- Modify: `C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\references\persistence-recipes.md`
- Modify: `C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\references\indicadores-retorno.md`

---

- [ ] **Step 1: Agregar `dy` a la tabla master en persistence-recipes.md**

En la tabla "Tabla Master", agregar fila para `dy` (después de `dividend_yield`):

```markdown
| `dy` | DY contable+bursátil histórico (recipe dy_v1) | `dy_v1` | **Sí** — backfill completo | <100ms | Mensual |
```

Y agregar nota al final de la sección "Invalidación de Cache":

```markdown
### KPIs validados en derived_kpi

- `dy` con recipe `dy_v1` está **validado** contra CDG MAR-2026 para TRI A/C/I, PT y Apo.
  - Leer siempre de `derived_kpi` primero (query: `WHERE kpi='dy' AND variante=? AND recipe='dy_v1'`)
  - Columna `variante`: `'contable'` (precio libro) | `'bursatil'` (precio mercado)
  - Si no está en cache → ejecutar `python scripts/compute_kpis_series.py --kpi dy`
```

- [ ] **Step 2: Agregar regla de fuente bursátil en indicadores-retorno.md**

Al final de la sección "Dividend Yield", agregar:

```markdown
### Regla de Fuente Bursátil (permanente)

Los precios bursátiles siempre vienen de `raw_valor_cuota_bursatil_line` (LarrainVial).
Los valores en `raw_valor_cuota_contable_line tipo='bursatil'` son fallback solo para períodos
sin cobertura de LarrainVial (pre-2024-05 para TRI, pre-2017-11 para PT).

Esta regla aplica a DY, CAGR, U12M, YTD y cualquier indicador que use precio bursátil.

**Implementación**: `scripts/compute_kpis_series.py` — `_get_precio_bursatil_clp()`
```

- [ ] **Step 3: Verificar que los archivos quedaron bien**

Leer ambos archivos modificados y confirmar que las secciones nuevas están presentes y con formato correcto.

- [ ] **Step 4: Commit**

```bash
git add "C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\references\persistence-recipes.md"
git add "C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\references\indicadores-retorno.md"
git commit -m "docs(skill): registrar dy_v1 validado y regla fuente bursatil"
```

---

## Self-Review

### Spec coverage

| Req spec | Cubierto en |
|---|---|
| Migración 033 — columna `variante` | Task 1 Step 1 |
| UNIQUE efectivo: (entity, period, kpi, variante) | Task 1 Step 1 (tabla nueva) |
| Script `compute_kpis_series.py` con modo backfill/incremental/rango | Task 2 Step 1 |
| Jerarquía precio bursátil: LarrainVial → fallback | Task 2 Step 1 `_get_precio_bursatil_clp` |
| Precio contable: último disponible <= t | Task 2 Step 1 `_get_precio_contable_clp` |
| Upsert con recipe `dy_v1` | Task 2 Step 1 `run_dy` |
| APO-UNICA: solo contable, desde 2019-03 | Task 2 Step 1 `SERIES_CONFIG` |
| Actualización skill persistence-recipes | Task 3 Step 1 |
| Actualización skill indicadores-retorno | Task 3 Step 2 |
| Regla fuente bursátil documentada | Task 3 Step 2 |

### Placeholders

Ninguno — todos los steps tienen código completo o comandos ejecutables.

### Type consistency

- `repo_kpi.upsert(..., variante=None)` definido en Task 1 Step 4, consumido en Task 2 Step 1 con `variante='contable'|'bursatil'`.
- `_compute_dy` retorna `float | None`; `run_dy` guarda solo cuando `dy is not None`.
- `_months_range` yield `(str, date)` consumido en `run_dy` como `(periodo, t)`.
