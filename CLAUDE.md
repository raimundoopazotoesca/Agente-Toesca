# Automation Agent — Contexto del proyecto

## Stack

- Python + Gemini 2.5 Flash vía API compatible con OpenAI (`generativelanguage.googleapis.com/v1beta/openai/`)
- `pywin32` para Outlook (COM), `openpyxl` para Excel
- SharePoint sincronizado localmente; servidor de red en unidad `R:`
- `pdfplumber` para extraer texto de PDFs de EEFF

## Arquitectura

```
agent.py              # runner principal: tool-calling loop + TOOL_DEFINITIONS + _dispatch
config.py             # variables de entorno
tools/
  email_tools.py      # Outlook: listar, descargar adjuntos, enviar, buscar
  sharepoint_tools.py # listar/copiar desde/hacia SharePoint
  local_tools.py      # listar/copiar desde/hacia servidor R:
  excel_tools.py      # leer, validar, actualizar celdas
  gestion_renta_tools.py  # planilla mensual CDG Rentas Comerciales
  eeff_tools.py       # leer PDFs de EEFF desde R:\Rentas\Fondos
  datos_fs_tools.py   # rentabilidad del fondo, TIR, hoja DATOS FS
  caja_tools.py       # hoja Caja del CDG: copiar desde Saldo Caja, archivar
  input_tools.py      # hojas Input AP/PT/Ren: balance trimestral, fechas, dividendos
  web_bursatil_tools.py  # precios cuota desde web
```

## Variables de entorno (.env)

```
GEMINI_API_KEY=...
LOCAL_FILES_DIR=R:\
WORK_DIR=C:\Users\raimundo.opazo\automation_agent\work
SHAREPOINT_DIR=C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos
RENTA_COMERCIAL_DIR=R:\Rentas\Control de Gestión Rentas Inmobiliarias\Control de Gestión Históricos\Comercial
FONDOS_DIR=R:\Rentas\Fondos
SALDO_CAJA_DIR=R:\Rentas\Control de Gestión Rentas Inmobiliarias\Saldo Caja
```

## Fondos gestionados

| Clave `fondo_key` | Carpeta en R:\Rentas\Fondos | Hoja en CDG |
|---|---|---|
| `A&R Apoquindo` | `FI Toesca Rentas Apoquindo` | `Input AP` |
| `A&R PT` | `FI Toesca Rentas PT` | `Input PT` |
| `A&R Rentas` | `FI Toesca Rentas` | `Input Ren` (series A, C, I) |

## Celdas fecha en hojas Input (¡inconsistente entre fondos!)

| Fondo | Fecha contable | Fecha bursátil |
|---|---|---|
| A&R Apoquindo | C9 | D9 |
| A&R PT | D11 | C11 |
| A&R Rentas | D10 | C10 |

## Agregar herramienta nueva

1. Crear función en `tools/<nombre>.py`
2. Importar en `agent.py`
3. Agregar entrada en `TOOL_DEFINITIONS` (lista de dicts con `type`, `function.name`, `function.description`, `function.parameters`)
4. Agregar lambda en `_dispatch`

## Formato de fechas Excel

Serial = `(date - date(1899, 12, 30)).days`
Ejemplos: 46022 = 31-dic-2025 · 46112 = 31-mar-2026

## Números chilenos

`"1.234.567"` → `1234567.0` (puntos = miles, sin decimales)
`"1.234,56"` → `1234.56` (punto = miles, coma = decimal)
