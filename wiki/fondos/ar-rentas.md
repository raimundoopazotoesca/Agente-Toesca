---
tipo: fondo
nombre: "Toesca Rentas Inmobiliarias"
clave: "A&R Rentas"
nemotecnicos: ["CFITOERI1A", "CFITOERI1C", "CFITOERI1I"]
carpeta_fondos: "FI Toesca Rentas"
estado: activo
fuentes: 1
actualizado: 2026-05-06
---

# A&R Rentas

## Descripción

Fondo de inversión inmobiliario con tres series (A, C, I). Tiene VR Bursátil mensual para cada serie.

## Activos y estructura

Estructura validada por el usuario el 2026-05-06 a partir del diagrama del fondo:

| Participación TRI | Vehículo / sociedad | Activo final | Peso histórico diagrama | Peso pro forma sin Machalí |
|-------------------|---------------------|--------------|--------------------------|-----------------------------|
| 100% | Inmobiliaria Machalí Ltda | Strip Center Paseo Machalí | 4% | 0%; liquidado |
| 100% | Inmobiliaria Chañarcillo Ltda | Bodegas Maipú (Sucden) | 5% | 5,21% |
| 100% | Inmobiliaria Chañarcillo Ltda | 68,5% Apoquindo 3001 | 6% | 6,25% |
| 100% | Inmobiliaria VC SpA -> Inmobiliaria Viña Centro SpA | Mall Paseo Viña Centro | 34% | 35,42% |
| 80% | Power Center Curicó SpA | Power Center Paseo Curicó | 6% | 6,25% |
| 43% | Inmobiliaria e Inversiones Senior Assist Chile S.A. | 6 residencias adulto mayor / INMOSA | 12% | 12,50% |
| 33,3% | Fondo Toesca Rentas Inmobiliarias PT -> Torre A S.A. e Inmobiliaria Boulevard PT SpA | Torre A y Boulevard Parque Titanium | 16% | 16,67% |
| 30% | Fondo Toesca Rentas Inmobiliarias Apoquindo -> Inmobiliaria Apoquindo SpA | Apoquindo 4501 y 4700 | 17% | 17,71% |

Notas:

- Machalí fue liquidado y ya no forma parte del fondo. No considerarlo activo vigente.
- Los pesos históricos del diagrama sumaban 100%. Al excluir Machalí, los pesos vigentes de referencia se rebajan sobre 96%.
- Estos pesos pro forma son solo referencia si no hay una fuente más actualizada como CDG, fact sheet o EEFF.

## Vínculos de activos

- [[activos/vina-centro]]
- [[activos/mall-curico]]
- [[activos/inmosa]]
- [[activos/apoquindo-3001]]
- [[activos/parque-titanium]]
- [[activos/apoquindo]]

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
