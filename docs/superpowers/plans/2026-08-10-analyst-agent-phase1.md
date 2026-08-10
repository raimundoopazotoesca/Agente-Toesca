# Analyst Agent — Fase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a semantic layer (YAML metric/entity catalog), structured intent
resolution, in-memory conversation state, a verified-query repository, and
deterministic result checks in front of `tools/db_chat.py`'s existing
SQL-generation flow — without touching its SQL validation, execution, or LLM
provider fallback.

**Architecture:** New `semantic/` YAML catalog (loaded once, cached in
memory) + new `tools/analyst/` package (loader, entity resolver, intent
extraction, conversation state, result checks) that `db_chat.answer()` calls
before/after its existing SQL generation and execution steps. Existing
`_validate_sql`/`_run_sql`/provider chain are untouched.

**Tech Stack:** Python 3, `jsonschema` (new dependency, for validating
YAML against JSON Schema), `PyYAML` (already used elsewhere in repo — verify
in Task 1), `pytest`, existing `openai` client / provider chain from
`tools/db_chat.py`.

## Global Constraints

- Never modify `_validate_sql`, `_run_sql`, `_PROVIDER_LIST`, or the Flask
  auth in `scripts/ingesta_server.py` — spec requires these stay as-is.
- `derived_kpi` stays a results cache only; semantic YAML never gets written
  back into it, and no code in this plan writes to `derived_kpi`.
- Any metric/entity fact placed in YAML must cite its source (migration
  file, wiki page) in a `notes`/comment — no invented business definitions.
  If a definition can't be confirmed, mark it `definicion_pendiente: true`
  and do not fabricate a formula.
- All new Python files are cross-platform (repo runs on Windows per
  `CLAUDE.md`) — no POSIX-only path assumptions.
- Spanish stays in user-facing strings and YAML `business_definition`
  fields, consistent with the rest of the codebase.

---

## File Structure

```
semantic/
  metrics/vacancia.yaml
  metrics/noi.yaml
  metrics/dividend_yield.yaml
  metrics/tir.yaml
  metrics/tasa_arriendo.yaml
  entities.yaml
  relationships.yaml
  synonyms.yaml
  domains.yaml
  schema/metric.schema.json
  schema/entity.schema.json

tools/analyst/
  __init__.py
  semantic_loader.py
  entity_resolver.py
  conversation_state.py
  intent.py
  result_checks.py
  verified_queries/
    noi_pt_mensual.yaml
    vacancia_activo_snapshot.yaml
    dy_amort_serie.yaml

tests/analyst/
  __init__.py
  test_semantic_loader.py
  test_entity_resolver.py
  test_conversation_state.py
  test_result_checks.py
  test_intent.py

tests/eval/
  questions.yaml
  run_eval.py

tools/db_chat.py   # modified: wire intent/entity/result_checks into answer()
requirements.txt (or equivalent)  # add jsonschema if not present
```

---

## Task 1: Semantic YAML schema + `semantic_loader.py`

**Files:**
- Create: `semantic/schema/metric.schema.json`
- Create: `semantic/schema/entity.schema.json`
- Create: `semantic/metrics/vacancia.yaml`
- Create: `semantic/metrics/noi.yaml`
- Create: `semantic/metrics/dividend_yield.yaml`
- Create: `semantic/metrics/tir.yaml`
- Create: `semantic/metrics/tasa_arriendo.yaml`
- Create: `semantic/entities.yaml`
- Create: `semantic/relationships.yaml`
- Create: `semantic/synonyms.yaml`
- Create: `semantic/domains.yaml`
- Create: `tools/analyst/__init__.py`
- Create: `tools/analyst/semantic_loader.py`
- Test: `tests/analyst/test_semantic_loader.py`

**Interfaces:**
- Produces: `tools/analyst/semantic_loader.py::load_semantic_catalog(semantic_dir: Path = SEMANTIC_DIR) -> SemanticCatalog`
  where `SemanticCatalog` is a `dataclass` with fields
  `metrics: dict[str, dict]` (keyed by `name`), `entities: dict`,
  `relationships: dict`, `synonyms: dict`, `domains: dict`.
  Raises `SemanticValidationError(message: str)` on schema failure.
- Produces: `tools/analyst/semantic_loader.py::SEMANTIC_DIR` = `Path(__file__).resolve().parents[2] / "semantic"`.

- [ ] **Step 1: Check `jsonschema` and `PyYAML` availability**

Run: `python -c "import jsonschema, yaml; print('ok')"`

If it fails, add `jsonschema` to the project's dependency file (find it
first — check for `requirements.txt` or `pyproject.toml` at repo root with
`ls requirements.txt pyproject.toml 2>/dev/null` — and install with
`pip install jsonschema` in the project's environment). `PyYAML` is already
a transitive dependency (used by other tools) — confirm via the same
import check; if missing, add it too.

- [ ] **Step 2: Write `semantic/schema/metric.schema.json`**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "metric",
  "type": "object",
  "required": ["name", "business_definition", "formula", "unit", "grain",
               "aggregation", "time_behavior", "source", "relevant_tables",
               "synonyms"],
  "properties": {
    "name": {"type": "string"},
    "business_definition": {"type": "string"},
    "formula": {"type": "string"},
    "unit": {"type": "string"},
    "grain": {"type": "string"},
    "aggregation": {"type": "string"},
    "time_behavior": {"type": "string"},
    "source": {"type": "object"},
    "relevant_tables": {"type": "array", "items": {"type": "string"}},
    "allowed_dimensions": {"type": "array", "items": {"type": "string"}},
    "synonyms": {"type": "array", "items": {"type": "string"}},
    "invariants": {"type": "array", "items": {"type": "string"}},
    "notes": {"type": "string"},
    "definicion_pendiente": {"type": "boolean"}
  },
  "additionalProperties": false
}
```

- [ ] **Step 3: Write `semantic/schema/entity.schema.json`**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "entities_file",
  "type": "object",
  "required": ["fondos", "activos", "sociedades"],
  "properties": {
    "fondos": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "required": ["nombre"],
        "properties": {
          "nombre": {"type": "string"},
          "fondo_padre": {"type": ["string", "null"]},
          "participacion_en_padre": {"type": ["number", "null"]}
        }
      }
    },
    "activos": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "required": ["nombre", "fondo_key"],
        "properties": {
          "nombre": {"type": "string"},
          "fondo_key": {"type": "string"},
          "categoria": {"type": "string"},
          "sociedad_key": {"type": ["string", "null"]},
          "vigente": {"type": "boolean"}
        }
      }
    },
    "sociedades": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "required": ["nombre", "fondo_key"],
        "properties": {
          "nombre": {"type": "string"},
          "fondo_key": {"type": "string"}
        }
      }
    }
  },
  "additionalProperties": false
}
```

- [ ] **Step 4: Write `semantic/metrics/vacancia.yaml`**

```yaml
name: vacancia_pct
business_definition: >
  Porcentaje de superficie (m2 GLA) vacante respecto del total arrendable,
  excluyendo estacionamientos. Unidad vacante = arrendatario = "vacante"
  (case-insensitive) en raw_rent_roll_line.
formula: m2_vacantes / m2_gla
unit: pct_0_100
grain: activo-mes
aggregation: weighted_by_participacion
time_behavior: month_end_snapshot
source:
  primary_view: v_vacancia_activo
  by_type_view: v_vacancia_activo_tipo
  fund_rollups:
    PT: v_vacancia_pt_consolidado_tipo
    Apo: v_vacancia_apoquindo_consolidado_tipo
  weighted_view: v_vacancia_activo_efectivo
  citation: "tools/db/migrations/077_fix_vacancia_case.sql:23-91; wiki/db.md:365-452"
relevant_tables: [raw_rent_roll_line, dim_activo]
allowed_dimensions: [activo, fondo, tipo_activo, periodo]
synonyms: [vacancia, ocupacion, ocupación, occupancy, "tasa de ocupacion"]
invariants:
  - "0 <= value <= 100"
notes: >
  Estacionamiento excluido de los totales. Bug de case-sensitivity en
  arrendatario='vacante' corregido 2026-08-03 (migracion 077).
```

- [ ] **Step 5: Write `semantic/metrics/noi.yaml`**

```yaml
name: noi
business_definition: >
  Resultado operacional neto: SUM(monto_clp) de raw_er_activo_line con signo
  ya aplicado (ingresos positivos, gastos negativos), filtrado por periodo y
  superseded_at IS NULL. Variantes: noi_mes (un mes) y noi_u12m (ultimos 12
  meses).
formula: "SUM(monto_clp) FROM raw_er_activo_line WHERE periodo IN <ventana> AND superseded_at IS NULL"
unit: clp_or_uf
grain: activo-mes
aggregation: sum
time_behavior: rolling_12m_or_month
source:
  table: raw_er_activo_line
  citation: "wiki/kpis_noi_cap_rate_apo.md:10-49"
  derived_kpi_cache: {kpi: ["noi_u12m", "noi_mes"], formula: raw_er_noi_v1}
relevant_tables: [raw_er_activo_line]
allowed_dimensions: [activo, fondo, periodo]
synonyms: [noi, "resultado operacional neto", "ingreso operacional"]
notes: >
  TRAMPA DE UNIDAD: para el fondo Apo, raw_er_activo_line.monto_clp esta en
  UF, no en CLP (wiki/kpis_noi_cap_rate_apo.md:23-27). Nunca sumar NOI de Apo
  con NOI de otro fondo sin convertir unidades primero.
```

- [ ] **Step 6: Write `semantic/metrics/dividend_yield.yaml`**

```yaml
name: dividend_yield
business_definition: >
  DY_libro = SUM(dividendos_u12m) / VNA_contable_corte.
  DY_bursatil = SUM(dividendos_u12m) / VNA_bursatil_corte.
  DY_amort = (dividendos_u12m + amort_u12m) / VNA_{bursatil|contable}_corte;
  para Apo el denominador es capital_suscrito_por_cuota en vez de VNA.
formula: "dividendos_u12m / VNA_corte  (variante amort suma amortizacion al numerador)"
unit: pct_0_100
grain: fondo-serie-mes
aggregation: ratio
time_behavior: rolling_12m
source:
  citation: "wiki/kpis_rentabilidad_fondos.md:103-153"
  derived_kpi_cache: {kpi: ["dy", "dy_amort"], formula: ["dy_v2", "dividend_yield_con_amort_capital_v1"]}
relevant_tables: [raw_dividendo, raw_valor_cuota_line, raw_amortizacion]
allowed_dimensions: [fondo, serie, periodo]
synonyms: ["dividend yield", "dy", "rentabilidad por dividendos"]
notes: >
  Filtros de dividendos: tipo='dividendo', superseded_at IS NULL,
  monto_uf_cuota > 0. Apo usa capital_suscrito_por_cuota como denominador en
  dy_amort, no VNA — no generalizar la formula de TRI/PT a Apo sin ajustar.
```

- [ ] **Step 7: Write `semantic/metrics/tir.yaml`**

```yaml
name: tir_desde_inicio
business_definition: >
  TIR (XIRR) desde el inicio del fondo/serie. Dos metodos segun cantidad de
  aportes: series TRI (multi-aporte) usan divisor por cuota; PT/Apo
  (aporte unico) usan metodo agregado sin divisor. El valor terminal SIEMPRE
  viene de raw_valor_cuota_line.precio_uf, nunca de raw_ar_event_line.
formula: "XIRR(flujos_aportes_y_dividendos, valor_terminal=raw_valor_cuota_line.precio_uf)"
unit: pct_annualized
grain: fondo-serie
aggregation: xirr
time_behavior: since_inception
source:
  citation: "wiki/tir_contable_desde_inicio.md; skills/real-estate-finance-expert/scripts/tir.py"
  derived_kpi_cache: {kpi: ["tir_contable_desde_inicio", "tir_bursatil_desde_inicio"]}
relevant_tables: [raw_ar_event, raw_dividendo, raw_valor_cuota_line]
allowed_dimensions: [fondo, serie]
synonyms: ["tir", "tir desde inicio", "rentabilidad desde inicio", "irr"]
notes: >
  PT y Apo usan _calcular_tir_agregado (aporte unico, sin divisor por
  cuota); las series de TRI usan _calcular_tir_por_cuota. No mezclar los dos
  metodos entre fondos.
```

- [ ] **Step 8: Write `semantic/metrics/tasa_arriendo.yaml`**

```yaml
name: tasa_arriendo
business_definition: >
  Tasa de arriendo ajustada = ingresos_u12m / denom_uf, donde denom_uf es el
  mismo denominador usado en cap rate implicito (patrimonio o market cap +
  deuda financiera neta + caja minima, en UF).
formula: "ingresos_u12m / denom_uf"
unit: pct_annualized
grain: activo-fondo
aggregation: ratio
time_behavior: rolling_12m
source:
  citation: "wiki/kpis_noi_cap_rate_apo.md secciones 4, 8, 9 (lineas 84-86, 182-183, 263)"
relevant_tables: [raw_er_activo_line]
allowed_dimensions: [activo, fondo]
synonyms: ["tasa de arriendo", "tasa de arriendo ajustada"]
definicion_pendiente: false
notes: >
  No hay vista confirmada de renta UF/m2 a nivel unidad de rent roll —
  raw_rent_roll_line.renta_uf existe pero no hay formula UF/m2 documentada
  en wiki. Si se pregunta por UF/m2 de rent roll (no la tasa de arriendo
  ajustada de fondo/activo), responder que la definicion esta pendiente de
  validar, no inventarla.
```

- [ ] **Step 9: Write `semantic/entities.yaml`**

Populate from `dim_fondo`/`dim_activo`/`dim_sociedad` facts already quoted
in `tools/db_chat.py:172-231` (do not invent new entities):

```yaml
fondos:
  TRI:
    nombre: "Toesca Rentas Inmobiliarias Fondo de Inversion"
    fondo_padre: null
  PT:
    nombre: "Fondo Toesca Rentas Inmobiliarias PT"
    fondo_padre: TRI
    participacion_en_padre: 0.3333
  Apo:
    nombre: "Fondo Toesca Rentas Inmob Apoquindo"
    fondo_padre: TRI
    participacion_en_padre: 0.30

activos:
  "Viña Centro": {nombre: "Mall Paseo Viña Centro", fondo_key: TRI, categoria: "Centros Comerciales"}
  "Mall Curicó": {nombre: "Power Center Paseo Curicó", fondo_key: TRI, categoria: "Centros Comerciales"}
  "INMOSA": {nombre: "Residencias adulto mayor (Senior Assist)", fondo_key: TRI, categoria: "Residencias"}
  "Apo3001": {nombre: "Apoquindo 3001", fondo_key: TRI, sociedad_key: "Chañarcillo", categoria: "Oficinas"}
  "Sucden": {nombre: "Bodegas Maipu", fondo_key: TRI, sociedad_key: "Chañarcillo", categoria: "Industrial"}
  "Torre A": {nombre: "Torre A Parque Titanium", fondo_key: PT, categoria: "Oficinas"}
  "Boulevard": {nombre: "Boulevard Parque Titanium", fondo_key: PT, categoria: "Oficinas"}
  "Parking PT": {nombre: "Estacionamientos PT (SABA)", fondo_key: PT, categoria: "Parking"}
  "Apo4501": {nombre: "Apoquindo 4501", fondo_key: Apo, categoria: "Oficinas"}
  "Apo4700": {nombre: "Apoquindo 4700", fondo_key: Apo, categoria: "Oficinas"}

sociedades:
  "Chañarcillo": {nombre: "Chañarcillo Ltda", fondo_key: TRI}
```

- [ ] **Step 10: Write `semantic/relationships.yaml`**

```yaml
jerarquia:
  - fondo: TRI
    subfondos: [PT, Apo]
notas_ambiguedad:
  - clave: "Apo3001"
    advertencia: >
      Apo3001 es un activo del fondo TRI, NO del fondo Apo, a pesar del
      nombre. Ver CLAUDE.md tabla de claves ambiguas Apoquindo.
  - clave: "Apoquindo (a secas)"
    advertencia: >
      Ambiguo entre el fondo Apo y el activo consolidado 'Apoquindo'
      (= Apo4501+Apo4700) usado en derived_kpi para NOI/vacancia.
```

- [ ] **Step 11: Write `semantic/synonyms.yaml`**

Migrate every alias line from `tools/db_chat.py:188-231` verbatim (fondo
aliases + activo aliases) into structured form:

```yaml
fondos:
  TRI: ["Rentas Inmobiliarias", "Rentas", "TRI", "fondo madre"]
  PT: ["PT", "Parque Titanium", "Fondo PT", "Rentas PT"]
  Apo: ["Apo", "Apoquindo (el fondo)", "Fondo Apoquindo", "APO"]
activos:
  "Viña Centro": ["Vina", "Viña", "VC", "Paseo Viña", "Mall Viña"]
  "Mall Curicó": ["Curicó", "Curico", "Power Center", "PC Curicó"]
  "Apo3001": ["Apo 3001", "3001", "Apoquindo 3001", "Chañarcillo (Apo3001)"]
  "Apo4501": ["Apo 4501", "Apoquindo 4501"]
  "Apo4700": ["Apo 4700", "Apoquindo 4700"]
  "Sucden": ["Sucden", "Bodegas Maipú", "Sucden Chile"]
  "INMOSA": ["INMOSA", "Senior Assist", "residencias"]
  "Torre A": ["Torre A", "PT Torre A", "PT Oficinas"]
  "Boulevard": ["Boulevard", "CDC", "Centro Convenciones", "PT Comercial"]
```

- [ ] **Step 12: Write `semantic/domains.yaml`**

```yaml
leasing:
  metrics: [vacancia_pct, tasa_arriendo]
  tables: [raw_rent_roll_line, dim_activo]
financiero:
  metrics: [noi, dividend_yield, tir_desde_inicio]
  tables: [raw_er_activo_line, raw_dividendo, raw_valor_cuota_line, raw_ar_event, raw_amortizacion]
```

- [ ] **Step 13: Write the failing test**

```python
# tests/analyst/test_semantic_loader.py
import pytest
from tools.analyst.semantic_loader import load_semantic_catalog, SemanticValidationError, SEMANTIC_DIR


def test_loads_real_catalog():
    catalog = load_semantic_catalog()
    assert "vacancia_pct" in catalog.metrics
    assert catalog.metrics["vacancia_pct"]["unit"] == "pct_0_100"
    assert "TRI" in catalog.entities["fondos"]
    assert catalog.synonyms["fondos"]["PT"] == ["PT", "Parque Titanium", "Fondo PT", "Rentas PT"]


def test_invalid_metric_yaml_raises(tmp_path):
    bad_dir = tmp_path / "semantic"
    (bad_dir / "metrics").mkdir(parents=True)
    (bad_dir / "schema").mkdir()
    (SEMANTIC_DIR / "schema" / "metric.schema.json").read_text(encoding="utf-8")
    import shutil
    shutil.copy(SEMANTIC_DIR / "schema" / "metric.schema.json", bad_dir / "schema" / "metric.schema.json")
    shutil.copy(SEMANTIC_DIR / "schema" / "entity.schema.json", bad_dir / "schema" / "entity.schema.json")
    (bad_dir / "metrics" / "broken.yaml").write_text("name: broken\n", encoding="utf-8")
    (bad_dir / "entities.yaml").write_text("fondos: {}\nactivos: {}\nsociedades: {}\n", encoding="utf-8")
    (bad_dir / "relationships.yaml").write_text("{}\n", encoding="utf-8")
    (bad_dir / "synonyms.yaml").write_text("{}\n", encoding="utf-8")
    (bad_dir / "domains.yaml").write_text("{}\n", encoding="utf-8")
    with pytest.raises(SemanticValidationError):
        load_semantic_catalog(semantic_dir=bad_dir)
```

- [ ] **Step 14: Run test to verify it fails**

Run: `pytest tests/analyst/test_semantic_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.analyst.semantic_loader'`

- [ ] **Step 15: Implement `tools/analyst/__init__.py` (empty) and `tools/analyst/semantic_loader.py`**

```python
"""Loads and validates the YAML semantic layer (semantic/) into memory."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import validate, ValidationError

SEMANTIC_DIR = Path(__file__).resolve().parents[2] / "semantic"


class SemanticValidationError(Exception):
    pass


@dataclass
class SemanticCatalog:
    metrics: dict[str, dict] = field(default_factory=dict)
    entities: dict[str, Any] = field(default_factory=dict)
    relationships: dict[str, Any] = field(default_factory=dict)
    synonyms: dict[str, Any] = field(default_factory=dict)
    domains: dict[str, Any] = field(default_factory=dict)


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_schema(schema_dir: Path, name: str) -> dict:
    with (schema_dir / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


_CACHE: dict[Path, SemanticCatalog] = {}


def load_semantic_catalog(semantic_dir: Path = SEMANTIC_DIR) -> SemanticCatalog:
    """Loads all semantic/*.yaml files, validates them, caches by directory."""
    if semantic_dir in _CACHE:
        return _CACHE[semantic_dir]

    schema_dir = semantic_dir / "schema"
    metric_schema = _load_schema(schema_dir, "metric.schema.json")
    entity_schema = _load_schema(schema_dir, "entity.schema.json")

    metrics: dict[str, dict] = {}
    metrics_dir = semantic_dir / "metrics"
    for metric_file in sorted(metrics_dir.glob("*.yaml")):
        data = _load_yaml(metric_file)
        try:
            validate(instance=data, schema=metric_schema)
        except ValidationError as exc:
            raise SemanticValidationError(f"{metric_file}: {exc.message}") from exc
        metrics[data["name"]] = data

    entities = _load_yaml(semantic_dir / "entities.yaml")
    try:
        validate(instance=entities, schema=entity_schema)
    except ValidationError as exc:
        raise SemanticValidationError(f"entities.yaml: {exc.message}") from exc

    catalog = SemanticCatalog(
        metrics=metrics,
        entities=entities,
        relationships=_load_yaml(semantic_dir / "relationships.yaml"),
        synonyms=_load_yaml(semantic_dir / "synonyms.yaml"),
        domains=_load_yaml(semantic_dir / "domains.yaml"),
    )
    _CACHE[semantic_dir] = catalog
    return catalog
```

- [ ] **Step 16: Run test to verify it passes**

Run: `pytest tests/analyst/test_semantic_loader.py -v`
Expected: PASS (2 tests)

- [ ] **Step 17: Commit**

```bash
git add semantic/ tools/analyst/__init__.py tools/analyst/semantic_loader.py tests/analyst/test_semantic_loader.py
git commit -m "feat(analyst): add semantic YAML catalog + loader with schema validation"
```

---

## Task 2: `entity_resolver.py`

**Files:**
- Create: `tools/analyst/entity_resolver.py`
- Test: `tests/analyst/test_entity_resolver.py`

**Interfaces:**
- Consumes: `tools.analyst.semantic_loader.load_semantic_catalog() -> SemanticCatalog`
  (`.synonyms`, `.entities`)
- Produces: `tools/analyst/entity_resolver.py::resolve_entity(text: str, kind: str, catalog: SemanticCatalog | None = None) -> str | None`
  where `kind` is `"fondo"` or `"activo"`. Returns the canonical key
  (e.g. `"Apo"`, `"Viña Centro"`) or `None` if no match. Matching is
  case-insensitive, accent-insensitive, exact match on canonical key or any
  listed synonym (no fuzzy/partial matching in this phase).

- [ ] **Step 1: Write the failing test**

```python
# tests/analyst/test_entity_resolver.py
from tools.analyst.entity_resolver import resolve_entity


def test_resolves_fondo_alias():
    assert resolve_entity("APO", "fondo") == "Apo"
    assert resolve_entity("Parque Titanium", "fondo") == "PT"
    assert resolve_entity("fondo madre", "fondo") == "TRI"


def test_resolves_activo_alias():
    assert resolve_entity("Vina", "activo") == "Viña Centro"
    assert resolve_entity("Power Center", "activo") == "Mall Curicó"
    assert resolve_entity("3001", "activo") == "Apo3001"


def test_apo3001_belongs_to_tri_not_apo():
    from tools.analyst.semantic_loader import load_semantic_catalog
    catalog = load_semantic_catalog()
    assert catalog.entities["activos"]["Apo3001"]["fondo_key"] == "TRI"


def test_no_match_returns_none():
    assert resolve_entity("activo inexistente xyz", "activo") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/analyst/test_entity_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `tools/analyst/entity_resolver.py`**

```python
"""Resolves free-text mentions of funds/assets to their canonical keys
using semantic/synonyms.yaml and semantic/entities.yaml."""
from __future__ import annotations

import unicodedata

from tools.analyst.semantic_loader import SemanticCatalog, load_semantic_catalog

_KIND_TO_SECTION = {"fondo": "fondos", "activo": "activos"}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.strip().lower()


def resolve_entity(text: str, kind: str, catalog: SemanticCatalog | None = None) -> str | None:
    if kind not in _KIND_TO_SECTION:
        raise ValueError(f"kind debe ser 'fondo' o 'activo', recibido: {kind!r}")
    catalog = catalog or load_semantic_catalog()
    section = _KIND_TO_SECTION[kind]
    entities = catalog.entities.get(section, {})
    synonyms = catalog.synonyms.get(section, {})
    needle = _normalize(text)

    for canonical_key in entities:
        if _normalize(canonical_key) == needle:
            return canonical_key

    for canonical_key, alias_list in synonyms.items():
        for alias in alias_list:
            if _normalize(alias) == needle:
                return canonical_key

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/analyst/test_entity_resolver.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/entity_resolver.py tests/analyst/test_entity_resolver.py
git commit -m "feat(analyst): add entity resolver over semantic synonyms catalog"
```

---

## Task 3: `conversation_state.py`

**Files:**
- Create: `tools/analyst/conversation_state.py`
- Test: `tests/analyst/test_conversation_state.py`

**Interfaces:**
- Produces:
  `tools/analyst/conversation_state.py::get_state(session_id: str) -> dict`
  (returns `{"last_metric": None, "last_entities": {}, "last_period": None, "last_analysis_type": None}` if unseen)
  `tools/analyst/conversation_state.py::update_state(session_id: str, **fields) -> None`
  `tools/analyst/conversation_state.py::clear_state(session_id: str) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/analyst/test_conversation_state.py
from tools.analyst.conversation_state import get_state, update_state, clear_state


def test_unseen_session_returns_defaults():
    clear_state("test-session-1")
    state = get_state("test-session-1")
    assert state == {
        "last_metric": None,
        "last_entities": {},
        "last_period": None,
        "last_analysis_type": None,
    }


def test_update_and_retrieve():
    clear_state("test-session-2")
    update_state("test-session-2", last_metric="vacancia_pct", last_entities={"activo": "Torre A"})
    state = get_state("test-session-2")
    assert state["last_metric"] == "vacancia_pct"
    assert state["last_entities"] == {"activo": "Torre A"}
    assert state["last_period"] is None


def test_sessions_are_isolated():
    clear_state("test-session-3a")
    clear_state("test-session-3b")
    update_state("test-session-3a", last_metric="noi")
    assert get_state("test-session-3b")["last_metric"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/analyst/test_conversation_state.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `tools/analyst/conversation_state.py`**

```python
"""In-memory conversation state, keyed by session_id, for the Flask process.

Lost on server restart by design (confirmed acceptable for daily internal
use — see docs/superpowers/specs/2026-08-10-analyst-agent-phase1-design.md).
"""
from __future__ import annotations

from typing import Any

_DEFAULTS: dict[str, Any] = {
    "last_metric": None,
    "last_entities": {},
    "last_period": None,
    "last_analysis_type": None,
}

_STATE: dict[str, dict[str, Any]] = {}


def get_state(session_id: str) -> dict[str, Any]:
    if session_id not in _STATE:
        return dict(_DEFAULTS)
    return dict(_STATE[session_id])


def update_state(session_id: str, **fields: Any) -> None:
    current = _STATE.setdefault(session_id, dict(_DEFAULTS))
    current.update(fields)


def clear_state(session_id: str) -> None:
    _STATE.pop(session_id, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/analyst/test_conversation_state.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/conversation_state.py tests/analyst/test_conversation_state.py
git commit -m "feat(analyst): add in-memory per-session conversation state"
```

---

## Task 4: `result_checks.py`

**Files:**
- Create: `tools/analyst/result_checks.py`
- Test: `tests/analyst/test_result_checks.py`

**Interfaces:**
- Consumes: `SemanticCatalog.metrics[metric_name]["invariants"]` (list of
  strings like `"0 <= value <= 100"`), produced by Task 1.
- Produces:
  `tools/analyst/result_checks.py::check_result(metric_name: str, value: float, catalog: SemanticCatalog | None = None) -> CheckResult`
  where `CheckResult` is a `dataclass` with `passed: bool`, `violated: list[str]`.
  Only supports invariants of the exact forms `"X <= value <= Y"` and
  `"value >= X"` / `"value <= X"` (numeric bounds) — this phase does not
  build a general expression evaluator.

- [ ] **Step 1: Write the failing test**

```python
# tests/analyst/test_result_checks.py
from tools.analyst.result_checks import check_result


def test_vacancia_within_bounds_passes():
    result = check_result("vacancia_pct", 45.0)
    assert result.passed is True
    assert result.violated == []


def test_vacancia_over_100_fails():
    result = check_result("vacancia_pct", 134.0)
    assert result.passed is False
    assert "0 <= value <= 100" in result.violated


def test_metric_without_invariants_always_passes():
    result = check_result("noi", -50000.0)
    assert result.passed is True


def test_unknown_metric_raises():
    import pytest
    with pytest.raises(KeyError):
        check_result("metrica_inexistente", 1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/analyst/test_result_checks.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `tools/analyst/result_checks.py`**

```python
"""Deterministic sanity checks over query results, using invariants
declared in semantic/metrics/*.yaml. Intentionally supports only simple
numeric-bound expressions in this phase — no general expression evaluator."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from tools.analyst.semantic_loader import SemanticCatalog, load_semantic_catalog

_RANGE_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*<=\s*value\s*<=\s*(-?\d+(?:\.\d+)?)\s*$")
_GE_RE = re.compile(r"^\s*value\s*>=\s*(-?\d+(?:\.\d+)?)\s*$")
_LE_RE = re.compile(r"^\s*value\s*<=\s*(-?\d+(?:\.\d+)?)\s*$")


@dataclass
class CheckResult:
    passed: bool
    violated: list[str] = field(default_factory=list)


def _invariant_holds(invariant: str, value: float) -> bool:
    m = _RANGE_RE.match(invariant)
    if m:
        low, high = float(m.group(1)), float(m.group(2))
        return low <= value <= high
    m = _GE_RE.match(invariant)
    if m:
        return value >= float(m.group(1))
    m = _LE_RE.match(invariant)
    if m:
        return value <= float(m.group(1))
    raise ValueError(f"Invariante no soportado en esta fase: {invariant!r}")


def check_result(metric_name: str, value: float, catalog: SemanticCatalog | None = None) -> CheckResult:
    catalog = catalog or load_semantic_catalog()
    metric = catalog.metrics[metric_name]  # KeyError si no existe, intencional
    invariants = metric.get("invariants", [])
    violated = [inv for inv in invariants if not _invariant_holds(inv, value)]
    return CheckResult(passed=not violated, violated=violated)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/analyst/test_result_checks.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/result_checks.py tests/analyst/test_result_checks.py
git commit -m "feat(analyst): add deterministic result invariant checks"
```

---

## Task 5: `verified_queries/` repository + lookup

**Files:**
- Create: `tools/analyst/verified_queries/noi_pt_mensual.yaml`
- Create: `tools/analyst/verified_queries/vacancia_activo_snapshot.yaml`
- Create: `tools/analyst/verified_queries/dy_amort_serie.yaml`
- Create: `tools/analyst/verified_queries_repo.py`
- Test: `tests/analyst/test_verified_queries_repo.py`

**Interfaces:**
- Produces:
  `tools/analyst/verified_queries_repo.py::find_similar(question: str, top_k: int = 1, repo_dir: Path | None = None) -> list[dict]`
  Each returned dict has keys `question`, `intent`, `sql`, `notes`, `score`
  (float, higher = more similar). Similarity = token-overlap ratio
  (`len(intersection) / len(union)` of lowercased word sets) — no
  embeddings in this phase, per spec.

- [ ] **Step 1: Write the 3 verified-query YAML files**

```yaml
# tools/analyst/verified_queries/noi_pt_mensual.yaml
question: "cuanto fue el NOI del fondo PT en enero 2024?"
intent: noi_mes
entities: {fondo: PT}
sql: >
  SELECT kpi, valor, periodo FROM derived_kpi
  WHERE entidad_tipo='fondo' AND entidad_key='PT' AND kpi='noi_mes'
    AND periodo='2024-01'
notes: "Usa derived_kpi cacheado; formula raw_er_noi_v1. Ver wiki/kpis_noi_cap_rate_apo.md."
```

```yaml
# tools/analyst/verified_queries/vacancia_activo_snapshot.yaml
question: "vacancia de Viña Centro en el ultimo periodo"
intent: vacancia_snapshot
entities: {activo: "Viña Centro"}
sql: >
  SELECT * FROM v_vacancia_activo
  WHERE activo_key='Viña Centro'
  ORDER BY periodo DESC LIMIT 1
notes: "v_vacancia_activo ya excluye estacionamientos y corrige el bug de case de 'vacante' (migracion 077)."
```

```yaml
# tools/analyst/verified_queries/dy_amort_serie.yaml
question: "dividend yield con amortizacion de la serie A de TRI"
intent: dy_amort
entities: {fondo: TRI, serie: A}
sql: >
  SELECT kpi, valor, periodo FROM derived_kpi
  WHERE entidad_tipo='serie' AND entidad_key='TRI-A' AND kpi='dy_amort'
  ORDER BY periodo DESC LIMIT 1
notes: "formula dividend_yield_con_amort_capital_v1. Para Apo el denominador cambia (ver metrics/dividend_yield.yaml notes)."
```

- [ ] **Step 2: Write the failing test**

```python
# tests/analyst/test_verified_queries_repo.py
from tools.analyst.verified_queries_repo import find_similar


def test_finds_close_match():
    results = find_similar("cual fue el NOI de PT en enero 2024")
    assert results
    assert results[0]["intent"] == "noi_mes"
    assert results[0]["score"] > 0.3


def test_no_match_returns_empty_or_low_score():
    results = find_similar("algo totalmente distinto sobre el clima")
    assert results == [] or results[0]["score"] < 0.2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/analyst/test_verified_queries_repo.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement `tools/analyst/verified_queries_repo.py`**

```python
"""Verified-query lookup: lexical token-overlap similarity over
tools/analyst/verified_queries/*.yaml. No embeddings in this phase."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

VERIFIED_QUERIES_DIR = Path(__file__).resolve().parent / "verified_queries"

_WORD_RE = re.compile(r"[a-záéíóúñ0-9]+", re.IGNORECASE)


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _load_all(repo_dir: Path) -> list[dict]:
    entries = []
    for path in sorted(repo_dir.glob("*.yaml")):
        with path.open("r", encoding="utf-8") as fh:
            entries.append(yaml.safe_load(fh))
    return entries


def find_similar(question: str, top_k: int = 1, repo_dir: Path | None = None) -> list[dict]:
    repo_dir = repo_dir or VERIFIED_QUERIES_DIR
    query_tokens = _tokenize(question)
    scored = []
    for entry in _load_all(repo_dir):
        candidate_tokens = _tokenize(entry["question"])
        union = query_tokens | candidate_tokens
        overlap = query_tokens & candidate_tokens
        score = len(overlap) / len(union) if union else 0.0
        scored.append({**entry, "score": score})
    scored.sort(key=lambda e: e["score"], reverse=True)
    return [e for e in scored[:top_k] if e["score"] > 0]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/analyst/test_verified_queries_repo.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add tools/analyst/verified_queries/ tools/analyst/verified_queries_repo.py tests/analyst/test_verified_queries_repo.py
git commit -m "feat(analyst): add verified-query repository with lexical similarity lookup"
```

---

## Task 6: `intent.py`

**Files:**
- Create: `tools/analyst/intent.py`
- Test: `tests/analyst/test_intent.py`

**Interfaces:**
- Consumes: `tools.analyst.entity_resolver.resolve_entity`,
  `tools.analyst.semantic_loader.load_semantic_catalog`,
  `tools.analyst.conversation_state.get_state`.
- Produces:
  `tools/analyst/intent.py::IntentResult` — dataclass with
  `metric: str | None`, `entities: dict[str, str]`, `period: str | None`,
  `comparison: str | None`, `confidence: float`, `needs_clarification: bool`.
  `tools/analyst/intent.py::extract_intent(question: str, session_id: str, llm_call: Callable[[str], str]) -> IntentResult`
  where `llm_call` takes a prompt string and returns the raw LLM text
  response (dependency-injected so tests don't call a real LLM — the real
  wiring in Task 8 passes a closure over `db_chat`'s existing provider
  chain).

- [ ] **Step 1: Write the failing test (LLM call is injected/mocked)**

```python
# tests/analyst/test_intent.py
import json

from tools.analyst.intent import extract_intent
from tools.analyst.conversation_state import clear_state, update_state


def _fake_llm(expected_json: str):
    def _call(prompt: str) -> str:
        return expected_json
    return _call


def test_extracts_metric_and_entity():
    clear_state("intent-test-1")
    llm_response = json.dumps({
        "metric": "vacancia_pct",
        "entities": {"activo": "Torre A"},
        "period": "2026-07",
        "comparison": None,
        "confidence": 0.9,
    })
    result = extract_intent("vacancia de Torre A en julio 2026", "intent-test-1", _fake_llm(llm_response))
    assert result.metric == "vacancia_pct"
    assert result.entities == {"activo": "Torre A"}
    assert result.confidence == 0.9
    assert result.needs_clarification is False


def test_low_confidence_triggers_clarification():
    clear_state("intent-test-2")
    llm_response = json.dumps({
        "metric": None, "entities": {}, "period": None, "comparison": None, "confidence": 0.2,
    })
    result = extract_intent("como viene esto?", "intent-test-2", _fake_llm(llm_response))
    assert result.needs_clarification is True


def test_follow_up_inherits_state():
    clear_state("intent-test-3")
    update_state("intent-test-3", last_metric="noi", last_entities={"fondo": "PT"}, last_period="2026-06")
    llm_response = json.dumps({
        "metric": None, "entities": {}, "period": "2025-06", "comparison": "same_period_last_year", "confidence": 0.85,
    })
    result = extract_intent("¿y el año pasado?", "intent-test-3", _fake_llm(llm_response))
    assert result.metric == "noi"
    assert result.entities == {"fondo": "PT"}
    assert result.period == "2025-06"


def test_invalid_llm_json_returns_low_confidence():
    clear_state("intent-test-4")
    result = extract_intent("pregunta rara", "intent-test-4", _fake_llm("no es json"))
    assert result.needs_clarification is True
    assert result.confidence == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/analyst/test_intent.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `tools/analyst/intent.py`**

```python
"""Structured intent extraction: question + conversation state -> IntentResult.

Replaces db_chat's direct SQL generation as the first LLM call. The actual
LLM invocation is injected as `llm_call` so this module has no direct
dependency on db_chat's provider chain (kept untouched per spec) and can be
unit-tested without network calls.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from tools.analyst.conversation_state import get_state, update_state
from tools.analyst.entity_resolver import resolve_entity
from tools.analyst.semantic_loader import load_semantic_catalog

_CONFIDENCE_CLARIFY_THRESHOLD = 0.5

_INTENT_PROMPT_TEMPLATE = """Extrae de la pregunta del usuario un JSON con:
{{"metric": "<nombre de metrica del catalogo o null>",
 "entities": {{"fondo": "<...>", "activo": "<...>"}},
 "period": "<YYYY-MM, YYYY, o null>",
 "comparison": "<same_period_last_year | previous_period | null>",
 "confidence": <0.0-1.0>}}

Metricas disponibles: {metric_names}
Pregunta: {question}
Responde SOLO el JSON, sin texto adicional."""


@dataclass
class IntentResult:
    metric: str | None
    entities: dict[str, str] = field(default_factory=dict)
    period: str | None = None
    comparison: str | None = None
    confidence: float = 0.0
    needs_clarification: bool = False


def _build_prompt(question: str) -> str:
    catalog = load_semantic_catalog()
    return _INTENT_PROMPT_TEMPLATE.format(
        metric_names=", ".join(sorted(catalog.metrics)),
        question=question,
    )


def extract_intent(question: str, session_id: str, llm_call: Callable[[str], str]) -> IntentResult:
    catalog = load_semantic_catalog()
    prompt = _build_prompt(question)
    raw = llm_call(prompt)

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return IntentResult(metric=None, confidence=0.0, needs_clarification=True)

    state = get_state(session_id)

    metric = parsed.get("metric") or state["last_metric"]

    entities_raw = parsed.get("entities") or {}
    resolved_entities: dict[str, str] = {}
    for kind, text in entities_raw.items():
        if kind in ("fondo", "activo") and text:
            resolved = resolve_entity(text, kind, catalog)
            resolved_entities[kind] = resolved or text
        elif text:
            resolved_entities[kind] = text
    entities = resolved_entities or state["last_entities"]

    period = parsed.get("period") or state["last_period"]
    comparison = parsed.get("comparison")
    confidence = float(parsed.get("confidence", 0.0))
    needs_clarification = confidence < _CONFIDENCE_CLARIFY_THRESHOLD and not (metric and entities)

    update_state(
        session_id,
        last_metric=metric,
        last_entities=entities,
        last_period=period,
        last_analysis_type=comparison,
    )

    return IntentResult(
        metric=metric,
        entities=entities,
        period=period,
        comparison=comparison,
        confidence=confidence,
        needs_clarification=needs_clarification,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/analyst/test_intent.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/intent.py tests/analyst/test_intent.py
git commit -m "feat(analyst): add structured intent extraction with conversation-state fallback"
```

---

## Task 7: Eval set (`tests/eval/`)

**Files:**
- Create: `tests/eval/questions.yaml`
- Create: `tests/eval/run_eval.py`

**Interfaces:**
- Consumes: `tools.analyst.intent.extract_intent`, `tools.db_chat` (real
  provider chain — this script makes real LLM calls, it is a manual
  verification tool, not part of `pytest` CI).
- Produces: `tests/eval/run_eval.py` is a standalone script (`python
  tests/eval/run_eval.py`) that prints a per-question and aggregate
  accuracy report to stdout. No pytest integration (spec: "no es parte de
  la suite de CI normal").

- [ ] **Step 1: Write `tests/eval/questions.yaml`**

```yaml
- question: "¿cómo ha evolucionado la vacancia de Parque Titanium este año?"
  expected_metric: vacancia_pct
  expected_entities: {fondo: PT}
- question: "vacancia de bodegas en Apoquindo"
  expected_metric: vacancia_pct
  expected_entities: {fondo: Apo}
- question: "¿y el mes anterior?"
  expected_metric: null
  notes: "requiere conversation_state previo -- correr despues de una pregunta de vacancia en la misma sesion"
- question: "NOI de Viña Centro en los últimos 12 meses"
  expected_metric: noi
  expected_entities: {activo: "Viña Centro"}
- question: "compara el NOI de Apo y PT este año"
  expected_metric: noi
- question: "dividend yield con amortización de la serie A de TRI"
  expected_metric: dividend_yield
  expected_entities: {fondo: TRI}
- question: "¿cuál es la TIR desde inicio bursátil de la serie C?"
  expected_metric: tir_desde_inicio
  expected_entities: {fondo: TRI}
- question: "tasa de arriendo ajustada contable de Apo3001"
  expected_metric: tasa_arriendo
  expected_entities: {activo: Apo3001}
  notes: "Apo3001 pertenece a TRI, no a Apo -- valida entity_resolver/relationships.yaml"
- question: "¿cómo viene Parque Titanium?"
  expected_metric: null
  notes: "ambiguo -- debe pedir aclaracion o cubrir mas de una metrica, no elegir una sola sin avisar"
- question: "vacancia del fondo TRI por tipo de activo"
  expected_metric: vacancia_pct
  expected_entities: {fondo: TRI}
- question: "NOI de enero 2024 de PT"
  expected_metric: noi
  expected_entities: {fondo: PT}
  expected_period: "2024-01"
- question: "¿la vacancia de Curicó está sobre 100%?"
  expected_metric: vacancia_pct
  expected_entities: {activo: "Mall Curicó"}
  notes: "result_checks debe marcar violado si el dato ejecutado supera 100"
- question: "dividend yield de las tres series de TRI, sin amortización"
  expected_metric: dividend_yield
  expected_entities: {fondo: TRI}
- question: "¿qué fondo tiene menor vacancia hoy?"
  expected_metric: vacancia_pct
- question: "TIR contable desde inicio de Apo"
  expected_metric: tir_desde_inicio
  expected_entities: {fondo: Apo}
- question: "renta promedio UF/m2 en oficinas de Parque Titanium"
  expected_metric: tasa_arriendo
  notes: "no hay formula UF/m2 de rent roll confirmada -- debe decir que esta pendiente de validar"
- question: "capex de Viña Centro este año"
  expected_metric: null
  notes: "capex no tiene YAML en esta fase -- debe decir explicitamente que no puede responder"
- question: "muéstrame lo mismo para Viña Centro"
  expected_metric: null
  notes: "sigue a una pregunta de NOI de PT en la misma sesion -- debe heredar metrica/periodo, cambiar solo entidad"
```

- [ ] **Step 2: Implement `tests/eval/run_eval.py`**

```python
"""Manual eval runner for the analyst-agent intent layer. Not part of pytest
CI (makes real LLM calls via db_chat's existing provider chain). Run with:
    python tests/eval/run_eval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools import db_chat
from tools.analyst.conversation_state import clear_state
from tools.analyst.intent import extract_intent

QUESTIONS_FILE = Path(__file__).parent / "questions.yaml"
SESSION_ID = "eval-session"


def _llm_call(prompt: str) -> str:
    chain = db_chat._provider_chain()
    provider = chain[0]
    client = db_chat._get_client(provider)
    response = client.chat.completions.create(
        model=provider["model"],
        messages=[{"role": "system", "content": prompt}],
        temperature=0,
    )
    return response.choices[0].message.content or ""


def run() -> None:
    cases = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    clear_state(SESSION_ID)

    metric_correct = 0
    entity_correct = 0
    total = len(cases)

    for case in cases:
        result = extract_intent(case["question"], SESSION_ID, _llm_call)
        expected_metric = case.get("expected_metric")
        metric_ok = result.metric == expected_metric
        metric_correct += int(metric_ok)

        expected_entities = case.get("expected_entities")
        entity_ok = expected_entities is None or all(
            result.entities.get(k) == v for k, v in expected_entities.items()
        )
        entity_correct += int(entity_ok)

        status = "OK" if metric_ok and entity_ok else "MISS"
        print(f"[{status}] {case['question']}")
        print(f"    esperado: metric={expected_metric} entities={expected_entities}")
        print(f"    obtenido: metric={result.metric} entities={result.entities} confidence={result.confidence}")
        if case.get("notes"):
            print(f"    nota: {case['notes']}")

    print(f"\nMetric accuracy: {metric_correct}/{total}")
    print(f"Entity accuracy: {entity_correct}/{total}")


if __name__ == "__main__":
    run()
```

*Note for implementer:* `db_chat._get_client(provider)` may not exist yet
under that exact name — inspect `tools/db_chat.py`'s
`_chat_completion_with_fallback` (around line 115) before writing this
step and adapt `_llm_call` to reuse whatever client-construction helper
already exists there, rather than duplicating client setup. Do not modify
`db_chat.py` in this task — only read from it.

- [ ] **Step 3: Run it manually and record the baseline**

Run: `python tests/eval/run_eval.py`

This is the Fase 0 baseline required by the original brief — record the
metric/entity accuracy numbers in the commit message.

- [ ] **Step 4: Commit**

```bash
git add tests/eval/
git commit -m "test(analyst): add eval question set + manual eval runner (baseline: <fill in numbers from Step 3>)"
```

---

## Task 8: Wire into `tools/db_chat.py::answer()`

**Files:**
- Modify: `tools/db_chat.py` (function `answer`, lines 798-964; imports at
  top, lines 16-32)
- Test: `tests/test_db_chat.py` (extend existing file — check its current
  test classes before adding, to match existing style/imports)

**Interfaces:**
- Consumes everything produced in Tasks 1-6:
  `tools.analyst.intent.extract_intent`, `tools.analyst.entity_resolver`,
  `tools.analyst.verified_queries_repo.find_similar`,
  `tools.analyst.result_checks.check_result`,
  `tools.analyst.conversation_state`.
- Produces: `answer(question, history=None, session_id="default")` — new
  optional `session_id` param, backward compatible (existing callers that
  don't pass it keep working against the `"default"` session). Return dict
  gains two optional keys: `intent` (the resolved `IntentResult` as dict, for
  debugging/tracing) and `result_check` (`{"passed": bool, "violated": [...]}`
  when the query mapped to a known metric with invariants, else absent).

- [ ] **Step 1: Read the current `answer()` body in full**

Run: `sed -n '798,964p' tools/db_chat.py` to see exact current logic before
editing — this task inserts calls around the existing SQL-generation and
execution steps rather than rewriting them.

- [ ] **Step 2: Write the failing test**

```python
# append to tests/test_db_chat.py — match existing imports/style already in that file
from unittest.mock import patch


class TestAnswerWithIntentLayer:
    def test_answer_accepts_session_id_param(self):
        # Full call would hit a real LLM; verify the signature accepts
        # session_id without raising TypeError, using empty question shortcut.
        import tools.db_chat as db_chat
        result = db_chat.answer("", session_id="test-wiring-session")
        assert result["error"] == "empty"

    def test_answer_result_check_flags_out_of_bounds(self):
        import tools.db_chat as db_chat
        from tools.analyst.result_checks import CheckResult
        with patch.object(db_chat, "_run_sql", return_value=(["vacancia_pct"], [[134.0]])), \
             patch.object(db_chat, "_extract_metric_from_sql", return_value="vacancia_pct"):
            result = db_chat.answer("vacancia de Curicó", session_id="test-wiring-session-2")
            assert "result_check" in result
            assert result["result_check"]["passed"] is False
```

*Note for implementer:* `_extract_metric_from_sql` does not exist yet — you
are defining its contract via this test as part of Step 3's implementation
(it's a small helper you add in `db_chat.py`: given the SQL/derived_kpi
`kpi` value selected, map it back to a `semantic/metrics/*.yaml` `name` if
one exists, else return `None`). If, after reading the real `answer()` body
in Step 1, a cleaner integration point exists (e.g. the code already knows
which `derived_kpi.kpi` value it queried), wire `result_checks.check_result`
from that existing variable instead of adding a new helper — prefer the
smaller diff.

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_db_chat.py::TestAnswerWithIntentLayer -v`
Expected: FAIL (either `TypeError: answer() got an unexpected keyword
argument 'session_id'` or `AttributeError` on the missing helper)

- [ ] **Step 4: Implement the wiring**

Add imports near the top of `tools/db_chat.py` (after existing imports,
before `_SCHEMA_CACHE`):

```python
from tools.analyst.conversation_state import get_state, update_state
from tools.analyst.result_checks import check_result
from tools.analyst.semantic_loader import load_semantic_catalog
from tools.analyst.verified_queries_repo import find_similar
```

Change the `answer()` signature:

```python
def answer(question: str, history: list[dict] | None = None, session_id: str = "default") -> dict:
```

Insert, right after the existing shortcut check (`if shortcut is not None:
return shortcut`) and before the SQL-generation messages are built:

```python
    verified = find_similar(question, top_k=1)
    verified_hint = verified[0] if verified else None
```

If `verified_hint` exists, add one more system message to `sql_messages`
right before the few-shot messages:

```python
    if verified_hint:
        sql_messages.append({
            "role": "system",
            "content": (
                "Pregunta similar ya verificada:\n"
                f"Q: {verified_hint['question']}\n"
                f"SQL: {verified_hint['sql']}\n"
                f"Notas: {verified_hint.get('notes', '')}"
            ),
        })
```

After the existing result-execution step (wherever `_run_sql` result is
obtained — inspect Step 1's output to find the exact variable name) and
before the Pasada 2 synthesis call, add:

```python
    result_payload: dict[str, Any] = {}
    metric_name = _extract_metric_from_sql(sql) if 'sql' in locals() and sql else None
    if metric_name:
        catalog = load_semantic_catalog()
        if metric_name in catalog.metrics and rows:
            try:
                first_value = float(rows[0][0])
                check = check_result(metric_name, first_value, catalog)
                result_payload["result_check"] = {"passed": check.passed, "violated": check.violated}
            except (ValueError, TypeError, IndexError):
                pass
```

*Note for implementer:* the exact variable names (`sql`, `rows`) must be
confirmed against what Step 1 revealed — do not guess blindly; read the
actual function body first.

Add the helper function near the bottom of the file, above `answer`:

```python
def _extract_metric_from_sql(sql: str | None) -> str | None:
    """Best-effort: maps a derived_kpi.kpi literal referenced in the SQL to
    a semantic/metrics/*.yaml metric name, for result_checks. Returns None
    if no known metric is referenced — this is a heuristic, not a parser."""
    if not sql:
        return None
    catalog = load_semantic_catalog()
    sql_lower = sql.lower()
    _KPI_TO_METRIC = {
        "vacancia_pct": "vacancia_pct",
        "noi_u12m": "noi", "noi_mes": "noi",
        "dy": "dividend_yield", "dy_amort": "dividend_yield",
        "tir_contable_desde_inicio": "tir_desde_inicio",
        "tir_bursatil_desde_inicio": "tir_desde_inicio",
    }
    for kpi_literal, metric_name in _KPI_TO_METRIC.items():
        if f"'{kpi_literal}'" in sql_lower and metric_name in catalog.metrics:
            return metric_name
    return None
```

Finally, merge `result_payload` into the dict `answer()` already returns
(find the final `return {...}` in the function body from Step 1's output
and add `**result_payload` to it), and before that final return, update
conversation state:

```python
    update_state(session_id, last_metric=metric_name or get_state(session_id)["last_metric"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_db_chat.py::TestAnswerWithIntentLayer -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full existing test_db_chat.py suite to check no regression**

Run: `pytest tests/test_db_chat.py -v`
Expected: all previously-passing tests still PASS

- [ ] **Step 7: Update `scripts/ingesta_server.py` to pass `session_id`**

Read `scripts/ingesta_server.py:326-334` first. Add a `session_id` derived
from the existing request/session mechanism (check how `_get_user()` or
equivalent identifies the caller in that file — reuse it, do not invent a
new session mechanism) when calling `db_chat.answer(...)`.

- [ ] **Step 8: Commit**

```bash
git add tools/db_chat.py scripts/ingesta_server.py tests/test_db_chat.py
git commit -m "feat(analyst): wire intent resolution, verified queries, and result checks into db_chat.answer()"
```

---

## Task 9: Full regression pass

**Files:** none created — verification only.

- [ ] **Step 1: Run the entire test suite**

Run: `pytest tests/ -v`
Expected: all tests pass, including the new `tests/analyst/` package and
the modified `tests/test_db_chat.py`.

- [ ] **Step 2: Run existing DB invariant tests to confirm no unrelated regression**

Run: `pytest tests/db/test_invariantes.py -v`
Expected: PASS (unchanged — this task doesn't touch DB schema)

- [ ] **Step 3: Confirm the Flask server still starts**

Run: `python scripts/ingesta_server.py` (in background, or with a short
timeout) and check it starts without import errors from the new
`tools/analyst` package, then stop it.

- [ ] **Step 4: Run `git status` and `git diff` to review the full changeset**

Run: `git status` then `git diff HEAD~9` (or diff against the commit before
Task 1) to review the full changeset end-to-end before considering Phase 1
complete.

- [ ] **Step 5: Final commit if any cleanup was needed, else confirm working tree is clean**

```bash
git status
```

Expected: clean working tree (all prior commits already captured the work).
