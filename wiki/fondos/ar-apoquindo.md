---
tipo: fondo
nombre: "Toesca Rentas Inmobiliarias Apoquindo"
clave: "A&R Apoquindo"
nemotecnico: ""
carpeta_fondos: "FI Toesca Rentas Apoquindo"
estado: activo
fuentes: 0
actualizado: 2026-05-01
---

# A&R Apoquindo

## Descripción

Fondo de inversión inmobiliario. **No tiene VR Bursátil** (a diferencia de PT y Rentas).

## Activos

- [[activos/apoquindo]]
- [[activos/apoquindo-3001]]

## Celdas fecha en hoja Input

| Campo | Celda |
|-------|-------|
| Fecha contable | C9 |
| Fecha bursátil | D9 |

## Hoja en CDG XLSX

- Sheet: `xl/worksheets/sheet15.xml`
- Tabla: `Tabla133` (`xl/tables/table2.xml`)
- Columnas: A=YEAR, B=MONTH, C=ID, D=Fecha/SF, E=Detalle, F=Serie, G=Tipo, H=Monto$, I=Precio/cuota, J=Cuotas, K=UF, L=MontoUF, M=MontoUF/cuota, N-Y=Libro/Bolsa

## Notas críticas

- **Sin VR Bursátil**: `agregar_vr_bursatil_apoquindo` no existe en el flujo mensual
- Los EEFF para fin de trimestre: CDG mes X → EEFF del trimestre anterior (ver [[procesos/cdg-mensual]])

## Vínculos

- [[procesos/cdg-mensual]]
- [[conceptos/ooxml]]
- [[overview]]
