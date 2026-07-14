# TRI Consolidación — Arquitectura DB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migración aditiva 049 que agrega jerarquía sociedad + fondo padre a la DB, preservando las 3 capas de participación del organigrama TRI y sin romper consumidores existentes.

**Architecture:** Aditivo puro — nueva tabla `dim_sociedad`, nuevas columnas nullable en `dim_activo` y `dim_fondo`, nueva vista `v_activo_fondo_efectivo`. Valores existentes intactos. Consumidores viejos (`noi_query.py`) siguen leyendo columna vieja sin cambios. Consumidores nuevos usan la vista.

**Tech Stack:** SQLite, Python 3.11+, pytest. Migration runner: `tools/db/connection.py:apply_migrations()` que descubre `.sql` en `tools/db/migrations/`, cada uno auto-envuelto en transacción.

## Global Constraints

- DB path: `memory/agente_toesca_v2.db`.
- Migración estrictamente **aditiva**: no `DROP`, no `RENAME`, no `UPDATE` de valores existentes en columnas viejas.
- Formato `loaded_at`: `'YYYY-MM-DD HH:MM:SS'` (sin `T`) — no aplica en esta migración pero regla global del repo.
- Idempotencia: la columna `participacion_fondo_activo` (vieja, semántica mezclada) **no se toca** — permanece con sus valores actuales.
- Reference spec: `docs/superpowers/specs/2026-07-14-tri-consolidacion-arquitectura-design.md`.

---

## File Structure

- Create: `tools/db/migrations/049_dim_sociedad_y_fondo_padre.sql` — DDL + seed de participaciones.
- Create: `tests/db/test_migration_049.py` — test que valida estado post-migración (13 filas en vista, participaciones esperadas, campos poblados).
- Create: `scripts/snapshot_pre_049.py` — captura serie NOI ponderada de PT y Apo pre-migración para diff post.
- Create: `scripts/verify_post_049.py` — corre el snapshot post-migración y compara vs baseline.
- Modify: `wiki/db.md` — documentar `dim_sociedad`, `v_activo_fondo_efectivo`, jerarquía subfondos.
- Modify: `wiki/log.md` — entrada de la migración.

---

## Task 1: Baseline snapshot pre-migración

**Files:**
- Create: `scripts/snapshot_pre_049.py`
- Create: `memory/backups/agente_toesca_v2.pre-049.db` (copia)
- Create: `scratchpad/noi_snapshot_pre_049.json` (baseline)

**Interfaces:**
- Produces: JSON snapshot con serie NOI mensual ponderada de fondos PT y Apo (todas las periodos con datos) — leído por Task 3 para verificar no-regresión de `noi_query.serie_mensual(ponderado=True)`.

- [ ] **Step 1: Backup de la DB**

```bash
mkdir -p memory/backups
cp memory/agente_toesca_v2.db memory/backups/agente_toesca_v2.pre-049.db
ls -la memory/backups/agente_toesca_v2.pre-049.db
```

Expected: archivo copiado, mismo tamaño que el original.

- [ ] **Step 2: Crear script de snapshot**

```python
# scripts/snapshot_pre_049.py
"""Captura serie NOI ponderada de PT y Apo antes de migración 049.
Se usa como baseline anti-regresión: post-049, el mismo script debe
devolver los mismos números (la columna vieja participacion_fondo_activo
no se toca, entonces noi_query sigue leyendo los mismos valores).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.db.connection import get_conn_for
from tools import noi_query


def capture(db_path: str) -> dict:
    conn = get_conn_for(db_path)
    out = {}
    for fondo in ("PT", "Apo"):
        serie = noi_query.serie_mensual(conn, nivel="fondo", clave=fondo, ponderado=True)
        out[fondo] = {p: round(v, 6) for p, v in serie.items()}
    return out


if __name__ == "__main__":
    db = "memory/agente_toesca_v2.db"
    out_path = "scratchpad/noi_snapshot_pre_049.json"
    Path("scratchpad").mkdir(exist_ok=True)
    snap = capture(db)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2, sort_keys=True)
    print(f"OK: {out_path} — PT={len(snap['PT'])} periodos, Apo={len(snap['Apo'])} periodos")
```

- [ ] **Step 3: Ejecutar snapshot pre-migración**

Run: `python scripts/snapshot_pre_049.py`
Expected: `OK: scratchpad/noi_snapshot_pre_049.json — PT=N periodos, Apo=M periodos` (N y M > 0).

- [ ] **Step 4: Verificar snapshot no vacío**

```bash
python -c "import json; d=json.load(open('scratchpad/noi_snapshot_pre_049.json')); print('PT sample:', list(d['PT'].items())[:2]); print('Apo sample:', list(d['Apo'].items())[:2])"
```

Expected: dos muestras de cada fondo con valores numéricos no-cero.

- [ ] **Step 5: Commit**

```bash
git add scripts/snapshot_pre_049.py memory/backups/agente_toesca_v2.pre-049.db
git commit -m "chore(db): snapshot NOI ponderado PT/Apo pre-migracion 049"
```

---

## Task 2: Migración 049 — SQL + test

**Files:**
- Create: `tools/db/migrations/049_dim_sociedad_y_fondo_padre.sql`
- Create: `tests/db/test_migration_049.py`

**Interfaces:**
- Consumes: schema actual (`dim_activo`, `dim_fondo`, `dim_sociedad` no existe todavía).
- Produces: nueva tabla `dim_sociedad(sociedad_key, nombre, fondo_key, participacion_fondo_en_sociedad)`, nuevas columnas `dim_activo.sociedad_key`, `dim_activo.participacion_en_sociedad`, `dim_fondo.fondo_padre`, `dim_fondo.participacion_en_padre`, vista `v_activo_fondo_efectivo(activo_key, fondo_key, participacion_efectiva, via)`.

- [ ] **Step 1: Escribir test que valida estado post-migración (falla ahora)**

```python
# tests/db/test_migration_049.py
"""Validación post-migración 049: schema, seeds y vista de look-through."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.db.connection import apply_migrations

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "tools" / "db" / "migrations"


@pytest.fixture
def db(tmp_path):
    """DB temporal con todas las migraciones aplicadas."""
    path = tmp_path / "test.db"
    apply_migrations(str(path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_dim_sociedad_existe_y_tiene_7_filas(db):
    rows = db.execute(
        "SELECT sociedad_key, fondo_key, participacion_fondo_en_sociedad "
        "FROM dim_sociedad ORDER BY sociedad_key"
    ).fetchall()
    assert len(rows) == 7
    keys = {r["sociedad_key"] for r in rows}
    assert keys == {
        "ApoquindoSpA", "BlvdSpA", "Chanarcillo", "CuricoSpA",
        "SeniorAssist", "TorreASA", "VCSpA",
    }


def test_dim_sociedad_participaciones(db):
    got = {
        r["sociedad_key"]: (r["fondo_key"], r["participacion_fondo_en_sociedad"])
        for r in db.execute("SELECT * FROM dim_sociedad")
    }
    assert got["Chanarcillo"] == ("TRI", 1.0)
    assert got["CuricoSpA"] == ("TRI", 0.80)
    assert got["SeniorAssist"] == ("TRI", 0.43)
    assert got["VCSpA"] == ("TRI", 1.0)
    assert got["TorreASA"] == ("PT", 1.0)
    assert got["BlvdSpA"] == ("PT", 1.0)
    assert got["ApoquindoSpA"] == ("Apo", 1.0)


def test_dim_activo_sociedad_key_poblado(db):
    esperado = {
        "Sucden": ("Chanarcillo", 1.0),
        "Apo3001": ("Chanarcillo", 0.685),
        "Viña Centro": ("VCSpA", 1.0),
        "Mall Curicó": ("CuricoSpA", 1.0),
        "INMOSA": ("SeniorAssist", 1.0),
        "Torre A": ("TorreASA", 1.0),
        "Boulevard": ("BlvdSpA", 1.0),
        "Apo4501": ("ApoquindoSpA", 1.0),
        "Apo4700": ("ApoquindoSpA", 1.0),
    }
    rows = db.execute(
        "SELECT activo_key, sociedad_key, participacion_en_sociedad "
        "FROM dim_activo WHERE sociedad_key IS NOT NULL"
    ).fetchall()
    got = {r["activo_key"]: (r["sociedad_key"], r["participacion_en_sociedad"]) for r in rows}
    for act, expected in esperado.items():
        assert act in got, f"activo {act} no tiene sociedad_key poblado"
        s_got, p_got = got[act]
        assert s_got == expected[0], f"{act}: sociedad_key {s_got} != {expected[0]}"
        assert abs(p_got - expected[1]) < 1e-9, f"{act}: part {p_got} != {expected[1]}"


def test_dim_fondo_padre_poblado(db):
    rows = {r["fondo_key"]: (r["fondo_padre"], r["participacion_en_padre"])
            for r in db.execute("SELECT * FROM dim_fondo")}
    assert rows["PT"] == ("TRI", 0.333)
    assert rows["Apo"] == ("TRI", 0.30)
    assert rows["TRI"] == (None, None)


def test_vista_lookthrough_13_filas(db):
    n = db.execute("SELECT COUNT(*) FROM v_activo_fondo_efectivo").fetchone()[0]
    assert n == 13, f"esperaba 13 filas, hay {n}"


def test_vista_lookthrough_directas(db):
    rows = db.execute(
        "SELECT activo_key, participacion_efectiva FROM v_activo_fondo_efectivo "
        "WHERE fondo_key='TRI' AND via='directa' ORDER BY activo_key"
    ).fetchall()
    got = {r["activo_key"]: round(r["participacion_efectiva"], 6) for r in rows}
    assert got == {
        "Apo3001": 0.685,
        "INMOSA": 0.43,
        "Mall Curicó": 0.80,
        "Sucden": 1.0,
        "Viña Centro": 1.0,
    }


def test_vista_lookthrough_via_padre(db):
    rows = db.execute(
        "SELECT activo_key, participacion_efectiva FROM v_activo_fondo_efectivo "
        "WHERE fondo_key='TRI' AND via='lookthrough' ORDER BY activo_key"
    ).fetchall()
    got = {r["activo_key"]: round(r["participacion_efectiva"], 6) for r in rows}
    assert got == {
        "Apo4501": 0.30,
        "Apo4700": 0.30,
        "Boulevard": 0.333,
        "Torre A": 0.333,
    }


def test_vieja_participacion_fondo_activo_intacta(db):
    """La columna vieja no se toca. Valores conocidos permanecen."""
    got = {r["activo_key"]: r["participacion_fondo_activo"]
           for r in db.execute("SELECT activo_key, participacion_fondo_activo FROM dim_activo")}
    assert got.get("Apo4501") == 1.0
    assert got.get("Apo4700") == 1.0
    assert got.get("Torre A") == 0.333
    assert got.get("Boulevard") == 0.333
    assert got.get("INMOSA") == 0.43
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/db/test_migration_049.py -v`
Expected: FAIL con `sqlite3.OperationalError: no such table: dim_sociedad` (o similar). Los 8 tests deben fallar.

- [ ] **Step 3: Escribir la migración**

```sql
-- tools/db/migrations/049_dim_sociedad_y_fondo_padre.sql
-- Agrega jerarquía sociedad + fondo padre para consolidación TRI.
-- Aditivo puro: no toca columnas ni valores existentes.

-- ── 1. Sociedades / holdings intermedias ─────────────────────────────────────
CREATE TABLE dim_sociedad (
  sociedad_key TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  fondo_key TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
  participacion_fondo_en_sociedad REAL NOT NULL
);

INSERT INTO dim_sociedad (sociedad_key, nombre, fondo_key, participacion_fondo_en_sociedad) VALUES
  ('Chanarcillo',   'Inmobiliaria Chañarcillo Ltda',                             'TRI', 1.0),
  ('CuricoSpA',     'Power Center Curicó SpA',                                   'TRI', 0.80),
  ('SeniorAssist',  'Inmobiliaria e Inversiones Senior Assist Chile S.A.',       'TRI', 0.43),
  ('VCSpA',         'Inmobiliaria VC SpA / Viña Centro SpA (colapsada)',         'TRI', 1.0),
  ('TorreASA',      'Torre A S.A.',                                              'PT',  1.0),
  ('BlvdSpA',       'Inmobiliaria Boulevard PT SpA',                             'PT',  1.0),
  ('ApoquindoSpA',  'Inmobiliaria Apoquindo SpA',                                'Apo', 1.0);

-- ── 2. Activo ↔ sociedad ─────────────────────────────────────────────────────
ALTER TABLE dim_activo ADD COLUMN sociedad_key TEXT REFERENCES dim_sociedad(sociedad_key);
ALTER TABLE dim_activo ADD COLUMN participacion_en_sociedad REAL;

UPDATE dim_activo SET sociedad_key='Chanarcillo',   participacion_en_sociedad=1.0    WHERE activo_key='Sucden';
UPDATE dim_activo SET sociedad_key='Chanarcillo',   participacion_en_sociedad=0.685  WHERE activo_key='Apo3001';
UPDATE dim_activo SET sociedad_key='VCSpA',         participacion_en_sociedad=1.0    WHERE activo_key='Viña Centro';
UPDATE dim_activo SET sociedad_key='CuricoSpA',     participacion_en_sociedad=1.0    WHERE activo_key='Mall Curicó';
UPDATE dim_activo SET sociedad_key='SeniorAssist',  participacion_en_sociedad=1.0    WHERE activo_key='INMOSA';
UPDATE dim_activo SET sociedad_key='TorreASA',      participacion_en_sociedad=1.0    WHERE activo_key='Torre A';
UPDATE dim_activo SET sociedad_key='BlvdSpA',       participacion_en_sociedad=1.0    WHERE activo_key='Boulevard';
UPDATE dim_activo SET sociedad_key='ApoquindoSpA',  participacion_en_sociedad=1.0    WHERE activo_key='Apo4501';
UPDATE dim_activo SET sociedad_key='ApoquindoSpA',  participacion_en_sociedad=1.0    WHERE activo_key='Apo4700';

-- ── 3. Subfondos ─────────────────────────────────────────────────────────────
ALTER TABLE dim_fondo ADD COLUMN fondo_padre TEXT REFERENCES dim_fondo(fondo_key);
ALTER TABLE dim_fondo ADD COLUMN participacion_en_padre REAL;

UPDATE dim_fondo SET fondo_padre='TRI', participacion_en_padre=0.333 WHERE fondo_key='PT';
UPDATE dim_fondo SET fondo_padre='TRI', participacion_en_padre=0.30  WHERE fondo_key='Apo';

-- ── 4. Vista look-through ────────────────────────────────────────────────────
CREATE VIEW v_activo_fondo_efectivo AS
  SELECT
    a.activo_key,
    s.fondo_key AS fondo_key,
    a.participacion_en_sociedad * s.participacion_fondo_en_sociedad AS participacion_efectiva,
    'directa' AS via
  FROM dim_activo a
  JOIN dim_sociedad s ON a.sociedad_key = s.sociedad_key
  WHERE a.sociedad_key IS NOT NULL
  UNION ALL
  SELECT
    a.activo_key,
    f.fondo_padre AS fondo_key,
    a.participacion_en_sociedad * s.participacion_fondo_en_sociedad * f.participacion_en_padre AS participacion_efectiva,
    'lookthrough' AS via
  FROM dim_activo a
  JOIN dim_sociedad s ON a.sociedad_key = s.sociedad_key
  JOIN dim_fondo   f ON s.fondo_key    = f.fondo_key
  WHERE a.sociedad_key IS NOT NULL
    AND f.fondo_padre IS NOT NULL;
```

- [ ] **Step 4: Correr los tests para verificar que pasan (en DB temporal)**

Run: `pytest tests/db/test_migration_049.py -v`
Expected: **8 passed**.

- [ ] **Step 5: Correr toda la suite de db para no-regresión**

Run: `pytest tests/db/ -v`
Expected: todos los tests existentes siguen pasando + los 8 nuevos = **N passed** sin fallos.

- [ ] **Step 6: Commit**

```bash
git add tools/db/migrations/049_dim_sociedad_y_fondo_padre.sql tests/db/test_migration_049.py
git commit -m "feat(db): migracion 049 dim_sociedad + fondo padre + vista look-through"
```

---

## Task 3: Aplicar migración a DB de producción + verificar no-regresión

**Files:**
- Create: `scripts/verify_post_049.py`
- Modify: `memory/agente_toesca_v2.db` (aplicación de la migración)

**Interfaces:**
- Consumes: baseline `scratchpad/noi_snapshot_pre_049.json` de Task 1.
- Produces: DB de producción actualizada con schema 049, snapshot post confirmado igual al baseline.

- [ ] **Step 1: Aplicar la migración a la DB real**

```bash
python -c "from tools.db.connection import apply_migrations; print(apply_migrations('memory/agente_toesca_v2.db'))"
```

Expected: imprime `[049]` (o lista que incluye 049). Si imprime `[]`, alguna migración anterior ya está aplicada — verificar `SELECT * FROM schema_version` — pero 049 debe aparecer una vez.

- [ ] **Step 2: Sanity queries manuales**

```bash
python -c "
import sqlite3
c = sqlite3.connect('memory/agente_toesca_v2.db')
c.row_factory = sqlite3.Row
print('=== dim_sociedad ==='); [print(dict(r)) for r in c.execute('SELECT * FROM dim_sociedad ORDER BY sociedad_key')]
print('=== TRI look-through ==='); [print(dict(r)) for r in c.execute(\"SELECT * FROM v_activo_fondo_efectivo WHERE fondo_key='TRI' ORDER BY via, activo_key\")]
print('=== count vista ==='); print(c.execute('SELECT COUNT(*) FROM v_activo_fondo_efectivo').fetchone()[0])
"
```

Expected:
- 7 filas en `dim_sociedad`.
- 9 filas TRI en la vista (5 directas de sociedades TRI + 4 lookthrough vía PT/Apo).
- Total = 13 filas en la vista.

- [ ] **Step 3: Crear script de verificación post**

```python
# scripts/verify_post_049.py
"""Compara snapshot post-migración con baseline pre-049 (Task 1).
Debe ser idéntico: participacion_fondo_activo no se tocó, entonces
noi_query devuelve los mismos números.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.snapshot_pre_049 import capture


def main():
    baseline = json.load(open("scratchpad/noi_snapshot_pre_049.json"))
    now = capture("memory/agente_toesca_v2.db")

    ok = True
    for fondo in ("PT", "Apo"):
        b, n = baseline[fondo], now[fondo]
        if set(b.keys()) != set(n.keys()):
            print(f"FAIL {fondo}: distintos periodos. Baseline={len(b)}, ahora={len(n)}")
            ok = False
            continue
        for periodo, v_base in b.items():
            v_now = round(n[periodo], 6)
            if abs(v_base - v_now) > 1e-6:
                print(f"FAIL {fondo} {periodo}: baseline={v_base} vs ahora={v_now}")
                ok = False
    if ok:
        print("OK: noi_query.serie_mensual(ponderado=True) idéntico pre vs post 049")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Ejecutar verificación**

Run: `python scripts/verify_post_049.py`
Expected: `OK: noi_query.serie_mensual(ponderado=True) idéntico pre vs post 049`, exit 0.

- [ ] **Step 5: Correr suite completa de tests para no-regresión final**

Run: `pytest tests/ -v --tb=short`
Expected: todos los tests pasan (los que pasaban antes + los 8 nuevos de 049). Ningún fallo en `test_seeds.py`, `test_ingest_er_apoquindo.py`, `test_migrations.py`, etc.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify_post_049.py
git commit -m "chore(db): verifica no-regresion NOI PT/Apo post migracion 049"
```

---

## Task 4: Actualizar wiki + memoria

**Files:**
- Modify: `wiki/db.md` — agregar sección `dim_sociedad`, columnas nuevas de `dim_activo`/`dim_fondo`, vista `v_activo_fondo_efectivo`.
- Modify: `wiki/log.md` — nueva entrada `[2026-07-14] db | migracion 049 ...`.
- Modify: `CLAUDE.md` — sección "Base de datos": mencionar `dim_sociedad` y vista canónica.
- Create: memoria `project_tri_consolidacion_arquitectura.md` en `C:\Users\raimundo.opazo\.claude\projects\c--Users-raimundo-opazo-automation-agent\memory\` + entrada en `MEMORY.md`.

**Interfaces:**
- Consumes: nada.
- Produces: documentación consultable en sesiones futuras.

- [ ] **Step 1: Actualizar wiki/db.md**

Agregar sección al final de la explicación de dimensiones:

```markdown
## Jerarquía de participaciones (post migración 049)

Las participaciones del organigrama TRI viven en 3 lugares:

- **`dim_sociedad(sociedad_key, nombre, fondo_key, participacion_fondo_en_sociedad)`** — holding/vehicle intermedia. Ej: Chañarcillo→TRI (100%), Curicó SpA→TRI (80%), Senior Assist→TRI (43%).
- **`dim_activo.sociedad_key`, `dim_activo.participacion_en_sociedad`** — participación del activo dentro de su sociedad. Ej: Apo3001 dentro de Chañarcillo = 68.5%.
- **`dim_fondo.fondo_padre`, `dim_fondo.participacion_en_padre`** — un subfondo dentro de un fondo padre. Ej: PT→TRI 33.3%, Apo→TRI 30%.

Vista canónica de look-through: **`v_activo_fondo_efectivo(activo_key, fondo_key, participacion_efectiva, via)`**. `via='directa'` = activo→fondo dueño de su sociedad. `via='lookthrough'` = activo→fondo abuelo vía fondo padre. Usar esta vista para toda consolidación por fondo.

⚠️ La columna vieja `dim_activo.participacion_fondo_activo` está **deprecada** (semántica mezclada) pero se conserva porque `tools/noi_query.py` aún la lee. Migrar a la vista en Fase 3.
```

- [ ] **Step 2: Actualizar wiki/log.md**

Agregar al final:

```markdown
## [2026-07-14] db | Migración 049: dim_sociedad + fondo padre + vista look-through

Aditivo puro para consolidación TRI. Nueva tabla `dim_sociedad` con 7 holdings; nuevas columnas `dim_activo.sociedad_key`/`participacion_en_sociedad`, `dim_fondo.fondo_padre`/`participacion_en_padre`; vista `v_activo_fondo_efectivo`. La columna vieja `dim_activo.participacion_fondo_activo` queda deprecada pero intacta — `noi_query.py` sigue funcionando sin cambios (verificado con snapshot pre/post).

Habilita ingestas próximas de INMOSA, Sucden, Viña, Curicó, Apo3001 y consolidación TRI que incluye subfondos PT/Apo.
```

- [ ] **Step 3: Actualizar CLAUDE.md**

En la sección "Base de datos", en la lista de tablas, agregar antes de `derived_kpi`:

```markdown
  - `dim_sociedad` — holdings/sociedades intermedias entre fondo y activo (Chañarcillo, Senior Assist, Curicó SpA, etc.) con % del fondo en la sociedad
```

Y agregar `v_activo_fondo_efectivo` a la lista de vistas.

- [ ] **Step 4: Crear memoria persistente**

```markdown
---
name: project-tri-consolidacion-arquitectura
description: TRI es fondo paraguas. Jerarquía activo↔sociedad↔fondo↔fondo padre modelada en dim_sociedad + dim_fondo.fondo_padre; consolidar vía v_activo_fondo_efectivo
metadata:
  type: project
---

Post migración 049 (2026-07-14), TRI consolida vía la vista canónica `v_activo_fondo_efectivo(activo_key, fondo_key, participacion_efectiva, via)`.

**Estructura de participaciones:**
- `dim_sociedad`: 7 holdings (Chañarcillo, Curicó SpA, Senior Assist, VC SpA, Torre A SA, Blvd SpA, Apoquindo SpA) con `fondo_key` + `participacion_fondo_en_sociedad`
- `dim_activo.sociedad_key` + `participacion_en_sociedad` (nueva)
- `dim_fondo.fondo_padre` + `participacion_en_padre` (nueva; PT→TRI 33.3%, Apo→TRI 30%)

**Why:** Preservar las 3 capas del organigrama sin colapsarlas. `dim_activo.participacion_fondo_activo` (vieja) tenía semántica mezclada e incompleta (no soportaba subfondos ni sociedades intermedias con % != 1.0 como Apo3001 dentro de Chañarcillo = 68.5%).

**How to apply:** Para consolidación NOI/Ingresos por fondo, JOIN a `v_activo_fondo_efectivo` en lugar de leer `dim_activo.fondo_key` o `participacion_fondo_activo` directamente. La columna vieja está deprecada pero intacta porque `tools/noi_query.py` aún la usa (Fase 3 pendiente). Ver spec: `docs/superpowers/specs/2026-07-14-tri-consolidacion-arquitectura-design.md`.

Complementa [[db_ingesta_progress]] y [[project_estructura_fondos]].
```

Y agregar línea al final de `MEMORY.md`:

```markdown
- [TRI consolidación — arquitectura DB](project_tri_consolidacion_arquitectura.md) — jerarquía activo↔sociedad↔fondo↔padre post migración 049; consolidar vía v_activo_fondo_efectivo
```

- [ ] **Step 5: Commit**

```bash
git add wiki/db.md wiki/log.md CLAUDE.md
git commit -m "wiki+claude.md: documenta jerarquia dim_sociedad y v_activo_fondo_efectivo (mig 049)"
git push
```

(La memoria persistente vive fuera del repo, se guarda con Write pero no se commitea.)

---

## Self-Review

**Spec coverage:**
- Migración 049 aditiva → Task 2 ✓
- `dim_sociedad` con 7 filas → Task 2 (SQL + test) ✓
- Columnas nuevas `dim_activo`/`dim_fondo` → Task 2 ✓
- Vista `v_activo_fondo_efectivo` → Task 2 ✓
- Backup + snapshot no-regresión → Tasks 1 y 3 ✓
- Guardas: transacción (automática vía `apply_migrations`), tests, sanity queries → Tasks 2 y 3 ✓
- Wiki + memoria → Task 4 ✓
- Ingesta de los 5 activos → **fuera de scope** por diseño (Fase 2, planes separados).
- Migración `noi_query.py` → **fuera de scope** por diseño (Fase 3).

**Placeholder scan:** no TBDs. Todo código y todos los comandos concretos. Test cases tienen aserciones explícitas.

**Type consistency:** `sociedad_key` slugs (`Chanarcillo`, `CuricoSpA`, `SeniorAssist`, `VCSpA`, `TorreASA`, `BlvdSpA`, `ApoquindoSpA`) idénticos entre migración SQL, tests y wiki. Columna `via` en la vista tiene los mismos valores literales (`'directa'`, `'lookthrough'`) usados en tests. `participacion_efectiva` es REAL en todos lados.
