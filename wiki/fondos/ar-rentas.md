---
tipo: fondo
nombre: "Toesca Rentas Inmobiliarias"
clave: "A&R Rentas"
nemotecnicos: ["CFITOERI1A", "CFITOERI1C", "CFITOERI1I"]
carpeta_fondos: "FI Toesca Rentas"
estado: activo
fuentes: 0
actualizado: 2026-05-01
---

# A&R Rentas

## Descripción

Fondo de inversión inmobiliario con tres series (A, C, I). Tiene VR Bursátil mensual para cada serie.

## Activos

- [[activos/vina-centro]]
- [[activos/mall-curico]]
- [[activos/inmosa]]

## Nemotécnicos

| Nemotécnico | Serie |
|-------------|-------|
| `CFITOERI1A` | A |
| `CFITOERI1C` | C |
| `CFITOERI1I` | I |

## Celdas fecha en hoja Input

| Campo | Celda |
|-------|-------|
| Fecha contable | D10 |
| Fecha bursátil | C10 |

## Hoja en CDG XLSX

- Sheet: `xl/worksheets/sheet17.xml`
- Tabla: `Tabla1` (`xl/tables/table4.xml`)
- **Columna C usa fórmulas compartidas**: `<f t="shared" ref="C590:C621" si="127">` — no sobreescribir si ya existe

## Flujo de actualización mensual

1. `agregar_vr_bursatil_rentas(...)` — series A/C/I (mensual)
2. Si fin de trimestre: `agregar_vr_contable_rentas(...)`
   - Misma regla de desfase trimestral que [[fondos/ar-pt]]

## Vínculos

- [[activos/vina-centro]] · [[activos/mall-curico]] · [[activos/inmosa]]
- [[procesos/cdg-mensual]]
- [[conceptos/ooxml]]
- [[overview]]
