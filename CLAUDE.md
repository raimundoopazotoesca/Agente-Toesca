# Automation Agent — Contexto del proyecto

## Wiki de conocimiento

La wiki acumulativa del agente vive en `wiki/` (relativo a la raíz de este repo).
Vault de Obsidian: abrir la carpeta `wiki/` como vault.

**Reglas:**
1. **Antes de explorar código ya visto**, leer `wiki/index.md` — puede estar ya documentado
2. **Antes de buscar un archivo en SharePoint**, leer `wiki/sharepoint/index.md` — contiene el árbol completo con patrones de nombre por carpeta. No escanear el disco si la respuesta está ahí.
3. **Al aprender algo nuevo** (error resuelto, detalle de proceso, comportamiento inesperado), actualizar la página wiki correspondiente y el log
4. **Al responder preguntas de dominio** (fondos, activos, procesos), leer primero las páginas relevantes del wiki
5. Agregar entrada en `wiki/log.md` con formato `## [YYYY-MM-DD] tipo | Descripción`
6. Después de cualquier actualización al wiki, hacer commit y push al repo del agente:
   ```bash
   git add -A && git commit -m "wiki: <descripción breve>" && git push
   ```

## Gestión de recursos — regla permanente

Antes de cada tarea, elegir el recurso más barato capaz de resolverla:

| Tarea | Recurso |
|---|---|
| Arquitectura, razonamiento complejo, decisiones multi-paso | Claude Opus (este modelo) |
| Código mecánico, funciones simples, fixes puntuales, ediciones de 1-2 archivos | Codex (`/codex:rescue`) |
| Review de diff / código nuevo | Codex (`/codex:review`) |
| Exploración de codebase, búsquedas en archivos | Subagente `Explore` |
| Planificación de implementación no trivial | Subagente `Plan` |
| Tareas independientes simultáneas | Múltiples subagentes en paralelo |
| Ediciones simples, respuestas cortas | Inline, sin subagente |

**Reglas de eficiencia (siempre activas):**
1. Leer `MEMORY.md` antes de explorar código ya visto — evita re-trabajo
2. Paralelizar tool calls independientes en un solo mensaje
3. Usar Codex para código simple: no consume tokens de Anthropic
4. Lanzar subagentes solo para búsquedas que toman >3 queries — si son 1-2, hacerlas inline
5. Leer solo la sección necesaria de un archivo, nunca el archivo completo si no hace falta
6. Si la memoria o el contexto ya tienen la respuesta, no buscar en el código

## Base de datos

- **Path negocio**: `memory/agente_toesca_v2.db` — EEFF, rent roll, precios, KPIs derivados, etc.
- **Path estado agente**: `memory/agente_state.db` — historial_chat, contexto y kpis por usuario. Se gestiona desde `tools/memory_tools.py`.
- `memory/agente_toesca.db` está vacía — ignorar.
- Módulo de acceso a la DB de negocio: `tools.db.connection.get_conn()`.
- Estructura:
  - `dim_*` (fondo, activo, serie, cuenta_eeff, credito) — catálogos maestros
  - `raw_*_line` — una fila por línea de documento fuente: `raw_eeff_line`, `raw_er_activo_line`, `raw_flujo_line`, `raw_rent_roll_line`
  - `raw_*` (sin `_line`) — snapshots/observaciones/eventos: `raw_caja`, `raw_capital_suscrito`, `raw_cuota_en_circulacion`, `raw_saldo_deuda`, `raw_valor_cuota_bursatil`, `raw_valor_cuota_contable`, `raw_ar_event` (aportes/dism/canjes), `raw_dividendo`, `raw_amortizacion`, `raw_pagare_intercompania`
  - `fact_adquisicion`, `fact_tasacion` — hechos derivados
  - `derived_kpi` — cache de KPIs (`entidad_tipo`+`kpi`+`variante`+`formula`)
  - Vistas: `v_serie_patrimonio`, `v_capital_suscrito_serie`, `v_flujos_tir_serie`, `raw_valor_cuota_line` (unión bursátil+contable), `fact_precio_cuota`, `fact_dividendo`, `fact_uf`, y vistas de compat con nombres viejos (`raw_dividendo_line`, etc.) para consumidores externos.
  - Trazabilidad: `ingest_run`, `schema_version`
- **Plan de cuentas**: `dim_cuenta_eeff` (`cuenta_codigo`, `source_sheet`, `grupo`, `descripcion`, `es_subtotal`). No tiene columna `signo` — el signo contable ya viene aplicado en `raw_eeff_line.monto_clp`.
- **Formato `periodo`**: siempre `YYYY-MM` (string). Todas las tablas normalizadas 2026-07-01. Las ingestas deben truncar `YYYY-MM-DD → YYYY-MM` al persistir.
- **Formato `loaded_at`**: siempre `'YYYY-MM-DD HH:MM:SS'` (string, sin `T`). DEFAULT `datetime('now')` en la mayoría; `fact_adquisicion` y `fact_tasacion` tienen DEFAULT ISO con `T` — los datos existentes fueron normalizados, pero al insertar filas nuevas ahí queda con `T` hasta que se recreen esas tablas.
- **Enums válidos** (no enforced por CHECK en SQLite, respetar al insertar):
  - `derived_kpi.entidad_tipo`: `fondo` | `activo` | `serie`
  - `dim_credito.estado`: `VIGENTE` | `PAGADO`
  - `raw_dividendo.tipo`: `dividendo` | `disminucion`
  - `dim_serie.transa_bolsa`: `0` | `1`
- Filtrar siempre `WHERE superseded_at IS NULL` en tablas raw versionadas.

## Stack

- Python + Gemini 2.5 Flash vía API compatible con OpenAI (`generativelanguage.googleapis.com/v1beta/openai/`)
- `pywin32` para Outlook (COM), `openpyxl` para Excel
- `zipfile` + XML directo para escritura en xlsx grandes (14MB+/87 hojas) — 3x más rápido que openpyxl
- SharePoint sincronizado localmente; servidor de red en unidad `R:`
- MarkItDown para extraer texto de PDFs de EEFF

## Arquitectura

```
agent.py              # runner principal: loop de conversación, system prompt
config.py             # variables de entorno
tools/
  registry.py         # TOOL_DEFINITIONS, _dispatch, selección dinámica por intent
  memory_tools.py     # contexto, historial, KPIs (SQLite memory/agente_toesca_v2.db)
  email_tools.py      # Outlook: listar, descargar adjuntos, enviar, buscar
  sharepoint_tools.py # listar/copiar desde/hacia SharePoint
  local_tools.py      # listar/copiar desde/hacia servidor R:
  excel_tools.py      # leer, validar, actualizar celdas
  gestion_renta_tools.py  # planilla mensual CDG Rentas Comerciales
  eeff_tools.py       # leer PDFs de EEFF desde SharePoint/Fondos
  datos_fs_tools.py   # rentabilidad del fondo, TIR, hoja DATOS FS
  caja_tools.py       # hoja Caja del CDG: copiar desde Saldo Caja, archivar
  input_tools.py      # hojas Input AP/PT/Ren: balance trimestral, fechas, dividendos
  web_bursatil_tools.py  # precios cuota desde web
  noi_tools.py        # hoja NOI-RCSD: ER Viña, ER Curico, JLL PT/Apoquindo/Apo3001, INMOSA
  rentroll_tools.py   # validación RR JLL y Tres Asociados (en desarrollo)
  vacancia_tools.py   # vacancia mensual (en desarrollo)
  factsheet_tools.py  # actualización PPTX fact sheets (PT, APO, TRI)
```

## Variables de entorno (.env)

```
GEMINI_API_KEY=...
LOCAL_FILES_DIR=R:\
WORK_DIR=C:\Users\raimundo.opazo\automation_agent\work
  datos_fs_tools.py   # rentabilidad del fondo, TIR, hoja DATOS FS
  caja_tools.py       # hoja Caja del CDG: copiar desde Saldo Caja, archivar
  input_tools.py      # hojas Input AP/PT/Ren: balance trimestral, fechas, dividendos
  web_bursatil_tools.py  # precios cuota desde web
  noi_tools.py        # hoja NOI-RCSD: ER Viña, ER Curico, JLL PT/Apoquindo/Apo3001, INMOSA
  rentroll_tools.py   # validación RR JLL y Tres Asociados (en desarrollo)
  vacancia_tools.py   # vacancia mensual (en desarrollo)
  factsheet_tools.py  # actualización PPTX fact sheets (PT, APO, TRI)
```

## Variables de entorno (.env)

```
GEMINI_API_KEY=...
LOCAL_FILES_DIR=R:\
WORK_DIR=C:\Users\raimundo.opazo\automation_agent\work
SHAREPOINT_DIR=C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos
RENTA_COMERCIAL_DIR=C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\Control de Gestión\CDG Mensual
FONDOS_DIR=
SALDO_CAJA_DIR=C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\Control de Gestión\Saldo Caja
| PT | D11 | C11 |
| TRI | D10 | C10 |

## Flujo mensual Control de Gestión Renta Comercial

1. `crear_planilla_mes("2604")` → copia desde mes anterior
2. Copiar al WORK_DIR (`copiar_del_servidor`)
3. `actualizar_fecha_pendientes(...)` → B2 de hoja Pendientes = 1º día del mes
4. `obtener_precios_mes(año, mes)` → precios último día del mes del CDG (ej. CDG 2604 → 30/04/2026)
5. `agregar_vr_bursatil_pt(...)` → PT (mensual)
6. `agregar_vr_bursatil_rentas(...)` → TRI series A/C/I (mensual)
   - Apo no tiene VR Bursátil
7. Si fin de trimestre (mar/jun/sep/dic):
   - Los EEFF de fondos A&R son del **trimestre anterior** al CDG:
     - CDG marzo → `leer_eeff(mes=12, año=año-1)`
     - CDG junio → `leer_eeff(mes=3, año=año)`
     - CDG sep → `leer_eeff(mes=6, año=año)`
     - CDG dic → `leer_eeff(mes=9, año=año)`
   - `agregar_vr_contable_pt(...)`
   - `agregar_vr_contable_rentas(...)`
   - `agregar_vr_contable_apoquindo(...)`
   - **EEFF Viña, Curicó, INMOSA**: siempre usan el mes del CDG (no trimestre anterior)
8. `guardar_en_servidor(...)`

## Flujo mensual NOI-RCSD (noi_tools.py)

Activos y fuentes de datos:

| Activo | Filas NOI-RCSD | Fuente | Función |
|---|---|---|---|
| INMOSA | 287-295 | ER-FC INMOSA (`Fondos/Rentas TRI/Activos/INMOSA/Flujos`) | `actualizar_noi_inmosa` |
| Parque Titanium | 335-379 | hoja 'NOI PT' del RR JLL (WORK_DIR) | `actualizar_noi_pt` |
| Viña Centro | 196-214 | INFORME EEFF Viña Centro (SharePoint TresA/Viña Centro) | `actualizar_er_vina` |
| Fondo Apoquindo | 426-456 | hoja 'NOI PT' del RR JLL (WORK_DIR) | `actualizar_noi_apoquindo` |
| Apoquindo 3001 | 468-476 | hoja 'NOI PT' del RR JLL (WORK_DIR) | `actualizar_noi_apo3001` |
| Mall Curicó | 258-278 | INFORME EEFF Curicó (SharePoint TresA/Curico) | `actualizar_er_curico` |

### Archivos fuente

- **RR JLL** (Nicole Carvajal): `{AAMM} Rent Roll y NOI.xlsx` — hoja "NOI PT" tiene datos para PT, Apoquindo, Apo3001
- **EEFF Curicó** (Tres Asociados): `MM-AAAA INFORME EEFF POWER CENTER CURICO SPA.xlsx` — hoja "ESTADO DE RESULTADO"
- **EEFF Viña** (Tres Asociados): `MM-AAAA INFORME EEFF VIÑA CENTRO SPA*.xlsx` — hoja "ESTADO DE RESULTADO AAAA"
  - Ambos EEFF: col B = código de cuenta, col E = valor CLP mes actual

### Estructura ER Curico / ER Viña en CDG

**ER Curico**: Section 1 (filas 3-112, cols E-BZ) = datos mensuales reales en CLP.
Section 2 (filas 113+) = agregaciones con fórmulas que referencian Section 1.
NOI-RCSD referencia Section 2. Al escribir Section 1 → Section 2 auto-calcula → NOI auto.

**ER Viña**: Section 1 (filas 5-90+, cols B-CA+) = datos mensuales en UF (CLP/UF_mes).
Section 2 (filas 95-119+) = valores estáticos sin fórmulas → requiere actualización directa (pendiente).
NOI-RCSD referencia Section 2 de ER Viña.

**Fila de fechas**: ER Curico = fila 4, ER Viña = fila 6 (seriales Excel).
**Fila de UF**: ER Curico = fila 3, ER Viña = fila 5.

### Mapeo NOI-RCSD → ER

Hardcoded en `_NOI_CURICO_MAP` / `_NOI_VINA_MAP`. NOI fila 7 = row de fechas (col CY = Ene 2026). `actualizar_er_curico/vina` escribe ER Section 1 + NOI col del mes en un solo zip.

### Archivos EEFF Viña disponibles

`C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\Fondos\Rentas TRI\Activos\Viña Centro\EEFF`

## Arquitectura XML directo en XLSX

El xlsx es un ZIP. Solo se modifican los archivos internos necesarios:

```
xl/worksheets/sheet15.xml  → Apo
xl/worksheets/sheet16.xml  → PT
xl/worksheets/sheet17.xml  → TRI
xl/tables/table2.xml       → Tabla133 (Apoquindo)
xl/tables/table3.xml       → Tabla13  (PT)
xl/tables/table4.xml       → Tabla1   (Rentas)
xl/sharedStrings.xml       → strings compartidos
xl/worksheets/sheet3.xml   → Pendientes
```

`SHEET_CFG` define por hoja: `sheet_file`, `table_file`, `tabla`, `date_col`, `series`, `cuotas`, `has_bursatil`, `nemotecnico/nemotecnicos`.

## Detalles críticos OOXML

**Formatos de celda:**
```xml
<c r="D189" s="1622"/>                           <!-- self-closing: sin valor -->
<c r="D189" s="1622"><v>46112</v></c>            <!-- con valor numérico -->
<c r="A189" s="106"><f>+YEAR(...)</f><v>2026</v></c>  <!-- con fórmula -->
<c r="E189" s="133" t="s"><v>821</v></c>         <!-- string compartido -->
```

**NUNCA usar regex `[^>]*` para parsear celdas** — falla con self-closing (`/>` contiene `/`).
Usar las helpers que escanean char-by-char:
- `_cell_has_value(sheet_xml, ref)` → `True/False/None`
- `_find_cell_bounds(row_xml, ref)` → `(start, end)`
- `_replace_or_insert_cell(row_xml, ref, new_cell)` → row_xml modificado

**Filas pre-asignadas:** Las 3 tablas tienen filas vacías con estilos y fórmulas N-Y (Libro/Bolsa) ya presentes. Solo rellenar columnas A-M.

**Columnas por hoja:** A=YEAR, B=MONTH, C=ID, D=Fecha/SF, E=Detalle, F=Serie, G=Tipo, H=Monto$, I=Precio/cuota, J=Cuotas, K=UF, L=MontoUF, M=MontoUF/cuota, N-Y=Libro/Bolsa.

**Fórmulas compartidas (TRI):** Columna C usa `<f t="shared" ref="C590:C621" si="127">`. No sobreescribir si ya existe.

## Agregar herramienta nueva

1. Crear función en `tools/<nombre>.py`
2. Importar en `tools/registry.py`
3. Agregar entrada en `TOOL_DEFINITIONS` en `registry.py` (dict con `type`, `function.name`, `function.description`, `function.parameters`)
4. Agregar lambda en `_dispatch` en `registry.py`

## Formato de fechas Excel

Serial = `(date - date(1899, 12, 30)).days`
Ejemplos: 46022 = 31-dic-2025 · 46112 = 31-mar-2026

## Números chilenos

`"1.234.567"` → `1234567.0` (puntos = miles, sin decimales)
`"1.234,56"` → `1234.56` (punto = miles, coma = decimal)

## Compatibilidad

- `email_tools.py`: solo Windows (pywin32/COM); en Mac retorna error claro sin crashear
- Resto del agente: 100% cross-platform
