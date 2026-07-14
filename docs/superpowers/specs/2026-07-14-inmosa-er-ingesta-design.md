# Ingesta ER INMOSA — diseño

**Fecha**: 2026-07-14
**Contexto**: Primer activo pendiente del fondo TRI a consolidar (de los 5: INMOSA, Sucden, Viña Centro, Curicó, Apo3001), siguiendo la arquitectura de participaciones ya migrada (`dim_sociedad`, `v_activo_fondo_efectivo`, migración 049). PT y Apo ya están consolidados con `raw_er_activo_line`; este spec extiende el mismo patrón a INMOSA.

## Fuente

**Archivo real localizado y verificado**: `RAW/NOI INMOSA.xlsx` (SharePoint), hoja única `Hoja1`.

Estructura confirmada por inspección directa del archivo (`openpyxl`, `data_only=True`):

| Fila | Contenido |
|---|---|
| 3 | Header de fechas (`datetime`, fin de mes), columnas B (2018-01-31) a CV (2026-03-31) — **99 meses**, sin huecos |
| 4 | vacía |
| 5 | `"INMOSA"` — label del activo (ancla para ubicar el bloque) |
| 6 | `"(+) Ingresos por Arriendos"` — usar |
| 7 | `"(+) Ingresos por Arriendos"` — **duplicada, IGNORAR** (subtotal visual, valores idénticos a la fila 6) |
| 8 | `"(+) Contribuciones"` |
| 9 | `"(-) Administraci�n"` (mojibake: ó → U+FFFD) |
| 10 | `"(-) Provision Reparaciones "` (**espacio final** en el label) |
| 11 | `"(-) Aseo, Mantenci�n y Otros"` (mojibake) |
| 12 | `"(-) Otros Gastos Operacionales"` |
| 13 | `"(-) IVA"` |
| 14 | `"(-) Seguros"` |
| 15 | `"NOI Mensual"` — fila de control, **no se persiste**, solo se usa para la validación de integridad |
| 16 | vacía (fin de datos) |

No hay celdas merged. El formato es estable en las 99 columnas de datos (no cambia de layout).

**Validación de integridad ejecutada sobre el archivo real completo**: sumando filas 6, 8, 9, 10, 11, 12, 13, 14 (excluyendo la fila 7 duplicada) por columna, contra la fila 15 (NOI Mensual), para los 99 periodos (2018-01 a 2026-03) → **0 discrepancias** (tolerancia 0.01). Confirma que el modelo "suma de 8 categorías = NOI" es válido en todo el histórico real, no solo en el ejemplo de la foto.

**Hallazgo relevante**: la fila "(+) Contribuciones" **no siempre es positiva** — en varios periodos toma valores negativos (ej. -1.381, -538, -174 UF). Esto no rompe el modelo: la clasificación `seccion` (`INGRESOS_OPERACION`/`GASTOS_OPERACION`) es solo informativa y no afecta el cálculo de NOI (que es una suma simple de `monto_clp` sin importar la sección) — se mantiene la etiqueta `INGRESOS_OPERACION` para Contribuciones porque así viene clasificada en la fuente (prefijo `(+)`), igual que ocurre con "Ingresos por Contribuciones" en PT (recuperación de gasto, puede ir negativo en ajustes).

**Confirmado por el usuario:**
- La fila "Ingresos por Arriendos" está duplicada en la planilla (subtotal visual) — se ingesta solo la primera ocurrencia.
- Montos en **UF**.
- Gastos ya vienen con signo negativo en la fuente — no se re-aplica signo.
- Layout categoría×mes es consistente en todo el rango histórico (no cambia de formato).
- `activo_key='INMOSA'` fijo, sin desglose por residencia individual (INMOSA engloba las residencias como una sola entidad para efectos de esta ingesta).

## Diseño

### Nuevo módulo: `tools/db/ingest_er_inmosa.py`

Mismo patrón que `tools/db/ingest_er_apoquindo.py`: mapeo de categoría (nombre normalizado) → `cuenta_codigo` + `seccion`, parser de tabla categoría×mes, persistencia idempotente por `file_hash` en `raw_er_activo_line`.

**Mapeo de categorías:**

| Categoría planilla | `cuenta_codigo` | `seccion` |
|---|---|---|
| Ingresos por Arriendos (1ª ocurrencia) | `INMOSA_ING_ARR` | `INGRESOS_OPERACION` |
| Contribuciones | `INMOSA_CONTRIB` | `INGRESOS_OPERACION` |
| Administración | `INMOSA_ADM` | `GASTOS_OPERACION` |
| Provisión Reparaciones | `INMOSA_PROV_REP` | `GASTOS_OPERACION` |
| Aseo, Mantención y Otros | `INMOSA_ASEO` | `GASTOS_OPERACION` |
| Otros Gastos Operacionales | `INMOSA_OTROS_GASTOS` | `GASTOS_OPERACION` |
| IVA | `INMOSA_IVA` | `GASTOS_OPERACION` |
| Seguros | `INMOSA_SEG` | `GASTOS_OPERACION` |

Todas las categorías tienen `es_operacional=1` (todas entran al cálculo de NOI, confirmado por la validación de suma arriba). NOI **no se persiste** — se deriva como `SUM(monto_clp) WHERE es_operacional=1 AND activo_key='INMOSA' AND periodo=?`.

**Parser — ancla + offsets fijos, con normalización de nombre como verificación cruzada:**

1. Ubicar la fila con label `"INMOSA"` en columna A (fila 5 en el archivo actual) — no hardcodear el número de fila, buscarla dinámicamente para tolerar filas insertadas antes del bloque en el futuro.
2. Las 9 filas siguientes a esa ancla son: Ingresos (usar), Ingresos (duplicado, ignorar), Contribuciones, Administración, Provisión Reparaciones, Aseo/Mantención/Otros, Otros Gastos Operacionales, IVA, Seguros. La fila 10ª siguiente es `"NOI Mensual"` (fila de control).
3. Para cada fila del bloque, normalizar el label (`_norm()`: lowercase, strip, colapsar espacios, remover prefijo `(+)`/`(-)`, tolerar U+FFFD) y mapearlo contra el diccionario de categorías. Si el nombre normalizado no matchea ninguna entrada conocida (incluyendo variantes de mojibake ya vistas), **fallar explícitamente** en vez de ignorar la fila silenciosamente — evita que un cambio de nombre en la fuente pase desapercibido.
4. La primera vez que aparece `"ingresos por arriendos"` (normalizado) se persiste; la segunda ocurrencia consecutiva se descarta explícitamente (detectado por nombre normalizado repetido dentro del mismo bloque, no por número de fila fijo, para tolerar que la planilla reordene filas).
5. Columnas de datos: iterar desde la columna B hasta la última columna con fecha no nula en la fila de header (fila 3 relativa al bloque, o buscada dinámicamente 2 filas arriba de la fila ancla) — no hardcodear el rango de columnas (hoy llega a CV=2026-03, crecerá cada mes).
6. Celdas vacías (`None`) se tratan como `0.0`.
7. `periodo` = truncar la fecha de fin de mes a `'YYYY-MM'`.

**Validación de integridad (obligatoria, no opcional):** para cada periodo, sumar los montos de las 8 categorías ingresadas (excluyendo la fila duplicada de Ingresos) y comparar contra el valor de la fila "NOI Mensual" de la misma columna. Si no cuadra exacto (tolerancia `abs(delta) < 0.01`, calibrada contra la validación real de 99 periodos que dio 0 discrepancias), el ingest debe fallar con un error explícito indicando el periodo y el delta — no se persiste ningún periodo de esa corrida (falla atómica, todo o nada). Esto sigue la regla ya establecida en memoria (`feedback_gastos_check_suma`): siempre verificar que la suma de componentes cuadre con el total reportado por la fuente.

**Idempotencia:** por `file_hash` (sha256 del archivo), igual que PT/Apo — reingestas del mismo archivo no duplican filas (versiona con `superseded_at` si el archivo cambia).

**CLI:** `--dry-run` para previsualizar sin persistir, mismo patrón que `ingest_er_apoquindo.py`.

### Test

`tests/db/test_ingest_er_inmosa.py` — fixture xlsx construida programáticamente (vía `openpyxl`, no el archivo real) replicando la estructura exacta confirmada arriba (ancla "INMOSA" en fila 5, 9 filas de categorías incluyendo la duplicada, fila de header 2 arriba de la ancla, fila NOI Mensual al final), con al menos 3 meses de datos usando los valores reales de enero-marzo 2018 (6440.0915337339 / 6434.459445817043 / 6437.583242252402 para Ingresos; -175 fijo para Administración; -35.82156799923614 / -19.76057110904785 / -69.61203164324844 para Provisión Reparaciones; resto en 0/None), verificando:
- Se persisten 8 categorías × 3 meses = 24 filas en `raw_er_activo_line` (99 columnas de datos reales dan 8×99=792).
- NOI derivado (`SUM(monto_clp) WHERE es_operacional=1`) = 6229.2699657346675 / 6239.698874707995 / 6192.971210609153 para cada mes respectivamente (valores reales del archivo, no redondeados).
- Idempotencia: reingestar el mismo archivo no crea filas duplicadas (mismo `file_hash`).
- Un test con label de categoría no reconocido (typo/variante nueva) hace fallar el ingest explícitamente, no lo ignora silenciosamente.
- La validación de integridad falla explícitamente si se corrompe un valor de prueba de forma que la suma no cuadre con "NOI Mensual".
- Un test que replica el hallazgo real: "Contribuciones" con valor negativo se persiste correctamente con `seccion='INGRESOS_OPERACION'` a pesar del signo (la clasificación no depende del signo del valor).

### Fuera de scope

- Consolidación del NOI/Ingresos a nivel fondo TRI usando `v_activo_fondo_efectivo` (ya construida en la migración 049; se usará una vez estén todos los activos pendientes ingresados, o incrementalmente si el usuario lo pide antes).
- Sucden, Viña Centro, Curicó, Apo3001 — se abordan en specs separados cuando el usuario entregue sus planillas respectivas.
- Archivar `RAW/NOI INMOSA.xlsx` a su carpeta canónica (`Fondos/Rentas TRI/Activos/INMOSA/Flujos/`) — el archivo permanece en RAW por ahora; no forma parte de este ingest.
