# Log — Wiki Agente Toesca

> Log cronológico append-only. Una entrada por operación.
> Parsear últimas entradas: `grep "^## \[" wiki/log.md | tail -10`

## [2026-06-11] feat | ingesta EEFF PT en raw_eeff_line completa 2020–2025

Ingesta manual de EEFF trimestrales PT (fondo paraguas, no el activo) desde PDFs vía ChatGPT → JSON → DB.
Períodos completados: 2020-03-31 a 2025-12-31 (24 períodos, 100 filas c/u).
Script: `tools/db/ingest_eeff_pt_json.py` (función `ingest_from_file`).
JSONs staging en `work/eeff_pt_json/`.

## [2026-06-11] feat | ingesta PT — raw_valor_cuota_line, dividendos, cuotas, precios

Inicio de poblamiento de DB para fondo PT (Toesca Rentas Inmobiliarias PT, CFITRIPT-E, Serie Única).

**Fuentes:**
- `A&R PT` del CDG → dividendos, VR Contable (valor cuota libro trimestral desde 2017-11), cuotas en circulación (siempre 1.640.000), precios bursátiles históricos, patrimonio bursátil.
- PDFs EEFF en `work/eeff_pt/` → valor cuota libro exacto por trimestre (tienen precedencia sobre CDG).

**Nuevo código:**
- `tools/db/ingest_cdg_extract.py::ingest_ar_pt` — lee hoja 'A&R PT' del CDG en un pase.
- `tools/db/ingest_eeff_pt.py` — parser regex EEFF PT para SERIE ÚNICA. Maneja formato 2017 ("tiene un valor cuota de\n$X") y formato 2025 ("tienen un valor cuota de $ X").
- `tools/db/backfill.py` → dominios `eeff_pt` y `ar_pt` registrados.

**Carpeta staging:** `work/eeff_pt/` — subir PDFs aquí sin subcarpetas.

**Validación:** 5 PDFs (2017-12 → 2018-12) parseados. VC cross-check vs CDG: ✓ (25.815,4355 dic-2017).

**Pendiente:**
- Subir PDFs 2019→2025 a `work/eeff_pt/` y re-correr `python -X utf8 -m tools.db.backfill eeff_pt`.
- Cuotas de PDFs no parseadas (formato tabular antiguo, Suscritas sin número en línea siguiente) — el CDG las cubre vía `ar_pt`.
- Validar resultado final del backfill `ar_pt` (CDG tiene 33 fechas VR Contable desde 2017-12).

## [2026-06-11] fix | dim_credito — fechas DD-MM-YYYY corregidas (bug ingesta)

Todas las `fecha_inicio` y `fecha_vencimiento` de `dim_credito` estaban almacenadas como
`YYYY-DD-MM` en vez de `YYYY-MM-DD` (formato chileno no convertido al ingestar).
Detectado al comparar duration PT: yo calculaba 2.43 años (con venc. ene-2029),
usuario tenía 3.17 años (con venc. nov-2029 = fecha correcta).
Fix: `scripts/fix_fechas_credito_apply.py` corrigió 23 valores en 15 créditos (PT, TRI, Apo).
PT vencimiento corregido: `2029-01-11` → `2029-11-01`. Duration PT: 3.12 años (Macaulay).
Prevención futura: parsear fechas chilenas con `dayfirst=True` al re-ingestar.

## [2026-06-08] dominio | TRI: sin dividendos en Q4-2023 ni en 2024 — confirmado por usuario

## [2026-05-27] feat | Extractor Groq EEFF TRI — independencia del CDG

Nuevo módulo `tools/db/ingest_eeff_tri_groq.py` (llama-3.3-70b-versatile via Groq):
extrae valor cuota libro, cuotas en circulación, capital/aportes/disminuciones y dividendos
desde PDFs de EEFF TRI. Fix bug regex (capturaba primer valor de tabla en vez del TOTAL).
Dedup: `tools/db/dedup_eeff_tri.py` supersede redundantes, DB sin duplicados.
Estado: 17/32 PDFs procesados (límite diario 100k tokens free tier). 15 PDFs pendientes
para próxima sesión. Validación 52/56 comparaciones EEFF vs CDG = 0.00% diff exacta;
2025-12-31 EEFF correcto (31.869), CDG tenía error (35.791) ya supersedido.
Pendiente: test capital+dividendos, backfill 15 PDFs restantes.

## [2026-05-27] refactor | Limpieza CDG legacy + pipeline ingesta DB-centric

Eliminados módulos CDG-write (`noi_tools`, `vacancia_tools`, `datos_fs_tools`, `caja_tools`, `input_tools`, `balance_consolidado_tools`) — 7.319 líneas, 32 tools desregistradas. Funciones de ingesta a DB recuperadas a `tools/db/ingest_er.py` y `tools/db/ingest_flujo.py`. Nuevo: `tools/db/coverage.py` (audit de gaps), `tools/db/ingest_router.py` (tool `ingestar_archivo` con detección por nombre), `scripts/ingest_eeff.py` generaliza a TRI/PT/APO, migración 010 con índices. System prompt explícito: DB es fuente primaria. Doc: `docs/ingest_pipeline.md`.

## [2026-05-27] skill | real-estate-finance-expert completado y integrado en agent

Skill custom finalizado para computar KPIs financieros derivados desde agente_toesca.db con caching inteligente. Aprobado evaluación (100% pass-rate, 55.6% mejora sobre baseline). Ubicación: `C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\`

**Integración en agent.py** (2026-05-27):
- Wrapper `tools/finance_tools.py` que invoca compute_or_fetch desde la skill
- 4 nuevas herramientas registradas en `tools/registry.py`:
  - `calcular_indicador`: invoca compute_or_fetch (kpi, entidad_tipo, entidad_key, periodo)
  - `listar_indicadores`: lista KPIs disponibles (8 operativos + 3 placeholders)
  - `invalidar_cache_indicador`: invalida cache para un KPI
  - `verificar_skill_finanzas`: diagnostica disponibilidad de la skill
- Herramientas agregadas a `_TOOLS_GENERAL` → siempre disponibles para agent
- Test: calcular_indicador computa 6.63% CAGR para TRI Serie A (2026-04)

Indicadores operativos: rent_desde_inicio/anualizada/u12m (CAGR), dividend_yield ±amort, cap_rate real/implícito, tasa_arriendo_uf_m2. Placeholders: TIR/XIRR, LTV/DSCR (requieren deuda), valuaciones.

Arquitectura: three-tier loop (read cache → compute → persist si criteria). Recipe versioning `<kpi>_v<base>_<override_hash>` con invalidación automática al editar `config/formulas.yaml`. Fórmulas editables sin tocar Python.

## [2026-05-25] feat | DB Fase 2 — backfill histórico completo

`tools/db/backfill.py` pobló la DB desde archivos ya en SharePoint/CDG (idempotente, reusa los `_persist_*`):
- rent_roll: 10.122 filas (2025-09..2026-03, 5 activos)
- er_activo: 400 (Viña/Curicó, 2025-12..2026-03)
- flujo INMOSA: 46 (2026-01..02; marzo "Senior Assist" queda al flujo en vivo)
- uf: 5.182 días (2012..2026, hoja UF del CDG)
- precios: 100 (4 nemos × 25 meses, datachart LarraínVial)
- valor_cuota_libro (eeff): 4 trimestres (regex parcial)
- dividendos: 108 en fact_dividendo (PT+Rentas) + 6 Apoquindo en derived_kpi (desde CDG)

Detalle técnico: `_persist_flujo_lines` ganó `hash_extra` para archivos multi-período (INMOSA).
Query tools ampliadas con `consultar_db_dividendos`. 81 tests verdes. Ver `wiki/db.md`.

## [2026-05-25] feat | DB Fase 1 — dual-write de 5 dominios

Cada tool de ingesta ahora escribe en paralelo a la DB (best-effort, no rompe Excel si la DB falla):
- `web_bursatil_tools.obtener_precio_cuota` → `fact_precio_cuota`
- `eeff_tools.leer_eeff` → `derived_kpi` (valor_cuota_libro; serie A/C/I por nemotécnico, fondo único para PT/Apoquindo)
- `noi_tools._actualizar_er_mall` (Viña/Curicó) → `raw_er_activo_line`
- `noi_tools.actualizar_noi_inmosa` → `raw_flujo_line`
- `rentroll_tools.consolidar_rent_rolls` → `raw_rent_roll_line` (por arrendatario, mapeo Activo1→activo_key para los 5 activos)

Idempotencia por (file_hash, source_row). 69 tests verdes. Ver `wiki/db.md` para estado y pendientes.

## [2026-05-25] feat | DB Fase 0 — esqueleto SQLite del agente

Se creó la base de datos real del agente (migración desde Excels como "base de datos"):
- `tools/db/` con capa de acceso por dominio: `connection.py` (migraciones idempotentes), `errors.py`, y repos `repo_fondo`, `repo_audit`, `repo_rent_roll`, `repo_eeff`, `repo_flujo`, `repo_er_activo`, `repo_fact`, `repo_kpi`.
- Schema versionado en `tools/db/migrations/` (001 dim, 002 raw, 003 facts, 004 derived, 005 audit, 006 seeds). 4 capas: dimensiones, raw (línea-a-línea del proveedor con linaje + hash idempotente), facts (precios/UF/dividendos), derived_kpi (formato largo para dashboards), audit (ingest_run/publish_run).
- Migraciones se aplican automáticamente al cargar `tools/memory_tools.py`.
- Seeds de 3 fondos, 6 activos, 4 series desde catálogos antes hardcoded.
- 48 tests, todos verdes. Backup pre-fase0 en `memory/backups/`.

Excels siguen siendo la verdad (entregable). DB lista para Fase 1 (dual-write por dominio).
Spec: `docs/superpowers/specs/2026-05-25-db-migration-design.md`. Plan: `docs/superpowers/plans/2026-05-25-db-fase0-esqueleto.md`.

## [2026-05-12] feat | EERR Viña Centro implementado en Balance Consolidado Rentas Nuevo

`VINA_EERR_MAP` (73 filas) en `tools/balance_consolidado_tools.py`. Fuente: hoja `BALANCE ACUMULADO` del INFORME EEFF Viña. Mapeado por descripción/valor en vez de strictly por label code: 7 filas re-mapeadas (94, 97, 113, 119, 120, 123, 137) por desalineación entre label y chart of accounts real del TB. Verificado Dec 2025: total G-Pd = 3.093.097.786 = D189 histórico (2.848.461.407) + D194 control (244.636.379) — el map nuevo elimina ese descuadre histórico de 244M. 0 cuentas EERR del TB quedan sin mapear. Wireado reemplazando `EERR: TODO` en `actualizar_balance_consolidado_rentas_nuevo`.

## [2026-05-12] feat | EERR Curicó implementado en Balance Consolidado Rentas Nuevo

`CURICO_EERR_MAP` (57 filas) en `tools/balance_consolidado_tools.py`. Códigos extraídos de los labels en col B filas 76-168 hoja `Curicó` del vF. Fuente: hoja `Acum MM-AAAA` del informe Curicó (misma que el balance). Verificado vs trial balance Dec 2025: resultado del período -405.776.897 calza con D174 histórico, 0 diferencias en las 57 filas. Wireado en `actualizar_balance_consolidado_rentas_nuevo` reemplazando el `EERR: TODO`. Fila 162 (`4-2-01-004`) duplica la 94 — se omite.

## [2026-05-11] feat | EERR Chañarcillo implementado en Balance Consolidado Rentas Nuevo

`CHANAR_EERR_MAP` (31 filas) en `tools/balance_consolidado_tools.py`. Códigos extraídos de los labels en col B filas 76-116 de la hoja Chañarcillo. Verificado vs trial balance Dec 2025: resultado del período 470.785.569 calza con D119 histórico.

**Observación importante:** los valores históricos en col D del planilla estaban desalineados respecto a sus labels — quien llenaba históricamente puso COMISIONES en la fila labelada ESTRUCTURACION, etc. (7 filas afectadas, rango 93-99). El nuevo map sigue el código del label (criterio contable correcto), por lo que los valores escritos en esas filas cambiarán respecto al histórico.

**Pendiente identificado:** bug `_copy_vals_sheet_rn` falla con `'MergedCell' object attribute 'value' is read-only` al copiar Resumen PT/Apoquindo. Hay que saltar celdas merged.

## [2026-05-11] fix | INMOSA — distinguir ER-FC vs Balance General + reconocer naming nuevo

Dos archivos distintos compartían carpetas mal asignadas:
- **ER-FC INMOSA** (estado de resultado + flujo de caja) → `INMOSA/Flujos/` — usado por CDG/NOI-RCSD.
- **Balance General Senior Assist** → `INMOSA/Contabilidad/` — usado por balance consolidado.

Desde 2026 el ER-FC viene nombrado `EEFF y FC Senior Assist Mar.26.xlsx` (sin "INMOSA" ni "ER-FC" en el nombre). `raw_tools.py` lo ruteaba a Contabilidad por matchear "senior assist", y `buscar_er_inmosa` no lo encontraba (filtraba por `"inmosa" in nombre`).

Cambios:
- `tools/raw_tools.py`: ruta ER-FC si nombre contiene "EEFF/FC" + "Senior Assist"; ruta Contabilidad solo si contiene "Balance" + "Senior Assist".
- `tools/noi_tools.py::buscar_er_inmosa`: matchea "inmosa" o "senior assist", excluye "balance".
- `tools/gestion_renta_tools.py`: el chequeo de "mes en filename" fallaba ("Ene a Feb" no implica que falte marzo). Ahora solo se valida existencia.
- Archivo `EEFF y FC Senior Assist Mar.26.xlsx` movido de Contabilidad/2026 → Flujos/2026.

## [2026-05-07] feat | Balance Consolidado Rentas Nuevo — implementación parcial

Implementada `actualizar_balance_consolidado_rentas_nuevo(mes, año)` en `tools/balance_consolidado_tools.py`.
Balance de 4 entidades (Chañarcillo, Curicó, Inmob VC, Viña Centro) + EERR Inmosa desde Senior Assist.
Copy de hojas PT/Apoquindo desde sus vAgente. Pendiente: EERR de 4 entidades, balance Inmosa Q1-Q3, Fondo Rentas PDF.
Instrucciones completas en `wiki/procesos/balance-consolidado-rentas-nuevo.md`.

---

## [2026-05-07] reorganización | SharePoint restructurado + carpeta RAW + raw_tools

- Nueva estructura: `Fondos/{Rentas Apoquindo|Rentas PT|Rentas TRI|Renta Residencial}/` agrupa EEFF, Fact Sheets y activos por fondo
- Activos de TRI (Viña, Curicó, INMOSA) ahora en `Fondos/Rentas TRI/Activos/{activo}/{EEFF|Rent Roll}/`
- CDG mensual: estructura canonica en `Control de Gestión/CDG Mensual/`
- Saldo Caja, Balances, TIR bajo `Control de Gestión/`
- Carpeta `RAW/` creada: usuario sube archivos, agente llama `ordenar_archivos_raw()` para clasificarlos
- Código actualizado: 7 tool files + registry.py + raw_tools.py (nuevo)
- Bug corregido en `factsheet_tools.py`: eliminado `_INMOBILIARIO` que causaba double-nesting

## [2026-05-07] integración | Power Automate — servidor HTTP + flujos recomendados

- `run_agent()` ahora retorna `str` (antes era `None`)
- Agregado `start_server()` en `agent.py` — Flask en puerto 5000 vía `python agent.py --server`
- Endpoints: `POST /run {"instruction": "..."}` y `GET /health`
- Wiki: `integraciones/power-automate.md` con flujos PA y framework de evaluación
- Flask 3.1.3 instalado

## [2026-05-06] aprendizaje | Estructura TRI desde diagrama validado

- Registrada estructura de Toesca Rentas Inmobiliarias con sociedades, participaciones y activos finales.
- Machalí marcado como liquidado; no debe considerarse activo vigente.
- Pesos históricos del diagrama rebajados pro forma excluyendo Machalí: base 96%.
- Fuente: diagrama enviado por usuario y confirmaciones del usuario en conversación.

## [2026-05-04] aprendizaje | Balance Consolidado PT documentado

- Mapeada hoja Fondo PT: clasificaciones, unidades (M$×1000), procedimiento inserción columna
- Verificado cruce EEFF 4Q2025 → planilla: Total Activo, Patrimonio, Resultado cuadran
- Fuente EEFF: SharePoint/Fondos/Rentas PT/EEFF/{año}/{TT}/
- Fuente planilla vF: SharePoint/Control de Gestión/Balances Consolidados/
- Pendiente: mapeo Inmob Boulevard, Torre A (fuente desconocida), EEFF trimestrales

## [2026-05-01] init | Wiki creada

- Estructura inicial creada: `raw/`, `wiki/agente/`, `fondos/`, `activos/`, `procesos/`, `conceptos/`, `errores/`
- CLAUDE.md escrito con schema completo de la wiki
- `index.md` inicializado con páginas semilla basadas en CLAUDE.md del agente
- `log.md` iniciado
- Páginas semilla creadas en todas las categorías
- Fuentes ingresadas: 0 — wiki lista para primer ingest real
