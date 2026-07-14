# Ingesta ER Mall Curicó — diseño

**Fecha**: 2026-07-14
**Contexto**: Continuación de la consolidación de activos individuales del fondo TRI vía `raw_er_activo_line` (ya migrados: Viña Centro, INMOSA, Sucden). Este spec cubre Mall Curicó, la misma familia de activos administrados por Tres Asociados que Viña Centro, con planilla de estructura muy similar.

## Fuente

**Archivo**: `RAW/NOI Curico.xlsx` (SharePoint), hoja única `Hoja1`, rango `A1:AK242` (34 meses, 2023-08 a 2026-05).

Estructura confirmada por inspección directa (`openpyxl`, `data_only=True/False`):

| Fila | Contenido |
|---|---|
| 3 | UF de cierre de mes por columna |
| 4 | Fecha de fin de mes (`datetime`), columna D en adelante |
| 5–16 | **Ingreso de Explotación** (leaf accounts, sin header de texto en col C — el label "Ingreso de Explotacion" solo existe en la columna B, que es un residuo de una plantilla vieja desalineada, igual que se encontró en Viña) |
| 19 | `"Total Resultado Operación"` — subtotal fórmula `SUM(D6:D18)`, rango contiguo sin huecos |
| 21–26 | **Ingreso Fuera De Explotación** (header en col C fila 21) |
| 28 | `"Total Ingreso Fuera De Explotación"` |
| 30 | `"Total Ingresos"` |
| 32–77 | **Gastos de administración y ventas** (header en col C fila 32), organizados en subcategorías (SEGURIDAD, ASEO, MANTENCIÓN, etc.) cada una con su propia fórmula `SUM()` sobre un rango de cuentas hoja |
| 79 | `"Total Gastos de administración y ventas"` — suma de las 15 subcategorías |
| 81 | `"Total Operacional"` |
| 83–100 | **Resultado No Operacional** (financiero: leasing, intereses, variación UF, reajustes) — fuera de scope de este ingest |
| 102–105 | Resultado Antes de Impuestos / Resultado del Periodo |
| 113–134 | Sección 2, bloque A: NOI condensado por categoría en UF — fila 133 `"Noi"` = `SUM(D115:D132)`, fila 134 `"Chequeo"` = `(Total Operacional − Total Fuera Explotación)/UF − Noi` (≈0, confirma la metodología) |
| 147–242 | Sección 2, bloque B: espejo completo de la Sección 1 dividido por UF — fila 219 `"Total Operacional"`, fila 242 `"Resultado del Periodo"` |

Columna B es un residuo de plantilla anterior, desalineada respecto a columna C (mismo patrón que Viña) — se ignora por completo.

**Columna C** es la fuente real: cuentas hoja con formato `"<código> <nombre>"` (regex `^(\d(?:-\d{1,3}){3})\s+(.+)$`, igual que Viña), intercaladas con filas de subcategoría (sin código, ej. `"SEGURIDAD"`) que no matchean el regex y se saltan automáticamente.

**Hallazgo relevante — cuentas huérfanas**: 3 cuentas hoja (`3-1-10-115` Mantención Cobro Directo, `3-1-10-116` Mantención Activo, `3-1-10-117` Servicios Administrativos Activo) están físicamente dentro del bloque de Gastos de Administración y Ventas, pero las fórmulas `SUM()` de sus subcategorías (MANTENCIÓN, SERVICIOS) no las incluyen en su rango — quedan fuera de "Total Gastos de administración y ventas" (fila 79) y de la fila 133 "Noi" oficial. Impacto real confirmado: hasta 5.7% del gasto total en algunos meses (2025-05 a 2026-05, montos entre 25.908 y 5.581.493 CLP). **Confirmado por el usuario 2026-07-14**: el NOI definitivo en la DB debe seguir la metodología de fila 133 (Ingreso Explotación + Gastos Admin y Ventas, sin Fuera de Explotación) pero recalculado desde las cuentas hoja crudas — **incluye estas 3 cuentas huérfanas**, igual que se hizo con los bugs de fórmula encontrados en Viña.

## Diseño

### Nuevo módulo: `tools/db/ingest_er_curico.py`

Mismo patrón que `tools/db/ingest_er_vina.py`: clasificación de cuentas por sección vía headers de columna C, código de cuenta por regex (no diccionario fijo), recálculo de NOI desde cuentas crudas sin reusar las fórmulas de subtotal de la fuente, persistencia idempotente por `file_hash` en `raw_er_activo_line`.

`activo_key = "Mall Curicó"` (ya existe en `dim_activo`; hay filas previas en `raw_er_activo_line` de una ingesta antigua vía `noi_tools.actualizar_er_curico` — dual-write desde el CDG — que quedarán `superseded` al correr este parser por primera vez, mismo comportamiento que con Viña).

**Diferencias clave vs. `ingest_er_vina.py`:**

1. **Sin header de ancla inicial**: Viña usa la última ocurrencia de `"Ingreso de Explotacion"` en columna C como punto de partida. Curicó no tiene ese texto en columna C — el bloque de Ingreso Explotación empieza directo después de la fila de fechas. El parser arranca con `current_seccion = "INGRESOS_OPERACION"` por defecto desde la primera fila con contenido después de la fila de fecha, y transiciona a `INGRESO_FUERA_EXPLOTACION` / `GASTOS_OPERACION` al encontrar esos headers de texto en columna C.
2. **Terminador — primera ocurrencia, no la última**: en Curicó la Sección 1 (datos reales) está arriba y la Sección 2 (espejo UF) está abajo — orden inverso a Viña. El parser corta en la **primera** ocurrencia de `"Total Operacional"` en columna C (fila 81), evitando así reprocesar la Sección 2 (que repite los mismos headers en las filas 159–219).
3. **`"Resultado No Operacional"` (filas 83–100) no se ingesta**: no lo usa la fila 133 "Noi", así que queda fuera del scope de este parser — igual criterio que Viña, que corta el recorrido antes de llegar a esa sección.
4. **Validación de Gastos de Administración y Ventas no puede ser estricta**: a diferencia de Viña (donde la suma de cuentas cuadra exacto contra el subtotal de la fuente), acá la fórmula fuente de "Total Gastos de administración y ventas" (fila 79) **subestima** el total real por el bug de cuentas huérfanas. En vez de comparar por igualdad, se valida que `abs(suma_calculada) >= abs(fila_79) - tolerancia` — sigue detectando errores de parseo (la suma nunca puede ser *menor* al subtotal de la fuente) sin fallar por el gap ya identificado y aceptado.
5. **Sin overrides de datos faltantes**: no se detectó el patrón de Viña (celda hija en blanco con total de categoría correcto en otra parte) en la inspección del archivo actual. Si aparece en el futuro, la validación estricta de Ingreso Explotación (ver abajo) lo va a atrapar y el ingest fallará explícitamente, igual que ocurriría con Viña.

**Secciones capturadas y `es_operacional`:**

| Sección | Header columna C | `es_operacional` |
|---|---|---|
| `INGRESOS_OPERACION` | (sin header, default inicial) | 1 |
| `INGRESO_FUERA_EXPLOTACION` | `"Ingreso Fuera De Explotacion"` | 0 |
| `GASTOS_OPERACION` | `"Gastos de administración y ventas"` | 1 |

**NOI**: `SUM(monto_uf) WHERE es_operacional=1 AND activo_key='Mall Curicó' AND periodo=?` — no se persiste como columna, se deriva en consulta (mismo patrón que Viña/INMOSA).

**Conversión CLP→UF**: en el parser, `monto_uf = monto_clp / uf_fin_de_mes` usando `fact_uf` de la DB (no la UF de la fila 3 de la planilla) — igual que Viña.

**Validación de integridad (obligatoria):**
- Ingreso Explotación: estricta, `abs(suma_cuentas - fila_19) < 2000 CLP`, por periodo.
- Gastos de Administración y Ventas: blanda, `abs(suma_cuentas) >= abs(fila_79) - 2000 CLP`, por periodo (documentado arriba, gap conocido y aceptado).
- Si cualquier validación falla fuera de estos criterios, el ingest falla explícito indicando periodo y delta — no se persiste ningún periodo de esa corrida (todo o nada, mismo patrón que Viña/INMOSA).

**Idempotencia:** por `file_hash` (sha256), igual que el resto de parsers `ingest_er_*`.

**CLI:** `--dry-run` para previsualizar sin persistir, mismo patrón que `ingest_er_vina.py`.

### Test

`tests/db/test_ingest_er_curico.py` — fixture xlsx construida programáticamente replicando la estructura confirmada arriba (fila de fechas, bloque Ingreso Explotación sin header, header "Ingreso Fuera De Explotacion", header "Gastos de administración y ventas" con subcategorías y las 3 cuentas huérfanas fuera de rango de fórmula, terminador "Total Operacional", más una Sección 2 repetida abajo para verificar que no se reprocesa), con al menos 3 meses de datos, verificando:
- Se persisten las cuentas de `INGRESOS_OPERACION` y `GASTOS_OPERACION` (incluyendo las 3 huérfanas) y `INGRESO_FUERA_EXPLOTACION`; nada de la sección "Resultado No Operacional" ni de la Sección 2 repetida.
- NOI derivado (`SUM(monto_uf) WHERE es_operacional=1`) incluye las 3 cuentas huérfanas.
- Validación estricta de Ingreso Explotación falla explícito si se corrompe un valor de forma que no cuadre con el subtotal de la fuente.
- Validación blanda de Gastos Admin y Ventas: pasa con el gap conocido de las 3 huérfanas, pero falla si la suma calculada cae *por debajo* del subtotal de la fuente (indicaría un bug de parseo real, no el gap conocido).
- Idempotencia: reingestar el mismo archivo no crea filas duplicadas.
- El parser corta en la primera ocurrencia de "Total Operacional" y no sigue hacia la Sección 2 (que repite headers).

### Fuera de scope

- Sección "Resultado No Operacional" (filas 83–100) — no la usa el NOI, se puede ingestar en un spec futuro si se necesita resultado financiero.
- Consolidación a nivel fondo TRI vía `v_activo_fondo_efectivo` — se hace una vez estén todos los activos pendientes (Apo3001 queda como el único restante tras este spec).
- Desactivar `noi_tools.actualizar_er_curico` (dual-write vía CDG) — igual pendiente que quedó abierto para Viña; las filas viejas quedan `superseded` pero el flujo mensual del CDG podría volver a insertar y re-supersede si se sigue llamando.
- Archivar `RAW/NOI Curico.xlsx` a su carpeta canónica — permanece en RAW por ahora.
