# Pipeline de ingesta DB-centric

La DB `memory/agente_toesca.db` es la fuente primaria de consulta. Cada archivo de proveedor pasa por un ingestor que persiste sus líneas a una tabla `raw_*` de forma idempotente (UNIQUE `file_hash, source_row`).

## Mapa archivo → tabla raw

| Tipo de archivo | Patrón de nombre | Ingestor | Tabla destino |
|---|---|---|---|
| INFORME EEFF Viña Centro (Tres A) | `MM-AAAA INFORME EEFF VIÑA CENTRO SPA*.xlsx` | `tools/db/ingest_er.py` | `raw_er_activo_line` |
| INFORME EEFF Curicó (Tres A) | `MM-AAAA INFORME EEFF POWER CENTER CURICO SPA.xlsx` | `tools/db/ingest_er.py` | `raw_er_activo_line` |
| Flujo INMOSA | `ER-FC INMOSA Flujos*.xlsx` | `tools/db/ingest_flujo.py` | `raw_flujo_line` |
| Rent Roll JLL | `AAMM Rent Roll y NOI.xlsx` | `tools/rentroll_tools.py` (backfill) | `raw_rent_roll_line` |
| Rent Roll Tres A | `Excel Tres A <activo> <Mes> AAAA.xlsx` | `tools/rentroll_tools.py` (backfill) | `raw_rent_roll_line` |
| EEFF PDF (CMF) | PDF de EEFF trimestral | `scripts/ingest_eeff.py` | `raw_eeff_line` |

Los Rent Rolls se buscan en SharePoint:
`Inmobiliario Toesca > Renta Comercial > Rent Rolls`.
JLL los envía Nicole; TresA los envía Sebastián Bravo. Generalmente hay que pedirlos
e insistir, porque se demoran en mandarlos.

## Cómo ingestar

### Archivo único (conversacional, vía agente)

El agente expone `ingestar_archivo(path, periodo?)`. Detecta el tipo por nombre y delega al ingestor correcto.

```
ingestar_archivo("C:\...\02-2026 INFORME EEFF VIÑA CENTRO SPA.xlsx")
→ {"tipo": "er_vina", "filas": 87, "periodo": "2026-02", "activo": "vina_centro"}
```

### EEFF históricos (batch, vía script)

```bash
# Una vez por fondo, después de subir PDFs:
python -m markitdown work/eeff_ingesta/PT/pdf/<archivo>.pdf > work/eeff_ingesta/PT/md/<archivo>.md
python scripts/ingest_eeff.py --fondo PT --all
```

Fondos soportados: `TRI` (completo), `PT` (en progreso), `APO` (en progreso).

### Backfill histórico (rent rolls, ER, flujos)

```bash
python -m tools.db.backfill                 # todo
python -m tools.db.backfill rent_roll       # solo rent rolls
python -m tools.db.backfill er              # solo ER Viña/Curicó
python -m tools.db.backfill inmosa          # solo flujos INMOSA
```

## Verificar cobertura

```python
from tools.query_tools import consultar_db_cobertura
print(consultar_db_cobertura())
```

Devuelve JSON con períodos disponibles por activo/fondo y gaps mensuales detectados.

## Idempotencia

Cada tabla raw tiene `UNIQUE (file_hash, source_row)`. Re-ingestar el mismo archivo no duplica. Si un proveedor entrega una nueva versión del mismo archivo (mismo nombre, contenido distinto), el `file_hash` cambia → se ingestan nuevas filas. Para invalidar la versión vieja: `mark_superseded(conn, file_hash)`.

## Capa derived

Los KPIs y agregados (NOI, vacancia, rentabilidades) se calculan on-demand desde las tablas raw, no se persisten salvo que el costo computacional sea alto. Política de caching en `wiki/db.md` y `skill: real-estate-finance-expert`.
