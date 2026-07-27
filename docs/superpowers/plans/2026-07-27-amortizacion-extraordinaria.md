# Tab de Ingesta: Amortización Extraordinaria — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a web tab to `web/ingesta.html` that lets a user log an extraordinary/prepayment amortization event against an existing crédito, persisting it durably and adjusting the projected debt schedule going forward.

**Architecture:** A new dedicated table (`raw_amortizacion_extraordinaria`) stores each event as an immutable log entry (never overwritten by the existing full-Excel-reload script). A small core module (`tools/db/ingest_amortizacion_extra.py`) exposes three plain functions taking an open `sqlite3.Connection`: list active créditos, list an event history, and commit a new event (which also shifts `raw_saldo_deuda` projections for that crédito forward in time). Three Flask endpoints in `scripts/ingesta_server.py` wire this to a new HTML tab that mirrors the existing "Sucden fijo" form pattern (structured inputs, no file upload, no separate validate step).

**Tech Stack:** Python 3, Flask, SQLite3 (stdlib), vanilla JS/HTML (no framework), pytest.

## Global Constraints

- `periodo` is always the string `'YYYY-MM'`.
- `loaded_at` is always `'YYYY-MM-DD HH:MM:SS'` (no `T` separator).
- All new `raw_*` tables filter on `superseded_at IS NULL` for "current" rows.
- `dim_credito.estado` enum is `VIGENTE` | `PAGADO` — only `VIGENTE` créditos may receive an extraordinary payment.
- Every `/api/*` route is auto-protected by the existing `before_request` token check in `scripts/ingesta_server.py` — no per-route auth code needed.
- `get_conn_for()` opens connections with `PRAGMA foreign_keys = ON` and `row_factory = sqlite3.Row`.
- Follow the design in `docs/superpowers/specs/2026-07-27-amortizacion-extraordinaria-design.md` — this plan implements it as approved; do not re-litigate scope decisions already made there (event-log table, form-only UI, no `estado_ingesta.py` entry, no touching `raw_amortizacion`).

---

## File Structure

- **Create:** `tools/db/migrations/072_amortizacion_extraordinaria.sql` — new table.
- **Create:** `tools/db/ingest_amortizacion_extra.py` — core logic (list créditos, list history, commit event + adjust projected saldo).
- **Create:** `tests/db/test_ingest_amortizacion_extra.py` — unit tests for the core module.
- **Modify:** `scripts/ingesta_server.py` — import the core module, add 3 endpoints.
- **Create:** `tests/test_ingesta_server_amort_extra.py` — endpoint tests (incl. auth).
- **Modify:** `web/ingesta.html` — new tab button, panel, and JS block.

---

### Task 1: Migration — `raw_amortizacion_extraordinaria` table

**Files:**
- Create: `tools/db/migrations/072_amortizacion_extraordinaria.sql`
- Test: `tests/db/test_migrations.py` (existing file — verify it picks up the new migration automatically, no edits needed unless it fails)

**Interfaces:**
- Produces: table `raw_amortizacion_extraordinaria(id, credito_key, fecha, periodo, monto_uf, nota, source_file, file_hash, ingest_run_id, loaded_at, superseded_at)`, consumed by Task 2's core module.

- [ ] **Step 1: Write the migration file**

```sql
-- 072: log de pagos extraordinarios (prepagos/bullet) sobre créditos vigentes.
--
-- No reemplaza raw_amortizacion (cronograma completo, recargado en bloque por
-- tools/db/ingest_financing.py desde el Excel maestro) — es un registro
-- independiente del evento en sí, para no perderlo entre un reload y el
-- siguiente. Ver docs/superpowers/specs/2026-07-27-amortizacion-extraordinaria-design.md.
CREATE TABLE raw_amortizacion_extraordinaria (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    credito_key     TEXT NOT NULL REFERENCES dim_credito(credito_key),
    fecha           TEXT NOT NULL,        -- 'YYYY-MM-DD'
    periodo         TEXT NOT NULL,        -- 'YYYY-MM', derivado de fecha
    monto_uf        REAL NOT NULL,
    nota            TEXT,
    source_file     TEXT,
    file_hash       TEXT,
    ingest_run_id   INTEGER REFERENCES ingest_run(id),
    loaded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at   TEXT
);
```

- [ ] **Step 2: Apply the migration to a scratch copy of the real DB to verify it runs cleanly**

Run:
```bash
python -X utf8 -c "
import shutil
shutil.copy('memory/agente_toesca_v2.db', 'memory/agente_toesca_v2.db.scratch_test')
from tools.db.connection import apply_migrations
applied = apply_migrations('memory/agente_toesca_v2.db.scratch_test')
print('applied:', applied)
"
```
Expected: prints a list ending in `72`, no exception. Then delete the scratch file:
```bash
rm memory/agente_toesca_v2.db.scratch_test
```

- [ ] **Step 3: Apply the migration to the real DB**

```bash
python -X utf8 -c "
from tools.db.connection import apply_migrations
print(apply_migrations('memory/agente_toesca_v2.db'))
"
```
Expected: `72` appears in the printed list (or the list is empty if already applied — re-running is a no-op).

- [ ] **Step 4: Commit**

```bash
git add tools/db/migrations/072_amortizacion_extraordinaria.sql memory/agente_toesca_v2.db
git commit -m "db(072): tabla raw_amortizacion_extraordinaria para prepagos"
```

---

### Task 2: Core module — `tools/db/ingest_amortizacion_extra.py`

**Files:**
- Create: `tools/db/ingest_amortizacion_extra.py`
- Test: `tests/db/test_ingest_amortizacion_extra.py`

**Interfaces:**
- Consumes: `sqlite3.Connection` from `tools.db.connection.get_conn_for` (Task 1's table; `dim_credito` and `raw_saldo_deuda`, both pre-existing).
- Produces (used by Task 3's endpoints):
  - `DB_PATH: Path` — module-level constant, same pattern as `ingest_balance_consolidado.DB_PATH`.
  - `listar_creditos(con: sqlite3.Connection) -> list[dict]` — each dict has `credito_key`, `acreedor`, `activo_key`, `fondo_key`.
  - `historial(con: sqlite3.Connection, credito_key: str) -> list[dict]` — each dict has `fecha`, `monto_uf`, `nota`, ordered newest first.
  - `commit(con: sqlite3.Connection, credito_key: str, fecha: str, monto_uf: float, nota: str | None = None) -> dict` — raises `ValueError` on invalid input; on success returns `{"status": "ok", "credito_key": str, "periodo": str, "monto_uf": float, "periodos_ajustados": int}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/db/test_ingest_amortizacion_extra.py`:

```python
from __future__ import annotations

import pytest

from tools.db import ingest_amortizacion_extra as amort


def _seed_credito(con, credito_key="TEST_CRED", estado="VIGENTE"):
    con.execute(
        "INSERT INTO dim_credito (credito_key, activo_key, fondo_key, acreedor, estado) "
        "VALUES (?, 'ActivoTest', 'TRI', 'BancoTest', ?)",
        (credito_key, estado),
    )
    con.commit()


def _seed_saldo(con, credito_key, proyectados=(), historicos=()):
    for periodo, saldo in proyectados:
        con.execute(
            "INSERT INTO raw_saldo_deuda (credito_key, periodo, saldo_uf, is_proyeccion) "
            "VALUES (?, ?, ?, 1)",
            (credito_key, periodo, saldo),
        )
    for periodo, saldo in historicos:
        con.execute(
            "INSERT INTO raw_saldo_deuda (credito_key, periodo, saldo_uf, is_proyeccion) "
            "VALUES (?, ?, ?, 0)",
            (credito_key, periodo, saldo),
        )
    con.commit()


def test_commit_rechaza_credito_inexistente(tmp_db):
    with pytest.raises(ValueError, match="no existe"):
        amort.commit(tmp_db, "NO_EXISTE", "2026-08-15", 100.0)


def test_commit_rechaza_credito_pagado(tmp_db):
    _seed_credito(tmp_db, estado="PAGADO")
    with pytest.raises(ValueError, match="VIGENTE"):
        amort.commit(tmp_db, "TEST_CRED", "2026-08-15", 100.0)


def test_commit_rechaza_monto_no_positivo(tmp_db):
    _seed_credito(tmp_db)
    with pytest.raises(ValueError, match="monto"):
        amort.commit(tmp_db, "TEST_CRED", "2026-08-15", 0)


def test_commit_rechaza_fecha_invalida(tmp_db):
    _seed_credito(tmp_db)
    with pytest.raises(ValueError, match="[Ff]echa"):
        amort.commit(tmp_db, "TEST_CRED", "15-08-2026", 100.0)


def test_commit_ajusta_solo_saldo_proyectado_futuro_del_mismo_credito(tmp_db):
    _seed_credito(tmp_db, credito_key="TEST_CRED")
    _seed_saldo(
        tmp_db, "TEST_CRED",
        proyectados=[("2026-08", 1000.0), ("2026-09", 950.0)],
        historicos=[("2026-07", 1050.0)],
    )
    _seed_credito(tmp_db, credito_key="OTRO_CRED")
    _seed_saldo(tmp_db, "OTRO_CRED", proyectados=[("2026-08", 500.0)])

    result = amort.commit(tmp_db, "TEST_CRED", "2026-08-10", 100.0, nota="prepago test")

    assert result["status"] == "ok"
    assert result["periodo"] == "2026-08"
    assert result["periodos_ajustados"] == 2

    saldo_hist = tmp_db.execute(
        "SELECT saldo_uf FROM raw_saldo_deuda WHERE credito_key='TEST_CRED' AND periodo='2026-07'"
    ).fetchone()[0]
    assert saldo_hist == 1050.0  # historico intacto (is_proyeccion=0)

    saldo_ago = tmp_db.execute(
        "SELECT saldo_uf FROM raw_saldo_deuda WHERE credito_key='TEST_CRED' AND periodo='2026-08'"
    ).fetchone()[0]
    assert saldo_ago == 900.0  # 1000 - 100

    saldo_sep = tmp_db.execute(
        "SELECT saldo_uf FROM raw_saldo_deuda WHERE credito_key='TEST_CRED' AND periodo='2026-09'"
    ).fetchone()[0]
    assert saldo_sep == 850.0  # 950 - 100

    saldo_otro = tmp_db.execute(
        "SELECT saldo_uf FROM raw_saldo_deuda WHERE credito_key='OTRO_CRED' AND periodo='2026-08'"
    ).fetchone()[0]
    assert saldo_otro == 500.0  # otro credito no se toca

    evento = tmp_db.execute(
        "SELECT credito_key, fecha, periodo, monto_uf, nota FROM raw_amortizacion_extraordinaria "
        "WHERE credito_key='TEST_CRED'"
    ).fetchone()
    assert tuple(evento) == ("TEST_CRED", "2026-08-10", "2026-08", 100.0, "prepago test")


def test_historial_orden_descendente_por_fecha(tmp_db):
    _seed_credito(tmp_db)
    amort.commit(tmp_db, "TEST_CRED", "2026-06-01", 50.0, nota="primero")
    amort.commit(tmp_db, "TEST_CRED", "2026-08-01", 30.0, nota="segundo")

    eventos = amort.historial(tmp_db, "TEST_CRED")

    assert [e["nota"] for e in eventos] == ["segundo", "primero"]


def test_listar_creditos_solo_vigentes(tmp_db):
    _seed_credito(tmp_db, credito_key="V1", estado="VIGENTE")
    _seed_credito(tmp_db, credito_key="P1", estado="PAGADO")

    creditos = amort.listar_creditos(tmp_db)

    keys = {c["credito_key"] for c in creditos}
    assert "V1" in keys
    assert "P1" not in keys
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_ingest_amortizacion_extra.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.db.ingest_amortizacion_extra'` (or `ImportError`).

- [ ] **Step 3: Write the implementation**

Create `tools/db/ingest_amortizacion_extra.py`:

```python
"""Registro de pagos extraordinarios (prepago/bullet) sobre créditos vigentes.

No reemplaza raw_amortizacion (cronograma completo, recargado en bloque desde
el Excel maestro por tools/db/ingest_financing.py) — es un log de eventos
independiente. Al registrar un evento se ajusta hacia adelante raw_saldo_deuda
(solo períodos con is_proyeccion=1) para que los KPIs de deuda/LTV reflejen el
prepago sin esperar el próximo reload completo del Excel.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[2] / "memory" / "agente_toesca_v2.db"


def listar_creditos(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT credito_key, acreedor, activo_key, fondo_key "
        "FROM dim_credito WHERE estado='VIGENTE' ORDER BY fondo_key, activo_key"
    ).fetchall()
    return [
        {
            "credito_key": r["credito_key"],
            "acreedor": r["acreedor"],
            "activo_key": r["activo_key"],
            "fondo_key": r["fondo_key"],
        }
        for r in rows
    ]


def historial(con: sqlite3.Connection, credito_key: str) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT fecha, monto_uf, nota FROM raw_amortizacion_extraordinaria "
        "WHERE credito_key=? AND superseded_at IS NULL ORDER BY fecha DESC",
        (credito_key,),
    ).fetchall()
    return [{"fecha": r["fecha"], "monto_uf": r["monto_uf"], "nota": r["nota"]} for r in rows]


def commit(
    con: sqlite3.Connection,
    credito_key: str,
    fecha: str,
    monto_uf: float,
    nota: str | None = None,
) -> dict[str, Any]:
    row = con.execute(
        "SELECT estado FROM dim_credito WHERE credito_key=?", (credito_key,)
    ).fetchone()
    if row is None:
        raise ValueError(f"El crédito '{credito_key}' no existe.")
    if row["estado"] != "VIGENTE":
        raise ValueError(
            f"El crédito '{credito_key}' no está VIGENTE (estado={row['estado']}); "
            "no puede recibir un pago extraordinario."
        )
    if monto_uf is None or not isinstance(monto_uf, (int, float)) or monto_uf <= 0:
        raise ValueError("El monto (monto_uf) debe ser un número mayor a 0.")
    try:
        fecha_parsed = date.fromisoformat(fecha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Fecha inválida: {fecha!r}. Usa formato YYYY-MM-DD.") from exc

    periodo = fecha_parsed.strftime("%Y-%m")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur = con.cursor()
    cur.execute(
        "INSERT INTO ingest_run (tool, started_at, status, periodo_declarado) VALUES (?,?,?,?)",
        ("ingest_amortizacion_extra", now, "running", periodo),
    )
    run_id = cur.lastrowid
    try:
        cur.execute(
            """INSERT INTO raw_amortizacion_extraordinaria
               (credito_key, fecha, periodo, monto_uf, nota, ingest_run_id, loaded_at)
               VALUES (?,?,?,?,?,?,?)""",
            (credito_key, fecha, periodo, monto_uf, nota, run_id, now),
        )
        cur.execute(
            "UPDATE raw_saldo_deuda SET saldo_uf = saldo_uf - ? "
            "WHERE credito_key=? AND periodo>=? AND is_proyeccion=1",
            (monto_uf, credito_key, periodo),
        )
        periodos_ajustados = cur.rowcount
        cur.execute(
            "UPDATE ingest_run SET ended_at=?, status='ok', rows_loaded=1 WHERE id=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), run_id),
        )
        con.commit()
    except Exception:
        con.rollback()
        cur.execute(
            "UPDATE ingest_run SET ended_at=?, status='error' WHERE id=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), run_id),
        )
        con.commit()
        raise

    return {
        "status": "ok",
        "credito_key": credito_key,
        "periodo": periodo,
        "monto_uf": monto_uf,
        "periodos_ajustados": periodos_ajustados,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/db/test_ingest_amortizacion_extra.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db/ingest_amortizacion_extra.py tests/db/test_ingest_amortizacion_extra.py
git commit -m "feat(db): registrar pagos extraordinarios sobre creditos vigentes"
```

---

### Task 3: Endpoints in `scripts/ingesta_server.py`

**Files:**
- Modify: `scripts/ingesta_server.py:42` (import), `scripts/ingesta_server.py:658-659` (insert new routes before the `if __name__ == "__main__":` block)
- Test: `tests/test_ingesta_server_amort_extra.py`

**Interfaces:**
- Consumes: `tools.db.ingest_amortizacion_extra.{DB_PATH, listar_creditos, historial, commit}` (Task 2), `tools.db.connection.get_conn_for` (already imported in this file as of line 43).
- Produces (consumed by Task 4's frontend):
  - `GET /api/amort_extra/creditos` → `{"creditos": [...]}`
  - `GET /api/amort_extra/historial?credito_key=X` → `{"eventos": [...]}`
  - `POST /api/amort_extra/commit` with JSON body `{credito_key, fecha, monto_uf, nota}` → `{"ok": true, ...}` on success (200) or `{"ok": false, "error": "..."}` (400) on failure.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingesta_server_amort_extra.py`:

```python
from __future__ import annotations

import pytest

from tools.db.connection import apply_migrations
from tools.db import ingest_amortizacion_extra


def _seed_credito(db_path, credito_key="TEST_CRED", estado="VIGENTE"):
    from tools.db.connection import get_conn_for
    con = get_conn_for(db_path)
    con.execute(
        "INSERT INTO dim_credito (credito_key, activo_key, fondo_key, acreedor, estado) "
        "VALUES (?, 'ActivoTest', 'TRI', 'BancoTest', ?)",
        (credito_key, estado),
    )
    con.commit()
    con.close()


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(ingest_amortizacion_extra, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        c.environ_base["HTTP_X_INGESTA_TOKEN"] = ingesta_server.API_TOKEN
        yield c


def test_creditos_endpoint_requiere_token(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(ingest_amortizacion_extra, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        res = c.get("/api/amort_extra/creditos")  # sin header de token
    assert res.status_code == 401


def test_creditos_endpoint_lista_solo_vigentes(client, tmp_db_path):
    _seed_credito(tmp_db_path, credito_key="V1", estado="VIGENTE")
    _seed_credito(tmp_db_path, credito_key="P1", estado="PAGADO")

    res = client.get("/api/amort_extra/creditos")

    assert res.status_code == 200
    keys = {c["credito_key"] for c in res.get_json()["creditos"]}
    assert "V1" in keys
    assert "P1" not in keys


def test_commit_endpoint_persiste_evento(client, tmp_db_path):
    _seed_credito(tmp_db_path, credito_key="TEST_CRED")

    res = client.post(
        "/api/amort_extra/commit",
        json={"credito_key": "TEST_CRED", "fecha": "2026-08-15", "monto_uf": 100.0, "nota": "test"},
    )

    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["periodo"] == "2026-08"

    hist_res = client.get("/api/amort_extra/historial?credito_key=TEST_CRED")
    eventos = hist_res.get_json()["eventos"]
    assert len(eventos) == 1
    assert eventos[0]["nota"] == "test"


def test_commit_endpoint_rechaza_credito_pagado(client, tmp_db_path):
    _seed_credito(tmp_db_path, credito_key="PAGADO_CRED", estado="PAGADO")

    res = client.post(
        "/api/amort_extra/commit",
        json={"credito_key": "PAGADO_CRED", "fecha": "2026-08-15", "monto_uf": 100.0},
    )

    assert res.status_code == 400
    assert res.get_json()["ok"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingesta_server_amort_extra.py -v`
Expected: FAIL — 404s on the new routes (they don't exist yet).

- [ ] **Step 3: Add the import**

In `scripts/ingesta_server.py`, after line 42 (`from tools.db import ingest_er_sucden_fijo as sucden_fijo_core  # noqa: E402`), add:

```python
from tools.db import ingest_amortizacion_extra as amort_extra_core  # noqa: E402
```

- [ ] **Step 4: Add the three endpoints**

In `scripts/ingesta_server.py`, insert this block right before the final `if __name__ == "__main__":` line (currently line 662, right after `api_er_mensual_commit` ends at line 658):

```python
@app.get("/api/amort_extra/creditos")
def api_amort_extra_creditos():
    con = get_conn_for(str(amort_extra_core.DB_PATH))
    try:
        return jsonify({"creditos": amort_extra_core.listar_creditos(con)})
    finally:
        con.close()


@app.get("/api/amort_extra/historial")
def api_amort_extra_historial():
    credito_key = request.args.get("credito_key", "")
    if not credito_key:
        return jsonify({"eventos": []})
    con = get_conn_for(str(amort_extra_core.DB_PATH))
    try:
        return jsonify({"eventos": amort_extra_core.historial(con, credito_key)})
    finally:
        con.close()


@app.post("/api/amort_extra/commit")
def api_amort_extra_commit():
    data = _json_body()
    credito_key = data.get("credito_key", "")
    fecha = data.get("fecha", "")
    monto_uf = data.get("monto_uf")
    nota = data.get("nota") or None
    if not credito_key or not fecha or monto_uf is None:
        return jsonify({"ok": False, "error": "Faltan credito_key, fecha o monto_uf."}), 400
    con = get_conn_for(str(amort_extra_core.DB_PATH))
    try:
        result = amort_extra_core.commit(con, credito_key, fecha, float(monto_uf), nota)
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        con.close()
    _rebuild_factsheet()
    return jsonify({"ok": True, **result})
```

Note: `_json_body()` is already defined at line 582 in this file, reused here as-is.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ingesta_server_amort_extra.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `pytest tests/ -x -q`
Expected: all tests PASS (no regressions in existing endpoint/routing tests).

- [ ] **Step 7: Commit**

```bash
git add scripts/ingesta_server.py tests/test_ingesta_server_amort_extra.py
git commit -m "feat(api): endpoints /api/amort_extra para pagos extraordinarios"
```

---

### Task 4: Frontend tab in `web/ingesta.html`

**Files:**
- Modify: `web/ingesta.html:389` (tab button), `web/ingesta.html:949` (insert new tab panel after `</div>` closing `#tab-er-activos`, before `</main>`), `web/ingesta.html:2998-2999` (insert new JS init call before the closing `</script></body></html>`)

**Interfaces:**
- Consumes: `GET /api/amort_extra/creditos`, `GET /api/amort_extra/historial?credito_key=X`, `POST /api/amort_extra/commit` (Task 3). Reuses global helpers already defined earlier in this file: `setStatus(el, text, state)` (line 1006), the `window.fetch` token-injection wrapper (lines 959-971), and the existing `.tab-btn`/`.tab-panel` switching logic (lines 973-985ish, unmodified — it works generically off `data-tab` attributes).

- [ ] **Step 1: Add the tab button**

In `web/ingesta.html`, after line 389 (`<button class="tab-btn" data-tab="er-activos">Ingresos/NOI Activos</button>`), add:

```html
    <button class="tab-btn" data-tab="amort-extra">Amort. Extraordinaria</button>
```

- [ ] **Step 2: Add the tab panel**

In `web/ingesta.html`, immediately after the `</div>` that closes `<div id="tab-er-activos" ...>` (line 949), add:

```html
<!-- ══════════════════════════ TAB AMORTIZACIÓN EXTRAORDINARIA ══════════════════════════ -->
<div id="tab-amort-extra" class="tab-panel">
  <div class="step">
    <div class="step-title"><span class="step-num">1</span> Pago extraordinario</div>
    <p class="muted" style="margin:0 0 10px;">
      Registra un prepago/bullet puntual sobre un crédito vigente (ej. la
      amortización extra de nov-2026 en Torre A). Ajusta hacia adelante el
      saldo proyectado de ese crédito — no toca el cronograma histórico.
    </p>
    <div class="row">
      <label class="muted" for="ae-credito">Crédito:</label>
      <select id="ae-credito"></select>
    </div>
    <div class="row" style="margin-top:10px;">
      <label class="muted" for="ae-fecha">Fecha del pago:</label>
      <input type="date" id="ae-fecha">
    </div>
    <div class="row" style="margin-top:10px;">
      <label class="muted" for="ae-monto">Monto (UF):</label>
      <input type="number" step="0.01" id="ae-monto">
    </div>
    <div class="row" style="margin-top:10px;">
      <label class="muted" for="ae-nota">Nota (opcional):</label>
      <input type="text" id="ae-nota" style="flex:1;">
    </div>
    <div class="row" style="margin-top:18px;">
      <button id="btn-ae-registrar">Registrar</button>
      <span id="ae-status" class="muted"></span>
    </div>
  </div>

  <div class="step" style="margin-top:20px;">
    <div class="step-title">Historial del crédito seleccionado</div>
    <table>
      <thead><tr><th>Fecha</th><th class="num">Monto UF</th><th>Nota</th></tr></thead>
      <tbody id="ae-historial-body"></tbody>
    </table>
  </div>
</div>
```

- [ ] **Step 3: Add the JS block**

In `web/ingesta.html`, immediately before the closing `</script>` at line 3000 (right after `initErSucdenFijo();` on line 2999), add:

```javascript
async function initAmortExtra() {
  const select = document.getElementById('ae-credito');
  const fechaInput = document.getElementById('ae-fecha');
  const montoInput = document.getElementById('ae-monto');
  const notaInput = document.getElementById('ae-nota');
  const btnRegistrar = document.getElementById('btn-ae-registrar');
  const status = document.getElementById('ae-status');
  const historialBody = document.getElementById('ae-historial-body');

  async function cargarCreditos() {
    try {
      const res = await fetch('/api/amort_extra/creditos');
      const data = await res.json();
      select.innerHTML = (data.creditos || [])
        .map(c => `<option value="${c.credito_key}">${c.acreedor} — ${c.activo_key} (${c.fondo_key})</option>`)
        .join('');
      if (select.value) cargarHistorial();
    } catch (e) {}
  }

  async function cargarHistorial() {
    if (!select.value) { historialBody.innerHTML = ''; return; }
    try {
      const res = await fetch(`/api/amort_extra/historial?credito_key=${encodeURIComponent(select.value)}`);
      const data = await res.json();
      historialBody.innerHTML = (data.eventos || [])
        .map(e => `<tr><td>${e.fecha}</td><td class="num">${e.monto_uf}</td><td>${e.nota || ''}</td></tr>`)
        .join('') || '<tr><td colspan="3" class="muted">Sin eventos registrados.</td></tr>';
    } catch (e) {}
  }

  select.addEventListener('change', cargarHistorial);
  cargarCreditos();

  btnRegistrar.addEventListener('click', async () => {
    if (!select.value || !fechaInput.value || !montoInput.value) {
      setStatus(status, 'Completa crédito, fecha y monto.', 'error');
      return;
    }
    btnRegistrar.disabled = true;
    setStatus(status, 'Registrando...', 'loading');
    try {
      const res = await fetch('/api/amort_extra/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          credito_key: select.value,
          fecha: fechaInput.value,
          monto_uf: parseFloat(montoInput.value),
          nota: notaInput.value || null,
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'error');
      setStatus(status, `Registrado. ${data.periodos_ajustados} período(s) de saldo proyectado ajustados.`, 'success');
      montoInput.value = '';
      notaInput.value = '';
      cargarHistorial();
    } catch (e) {
      setStatus(status, 'Error: ' + e.message, 'error');
    } finally {
      btnRegistrar.disabled = false;
    }
  });
}
initAmortExtra();
```

- [ ] **Step 4: Manual smoke test in a browser**

Run: `python -m scripts.ingesta_server` (uses the real `memory/agente_toesca_v2.db`, already migrated in Task 1).
Open: `http://127.0.0.1:8765/ingesta`, click the "Amort. Extraordinaria" tab.

Verify:
- The crédito dropdown populates with the 13 `VIGENTE` créditos from `dim_credito` (not the 2 `PAGADO` ones — `APO_APO_EUROAMERICA`, `APO_APO_BTG`).
- Selecting a crédito loads its historial (empty table initially, showing "Sin eventos registrados.").
- Filling fecha/monto/nota and clicking "Registrar" shows a success message and the new row appears in the historial table below.
- Leaving fecha or monto empty and clicking "Registrar" shows the client-side validation message without calling the API.

Then clean up the test event from the real DB (this was a manual smoke test, not meant to leave data behind):
```bash
python -X utf8 -c "
from tools.db.connection import get_conn
con = get_conn()
con.execute(\"DELETE FROM raw_amortizacion_extraordinaria WHERE nota LIKE '%smoke test%' OR credito_key=?\", ('<credito_key usado en la prueba>',))
con.commit()
con.close()
"
```
(Fill in the actual `credito_key` used during the manual test.)

- [ ] **Step 5: Commit**

```bash
git add web/ingesta.html
git commit -m "feat(ui): tab de ingesta para amortizacion extraordinaria"
```

---

## Self-Review Notes

- **Spec coverage:** all 5 sections of the design doc are covered — Sección 1 (schema) → Task 1; Sección 2 (backend) → Task 2 + Task 3; Sección 3 (frontend) → Task 4; "Fuera de alcance" items are explicitly not touched (no `estado_ingesta.py` entry, no `raw_amortizacion` writes, no edit/delete UI); "Testing" section → Tasks 2 and 3's test files.
- **Type consistency:** `commit()` signature `(con, credito_key, fecha, monto_uf, nota=None)` is identical across Task 2 (core), Task 3 (endpoint call site), and the test files. Return dict keys (`status`, `credito_key`, `periodo`, `monto_uf`, `periodos_ajustados`) match between the core function, its tests, and what the endpoint spreads into its JSON response.
- **No placeholders:** every step has literal code, not descriptions of code.
