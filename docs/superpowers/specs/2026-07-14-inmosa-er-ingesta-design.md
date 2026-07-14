# Ingesta ER INMOSA — diseño

**Fecha**: 2026-07-14
**Contexto**: Primer activo pendiente del fondo TRI a consolidar (de los 5: INMOSA, Sucden, Viña Centro, Curicó, Apo3001), siguiendo la arquitectura de participaciones ya migrada (`dim_sociedad`, `v_activo_fondo_efectivo`, migración 049). PT y Apo ya están consolidados con `raw_er_activo_line`; este spec extiende el mismo patrón a INMOSA.

## Fuente

Planilla Excel con formato categoría×mes (igual patrón que Apo, no filas fijas como PT). Ejemplo de referencia (foto entregada por el usuario):

```
                          ene-18   feb-18   mar-18
(+) Ingresos por Arriendos  6.440    6.434    6.438
(+) Ingresos por Arriendos  6.440    6.434    6.438   ← fila subtotal duplicada, IGNORAR
(+) Contribuciones             —        —        —
(-) Administración           -175     -175     -175
(-) Provision Reparaciones    -36      -20      -70
(-) Aseo, Mantención y Otros    0        0        0
(-) Otros Gastos Operacionales  —        —        —
(-) IVA                        —        —        —
(-) Seguros                    0        0        0
        NOI Mensual         6.229    6.240    6.193
```

Verificado: `6440 + 0 - 175 - 36 + 0 + 0 + 0 + 0 = 6229` ✓ (coincide exacto con NOI Mensual reportado). Confirma que la suma de las 7 categorías (sin la fila duplicada) reproduce el NOI sin ajustes adicionales.

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

**Normalización de nombres de categoría:** función `_norm()` tolerante a tildes/mayúsculas/mojibake (U+FFFD) y variantes de espaciado, siguiendo el mismo patrón que `ingest_er_apoquindo.py` — la planilla real puede traer variantes de encoding no vistas en la foto de referencia.

**Manejo de la fila duplicada:** el parser debe detectar la segunda ocurrencia de "Ingresos por Arriendos" (mismo nombre normalizado ya visto en esa hoja) y omitirla explícitamente, no simplemente tomar la última coincidencia (para evitar que un futuro cambio de orden en la planilla invierta silenciosamente cuál fila se usa).

**Validación de integridad (obligatoria, no opcional):** para cada periodo, sumar los montos de las 7 categorías ingresadas y compararla contra el valor de la fila "NOI Mensual" de la misma planilla. Si no cuadra exacto (tolerancia de redondeo ~1e-6), el ingest debe fallar con un error explícito indicando el periodo y el delta — no se persiste ese periodo. Esto sigue la regla ya establecida en memoria (`feedback_gastos_check_suma`): siempre verificar que la suma de componentes cuadre con el total reportado por la fuente.

**Idempotencia:** por `file_hash` (sha256 del archivo), igual que PT/Apo — reingestas del mismo archivo no duplican filas.

**CLI:** `--dry-run` para previsualizar sin persistir, mismo patrón que `ingest_er_apoquindo.py`.

### Test

`tests/db/test_ingest_er_inmosa.py` — fixture xlsx construida programáticamente (vía `openpyxl`, no un archivo real) que replica la tabla de la foto (3 meses: ene/feb/mar-2018), verificando:
- Se persisten 7 categorías × 3 meses = 21 filas en `raw_er_activo_line` (no 8×3=24 — la fila duplicada se descarta).
- NOI derivado (`SUM(monto_clp) WHERE es_operacional=1`) = 6229 / 6240 / 6193 para cada mes respectivamente.
- Idempotencia: reingestar el mismo archivo no crea filas duplicadas (mismo `file_hash`).
- La validación de integridad falla explícitamente si se corrompe un valor de prueba de forma que la suma no cuadre con "NOI Mensual".

### Fuera de scope

- Descubrimiento de la ubicación del archivo real en SharePoint (el usuario proveerá el archivo/ruta cuando esté listo).
- Consolidación del NOI/Ingresos a nivel fondo TRI usando `v_activo_fondo_efectivo` (ya construida en la migración 049; se usará una vez estén todos los activos pendientes ingresados, o incrementalmente si el usuario lo pide antes).
- Sucden, Viña Centro, Curicó, Apo3001 — se abordan en specs separados cuando el usuario entregue sus planillas respectivas.
