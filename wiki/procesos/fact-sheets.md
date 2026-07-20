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
columnas distintas. Se implementa vía `cfg["page2"]` en `FONDOS_CFG` (solo definido por ahora
para PT); si un fondo no tiene `page2`, el HTML muestra un aviso "pendiente" en vez de la tabla.

Estructura de PT (basada en fact sheet PT octubre 2025):
- Tabla "Resumen Performance Activos del Fondo": columnas agrupadas por activo (Torre A S.A. /
  Inmob. Boulevard PT SpA), cada uno con sus propias subcolumnas (Oficinas/Locales/Total/
  Bodegas/Estacionamientos); filas de m², renta y absorción — actualmente todo en placeholder
  ("—"), pendiente de wire a `raw_rent_roll_line`.
- 4 gráficos (composición por rubro arrendatario, composición por tipo de activo, evolución
  NOI+RCSD, evolución ingresos/NOI/vacancia) + gráfico de perfil de vencimiento de contratos y
  recaudación consolidada U12M: todos como `chart-box` con placeholder `Pendiente de datos`
  hasta definir fuente y forma de cálculo de cada serie.

TRI y Apo: pendiente traer su propio fact sheet de referencia (layout distinto al de PT) antes
de definir su `page2`.

## Vínculos

- [[fondos/ar-pt]] · [[fondos/ar-apoquindo]] · [[fondos/ar-rentas]]
- [[agente/herramientas]]
