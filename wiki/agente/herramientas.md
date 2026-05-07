---
tipo: agente
nombre: Catálogo de herramientas
actualizado: 2026-05-01
---

# Herramientas del Agente Toesca

## Catálogo

| Archivo | Herramienta / Módulo | Descripción |
|---------|----------------------|-------------|
| `tools/memory_tools.py` | memoria | Contexto, historial, KPIs en SQLite |
| `tools/email_tools.py` | email | Outlook: listar, descargar adjuntos, enviar, buscar |
| `tools/sharepoint_tools.py` | sharepoint | Listar/copiar desde/hacia SharePoint |
| `tools/local_tools.py` | local | Listar/copiar desde/hacia servidor `R:` |
| `tools/excel_tools.py` | excel | Leer, validar, actualizar celdas |
| `tools/gestion_renta_tools.py` | gestión_renta | Planilla mensual CDG Rentas Comerciales |
| `tools/eeff_tools.py` | eeff | Leer PDFs de EEFF desde `Fondos/Rentas TRI`, `Fondos/Rentas PT` y `Fondos/Rentas Apoquindo` |
| `tools/datos_fs_tools.py` | datos_fs | Rentabilidad del fondo, TIR, hoja DATOS FS |
| `tools/caja_tools.py` | caja | Hoja Caja del CDG: copiar desde Saldo Caja, archivar |
| `tools/input_tools.py` | input | Hojas Input AP/PT/Ren: balance trimestral, fechas, dividendos |
| `tools/web_bursatil_tools.py` | web_bursatil | Precios cuota desde web |
| `tools/noi_tools.py` | noi | Hoja NOI-RCSD: ER Viña, Curicó, JLL PT/Apo/Apo3001, INMOSA |
| `tools/rentroll_tools.py` | rentroll | Validación RR JLL y Tres Asociados _(en desarrollo)_ |
| `tools/vacancia_tools.py` | vacancia | Vacancia mensual _(en desarrollo)_ |
| `tools/factsheet_tools.py` | factsheet | Actualización PPTX fact sheets (PT, APO, TRI) |

## Cómo agregar una herramienta nueva

1. Crear función en `tools/<nombre>.py`
2. Importar en `tools/registry.py`
3. Agregar entrada en `TOOL_DEFINITIONS` (dict con `type`, `function.name`, `function.description`, `function.parameters`)
4. Agregar lambda en `_dispatch` en `registry.py`

## Vínculos

- [[agente/arquitectura]]
- [[procesos/cdg-mensual]]
- [[procesos/noi-rcsd]]
