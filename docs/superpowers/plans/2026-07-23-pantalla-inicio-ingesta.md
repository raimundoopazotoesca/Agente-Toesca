# Pantalla de Inicio del Menú de Ingesta — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a landing view to `/ingesta` that shows, per data type (EEFF, Rent Roll,
Mercado Oficinas), the last ingested period and the next pending one, so the user
doesn't have to open each tab to discover what's missing.

**Architecture:** A new backend module `tools/db/estado_ingesta.py` holds a small config
list (one entry per data type) plus pure period-arithmetic helpers and a DB-querying
`estado_ingesta()` function. A new `GET /api/estado_ingesta` endpoint in
`scripts/ingesta_server.py` exposes it as JSON. The frontend gets a 4th tab ("Inicio"),
active by default, that fetches this endpoint and renders 3 cards with a mini-timeline.
Clicking a card's button switches to the target tab and preselects the pending period.

**Tech Stack:** Python 3 stdlib (`datetime`), sqlite3 via `tools.db.connection.get_conn_for`,
Flask (existing `scripts/ingesta_server.py`), vanilla JS/CSS in `web/ingesta.html` (no new
frontend dependencies).

## Global Constraints

- Filter every raw-table query with `WHERE superseded_at IS NULL` (per spec and existing
  codebase convention).
- No new DB tables, no caching — compute on demand from `raw_eeff_line`,
  `raw_rent_roll_line`, `raw_mercado_oficinas` (spec: "Fuera de alcance").
- Only the 3 types already in the menu; config-driven so a 4th type is a config entry,
  not new HTML (spec: "Extensibilidad").
- Visual style reuses existing CSS custom properties already defined in
  `web/ingesta.html` (`--green`, `--err`, `--warn`, `--muted`, `--border`) — no new palette.
- `raw_dividendo` / `raw_valor_cuota_contable` are NOT tracked separately — they ride
  along with the EEFF card (same commit, see `tools/db/ingest_eeff_validated.py::commit`).

---

## Design decisions made while planning (not in the original spec, needed to make it concrete)

1. **"Expected/closed period" arithmetic is new, not reused from frontend JS.** The
   existing `populateEeffTrimestres()` in `web/ingesta.html` computes a *default dropdown
   selection* with a year-offset quirk that does not represent "the period that should
   already be ingested" (verified by tracing it: for July 2026 it defaults to
   `2025-09`, which is not useful as a correctness check). `estado_ingesta.py` therefore
   implements its own, independently correct closed-period calculation (Task 1).
2. **Timeline's "na" (gray) slot = the in-progress period**, not unknowable pre-history.
   The last slot of each timeline is always the current in-progress quarter/month
   (not yet due); it's gray unless data already exists for it. The preceding N-1 slots
   are closed periods, colored ok/miss. This gives "na" a concrete, computable meaning
   consistent with the spec's "no aplica todavía / futuro" wording.
3. **EEFF is "complete" for a period only when all 3 fondos (TRI, PT, APO) have rows.**
   A partially-loaded period (e.g. only TRI+PT) counts as not-complete for the single
   EEFF card, matching the "una card por tipo" design (no per-fondo breakdown in v1).

---

### Task 1: Period arithmetic helpers (`tools/db/estado_ingesta.py`)

**Files:**
- Create: `tools/db/estado_ingesta.py`
- Test: `tests/db/test_estado_ingesta.py`

**Interfaces:**
- Produces: `_shift_periodo(periodo: str, meses: int) -> str`,
  `_periodo_en_curso(hoy: date, frecuencia: str) -> str`,
  `_periodo_cerrado(periodo_en_curso: str, frecuencia: str) -> str`.
  `frecuencia` is one of the literal strings `"mensual"` / `"trimestral"`.
  `periodo` strings are always `"YYYY-MM"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/db/test_estado_ingesta.py
from __future__ import annotations

from datetime import date

from tools.db.estado_ingesta import (
    _shift_periodo,
    _periodo_en_curso,
    _periodo_cerrado,
)


def test_shift_periodo_forward_within_year():
    assert _shift_periodo("2026-01", 2) == "2026-03"


def test_shift_periodo_forward_across_year():
    assert _shift_periodo("2025-11", 3) == "2026-02"


def test_shift_periodo_backward_across_year():
    assert _shift_periodo("2026-01", -1) == "2025-12"


def test_periodo_en_curso_mensual():
    assert _periodo_en_curso(date(2026, 7, 23), "mensual") == "2026-07"


def test_periodo_en_curso_trimestral_mid_quarter():
    # Julio cae en el trimestre Jul-Sep, que termina en Septiembre
    assert _periodo_en_curso(date(2026, 7, 23), "trimestral") == "2026-09"


def test_periodo_en_curso_trimestral_first_month_of_quarter():
    # Enero cae en el trimestre Ene-Mar, que termina en Marzo
    assert _periodo_en_curso(date(2026, 1, 5), "trimestral") == "2026-03"


def test_periodo_cerrado_mensual():
    assert _periodo_cerrado("2026-07", "mensual") == "2026-06"


def test_periodo_cerrado_trimestral():
    assert _periodo_cerrado("2026-09", "trimestral") == "2026-06"


def test_periodo_cerrado_trimestral_year_wrap():
    assert _periodo_cerrado("2026-03", "trimestral") == "2025-12"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/db/test_estado_ingesta.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.db.estado_ingesta'`

- [ ] **Step 3: Write the implementation**

```python
# tools/db/estado_ingesta.py
"""Estado de ingesta por tipo de dato (EEFF, Rent Roll, Mercado Oficinas).

Calcula, para cada tipo soportado por el menú de ingesta (web/ingesta.html),
el último período ingestado y el próximo período pendiente, sin cache ni
tabla nueva — se computa on-demand desde las tablas raw_* correspondientes.

No confundir con la lógica de pre-selección de dropdowns en el frontend
(populateEeffTrimestres, etc.): esa es solo una conveniencia de UI y no
calcula correctamente "el período que ya debería estar cargado".
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"


def _shift_periodo(periodo: str, meses: int) -> str:
    """Suma (o resta, si meses<0) una cantidad de meses a un período YYYY-MM."""
    year, month = (int(p) for p in periodo.split("-"))
    total = year * 12 + (month - 1) + meses
    year2, month2 = divmod(total, 12)
    return f"{year2:04d}-{month2 + 1:02d}"


def _periodo_en_curso(hoy: date, frecuencia: str) -> str:
    """Período (YYYY-MM) en curso — el mes o trimestre que contiene ``hoy``.

    Para trimestral, es el mes de cierre del trimestre en curso (03/06/09/12),
    esté o no ya cerrado.
    """
    if frecuencia == "mensual":
        return f"{hoy.year:04d}-{hoy.month:02d}"
    if frecuencia == "trimestral":
        quarter_end_month = ((hoy.month - 1) // 3 + 1) * 3
        return f"{hoy.year:04d}-{quarter_end_month:02d}"
    raise ValueError(f"frecuencia inválida: {frecuencia!r}")


def _periodo_cerrado(periodo_en_curso: str, frecuencia: str) -> str:
    """El último período que ya debería estar cerrado y disponible para ingesta."""
    paso = 1 if frecuencia == "mensual" else 3
    return _shift_periodo(periodo_en_curso, -paso)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/db/test_estado_ingesta.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/db/estado_ingesta.py tests/db/test_estado_ingesta.py
git commit -m "feat(ingesta): agrega calculo de periodo cerrado/en curso para estado de ingesta"
```

---

### Task 2: Config de tipos + query de estado por tipo

**Files:**
- Modify: `tools/db/estado_ingesta.py`
- Test: `tests/db/test_estado_ingesta.py`

**Interfaces:**
- Consumes: `_shift_periodo`, `_periodo_en_curso`, `_periodo_cerrado` (Task 1).
- Consumes: `tools.db.connection.get_conn_for(path: str) -> sqlite3.Connection`
  (existing, used elsewhere in the codebase the same way).
- Produces:
  - `CONFIG: list[dict]` — module-level list, one dict per tipo, keys:
    `id: str`, `label: str`, `frecuencia: "mensual"|"trimestral"`, `tabla: str`,
    `columna_periodo: str`, `fondos: list[str] | None`, `columna_fondo: str | None`,
    `n_timeline: int`, `tab_destino: str`.
  - `estado_tipo(con: sqlite3.Connection, tipo_cfg: dict, hoy: date) -> dict` — returns
    `{"id", "label", "frecuencia", "ultimo_ingestado": str | None, "pendiente": str | None,
    "al_dia": bool, "tab_destino": str, "timeline": list[{"periodo": str, "estado": "ok"|"miss"|"na"}]}`.
  - `estado_ingesta(con: sqlite3.Connection, hoy: date | None = None) -> dict` — returns
    `{"tipos": [estado_tipo(...) for each entry in CONFIG]}`.

- [ ] **Step 1: Write the failing tests**

```python
# agregar al final de tests/db/test_estado_ingesta.py
from datetime import date

import pytest

from tools.db.connection import apply_migrations, get_conn_for
from tools.db.estado_ingesta import CONFIG, estado_tipo, estado_ingesta


@pytest.fixture
def con(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    yield conn
    conn.close()


def _insert_eeff(con, periodo, fondo):
    con.execute(
        "INSERT INTO raw_eeff_line (fondo_key, periodo, cuenta_codigo, monto_clp) "
        "VALUES (?, ?, 'X.TEST', 1)",
        (fondo, periodo),
    )
    con.commit()


def _insert_rentroll(con, periodo):
    con.execute(
        "INSERT INTO raw_rent_roll_line (activo_key, periodo, unidad) "
        "VALUES ('PT', ?, 'U1')",
        (periodo,),
    )
    con.commit()


def _insert_mercado(con, periodo):
    con.execute(
        "INSERT INTO raw_mercado_oficinas (periodo, proveedor, submercado, clase) "
        "VALUES (?, 'JLL', 'Las Condes', 'A')",
        (periodo,),
    )
    con.commit()


def test_config_tiene_los_3_tipos_del_menu():
    ids = {c["id"] for c in CONFIG}
    assert ids == {"eeff", "rentroll", "mercado"}


def test_estado_tipo_eeff_completo_y_al_dia(con):
    cfg = next(c for c in CONFIG if c["id"] == "eeff")
    hoy = date(2026, 7, 23)  # cerrado esperado: 2026-06
    for fondo in ("TRI", "PT", "APO"):
        _insert_eeff(con, "2026-06", fondo)
    resultado = estado_tipo(con, cfg, hoy)
    assert resultado["ultimo_ingestado"] == "2026-06"
    assert resultado["pendiente"] is None
    assert resultado["al_dia"] is True


def test_estado_tipo_eeff_incompleto_marca_pendiente(con):
    cfg = next(c for c in CONFIG if c["id"] == "eeff")
    hoy = date(2026, 7, 23)
    _insert_eeff(con, "2026-06", "TRI")
    _insert_eeff(con, "2026-06", "PT")
    # falta APO en 2026-06
    resultado = estado_tipo(con, cfg, hoy)
    assert resultado["pendiente"] == "2026-06"
    assert resultado["al_dia"] is False


def test_estado_tipo_rentroll_mensual(con):
    cfg = next(c for c in CONFIG if c["id"] == "rentroll")
    hoy = date(2026, 7, 23)  # cerrado esperado: 2026-06
    _insert_rentroll(con, "2026-05")
    resultado = estado_tipo(con, cfg, hoy)
    assert resultado["ultimo_ingestado"] == "2026-05"
    assert resultado["pendiente"] == "2026-06"
    assert resultado["al_dia"] is False


def test_estado_tipo_mercado_timeline_ultimo_slot_en_curso(con):
    cfg = next(c for c in CONFIG if c["id"] == "mercado")
    hoy = date(2026, 7, 23)  # en curso: 2026-09, cerrado: 2026-06
    _insert_mercado(con, "2025-12")
    _insert_mercado(con, "2026-03")
    _insert_mercado(con, "2026-06")
    resultado = estado_tipo(con, cfg, hoy)
    assert resultado["al_dia"] is True
    timeline = resultado["timeline"]
    assert [t["periodo"] for t in timeline] == ["2025-12", "2026-03", "2026-06", "2026-09"]
    assert [t["estado"] for t in timeline] == ["ok", "ok", "ok", "na"]


def test_estado_ingesta_devuelve_los_3_tipos(con):
    resultado = estado_ingesta(con, hoy=date(2026, 7, 23))
    ids = {t["id"] for t in resultado["tipos"]}
    assert ids == {"eeff", "rentroll", "mercado"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/db/test_estado_ingesta.py -v`
Expected: FAIL — `ImportError: cannot import name 'CONFIG'` (and similar for `estado_tipo`,
`estado_ingesta`).

- [ ] **Step 3: Write the implementation**

Add to `tools/db/estado_ingesta.py` (after the functions from Task 1):

```python
CONFIG: list[dict] = [
    {
        "id": "eeff",
        "label": "EEFF",
        "frecuencia": "trimestral",
        "tabla": "raw_eeff_line",
        "columna_periodo": "periodo",
        "fondos": ["TRI", "PT", "APO"],
        "columna_fondo": "fondo_key",
        "n_timeline": 4,
        "tab_destino": "eeff",
    },
    {
        "id": "rentroll",
        "label": "Rent Roll",
        "frecuencia": "mensual",
        "tabla": "raw_rent_roll_line",
        "columna_periodo": "periodo",
        "fondos": None,
        "columna_fondo": None,
        "n_timeline": 6,
        "tab_destino": "rentroll",
    },
    {
        "id": "mercado",
        "label": "Mercado Oficinas",
        "frecuencia": "trimestral",
        "tabla": "raw_mercado_oficinas",
        "columna_periodo": "periodo",
        "fondos": None,
        "columna_fondo": None,
        "n_timeline": 4,
        "tab_destino": "mercado",
    },
]


def _periodos_ingestados(con, tipo_cfg: dict) -> dict[str, set[str] | bool]:
    """Para cada período con datos, qué hay: set de fondos (si aplica) o True."""
    tabla = tipo_cfg["tabla"]
    col_periodo = tipo_cfg["columna_periodo"]
    col_fondo = tipo_cfg["columna_fondo"]
    if col_fondo:
        rows = con.execute(
            f"SELECT DISTINCT {col_periodo}, {col_fondo} FROM {tabla} "
            "WHERE superseded_at IS NULL"
        ).fetchall()
        out: dict[str, set[str]] = {}
        for periodo, fondo in rows:
            out.setdefault(periodo, set()).add(fondo)
        return out
    rows = con.execute(
        f"SELECT DISTINCT {col_periodo} FROM {tabla} WHERE superseded_at IS NULL"
    ).fetchall()
    return {periodo: True for (periodo,) in rows}


def _completo(periodo: str, ingestados: dict, tipo_cfg: dict) -> bool:
    valor = ingestados.get(periodo)
    if valor is None:
        return False
    if tipo_cfg["fondos"]:
        return set(tipo_cfg["fondos"]).issubset(valor)
    return bool(valor)


def estado_tipo(con, tipo_cfg: dict, hoy: date) -> dict:
    frecuencia = tipo_cfg["frecuencia"]
    en_curso = _periodo_en_curso(hoy, frecuencia)
    cerrado = _periodo_cerrado(en_curso, frecuencia)

    ingestados = _periodos_ingestados(con, tipo_cfg)
    completos = sorted(p for p in ingestados if _completo(p, ingestados, tipo_cfg))
    ultimo_ingestado = completos[-1] if completos else None

    al_dia = _completo(cerrado, ingestados, tipo_cfg)
    pendiente = None if al_dia else cerrado

    paso = 1 if frecuencia == "mensual" else 3
    n = tipo_cfg["n_timeline"]
    timeline = []
    for i in range(n - 1, -1, -1):
        periodo = _shift_periodo(en_curso, -paso * i)
        if periodo == en_curso:
            estado = "ok" if _completo(periodo, ingestados, tipo_cfg) else "na"
        else:
            estado = "ok" if _completo(periodo, ingestados, tipo_cfg) else "miss"
        timeline.append({"periodo": periodo, "estado": estado})

    return {
        "id": tipo_cfg["id"],
        "label": tipo_cfg["label"],
        "frecuencia": frecuencia,
        "ultimo_ingestado": ultimo_ingestado,
        "pendiente": pendiente,
        "al_dia": al_dia,
        "tab_destino": tipo_cfg["tab_destino"],
        "timeline": timeline,
    }


def estado_ingesta(con, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    return {"tipos": [estado_tipo(con, cfg, hoy) for cfg in CONFIG]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/db/test_estado_ingesta.py -v`
Expected: PASS (all tests from Task 1 and Task 2)

- [ ] **Step 5: Commit**

```bash
git add tools/db/estado_ingesta.py tests/db/test_estado_ingesta.py
git commit -m "feat(ingesta): calcula estado ingestado/pendiente por tipo (eeff/rentroll/mercado)"
```

---

### Task 3: Endpoint `GET /api/estado_ingesta`

**Files:**
- Modify: `scripts/ingesta_server.py`
- Test: `tests/test_ingesta_server_estado.py`

**Interfaces:**
- Consumes: `tools.db.estado_ingesta.estado_ingesta(con, hoy=None) -> dict` (Task 2),
  `tools.db.connection.get_conn_for(path: str)` (existing).
- Produces: route `GET /api/estado_ingesta` returning the `estado_ingesta()` dict as JSON.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingesta_server_estado.py
"""Tests del endpoint /api/estado_ingesta de scripts/ingesta_server.py."""
from __future__ import annotations

import pytest

from tools.db.connection import apply_migrations
from tools.db import estado_ingesta


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(estado_ingesta, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        yield c


def test_estado_ingesta_endpoint_devuelve_3_tipos(client):
    res = client.get("/api/estado_ingesta")
    assert res.status_code == 200
    data = res.get_json()
    ids = {t["id"] for t in data["tipos"]}
    assert ids == {"eeff", "rentroll", "mercado"}
    for tipo in data["tipos"]:
        assert "ultimo_ingestado" in tipo
        assert "pendiente" in tipo
        assert "al_dia" in tipo
        assert "timeline" in tipo
        assert "tab_destino" in tipo
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingesta_server_estado.py -v`
Expected: FAIL with 404 (route doesn't exist) — `assert 404 == 200`

- [ ] **Step 3: Add the route**

In `scripts/ingesta_server.py`, add the import near the other `tools.db` imports (after
line 25, `from tools.db.connection import get_conn_for`):

```python
from tools.db import estado_ingesta  # noqa: E402
```

Add the route (after `serve_page()`, before `get_prompt`):

```python
@app.get("/api/estado_ingesta")
def api_estado_ingesta():
    con = get_conn_for(str(estado_ingesta.DB_PATH))
    try:
        return jsonify(estado_ingesta.estado_ingesta(con))
    finally:
        con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ingesta_server_estado.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/ingesta_server.py tests/test_ingesta_server_estado.py
git commit -m "feat(ingesta): expone GET /api/estado_ingesta"
```

---

### Task 4: Landing view — HTML/CSS + render de cards

**Files:**
- Modify: `web/ingesta.html`

**Interfaces:**
- Consumes: `GET /api/estado_ingesta` (Task 3), response shape
  `{"tipos": [{"id", "label", "frecuencia", "ultimo_ingestado", "pendiente", "al_dia",
  "tab_destino", "timeline": [{"periodo", "estado"}]}]}`.
- Produces: tab button `[data-tab="inicio"]` (active by default), panel `#tab-inicio`,
  function `renderEstadoIngesta(data)` that populates `#inicio-cards`, function
  `loadEstadoIngesta()` that fetches and calls the renderer.

No automated test for this task (pure markup/CSS/rendering — verified visually in
Task 6). This is consistent with the rest of `web/ingesta.html`, which has no frontend
unit tests today; backend behavior is what's tested.

- [ ] **Step 1: Add the "Inicio" tab button**

In `web/ingesta.html`, modify the `.tabs` block (currently lines 137-141):

```html
  <div class="tabs">
    <button class="tab-btn active" data-tab="inicio">Inicio</button>
    <button class="tab-btn" data-tab="eeff">EEFF</button>
    <button class="tab-btn" data-tab="rentroll">Rent Roll</button>
    <button class="tab-btn" data-tab="mercado">Mercado Oficinas</button>
  </div>
```

Remove `active` from the EEFF tab button (was `class="tab-btn active"`, becomes
`class="tab-btn"`) since Inicio is now the default.

- [ ] **Step 2: Remove `active` from the EEFF panel and add the Inicio panel**

Modify line 147, from:
```html
<div id="tab-eeff" class="tab-panel active">
```
to:
```html
<div id="tab-eeff" class="tab-panel">
```

Insert a new panel immediately before the `<!-- ══ TAB EEFF ══ -->` comment (before
current line 146):

```html
<!-- ══════════════════════════ TAB INICIO ══════════════════════════ -->
<div id="tab-inicio" class="tab-panel active">
  <div id="inicio-cards" class="inicio-cards"></div>
</div>

```

- [ ] **Step 3: Add CSS for the cards**

Add to the `<style>` block, right after the existing `.raro-item input[type=checkbox]`
rule (currently line 130, just before `</style>`):

```css
  .inicio-cards {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px; margin-top: 4px;
  }
  .inicio-card {
    background: #fff; border: 1px solid #e5e5e5; border-radius: 4px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06); padding: 18px 20px;
  }
  .inicio-card h3 { margin: 0 0 2px; font-size: 15px; font-weight: 700; color: #2b2b2b; }
  .inicio-card .inicio-subtitle { font-size: 11.5px; color: var(--muted); margin-bottom: 14px; }
  .inicio-stat-row {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 12.5px; margin-bottom: 8px;
  }
  .inicio-stat-row .label { color: var(--muted); }
  .inicio-stat-row .value { font-weight: 700; font-variant-numeric: tabular-nums; }
  .inicio-stat-row .value.ok { color: var(--green); }
  .inicio-stat-row .value.miss { color: var(--err); }
  .inicio-timeline {
    display: flex; gap: 6px; margin: 14px 0; padding-top: 10px; border-top: 1px solid #eee;
  }
  .inicio-tl-item { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; }
  .inicio-tl-dot { width: 11px; height: 11px; border-radius: 50%; }
  .inicio-tl-dot.ok { background: var(--green); }
  .inicio-tl-dot.miss { background: var(--err); }
  .inicio-tl-dot.na { background: #d0d0d0; }
  .inicio-tl-label { font-size: 9.5px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .inicio-card button { width: 100%; }
```

- [ ] **Step 4: Add the render + fetch JS**

Add at the end of the `<script>` block (after the last line, currently
`checkMercadoPeriodoStatus();` around line 1101):

```javascript
// ── TAB INICIO ───────────────────────────────────────────────────────────
function _inicioPeriodoLabel(periodo, frecuencia) {
  const [y, m] = periodo.split('-');
  if (frecuencia === 'trimestral') return `T${{'03':1,'06':2,'09':3,'12':4}[m]} ${y}`;
  const meses = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
  return `${meses[parseInt(m, 10) - 1]} ${y}`;
}

function renderEstadoIngesta(data) {
  const container = document.getElementById('inicio-cards');
  container.innerHTML = '';
  for (const tipo of data.tipos) {
    const card = document.createElement('div');
    card.className = 'inicio-card';

    const timelineHtml = tipo.timeline.map(t => `
      <div class="inicio-tl-item">
        <div class="inicio-tl-dot ${t.estado}"></div>
        <span class="inicio-tl-label">${_inicioPeriodoLabel(t.periodo, tipo.frecuencia)}</span>
      </div>
    `).join('');

    const pendienteHtml = tipo.al_dia
      ? `<span class="value ok">Al día</span>`
      : `<span class="value miss">${_inicioPeriodoLabel(tipo.pendiente, tipo.frecuencia)}</span>`;

    card.innerHTML = `
      <h3>${tipo.label}</h3>
      <div class="inicio-subtitle">${tipo.frecuencia === 'trimestral' ? 'Trimestral' : 'Mensual'}</div>
      <div class="inicio-stat-row">
        <span class="label">Último ingestado</span>
        <span class="value ok">${tipo.ultimo_ingestado ? _inicioPeriodoLabel(tipo.ultimo_ingestado, tipo.frecuencia) : '—'}</span>
      </div>
      <div class="inicio-stat-row">
        <span class="label">Próximo pendiente</span>
        ${pendienteHtml}
      </div>
      <div class="inicio-timeline">${timelineHtml}</div>
      <button data-tab-destino="${tipo.tab_destino}" data-pendiente="${tipo.pendiente || ''}">Ingestar →</button>
    `;
    container.appendChild(card);
  }

  container.querySelectorAll('button[data-tab-destino]').forEach(btn => {
    btn.addEventListener('click', () => {
      const tabDestino = btn.dataset.tabDestino;
      const pendiente = btn.dataset.pendiente;
      document.querySelector(`[data-tab="${tabDestino}"]`).click();
      if (!pendiente) return;
      if (tabDestino === 'eeff') {
        eeffPeriodo.value = pendiente;
        checkEeffPeriodoStatus();
      } else if (tabDestino === 'rentroll') {
        rrPeriodo.value = pendiente;
        checkRrPeriodoStatus();
      } else if (tabDestino === 'mercado') {
        mercadoPeriodo.value = pendiente;
        checkMercadoPeriodoStatus();
      }
    });
  });
}

async function loadEstadoIngesta() {
  const container = document.getElementById('inicio-cards');
  try {
    const res = await fetch('/api/estado_ingesta');
    const data = await res.json();
    renderEstadoIngesta(data);
  } catch (e) {
    container.innerHTML = '<p class="muted">No se pudo cargar el estado de ingesta.</p>';
  }
}

loadEstadoIngesta();
```

- [ ] **Step 5: Commit**

```bash
git add web/ingesta.html
git commit -m "feat(ingesta): landing de estado con cards por tipo de dato"
```

---

### Task 5: Verificación manual en el navegador

**Files:** ninguno (solo verificación, sin cambios de código)

- [ ] **Step 1: Levantar el servidor**

Run: `python -m scripts.ingesta_server`
Expected output: `Ingesta EEFF: http://localhost:8765/ingesta` y el servidor Flask
corriendo sin trazas de error.

- [ ] **Step 2: Abrir en el navegador y verificar la landing**

Abrir `http://localhost:8765/ingesta`. Verificar:
- La pestaña "Inicio" está activa por defecto y muestra 3 cards (EEFF, Rent Roll,
  Mercado Oficinas).
- Cada card muestra último ingestado, próximo pendiente (o "Al día"), y una fila de
  puntos de colores (verde/rojo/gris).
- Los valores mostrados son coherentes con lo que hay realmente en
  `memory/agente_toesca_v2.db` (contrastar con lo que muestran los "periodo check" de
  cada tab al elegir el período correspondiente).

- [ ] **Step 3: Verificar la navegación "Ingestar →"**

Click en "Ingestar →" de la card EEFF: confirmar que cambia al tab EEFF y que el
selector de período queda en el valor pendiente (si había uno pendiente), disparando el
badge de "ya ingestado" si corresponde. Repetir para Rent Roll y Mercado Oficinas.

- [ ] **Step 4: Correr toda la suite de tests**

Run: `python -m pytest tests/ -v`
Expected: todos los tests pasan, incluyendo los nuevos de
`tests/db/test_estado_ingesta.py` y `tests/test_ingesta_server_estado.py`, sin romper
los existentes (`test_ingesta_server_mercado.py`, etc.).

- [ ] **Step 5: Detener el servidor**

Terminar el proceso de `python -m scripts.ingesta_server` (Ctrl+C en la terminal donde
corre, o cerrar esa terminal). No requiere commit — este task es solo verificación.
