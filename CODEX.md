# CODEX.md — Memoria Operativa Codex para Automation Agent Toesca

Este archivo es la memoria larga para continuar el proyecto cuando se agoten tokens/contexto en Claude. Leerlo al inicio de cualquier sesion Codex junto con `AGENTS.md`, `CLAUDE.md`, `wiki/index.md` y las paginas wiki relevantes.

## Regla De Prioridad

1. Las instrucciones del usuario y del sistema mandan.
2. `AGENTS.md` contiene las reglas irrompibles para agentes de codigo.
3. Este `CODEX.md` resume el estado actual verificado por Codex el 2026-07-13.
4. El wiki (`wiki/index.md` + `wiki/log.md`) contiene memoria viva y puede superar docs antiguas.
5. `docs/` tiene planes y guias, pero algunos archivos historicos estan atrasados. Si hay conflicto, verificar contra codigo y DB real.

## Mentalidad De Trabajo

- La fuente canonica de datos de negocio es `memory/agente_toesca_v2.db`.
- DB primero para responder datos ya procesados; Excel/SharePoint solo si la DB no tiene el dato.
- No inventar rutas, resultados de tools, cifras, fechas ni nombres de archivos.
- Antes de tocar ingestas por fondo, leer `docs/db-poblar-fondos.md`.
- Antes de dominio o procesos, leer `wiki/index.md`, `wiki/log.md` y la pagina wiki relevante.
- Antes de buscar SharePoint, leer `wiki/sharepoint/index.md` si existe y esta actualizado.
- Siempre usar `python -X utf8` en Windows.
- Nunca leer el CDG completo (`*Control De Gestion*.xlsx`, 14 MB). Usar `work/eeff_ingesta/TRI/cdg_extract.xlsx`.
- Machali esta excluido del portfolio. No ingestar, no calcular, no incluir en agregaciones.
- En tablas raw versionadas, filtrar `superseded_at IS NULL` salvo que se este auditando versiones.
- Respetar el worktree sucio: no revertir cambios ajenos.

## Estado DB Verificado 2026-07-13

Consulta local contra `memory/agente_toesca_v2.db`:

- `schema_version`: 46.
- Existe migracion `047_fix_participacion_apo_activos.sql` en repo, pero la DB consultada aun reporta 46. Antes de correr migraciones, verificar si realmente falta aplicar 047 y si los datos ya estan corregidos.
- Tablas principales actuales usan nombres sin `_line` para snapshots/eventos; existen vistas de compatibilidad con nombres viejos:
  - Tablas: `raw_valor_cuota_contable`, `raw_valor_cuota_bursatil`, `raw_dividendo`, `raw_cuota_en_circulacion`, `raw_capital_suscrito`, `raw_caja`, `raw_saldo_deuda`, `raw_amortizacion`, `raw_ar_event`.
  - Siguen siendo tablas `_line`: `raw_eeff_line`, `raw_er_activo_line`, `raw_flujo_line`, `raw_rent_roll_line`, `raw_balance_consolidado_line`.
  - Vistas legacy: `raw_valor_cuota_line`, `raw_dividendo_line`, `fact_precio_cuota`, `fact_uf`, `fact_dividendo`, etc.
- Fondos en `dim_fondo`: `Apo`, `PT`, `TRI`.
- Series en `dim_serie`:
  - `Apo` → fondo `Apo`, unica, no transa.
  - `CFITRIPT-E` → PT, unica, transa.
  - `CFITOERI1A`, `CFITOERI1C`, `CFITOERI1I` → TRI A/C/I, transan.
- Conteos verificados:
  - `raw_eeff_line`: `APO` 18.009 filas, 2019-03..2026-03; `Apo` 3 filas en 2026-03; `PT` 5.070 filas, 2017-01..2026-03; `TRI` 13.711 filas, 2017-01..2026-03.
  - `raw_valor_cuota_contable`: `APO` 15 filas, 2025-01-31..2026-03-31; `Apo` 30 filas, 2019-01-02..2026-03-31; `PT` 35 filas, 2017-12-31..2026-03-31; `TRI` 123 filas, 2017-12-31..2026-03-31.
  - `raw_dividendo`: Apo 6 dividendos + 6 disminuciones; PT 33 dividendos; TRI 167 dividendos.

Nota importante: `AGENTS.md` antiguo decia que Apo tenia `raw_eeff_line=0`; eso ya no es cierto en la DB actual.

## Arquitectura

- `agent.py`: runner conversacional Gemini, prompt base y seleccion dinamica de tools.
- `app.py`: app Streamlit con auth, UI de chat y runner del agente.
- `tools/registry.py`: define tools, imports y dispatch.
- `tools/db/connection.py`: `DEFAULT_DB_PATH` apunta a `memory/agente_toesca_v2.db`; aplica migraciones.
- `tools/db/backfill.py`: orquestador de backfills.
- `scripts/build_factsheet.py`: genera `factsheet.html` desde SQLite.
- `dashboards/`: Streamlit dashboards de KPIs.
- `wiki/`: memoria acumulativa del proyecto. `wiki/log.md` es muy importante.
- `docs/`: guias y planes; algunos documentos antiguos usan nombres de tablas viejos.
- Skill externo: `C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert`.

## Variables Y Rutas

Variables en `.env` via `config.py`:

- `GEMINI_API_KEY`
- `SHAREPOINT_DIR`
- `LOCAL_FILES_DIR`
- `RENTA_COMERCIAL_DIR`
- `FONDOS_DIR` legacy; rutas canonicas en `tools/sharepoint_paths.py`
- `SALDO_CAJA_DIR`
- `WORK_DIR`

No imprimir secretos. No leer `.env` salvo necesidad concreta.

## Fondos, Activos Y Participaciones

TRI:

- Activos directos: `Viña Centro`, `Mall Curicó`, `INMOSA`, `Apo3001`, `Sucden`.
- Participaciones en subfondos: 33,3% en PT y 30% en Apo.
- Series: `CFITOERI1A`, `CFITOERI1C`, `CFITOERI1I`.
- Machali excluido.

PT:

- Fondo `PT`, serie `CFITRIPT-E`.
- Activos: `Torre A`, `Boulevard`.
- TRI tiene 33,3% de PT.

Apo:

- Fondo `Apo`, serie interna `Apo`, no transa.
- Activos: `Apo4501`, `Apo4700`.
- TRI tiene 30% de Apo.
- Ojo con casing en algunas tablas EEFF: se usa `APO` en `raw_eeff_line`/scripts de EEFF, pero `Apo` en `dim_fondo`, serie y muchas raw. Para queries robustas usar `UPPER(fondo_key)='APO'` cuando aplique.

## Esquema Y Convenciones

- Periodos normalizados en DB moderna: `YYYY-MM`.
- Fechas de evento/cierre: `YYYY-MM-DD`.
- `loaded_at`: preferir `YYYY-MM-DD HH:MM:SS`.
- `dim_cuenta_eeff` usa `cuenta_codigo`; no hay columna `signo`.
- Los montos de EEFF vienen con signo ya aplicado.
- En `raw_er_activo_line`, las ingestas recientes de Apo/PT guardan valores en UF dentro de `monto_clp` por convencion heredada. No convertir ni renombrar sin revisar todo lo dependiente.
- Para tablas con `variante` nullable en `derived_kpi`, usar helpers existentes y verificar duplicados: SQLite permite multiples NULL en UNIQUE si no se maneja explicitamente.

## Ingestas

### CDG Extract

Fuente liviana: `work/eeff_ingesta/TRI/cdg_extract.xlsx`.

Codigo: `tools/db/ingest_cdg_extract.py`.

Comandos:

```bash
python -X utf8 -m tools.db.backfill ar_pt
python -X utf8 -m tools.db.backfill ar_apo
python -X utf8 -m tools.db.backfill dividendos
```

No usar el CDG completo para esta tarea. El extract tiene hojas `A&R PT`, `A&R Rentas`, `A&R Apoquindo`.

### EEFF PDFs A raw_eeff_line

Codigo:

- `scripts/ingest_eeff.py`: MD convertido por MarkItDown → Gemini/OpenAI-compatible → JSON → `raw_eeff_line`.
- `scripts/ingest_from_json.py`: JSON manual ChatGPT → DB.

Flujo:

```bash
python -m markitdown "ruta/EEFF.pdf" > work/eeff_ingesta/APO/md/EEFF_APO_YYYYMM.md
copy "ruta/EEFF.pdf" work/eeff_ingesta/APO/pdf/EEFF_APO_YYYYMM.pdf
python -X utf8 scripts/ingest_eeff.py --fondo APO --file work/eeff_ingesta/APO/md/EEFF_APO_YYYYMM.md
python -X utf8 scripts/ingest_from_json.py --fondo APO --json work/eeff_ingesta/APO/json/EEFF_APO_YYYYMM.json
```

`scripts/ingest_eeff.py` normaliza `periodo` a `YYYY-MM`. Usa `file_hash` del PDF/DOCX original para idempotencia.

### ER Operacional

- Apo: `tools/db/ingest_er_apoquindo.py`.
  - Fuente historica `raw/NOI.xlsx`/planilla local.
  - Activos `Apo4501`, `Apo4700`.
  - Cobertura log: 2019-01..2026-05.
  - Contribuciones combinadas historicas se splittean 25% Apo4700 / 75% Apo4501 cuando falta desglose.
- PT: `tools/db/ingest_er_pt.py`.
  - Fuente `NOI PT.xlsx`.
  - Activos `Torre A`, `Boulevard`.
  - Cobertura log: 2018-01..2026-05.
  - Supuestos PT definidos por usuario 2026-07-13, aplican solo desde 2026-07 en adelante y no deben reescribir historia; todos como gastos negativos en UF:
    administracion = 0,2% de ingresos operacionales de cada activo; GC vacancia Boulevard/Inmob CDC = 531 UF mensual; contribuciones Torre A = 1.257 UF mensual y Boulevard = 621 UF mensual; seguros Torre A = 173,464166666667 UF mensual y Boulevard = 63,46 UF mensual.
  - Pendiente: Margen Energia.
- Viña/Curicó: `tools/db/ingest_er.py`.
- INMOSA: `tools/db/ingest_flujo.py`.

### Backfill General

```bash
python -X utf8 -m tools.db.backfill
python -X utf8 -m tools.db.backfill rent_roll
python -X utf8 -m tools.db.backfill er
python -X utf8 -m tools.db.backfill inmosa
python -X utf8 -m tools.db.backfill uf
```

Revisar `tools/db/backfill.py` antes de correr todo: algunos dominios buscan CDG reciente en SharePoint/WORK_DIR y pueden ser lentos.

## KPIs Canónicos

Leer primero:

- `wiki/kpis_rentabilidad_fondos.md`
- `wiki/tir_contable_desde_inicio.md`
- `wiki/kpis_noi_cap_rate_apo.md`
- Skill externo `real-estate-finance-expert`.

Rentabilidad:

- TIR desde inicio TRI contable: metodo UF/cuota con divisor fijo por serie; terminal desde `raw_valor_cuota_line`, nunca desde `raw_ar_event_line`.
- TIR bursatil desde inicio: metodo agregado en UF, validado y congelado.
- PT y Apo tienen un solo aporte: usan metodo agregado para contable y bursatil (Apo solo contable).
- YTD anualizada: XIRR entre 31-dic anterior y corte, luego `(1+XIRR)^(MES(corte)/12)-1`. No volver al retorno simple.
- U12M: incluir todos los dividendos en ventana, aunque el CDG haya omitido alguno por bug de orden de filas.
- DY + amortizacion: usar `raw_amortizacion` consolidado tal cual; no excluir refinanciamientos sin nueva validacion explicita.
- Apo `dy_amort` usa denominador de capital suscrito por cuota, no VNA.

NOI / tasa arriendo / cap rate:

- Apo contable: validado a MAR-2026, tasa arriendo 5,39%, cap rate 4,58%.
- Caja minima: Apo 0,1% de total activo; PT/TRI 1%.
- PT bursatil: `scripts/consolidate_kpis_bursatil_pt.py`, 90 meses 2018-12..2026-05.
- Signo caja PT confirmado: denom = market_cap + deuda - (caja_consolidada - caja_minima).
- TRI pendiente para variante bursatil hasta consolidar ingresos/NOI por activo.

Leverage:

- `derived_kpi` contiene `ltv`, `ltc`, `deuda_consolidada`, `leverage_financiero`, `dscr`, `duration_deuda`, `deuda_financiera_neta`, etc.
- TRI usa look-through ponderado; Machali excluido.
- `raw_amortizacion` tiene correcciones directas en DB para `CONSOLIDADO_TRI`, `APO_APO_BTG`, `CONSOLIDADO_Apo`. Reingestar desde Excel fuente desactualizado puede perder parches.

## Hallazgos Y Trampas Recientes

- `raw_eeff_line` tiene variantes de nombres de cuenta: buscar case/plural-insensitive antes de concluir gap.
- Apo 2020-12 tuvo bug de versionado de `Total activo`; revisar wiki antes de tocar.
- `raw_caja` tiene 4 discrepancias conocidas vs tabla historica; usuario decidio no corregirlas por ahora.
- `raw_caja.source_file='screenshot_caja_historica'` no es un archivo real trazable.
- `dim_activo.participacion_fondo_activo` para `Apo4501`/`Apo4700` debe ser 1.0, no 0.3. La relacion 30% es TRI→Apo, no Apo→activos.
- `docs/ingest_pipeline.md` menciona `memory/agente_toesca.db`; tratarlo como historico. DB canonica actual es v2.
- Tests pueden estar parcialmente atrasados respecto a vistas/tablas renombradas; verificar antes de asumir.

## UI Y Entregables

- `app.py`: Streamlit chat del agente con autenticacion en `config.yaml`.
- `factsheet.html`: generado por `scripts/build_factsheet.py`.
- `scripts/build_factsheet.py` lee SQLite y arma datos por fondo/periodo; no editar `factsheet.html` manualmente si el cambio corresponde al generador.
- `dashboards/tir_tri.py`: dashboard TIR historica TRI, depende del skill externo.
- Assets en `assets/`, configs en `config/`.

## Verificacion Recomendada

Compilacion rapida:

```bash
python -X utf8 -m py_compile agent.py app.py tools/registry.py tools/db/backfill.py scripts/ingest_eeff.py scripts/ingest_from_json.py scripts/build_factsheet.py
```

Tests focales:

```bash
python -X utf8 -m pytest tests/db/test_ingest_er_apoquindo.py tests/db/test_noi_query.py
python -X utf8 -m pytest tests/db
```

Estado DB:

```bash
python -X utf8 -c "import sqlite3; c=sqlite3.connect('memory/agente_toesca_v2.db'); print(c.execute('select max(version) from schema_version').fetchone()); print(c.execute(\"select fondo_key,count(*),min(periodo),max(periodo) from raw_eeff_line group by fondo_key\").fetchall())"
```

Si PowerShell rompe comillas, crear un script temporal pequeño dentro de `scripts/` y eliminarlo despues con `apply_patch`.

## Como Continuar Una Sesion

1. Revisar `git status --short`.
2. Leer `wiki/log.md` ultimas entradas.
3. Si es una tarea de ingesta por fondo, leer `docs/db-poblar-fondos.md`.
4. Consultar DB real antes de actuar si la tarea depende de estado actual.
5. Preferir helpers/repos existentes sobre SQL ad hoc en codigo productivo.
6. Hacer cambios minimos y verificarlos.
7. Si se aprende algo permanente, actualizar wiki y log. El `CLAUDE.md` pide commit/push tras wiki; como Codex, no hacer commit/push salvo que el usuario lo pida explicitamente o el flujo lo requiera y este claro.
