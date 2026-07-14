---
tipo: activo
nombre: "Apoquindo 3001"
fondo: "TRI"
administrador: "JLL"
filas_noi: "468–476"
fuentes: 1
actualizado: 2026-07-14
---

# Apoquindo 3001

## Datos básicos

- **Fondo**: TRI, vía sociedad Inmobiliaria Chañarcillo Ltda (participación 0.685)
- **Administrador**: JLL (Nicole Carvajal)
- **Filas NOI-RCSD**: 468–476

## Ingesta a la DB (fuente canónica actual)

**Archivo**: `RAW/NOI 3001.xlsx` (SharePoint), hoja `Hoja1`
**Módulo**: `tools/db/ingest_er_apo3001.py`
**activo_key**: `Apo3001`

8 categorías (Taipei, Otros, Gastos Comunes, Administración, Comisión
Corredor, Provision Incobrables, Contribuciones + Sobretasa, Seguros) ×
77 periodos (2020-01 a 2026-05) = 616 filas en `raw_er_activo_line`. La
fila agregada "(+) Ingresos por Arriendos" de la fuente se descarta —
se usa el sub-detalle Taipei + Otros (ver [[db]] para el hallazgo completo).
NOI se deriva como `SUM(monto_clp) WHERE es_operacional=1`, no se persiste.

## Fuente de datos legacy (CDG, coexiste sin resolver)

**Archivo**: `{AAMM} Rent Roll y NOI.xlsx`
**Hoja**: "NOI PT"
**Función**: `actualizar_noi_apo3001`

## Vínculos

- [[fondos/ar-rentas]]
- [[activos/apoquindo]]
- [[procesos/noi-rcsd]]
- [[db]]
