---
tipo: overview
actualizado: 2026-05-04
fuentes_totales: 0
paginas_wiki: 13
---

# Overview — Agente Toesca

El Agente Toesca es un agente de automatización para la gestión de fondos inmobiliarios de Toesca Capital. Procesa información financiera mensual y trimestral a partir de múltiples fuentes (Excel, PDF, correo, SharePoint, web) y actualiza reportes de control de gestión.

## Stack

- **LLM**: Gemini 2.5 Flash vía API compatible OpenAI
- **Backend**: Python, pywin32 (Outlook), openpyxl, XML directo para XLSX grandes
- **Storage**: SQLite (memoria del agente), archivos en servidor R: y SharePoint
- **Plataforma**: Windows (email/COM) + cross-platform (resto)

## Fondos gestionados

| Fondo | Clave | Nemotécnico(s) |
|-------|-------|----------------|
| [[fondos/ar-apoquindo\|A&R Apoquindo]] | `A&R Apoquindo` | — |
| [[fondos/ar-pt\|A&R PT]] | `A&R PT` | `CFITRIPT-E` |
| [[fondos/ar-rentas\|A&R Rentas]] | `A&R Rentas` | `CFITOERI1A/C/I` |

## Activos principales

[[activos/parque-titanium]] · [[activos/apoquindo]] · [[activos/apoquindo-3001]] · [[activos/vina-centro]] · [[activos/mall-curico]] · [[activos/inmosa]]

## Procesos clave

- [[procesos/cdg-mensual]] — actualización mensual del CDG Rentas Comerciales
- [[procesos/noi-rcsd]] — actualización hoja NOI-RCSD con datos de activos
- [[procesos/fact-sheets]] — generación de Fact Sheets PPTX por fondo

## Herramientas del agente

Ver [[agente/herramientas]] para catálogo completo. Ver [[agente/arquitectura]] para el stack técnico detallado.
