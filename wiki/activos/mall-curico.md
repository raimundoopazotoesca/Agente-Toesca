---
tipo: activo
nombre: "Mall Curicó"
fondo: "TRI"
administrador: "Tres Asociados"
filas_noi: "258–278"
fuentes: 0
actualizado: 2026-05-01
---

# Mall Curicó

## Datos básicos

- **Fondo**: [[fondos/ar-rentas]]
- **Administrador**: Tres Asociados
- **Filas NOI-RCSD**: 258–278

## Fuente canónica en la DB (desde 2026-07-14)

`raw_er_activo_line`, `activo_key='Mall Curicó'`, vía `tools/db/ingest_er_curico.py`.
Fuente: `RAW/NOI Curico.xlsx` (SharePoint), no el CDG. Detalle completo del
diseño, la definición de NOI (incluye 3 cuentas huérfanas de la fuente) y la
validación de integridad en `wiki/db.md` → sección "Ingesta ER Mall Curicó".

**Nota**: existía una ingesta previa vía `actualizar_er_curico` (dual-write
desde el ER embebido en el CDG) que quedó `superseded`.

## Fuente de datos

**Archivo**: `MM-AAAA INFORME EEFF POWER CENTER CURICO SPA.xlsx`
**Hoja**: "ESTADO DE RESULTADO"
**Función**: `actualizar_er_curico`

## Estructura en CDG

- **Section 1** (filas 3–112, cols E–BZ): datos mensuales reales en CLP
  - Col B = código de cuenta, col E = valor CLP mes actual
- **Section 2** (filas 113+): agregaciones con **fórmulas que referencian Section 1** → auto-calcula
- NOI-RCSD referencia Section 2 → NOI se actualiza automáticamente al escribir Section 1
- Fila de fechas: **fila 4** (seriales Excel)
- Fila de UF: **fila 3**

## Notas críticas

A diferencia de [[activos/vina-centro]], la Section 2 de Curicó tiene fórmulas — solo hay que escribir Section 1 y el resto se calcula solo.

## Vacancia (rent roll)

Fuente: `raw_rent_roll_line`, `activo_key='Mall Curicó'`. Misma regla que
[[activos/vina-centro]] (confirmada 2026-07-30): se cuentan **todas** las
unidades vacantes, incluidos módulos, tanto en numerador como denominador.

**Ponderación 80%**: el fondo es dueño del 80% del activo Curicó, así que
para reportar m² absolutos (no el %) se multiplica por 0,8. El % de
vacancia no cambia (se pondera parejo numerador y denominador).

Periodo 2026-05: vacante = 3.017,87 m² (27 unidades, ponderado: 2.414,30 m²)
/ total 10.811,47 m² (ponderado: 8.649,18 m²) = **27,91%** en ambos casos.

## Vínculos

- [[fondos/ar-rentas]]
- [[activos/vina-centro]]
- [[procesos/noi-rcsd]]
- [[conceptos/fechas-excel]]
