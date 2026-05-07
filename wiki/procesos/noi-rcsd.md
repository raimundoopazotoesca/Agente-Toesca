---
tipo: proceso
nombre: "Actualización NOI-RCSD"
frecuencia: mensual
herramientas: [noi]
actualizado: 2026-05-01
---

# Flujo mensual — NOI-RCSD

## Activos y fuentes

| Activo | Filas en NOI-RCSD | Fuente | Función |
|--------|------------------|--------|---------|
| [[activos/inmosa\|INMOSA]] | 287–295 | ER-FC INMOSA (`Fondos/Rentas TRI/Activos/INMOSA/Flujos`) | `actualizar_noi_inmosa` |
| [[activos/parque-titanium\|Parque Titanium]] | 335–379 | hoja 'NOI PT' del RR JLL (WORK_DIR) | `actualizar_noi_pt` |
| [[activos/vina-centro\|Viña Centro]] | 196–214 | INFORME EEFF Viña Centro (SharePoint TresA/Viña Centro) | `actualizar_er_vina` |
| [[activos/apoquindo\|Fondo Apoquindo]] | 426–456 | hoja 'NOI PT' del RR JLL (WORK_DIR) | `actualizar_noi_apoquindo` |
| [[activos/apoquindo-3001\|Apoquindo 3001]] | 468–476 | hoja 'NOI PT' del RR JLL (WORK_DIR) | `actualizar_noi_apo3001` |
| [[activos/mall-curico\|Mall Curicó]] | 258–278 | INFORME EEFF Curicó (SharePoint TresA/Curico) | `actualizar_er_curico` |

## Archivos fuente

| Archivo | Origen | Hoja |
|---------|--------|------|
| `{AAMM} Rent Roll y NOI.xlsx` | Nicole Carvajal (JLL) | "NOI PT" → datos PT, Apoquindo, Apo3001 |
| `MM-AAAA INFORME EEFF POWER CENTER CURICO SPA.xlsx` | Tres Asociados | "ESTADO DE RESULTADO" |
| `MM-AAAA INFORME EEFF VIÑA CENTRO SPA*.xlsx` | Tres Asociados | "ESTADO DE RESULTADO AAAA" |

Los EEFF de Curicó y Viña: **col B = código de cuenta, col E = valor CLP mes actual**.

## Estructura ER Curicó en CDG

- Section 1 (filas 3–112, cols E–BZ): datos mensuales reales en CLP → el agente escribe aquí
- Section 2 (filas 113+): agregaciones con fórmulas que referencian Section 1 → auto-calcula
- NOI-RCSD referencia Section 2 → NOI se actualiza automáticamente al escribir Section 1

## Estructura ER Viña en CDG

- Section 1 (filas 5–90+, cols B–CA+): datos mensuales en UF (CLP/UF_mes)
- Section 2 (filas 95–119+): **valores estáticos sin fórmulas** → requiere actualización directa _(pendiente)_
- NOI-RCSD referencia Section 2 de ER Viña
- Fila de fechas: fila 6 (seriales Excel)
- Fila de UF: fila 5

## Fila de fechas NOI-RCSD

NOI fila 7 = row de fechas. Col CY = Ene 2026.

## Mapeo NOI-RCSD → ER

Hardcoded en `_NOI_CURICO_MAP` y `_NOI_VINA_MAP` en `noi_tools.py`.
`actualizar_er_curico/vina` escribe ER Section 1 + columna NOI del mes en un solo zip.

## Vínculos

- [[activos/parque-titanium]] · [[activos/apoquindo]] · [[activos/apoquindo-3001]]
- [[activos/vina-centro]] · [[activos/mall-curico]] · [[activos/inmosa]]
- [[procesos/cdg-mensual]]
- [[conceptos/ooxml]]
