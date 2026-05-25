# DB del agente

Archivo: `memory/agente_toesca.db` (SQLite).

## Schema

- **Dimensiones**: `dim_fondo`, `dim_activo`, `dim_serie`, `dim_cuenta`
- **Raw** (línea por línea del proveedor, con linaje + hash idempotente): `raw_rent_roll_line`, `raw_eeff_line`, `raw_flujo_line`, `raw_er_activo_line`
- **Facts**: `fact_precio_cuota`, `fact_uf`, `fact_dividendo`
- **Derived**: `derived_kpi` (formato largo, una fila por KPI — base de dashboards)
- **Audit**: `ingest_run`, `publish_run`, `schema_version`

## Cómo acceder

Nunca con SQL crudo desde el resto del agente. Siempre vía repos en `tools/db/repo_*.py`.

```python
from tools.db.connection import get_conn
from tools.db import repo_kpi

with get_conn() as conn:
    series = repo_kpi.serie_temporal(conn, "activo", "PT", "NOI")
```

Las migraciones se aplican solas al importar `tools.memory_tools` (que importa `tools.db.connection.apply_migrations`).

## Repos disponibles

| Repo | Tabla(s) | Funciones clave |
|---|---|---|
| `repo_fondo` | dim_* | `list_fondos`, `get_fondo`, `list_activos`, `list_series`, `upsert_cuenta`, `get_cuenta` |
| `repo_rent_roll` | raw_rent_roll_line | `insert_lines`, `list_by_periodo`, `mark_superseded` |
| `repo_eeff` | raw_eeff_line | `insert_lines`, `list_by_periodo`, `mark_superseded` |
| `repo_flujo` | raw_flujo_line | `insert_lines`, `list_by_periodo`, `mark_superseded` |
| `repo_er_activo` | raw_er_activo_line | `insert_lines`, `list_by_periodo`, `mark_superseded` |
| `repo_fact` | fact_* | `upsert_precio`/`get_precio`, `upsert_uf`/`get_uf`, `upsert_dividendo`/`list_dividendos` |
| `repo_kpi` | derived_kpi | `upsert`, `get`, `serie_temporal`, `snapshot_periodo` |
| `repo_audit` | ingest_run/publish_run | `start_*`/`finish_*`/`fail_*` |

## Idempotencia

Las tablas raw tienen `UNIQUE(file_hash, source_row)`. `insert_lines` usa `INSERT OR IGNORE` → reingestar el mismo archivo no duplica. Versión nueva (hash distinto) → `mark_superseded(file_hash)` marca el anterior.

## Tests

`pytest tests/db/ -v` (48 tests). Usan SQLite temporal vía fixture `tmp_db` en `tests/conftest.py`.

## Estado por fase

- Fase 0 (esqueleto): DONE (2026-05-25)
- Fase 1 (dual-write por dominio): EN CURSO — 5 dominios listos
- Fase 2 (backfill histórico): CASI COMPLETO — todos los dominios salvo dividendos
- Fase 3 (inversión del flujo): pendiente
- Fase 4 (query + dashboards): EN CURSO — tools `consultar_db_*` listas y registradas

### Backfill (Fase 2)

`tools/db/backfill.py` recorre los archivos de proveedor en SharePoint y los reingesta con las mismas
funciones del flujo en vivo (idempotente). Correr con:
```
python -X utf8 -m tools.db.backfill rent_roll
```
Dominios (`python -X utf8 -m tools.db.backfill [dominio...]`):
- `rent_roll` — JLL + Tres A. 10.122 filas, 2025-09..2026-03.
- `er` — ER Viña/Curicó desde INFORME EEFF. 400 filas, 2025-12..2026-03.
- `inmosa` — flujos INMOSA (meses en columnas; usa hash_extra=periodo). 46 filas, 2026-01..2026-02.
- `uf` — UF diaria desde hoja 'UF' del CDG más reciente. 5.182 días, 2012..2026.
- `eeff` — valor cuota libro desde PDFs (regex, parcial). 4 trimestres.
- `precios` — datachart LarraínVial, 1 fetch/nemo, fin de mes. 100 filas (4 nemos × 25 meses).

Gaps conocidos:
- `2511 Rent Roll y NOI.xlsx` (nov): hoja 'Rent Roll' vacía/ausente.
- INMOSA marzo `EEFF y FC Senior Assist Mar.26.xlsx`: estructura distinta (hoja 'Activo Pasivo EERR', sin columnas de fecha tipo date). Lo cubre el flujo en vivo.
- EEFF valor cuota: regex parcial (no siempre captura serie I).
- **dividendos**: aún sin fuente confiable definida (el parser EEFF no trae fecha/serie).

### Camino de lectura (Fase 4)

`tools/query_tools.py` expone, registradas en `registry.py` y siempre disponibles:
- `consultar_db_cobertura()` — qué hay en la DB (filas + rango de períodos por dominio). Empezar acá.
- `consultar_db_kpi(entidad_tipo, entidad_key, kpi, desde, hasta)`
- `consultar_db_precio(nemotecnico, fecha)`
- `consultar_db_rent_roll(activo_key, periodo)`
- `consultar_db_er(activo_key, periodo)`
- `consultar_db_flujo(activo_key, periodo)`

El system prompt (`agent.py`) instruye usar estas antes de abrir Excel para responder preguntas.
La DB se llena a medida que corren los flujos mensuales (o con el backfill de Fase 2).

### Dominios en dual-write (Fase 1)

| Dominio | Tool con dual-write | Destino DB |
|---|---|---|
| Precios cuota | `web_bursatil_tools.obtener_precio_cuota` | `fact_precio_cuota` |
| Valor cuota libro (EEFF) | `eeff_tools.leer_eeff` | `derived_kpi` (kpi=`valor_cuota_libro`) |
| ER Viña/Curicó | `noi_tools._actualizar_er_mall` | `raw_er_activo_line` |
| Flujos INMOSA | `noi_tools.actualizar_noi_inmosa` | `raw_flujo_line` |
| Rent roll (todos los activos) | `rentroll_tools.consolidar_rent_rolls` | `raw_rent_roll_line` |

Todos son **best-effort**: si la DB falla, el flujo de Excel sigue (nunca se rompe el entregable).

### Pendientes Fase 1

- **UF**: vive en la hoja 'UF' del CDG (Excel), no hay fuente web. Persistir cuando se toque ese flujo.
- **Dividendos EEFF**: el parser regex no trae fecha ni serie de forma confiable → no persistible aún.
- **NOI PT agregado (RR JLL)**: hoja multi-activo; se optó por persistir el rent roll detallado en su lugar (más valioso para dashboards). El NOI por activo se derivará en Fase computacional.

Spec completo: `docs/superpowers/specs/2026-05-25-db-migration-design.md`.
