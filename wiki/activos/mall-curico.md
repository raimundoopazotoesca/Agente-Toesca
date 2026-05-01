---
tipo: activo
nombre: "Mall Curicó"
fondo: "A&R Rentas"
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

## Vínculos

- [[fondos/ar-rentas]]
- [[activos/vina-centro]]
- [[procesos/noi-rcsd]]
- [[conceptos/fechas-excel]]
