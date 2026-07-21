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
columnas distintas. Se implementa vía `cfg["page2"]` en `FONDOS_CFG` (definido para PT y Apo;
TRI aún pendiente); si un fondo no tiene `page2`, el HTML muestra un aviso "pendiente" en vez
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

TRI: pendiente traer su propio fact sheet de referencia (layout distinto) antes de definir
su `page2`.

## Vínculos

- [[fondos/ar-pt]] · [[fondos/ar-apoquindo]] · [[fondos/ar-rentas]]
- [[agente/herramientas]]
