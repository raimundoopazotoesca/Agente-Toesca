---
tipo: agente
nombre: Arquitectura del Agente Toesca
archivo: agent.py
actualizado: 2026-05-01
---

# Arquitectura del Agente Toesca

## Stack técnico

- **LLM**: Gemini 2.5 Flash vía `generativelanguage.googleapis.com/v1beta/openai/`
- **Excel large files**: `zipfile` + XML directo (3x más rápido que openpyxl para archivos 14MB+/87 hojas)
- **Excel small files**: `openpyxl`
- **PDFs de EEFF**: `MarkItDown`
- **Email/Outlook**: `pywin32` (COM) — solo Windows
- **SharePoint**: sincronizado localmente; servidor de red en unidad `R:`

## Archivos principales

| Archivo | Rol |
|---------|-----|
| `agent.py` | Runner principal: loop de conversación, system prompt |
| `config.py` | Variables de entorno |
| `tools/registry.py` | `TOOL_DEFINITIONS`, `_dispatch`, selección dinámica por intent |
| `tools/memory_tools.py` | Contexto, historial, KPIs (SQLite `agente_toesca.db`) |

## Variables de entorno (.env)

| Variable | Valor típico |
|----------|-------------|
| `GEMINI_API_KEY` | _(secreto)_ |
| `LOCAL_FILES_DIR` | `R:\` |
| `WORK_DIR` | `C:\Users\raimundo.opazo\automation_agent\work` |
| `SHAREPOINT_DIR` | `C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos` |
| `RENTA_COMERCIAL_DIR` | `C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\Control de Gestión\CDG Mensual` |
| `FONDOS_DIR` | Canonico en codigo: `tools/sharepoint_paths.py` bajo `Fondos/` |
| `SALDO_CAJA_DIR` | `C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\Control de Gestión\Saldo Caja` |

## Compatibilidad

- `email_tools.py`: **solo Windows** — en Mac retorna error claro sin crashear
- Resto del agente: **100% cross-platform**

## Vínculos

- [[agente/herramientas]] — catálogo de tools
- [[conceptos/ooxml]] — arquitectura XML directo en XLSX
- [[overview]]
