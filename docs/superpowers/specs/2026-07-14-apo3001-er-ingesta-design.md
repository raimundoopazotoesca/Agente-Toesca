# Ingesta ER Apoquindo 3001 — diseño

**Fecha**: 2026-07-14
**Contexto**: Último activo pendiente de consolidar en el fondo TRI (de los 5: INMOSA ✅, Sucden ✅, Viña Centro ✅, Curicó ✅, Apo3001 pendiente), siguiendo la arquitectura ya usada para [[ingest_er_inmosa]] / [[ingest_er_sucden]]. `activo_key='Apo3001'` ya existe en `dim_activo` (migración 006), con `sociedad_key='Chanarcillo'`, `participacion_en_sociedad=0.685` (migración 049) — misma sociedad intermedia que Sucden (Inmobiliaria Chañarcillo Ltda.).

Aún no se recibió la planilla real ni la foto adjunta en el mensaje del usuario no llegó al contexto de esta conversación — este diseño asume el mismo patrón categoría×mes visto en INMOSA/Sucden y queda pendiente de confirmar contra el archivo real.

## Fuente (a confirmar)

Se espera un xlsx tipo `RAW/NOI Apoquindo 3001.xlsx` (o similar, en la misma carpeta `RAW/` de SharePoint que `NOI INMOSA.xlsx` y `NOI Sucden.xlsx`), hoja única, con el mismo layout categoría×mes:

- Fila ancla con label `"Apoquindo 3001"` (o variante) en columna A.
- Fila de header de fechas — puede estar en la misma fila que la ancla (patrón Sucden) o 2 filas arriba (patrón INMOSA). El parser debe detectar ambos casos igual que ya hace `ingest_er_sucden.py`/`ingest_er_inmosa.py` (buscar hacia arriba desde la ancla hasta encontrar ≥3 celdas fecha, sin asumir offset fijo).
- N filas de categoría debajo de la ancla (número desconocido hasta ver el archivo — INMOSA tiene 8 operacionales, Sucden 4).
- Fila `"NOI Mensual"` de control al final del bloque.
- Nota importante: **este activo ya tiene un feed de NOI vía RR JLL** ("NOI PT" del `{AAMM} Rent Roll y NOI.xlsx`, función `actualizar_noi_apo3001` en `noi_tools.py`, filas 468-476 del NOI-RCSD). Confirmar con el usuario si la planilla nueva **reemplaza** esa fuente para efectos de la DB (probable, dado que se está migrando todo a `raw_er_activo_line` como en INMOSA/Sucden) o si conviven ambas.

## Diseño

### Nuevo módulo: `tools/db/ingest_er_apo3001.py`

Mismo patrón que `ingest_er_inmosa.py` / `ingest_er_sucden.py`:

1. **Parser** `parse_planilla(xlsx_path) -> list[dict]`:
   - Ubicar fila ancla (label normalizado, tolerante a mojibake y variantes de nombre) — no hardcodear número de fila.
   - Ubicar fila de header de fechas dinámicamente (mismo offset flexible que ya usa `ingest_er_sucden.py`).
   - Recorrer filas de categoría hasta `"NOI Mensual"`, mapeando cada label normalizado → `cuenta_codigo` fijo (prefijo `APO3001_*`) + `seccion` (`INGRESOS_OPERACION`/`GASTOS_OPERACION`) vía diccionario `_CATEGORIAS`. Label no reconocido → **falla explícita**, no se ignora.
   - Filas duplicadas (si las hay, como en INMOSA) se descartan por nombre normalizado repetido, no por número de fila.
   - Celdas vacías → `0.0`. `periodo` = `'YYYY-MM'` truncado de la fecha de header.
   - Devuelve filas con: `activo_key='Apo3001'`, `periodo`, `cuenta_codigo`, `cuenta_nombre`, `monto_clp` (convención: aunque la unidad real sea UF, se guarda en esta columna como en INMOSA/Sucden — confirmar unidad real con el usuario), `monto_uf=None`, `seccion`, `es_operacional=1`, `source_file`, `source_sheet`, `source_row`.

2. **Validación de integridad obligatoria**: para cada periodo, `sum(monto de las categorías) == "NOI Mensual"` (tolerancia `abs(delta) < 0.01`). Si no cuadra, falla atómica — no persiste ningún periodo de esa corrida. Misma regla que [[feedback_gastos_check_suma]].

3. **Persistencia** `persist(xlsx_path, conn=None) -> dict`: idéntica a INMOSA/Sucden —
   - `file_hash` = sha256 del archivo.
   - Si ya existen filas activas con ese `file_hash` → `skipped_idempotent`.
   - Si existen filas activas previas de `activo_key='Apo3001'` con otro hash → `mark_superseded` + insertar nuevas (`superseded_and_reinserted`).
   - Si no hay filas previas → `inserted`.
   - Abre `ingest_run` (tool=`ingest_er_apo3001`), inserta vía `repo_er_activo.insert_lines`, cierra el run.

4. **NOI no se persiste** — se deriva como `SUM(monto_clp) WHERE es_operacional=1 AND activo_key='Apo3001' AND periodo=?`, igual que el resto.

5. **CLI**: `--dry-run` para previsualizar sin escribir, mismo patrón.

### Reutilización directa (sin cambios de schema)

No requiere migración nueva — `dim_activo`, `dim_sociedad`, `raw_er_activo_line` y `v_activo_fondo_efectivo` ya cubren Apo3001 desde las migraciones 006/007/008/015/049. Solo falta el módulo de ingesta y el registro en `backfill.py`.

### Test: `tests/db/test_ingest_er_apo3001.py`

Mismo esqueleto que `test_ingest_er_inmosa.py`/`test_ingest_er_sucden.py`: fixture xlsx construida con `openpyxl` replicando el layout confirmado (una vez se vea el archivo real), cubriendo:
- N categorías × M meses persistidas correctamente.
- NOI derivado coincide con `SUM(monto_clp)`.
- Idempotencia (reingesta no duplica).
- Label desconocido falla explícitamente.
- Validación de integridad falla si se corrompe un valor.

### Pendiente de confirmar con el usuario (antes de escribir código)

1. **Ubicación y nombre real del archivo** (carpeta SharePoint, nombre exacto).
2. **Layout exacto**: ancla, offset del header de fechas, lista real de categorías y si hay filas duplicadas.
3. **Unidad de los montos** (UF como INMOSA/Sucden, o CLP).
4. **Si esta ingesta reemplaza el feed actual vía RR JLL** (`actualizar_noi_apo3001`) para el cálculo en DB, o si ambas fuentes deben coexistir con alguna regla de precedencia.
5. **Reglas de negocio especiales** (como la Sobretasa fija de Sucden) que la planilla pueda traer.

## Fuera de scope

- Migrar/depreciar `actualizar_noi_apo3001` en `noi_tools.py` (Excel del CDG) — sigue funcionando en paralelo hasta decisión explícita.
- Consolidación final del NOI/Ingresos TRI vía `v_activo_fondo_efectivo` una vez estén los 5 activos — se dispara cuando el usuario lo pida (ya deberían estar los otros 4).
