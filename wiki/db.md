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
- Fase 1 (dual-write por dominio): pendiente
- Fase 2 (backfill histórico): pendiente
- Fase 3 (inversión del flujo): pendiente
- Fase 4 (query + dashboards): pendiente

Spec completo: `docs/superpowers/specs/2026-05-25-db-migration-design.md`.
