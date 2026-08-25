# Fund Financial Surface v1

Superficie gobernada para preguntas financieras de fondo y serie: distribuciones,
dividend yield, TIR, valor cuota, descuento/premio bursátil, amortizaciones,
capital, cuotas y patrimonio.

No es un pipeline nuevo. Es una extensión del mismo Generic Semantic Core que ya
sirve NOI, LTV, vacancia y conceptos contables: mismo catálogo, mismo executor,
misma evidencia, mismos guards, misma presentación determinista.

## 1. La extensión arquitectónica

Una sola estrategia de acceso nueva, `dimensioned`, en
`tools/analytics/catalog_v1.yaml`. Todo lo que cambia entre familias de métricas
es **dato**, no código:

| Concepto | Dónde vive |
|---|---|
| Sub-entidad observada (`series`, `credit`, `fund_template`) | `access.scope` |
| Dimensiones semánticas y sus valores | `access.dimensions` |
| Qué fuente selecciona cada combinación | `access.variants` |
| Contrato temporal de la fuente | `variant.source.temporal` |
| Horizonte de observación real | `access.observed_horizon` |

Piezas de soporte:

- `SemanticQuery.dimensions` / `.selector` — dimensiones genéricas y selector de
  sub-entidad. No hay campos por KPI.
- `MetricDefinition.temporal_completeness` — `dense` (un mes faltante es un
  hueco) vs `event` (un mes sin evento no es un hueco).
- Operación derivada `discount_premium` en `derived_claims.py`.
- Una capability, `analytics_lookup_dimensional`, cuyo esquema JSON se **deriva**
  del catálogo (métricas, dimensiones y valores permitidos).

**Series es una dimensión, no una entidad falsa.** Se llega a ella siempre por
fondo + `series`. Conserva identidad canónica propia (`dim_serie.nemotecnico`)
únicamente para que un hecho de TRI A nunca pueda colisionar con uno de TRI C o
TRI I a través de evidencia, claim, tabla o contexto durable.

## 2. Métricas, autoridad de fuente y contrato temporal

| Métrica | Grano | Dimensiones | Autoridad | Contrato temporal |
|---|---|---|---|---|
| `dividend_yield_serie` | serie | `valuation_basis` | `derived_kpi.dy` (variante `bursatil`/`contable`), persistido | ratio, sin agregación |
| `tir_serie` | serie | `return_basis`, `return_window` | `derived_kpi.tir_*`, persistido | ratio, sin agregación |
| `valor_cuota_serie` | serie | `valuation_basis` | `raw_valor_cuota_contable` (libro) / `raw_valor_cuota_bursatil` (mercado) | punto en el tiempo; última observación del mes |
| `distribucion_por_cuota_serie` | serie | `flow_type` | `raw_dividendo` | evento; SUM permitido sobre eventos observados |
| `capital_suscrito_serie` | serie | — | `raw_capital_suscrito` | as-of: última observación ≤ período pedido |
| `cuotas_en_circulacion_serie` | serie | — | `raw_cuota_en_circulacion` | as-of |
| `patrimonio_contable_serie` | serie | — | `v_serie_patrimonio.patrimonio_libro_uf` | punto en el tiempo |
| `patrimonio_bursatil_serie` | serie | — | `raw_valor_cuota_bursatil.patrimonio_bursatil_uf` | punto en el tiempo |
| `amortizacion_capital_fondo` | fondo | — | `raw_amortizacion` (`CONSOLIDADO_{fondo}`) | flujo denso, acotado al horizonte observado |
| `amortizacion_capital_credito` | crédito | — | `raw_amortizacion` vía `dim_credito` | flujo por evento, acotado al horizonte observado |

### Decisiones de autoridad explícitas

- **Valor cuota contable**: la autoridad es `raw_valor_cuota_contable`.
  `derived_kpi.valor_cuota_libro` (4 filas rezagadas del mismo concepto) **no se
  referencia en el catálogo**, para que dos fuentes no puedan discrepar en
  silencio sobre la misma cifra.
- **DY y TIR**: se exponen como KPI persistido y trazable. No se reconstruyen
  flujos de caja.
- **Amortización consolidada vs por crédito**: son conceptos **distintos**, no
  duplicados. El consolidado incluye prepagos y refinanciamientos que los cuadros
  de pago por facilidad no tienen (2025: 206.413,88 UF consolidado vs 41.422,71
  UF sumando calendarios). Se modelan por separado y nunca se sustituyen entre sí.
- **Capital suscrito**: `raw_capital_suscrito` directo, no
  `v_capital_suscrito_serie` — cuya columna `capital_suscrito_uf` es un
  `MAX()` sobre toda la historia y no una observación fechada.

## 3. Calidad de dato: qué se maneja y cómo

1. **Filas duplicadas de dividendos.** `raw_dividendo` tiene 86 filas
   `legacy_fact_dividendo` que duplican eventos ya presentes y no traen monto UF.
   El contrato `event` deduplica por (serie, fecha de pago) tomando la
   observación más reciente con valor, así que un evento nunca se cuenta dos
   veces.
2. **`monto_uf_cuota` nulo.** Una medición nula se excluye en la fuente: no es
   cero, es ausencia de observación.
3. **Duplicado en `raw_valor_cuota_contable`** (dos filas idénticas para
   2025-12): el contrato `period_point` colapsa a una observación por período.
4. **Mojibake de `fuente`.** En la DB actual el valor está bien codificado
   (`LarraínVial`). Aun así `fuente` sólo viaja en *provenance*: no se renderiza
   como parte de la respuesta.
5. **Cola futura de amortización.** `CONSOLIDADO_TRI` llega hasta 2072-05. El
   `observed_horizon` (último cierre observado de `derived_kpi.deuda_consolidada`
   del fondo) acota la ventana consultada; una ventana enteramente futura no
   devuelve observación. Un `MAX(periodo)` ingenuo no puede aparecer como
   "última amortización real".
6. **Capital suscrito antiguo.** El hecho conserva el período en que se observó
   (TRI A: 2021-09), de modo que se lee "a septiembre de 2021" y nunca se
   presenta como vigente hoy.
7. **Patrimonio bursátil sin cuotas.** Desde 2026-06 las filas de mercado no
   traen `cuotas`, así que el patrimonio bursátil de esos meses es **NONE**, no
   cero.

## 4. Ambigüedad y fail-closed

Una dimensión sin `default` es obligatoria. Si falta, el executor rechaza con
`dimension_required` y el runtime responde con una aclaración que enumera las
opciones reales, en vez de elegir una variante.

- "¿Cuál es la TIR de TRI?" → pide base (bursátil/contable) y ventana (desde
  inicio / U12M / YTD).
- "DY bursátil de TRI A en junio 2026" → responde sin aclarar: ya está
  identificada.
- Combinación inexistente (p. ej. TIR bursátil YTD) → `unavailable_dimension_combination`,
  con las combinaciones disponibles. Nunca se sustituye por otra.

## 5. Descuento / premio

Es una claim **derivada**, `discount_premium`, no aritmética en prosa:
`(observado / referencia - 1) × 100`, con `lhs` = valor libro y `rhs` = valor
bursátil. Exige que ambas observaciones sean **de la misma entidad y del mismo
período**; si no, falla cerrado. No existe convención defendible para comparar
una cotización diaria contra un cierre contable trimestral arbitrariamente
anterior, así que la respuesta correcta es pedir un período donde ambas existan.

Se renderiza como "un descuento de X%" / "un premio de X%": el signo lleva el
significado de negocio, no se le entrega al lector un porcentaje con signo.

## 6. Política monetaria

Los hechos permanecen nativos. `valor_cuota_serie` es CLP nativo y **lleva su
propia referencia de conversión gobernada** (`uf_dia` de la misma fila y la misma
fecha), así que el default global UF se aplica con linaje real, y "en pesos"
devuelve el CLP nativo sin volver a consultar. Cuando no hay referencia de
conversión, el valor se muestra en su unidad nativa: nunca se convierte a UF por
defecto sin contrato.

Un monto por cuota es una fracción de UF; el formateador eleva la precisión para
magnitudes sub-unitarias, de modo que una distribución real jamás se redondea a
"0 UF".

## 7. Qué NO soporta v1 (explícito)

- **"Patrimonio" genérico**: no existe una métrica llamada sólo `patrimonio`.
  Existen `patrimonio_contable_serie` y `patrimonio_bursatil_serie`. Un concepto
  ambiguo no se resuelve eligiendo la vista que esté a mano.
- **Patrimonio de fondo agregando series**: no se publica. Un fondo multi-serie
  devuelve el desglose por serie; no se inventa un total.
- **Distribución total del fondo en dinero**: la fuente es *por cuota*. No se
  multiplica por un número de cuotas de otro período para fabricar un total.
- **TIR bursátil YTD**: no existe como KPI persistido. Se rechaza explícitamente
  en vez de sustituirla por otra ventana. (`tir_contable_ytd` sí existe y es
  escasa: sólo Apo.)
- **Amortización programada futura**: fuera del horizonte observado no se
  reporta. Distinguir "programado" como categoría propia queda para un stage
  posterior.
- **Composición por arrendatario, rubros, vencimientos de contratos**: fuera de
  alcance de este stage.
