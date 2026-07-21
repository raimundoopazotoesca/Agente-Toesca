---
tipo: proceso
nombre: "Actualización Fact Sheets"
frecuencia: mensual
herramientas: [factsheet]
actualizado: 2026-05-01
---

# Fact Sheets PPTX

## Descripción

Actualización de presentaciones PPTX mensuales por fondo.

## Fondos cubiertos

| Clave | Fondo |
|-------|-------|
| PT | [[fondos/ar-pt]] |
| APO | [[fondos/ar-apoquindo]] |
| TRI | [[fondos/ar-rentas]] |

## Herramienta

`factsheet_tools.py` → `factsheet` tool

## Notas

_Pendiente documentar detalles de la implementación una vez que se ejecute por primera vez._

## Fact Sheet HTML dinámico (`factsheet.html`)

Generador: `scripts/build_factsheet.py` (lee `memory/agente_toesca_v2.db`, arma `FONDOS_CFG`
por fondo + JSON de datos, emite `factsheet.html` autocontenido con selectores TRI/PT/Apo,
navegación de período y modo admin con trazabilidad por celda).

**Página 2 (Resumen Performance Activos + gráficos)**: el layout de la página 2 **no se
comparte entre fondos** — cada uno tiene su propio fact sheet de referencia con secciones y
columnas distintas. Se implementa vía `cfg["page2"]` en `FONDOS_CFG` (definido para TRI, PT y
Apo); si un fondo no tiene `page2`, el HTML muestra un aviso "pendiente" en vez
de la tabla. El renderizado (`renderPerfActivosHeader` en el JS embebido) es genérico: arma
columnas/filas a partir de `page2.perf_groups`/`perf_rows` — agregar un fondo nuevo es solo
config, no requiere tocar el HTML/JS.

Estructura de PT (basada en fact sheet PT octubre 2025):
- Tabla "Resumen Performance Activos del Fondo": columnas agrupadas por activo (Torre A S.A. /
  Inmob. Boulevard PT SpA), cada uno con sus propias subcolumnas (Oficinas/Locales/Total/
  Bodegas/Estacionamientos); filas de m², renta y absorción.
- 4 gráficos (composición por rubro arrendatario, composición por tipo de activo, evolución
  NOI+RCSD, evolución ingresos/NOI/vacancia) + gráfico de perfil de vencimiento de contratos y
  recaudación consolidada U12M: todos como `chart-box` con placeholder `Pendiente de datos`
  hasta definir fuente y forma de cálculo de cada serie.
- Único fondo con `perf_data` wired (`_fetch_perf_data` → `tools/db/rent_roll_stats.py`) —
  la tabla ya rellena m²/renta/vacancia por período desde `raw_rent_roll_line`.

Estructura de Apo (basada en fact sheet Apo octubre 2025, agregado 2026-07-21):
- Tabla agrupada por edificio en vez de por sociedad (ambos activos están bajo la misma
  Inmobiliaria Apoquindo S.A.): grupos "Apoquindo 4501" / "Apoquindo 4700", mismas subcolumnas
  que PT (Oficinas/Locales Comerciales/Total/Bodegas/Estacionamientos).
- Mismos 6 gráficos que PT con sus propias categorías: rubro arrendatario (13 rubros, ej. Otro,
  Servicios, Inmobiliaria...) y tipo de activo (Oficinas/Locales Comerciales/Estacionamientos/
  Bodegas).
- `_fetch_perf_data` todavía solo implementa PT — para Apo la tabla queda en placeholder ("—")
  hasta agregar el agrupamiento por edificio en `tools/db/rent_roll_stats.py` y wire de
  `raw_rent_roll_line` de Apo. Ir poblando la DB progresivamente activará estos valores sin
  tocar el layout.

Estructura de TRI (basada en fact sheet TRI enero 2026, agregado 2026-07-21):
- Tabla "Resumen Performance Activos del Fondo" consolida a nivel de **fondo paraguas**, no por
  sociedad/edificio: columnas planas (una por activo/subfondo, sin subcolumnas por tipo de
  espacio) — Paseo Viña Centro, Paseo Curicó, Centros Comerciales (subtotal Viña+Curicó),
  Residencias Adulto Mayor, Bodegas Sucden, Apoquindo 3001, Fondo Apoquindo (consolida
  Apoquindo 4501+4700), Fondo Rentas PT (consolida Torre A+Boulevard), + columna Total que
  agrega el renderer genérico. Mismas filas de m²/renta/absorción que PT/Apo.
- Mismos 6 `chart-box` que PT/Apo con categorías propias: rubro arrendatario (13 rubros: Otro,
  Mejoramiento del hogar, Banco, Supermercado, Retail, Residencia Adulto Mayor, Agroindustrial,
  Salud, Gastronomía, Servicios, Financiera, Deporte, Inmobiliaria) y tipo de activo
  (Oficinas/Comercial/Industrial/Residencias, alineado con las tablas anuales de Ingresos/NOI
  por tipo de activo del fact sheet de referencia — esas tablas anuales en sí no tienen slot
  propio en el layout genérico hoy, quedan fuera de esta primera pasada).
- `_fetch_perf_data` no implementa TRI todavía — tabla en placeholder ("—") hasta consolidar
  `raw_rent_roll_line` a nivel fondo paraguas (requiere sumar los activos directos del fondo +
  los de PT/Apo vía su participación). Ir poblando la DB activará estos valores sin tocar el
  layout, igual que con Apo.

## Página 3 (Detalle de Activos) y Página 4 (Notas + Análisis de Mercado)

Agregadas 2026-07-21, basadas en el fact sheet Apo octubre 2025 (única referencia disponible
hasta ahora para estas dos páginas — PT/TRI no tienen su página 3/4 traída todavía). Mismo
patrón que la página 2: `cfg["page3"]`/`cfg["page4"]` por fondo en `FONDOS_CFG`, con aviso
"pendiente" (`#page3-pending`/`#page4-pending`) cuando el fondo no los define.

**Página 3** (`cfg["page3"]`) — distribución copiada del orden de secciones del PDF de
referencia (arriba → abajo):
1. Dos columnas (`.cols`, igual que la página 1): "Aspectos Relevantes" (tabla `kv` desde
   `aspectos`, solo campos estáticos: dirección, superficie arrendable, administración) a la
   izquierda; donuts placeholder "GLA (m²)" e "Ingresos (UF/mes)" a la derecha.
2. "Status Actual Oficinas por Activo" y "Status Actual Locales por Activo": un `chart-box`
   placeholder por edificio en `edificios`, en grids separados (la referencia las muestra en
   dos filas, no mezcladas).
3. "Aspectos del Mes": caja gris (`.aspectos-mes-box`) con los 4 sub-bloques de la referencia
   (Colocaciones/Resultados/Recaudación/Vencimientos), cada uno en placeholder.
4. "Gestión de Vacancia" y "Resumen Anual — Vencimientos y Renovaciones": una tabla
   (`.subtable-box`) por edificio, lado a lado (`charts-grid-2`), con las filas de la
   referencia (`vacancia_rows`, `resumen_anual_rows`) — todas en placeholder "—".
5. "Tasaciones": una tabla con una fila por edificio + fila "Total Fondo", columnas Valor
   Tasación/Fecha Tasación/Deuda/LTV — en placeholder.

Todo el contenido dinámico queda en "—"/placeholder: no hay modelo de datos aún para vacancia
por edificio, resumen anual de vencimientos ni tasaciones (fuentes previstas:
`raw_rent_roll_line` para vacancia, `fact_tasacion` para tasaciones). Solo se copió la
**distribución** (secciones, agrupación por edificio, filas/columnas) — los valores llegan
cuando se pueble la DB.

**Página 4** (`cfg["page4"]`):
- `notas`: lista de 10 strings (i)-(x), generada por `_notas_template(has_bursatil)` — texto
  metodológico prácticamente idéntico entre fondos (solo cambia según si el fondo tiene o no
  valor bursátil); sin fechas hardcodeadas a propósito, ya que las fechas concretas de cada
  indicador se muestran en la página 1/2.
- Tabla de "Análisis de Mercado de Oficinas" (submercado JLL) queda fuera del layout genérico:
  no es un dato del fondo sino del mercado completo (mismo informe JLL para PT y Apo, que
  comparten submercado Las Condes/oficinas), viene de un reporte externo trimestral no
  modelado en la DB — placeholder fijo hasta decidir dónde vive esa data.

## Vínculos

- [[fondos/ar-pt]] · [[fondos/ar-apoquindo]] · [[fondos/ar-rentas]]
- [[agente/herramientas]]
