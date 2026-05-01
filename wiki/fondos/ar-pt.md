---
tipo: fondo
nombre: "Toesca Rentas Inmobiliarias PT"
clave: "A&R PT"
nemotecnico: "CFITRIPT-E"
carpeta_fondos: "FI Toesca Rentas PT"
estado: activo
fuentes: 0
actualizado: 2026-05-01
---

# A&R PT

## Descripción

Fondo de inversión inmobiliario. Tiene VR Bursátil mensual. Actualización mensual con precio cuota.

## Activos

- [[activos/parque-titanium]]

## Nemotécnico

| Nemotécnico | Serie |
|-------------|-------|
| `CFITRIPT-E` | única |

## Celdas fecha en hoja Input

| Campo | Celda |
|-------|-------|
| Fecha contable | D11 |
| Fecha bursátil | C11 |

## Hoja en CDG XLSX

- Sheet: `xl/worksheets/sheet16.xml`
- Tabla: `Tabla13` (`xl/tables/table3.xml`)

## Flujo de actualización mensual

1. `agregar_vr_bursatil_pt(...)` — mensual
2. Si fin de trimestre: `agregar_vr_contable_pt(...)`
   - CDG marzo → `leer_eeff(mes=12, año=año-1)`
   - CDG junio → `leer_eeff(mes=3, año=año)`
   - CDG sep → `leer_eeff(mes=6, año=año)`
   - CDG dic → `leer_eeff(mes=9, año=año)`

## Vínculos

- [[activos/parque-titanium]]
- [[procesos/cdg-mensual]]
- [[conceptos/ooxml]]
- [[overview]]
