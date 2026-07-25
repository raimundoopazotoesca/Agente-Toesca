# Arquitectura del Sistema — Estado Real Verificado

**Fecha de verificación:** 2026-07-24
**Método:** inspección directa de código y de la DB productiva (`memory/agente_toesca_v2.db`), no de la documentación. Donde la documentación diverge del código real, manda el código; las divergencias están listadas en §10.

Este documento es el diagnóstico "as-is". El plan de evolución está en `ROADMAP.md`. Los principios que gobiernan el uso de IA están en `ai_principles.md`.

---

## 1. Qué resuelve el sistema hoy

Plataforma de datos e informes para los 3 fondos de renta inmobiliaria de Toesca (**TRI**, **PT**, **Apo**) y sus ~10 activos. Reemplaza progresivamente un flujo mensual basado en una planilla Excel de 14 MB (el "CDG") por:

1. Una **DB SQLite canónica** con datos financieros 2017-01 → 2026-08 (EEFF, ER por activo, rent roll, dividendos, valores cuota, deuda, tasaciones, parking, mercado de oficinas).
2. Una **web local de ingesta** con validación previa y confirmación humana.
3. Un **factsheet HTML** autogenerado 100% desde la DB, con trazabilidad por KPI (modo admin).
4. Un **chat text-to-SQL** de solo lectura embebido en el factsheet.
5. Un **agente conversacional** (Gemini) con 102 herramientas que aún opera los flujos Excel/Outlook/SharePoint legacy.

## 2. Mapa de componentes

```
                                ┌─────────────────────────────────┐
  Proveedores (JLL, TresA,      │  web/ingesta.html (6 tabs)      │
  SABA, EEFF PDFs, JLL mercado) │  wizard: check → validate →     │
        │                       │  preview → commit (humano)      │
        ▼                       └───────────────┬─────────────────┘
  ChatGPT web (extracción       ┌───────────────▼─────────────────┐
  EEFF PDF → JSON, manual)  ──▶ │  scripts/ingesta_server.py      │──▶ tools/db/ingest_*_validated.py
                                │  Flask 127.0.0.1:8765, sin auth │    + ingest_{mercado,parking,balance}
                                └───────┬───────────────┬─────────┘
                                        │               │ POST /api/chat
                                        ▼               ▼
                        ┌───────────────────────┐   ┌──────────────────────────┐
                        │ memory/               │◀──│ tools/db_chat.py         │
                        │ agente_toesca_v2.db   │ro │ text-to-SQL (DeepSeek/   │
                        │ 33 tablas, 22 vistas  │   │ Groq/Gemini), SELECT-only│
                        │ schema_version=57     │   └────────────┬─────────────┘
                        └───┬───────────────┬───┘                │
                            │               │              web/chat_bubble.js
              5 scripts     │               │              (embebido en factsheet)
              consolidate_*/│               ▼
              compute_kpis  │   ┌───────────────────────────┐
              (derived_kpi) │   │ scripts/build_factsheet.py│──▶ factsheet.html (5.2 MB)
                            │   │ 100% SQL, template string │
                            │   └───────────────────────────┘
                            ▼
              dashboards/{fondos,eeff_tri,tir_tri}.py  (Streamlit, duplican factsheet)

  ┌──────────────────────────────────────────────────────────────────────┐
  │ LEGACY aún vivo:                                                     │
  │ agent.py / app.py (Streamlit + auth) — agente Gemini, 102 tools      │
  │ tools/gestion_renta_tools.py — escribe el CDG por XML directo        │
  │ tools/factsheet_tools.py — PPTX cliente, NO lee la DB (PDF+scraping) │
  └──────────────────────────────────────────────────────────────────────┘
```

## 3. Flujo de datos principal

1. **Entrada.** Archivos de proveedores llegan por correo/SharePoint. El usuario los sube (o pega JSON/texto) en `web/ingesta.html`.
2. **Extracción.** Excel → `openpyxl` determinístico. PDF de EEFF → prompt fijo (`prompts/eeff_*.md`) ejecutado por el usuario en ChatGPT web → JSON pegado (ruta principal), o `scripts/ingest_eeff.py` con Gemini (ruta batch histórica).
3. **Validación (dry-run).** `validate()` recalcula cuadraturas server-side (no confía en lo que afirme el LLM), chequea rangos, duplicados por `file_hash`, período ya cargado, y devuelve preview con errores/warnings.
4. **Confirmación humana.** El botón "Confirmar e ingestar" se habilita solo si `ok`. `commit()` re-ejecuta `validate()` (defensa en profundidad) y persiste con `ingest_run` + `file_hash` + `loaded_at`.
5. **Derivados.** `derived_kpi` (31 KPIs) se puebla desde 5 escritores independientes sin orquestador: `compute_kpis_series.py` (DY), `consolidate_noi_tri.py`, `consolidate_ingresos_tri.py`, `consolidate_kpis_bursatil_{pt,tri}.py`, `tools/db/backfill.py`. Las TIR/LTV/duration vienen de una **skill externa no versionada** (`~/.claude/skills/real-estate-finance-expert`) hoy ausente en esta máquina.
6. **Salida.** Cada commit regenera `factsheet.html` síncronamente (`_rebuild_factsheet`, fallo silencioso, **no recalcula KPIs**). Mercado (UF/bursátil/DY) se refresca por tarea programada mensual de Windows (`refresh_market_task.xml`).

## 4. Modelo de datos

**DB real:** 33 tablas + 22 vistas, `schema_version = 57`, WAL, 21.8 MB. Capas:

| Capa | Tablas | Patrón |
|---|---|---|
| Dimensiones | `dim_fondo`, `dim_activo` (con `vigente_hasta`, look-through vía `sociedad_key`), `dim_serie`, `dim_sociedad`, `dim_credito`, `dim_cuenta_eeff`, `dim_concepto_parking` | catálogos maestros; `v_activo_fondo_efectivo` resuelve participación directa + look-through (PT→TRI 33,3%, Apo→TRI 30%) |
| Raw líneas | `raw_eeff_line`, `raw_er_activo_line`, `raw_flujo_line`, `raw_rent_roll_line`, `raw_balance_consolidado_line`, `raw_parking_*_line`, `raw_mercado_oficinas` | una fila por línea de documento fuente; linaje completo (`source_file/sheet/row`, `file_hash`, `ingest_run_id`, `loaded_at`, `superseded_at`) |
| Raw observaciones | `raw_caja`, `raw_dividendo`, `raw_valor_cuota_{contable,bursatil}`, `raw_saldo_deuda`, `raw_amortizacion`, `raw_ar_event`, `raw_capital_suscrito`, `raw_cuota_en_circulacion`, `raw_uf_diaria`, `raw_pagare_intercompania` | snapshots/eventos; linaje parcial; varias **sin** `superseded_at` |
| Hechos | `fact_tasacion`, `fact_adquisicion` | upsert con `COALESCE` (enriquecimiento no destructivo) |
| Derivados | `derived_kpi` (`entidad_tipo` fondo/activo/serie, `kpi`, `variante`, `formula`) | cache de KPIs; upsert que pisa sin historial |
| Auditoría | `ingest_run` (109 corridas), `schema_version` | trazabilidad de cargas |

**Versionado:** append-only con tombstone lógico — nueva versión de un archivo → filas nuevas + `mark_superseded(file_hash_viejo)`; toda lectura filtra `superseded_at IS NULL`. **Nada fuerza el supersede**: depende de disciplina del operador (y la UI web no tiene botón de re-ingesta).

## 5. Superficies de IA (tres, con controles muy distintos)

| Superficie | Modelo | Alcance | Controles |
|---|---|---|---|
| **Agente conversacional** (`agent.py` + `app.py` Streamlit) | Gemini 2.5 Flash | 102 tools: Excel, Outlook, SharePoint, consultas DB predefinidas | selección de tools por intent + gate de mutación por regex; tools de envío requieren intención explícita; escrituras Excel solo a archivos `*vagente*`; auto-modificación bloqueada; prompt anti-injection; 7 tools "autoritativas" devuelven output literal sin resumen del modelo; interceptores regex que evitan el LLM en 4 flujos críticos |
| **Chat DB** (`tools/db_chat.py` vía `POST /api/chat`) | DeepSeek → Groq Llama 3.3 → Gemini (fallback) | text-to-SQL sobre toda la DB de negocio | conexión SQLite **read-only real** (`mode=ro`), una sola sentencia, solo SELECT/WITH, regex de operaciones prohibidas, LIMIT 200, temperatura 0, `clarify` obligatorio ante ambigüedad, SQL visible al usuario |
| **Extracción de documentos** (EEFF PDF) | ChatGPT manual (principal) / Gemini batch / Groq (huérfano) | PDF → JSON estructurado | `prompt_version` chequeado (`eeff-v1`), cuadraturas recalculadas server-side, validación de esquema, preview + confirmación humana |

**Principio de diseño observado (correcto):** el LLM solo extrae estructura de documentos no estructurados o traduce lenguaje natural a SQL; nunca escribe a la DB sin un validador determinístico + humano en medio, y nunca es fuente de cifras.

### 5.1 Inventario de puntos de llamada a LLM (qué sale de la infraestructura local)

| # | Punto de llamada | Proveedor(es) y fallback | Información enviada |
|---|---|---|---|
| 1 | `agent.py`/`app.py` (`_llm_call`) | Gemini 2.5 Flash (endpoint OpenAI-compatible de Google) | system prompt (mapa de fondos/series/participaciones), instrucción del usuario, memoria acumulada (`load_memory`), resultados de tools (datos financieros, extractos de correos) truncados |
| 2 | `tools/db_chat.py` (generación SQL + síntesis) | `DB_CHAT_PROVIDER`: DeepSeek → Groq Llama 3.3 (2 cuentas) → Gemini; rota ante 429/quota. Con el `.env` actual solo hay clave Gemini | `_BUSINESS_CONTEXT` (esquema y KPIs), pregunta, historial (hoy provisto por el cliente), y en la síntesis hasta 50 filas de resultados de la DB |
| 3 | `scripts/ingest_eeff.py` (batch histórico EEFF) | Gemini por defecto; prefijos `groq:`/`anthropic:` opcionales | texto completo del EEFF PDF convertido a Markdown |
| 4 | Extracción EEFF vía **ChatGPT web** (ruta principal actual) | OpenAI (cuenta del usuario, fuera del sistema) | PDF del EEFF adjuntado manualmente + prompt `eeff-v1` |
| 5 | `tools/db/ingest_eeff_tri_groq.py` (huérfano, solo tests) | Groq Llama 3.3 | nota "Cuotas emitidas" del PDF TRI |

Estado (decisión 2026-07-24): este fallback es **configuración de desarrollo controlado**; la política formal de proveedores es un gate de salida a producción (ver `ai_principles.md` regla 6 y `ROADMAP.md` §6). No se envían secretos; los prompts instruyen minimización, pero los datos financieros reales sí transitan por estos proveedores.

## 6. Integridad y trazabilidad — estado real

Hallazgos verificados contra la DB productiva:

1. **La DB no fue construida por las migraciones.** Fue bootstrapeada desde `schema_v2.sql` (2026-06-01) y las versiones 2–22 se marcaron aplicadas en lote (timestamp idéntico) sin ejecutarse. Consecuencia: faltan en producción los `UNIQUE(file_hash, source_row)` de las tablas raw, 8 índices de performance, `dim_cuenta` y `publish_run`. **Los tests corren contra un schema (migraciones desde cero) distinto al de producción.**
2. **Duplicados reales por falta de UNIQUE:** ~12.300 filas vivas duplicadas en `raw_eeff_line` (33%), ~2.000 en `raw_er_activo_line`. El `INSERT OR IGNORE` de los repos es un no-op. Existen scripts de dedup ad-hoc que compensan.
3. **20.487 violaciones de FK** (invisibles porque `PRAGMA foreign_keys` solo valida escrituras nuevas): 18.009 por `fondo_key='APO'` vs `dim_fondo.fondo_key='Apo'` (toda la historia EEFF de Apoquindo, conviviendo con 3 filas `'Apo'` nuevas en 2026-03); 2.478 por `ingest_run_id` inválido, de las cuales **2.378 contienen file-hashes de texto en una columna INTEGER**.
4. **`derived_kpi` es casi no-trazable:** 99,8% de filas con `ingest_run_id` NULL; el upsert pisa valores sin historial; no hay invalidación al re-ingerir raw (flaw 3 de `docs/analisis-flaws-nuevo-enfoque.md`, abierto).
5. **`file_hash` NULL en 6,8% de `raw_eeff_line`** → esas filas son inalcanzables por `mark_superseded`.
6. `schema_v2.sql` está obsoleto y no es referenciado por nada; el registro `schema_version` 34–45 tiene timestamps manipulados a mano.
7. Lo que **sí** funciona bien: `ingest_run` completo (109 corridas, 24 herramientas, correcciones manuales registradas), filtrado `superseded_at IS NULL` consistente en lecturas de negocio, `estado_ingesta.py` calcula completitud on-demand por tipo/fondo/período, `KPI_META` del factsheet permite clickear cualquier número y ver su SQL.

## 7. Seguridad — estado real

| Control | Estado |
|---|---|
| `ingesta_server.py` (Flask :8765) | **Sin autenticación**, `debug=True` (consola Werkzeug), CORS acepta `Origin: null` y cualquier localhost, sin `MAX_CONTENT_LENGTH`, sin CSRF. Cualquier proceso local o página abierta en el navegador puede leer la DB vía `/api/chat` **y escribir vía `/api/*/commit`** |
| `POST /api/chat` | sin auth; `history` 100% controlado por el cliente (vector de prompt injection al generador SQL); sin cláusula anti-injection en los prompts de `db_chat`; **cero logging** de preguntas/SQL/respuestas |
| `agent.py --server` | bien: bearer token ≥32 chars obligatorio, `hmac.compare_digest`, loopback, límites de tamaño |
| `app.py` Streamlit | auth con bcrypt; pero `config.yaml` con hashes de 4 usuarios reales **versionado en git** |
| Path traversal | bien: `tools/path_security.py` + 8 tests |
| Datos sensibles a terceros | el chat DB envía esquema+filas a DeepSeek/Groq/Google según disponibilidad de API keys — sin política explícita |

## 8. Determinístico vs IA

- **Determinístico:** todos los ingestores Excel, parsers de PDF posicionales/regex (`ingest_gastos_pdf.py`, `ingest_eeff_pt.py`, `ingest_eeff_tri_series.py`), validaciones y cuadraturas, `estado_ingesta`, cálculo de KPIs (`consolidate_*`, `compute_kpis_series`), generación de factsheet/diagrama/dashboards, escritura del CDG por XML.
- **IA:** extracción EEFF desde PDF (con validación posterior), text-to-SQL del chat, y la conversación/orquestación del agente. Ninguna cifra se origina en el modelo.

## 9. Duplicaciones y fragilidades principales

1. **El factsheet existe 3 veces** con 3 fuentes: HTML (DB), Streamlit (DB), PPTX (PDF+scraping+CDG — el único entregable a clientes y el único que NO lee la DB).
2. **Config de fondos duplicada en ≥4 lugares** (`FONDOS_CFG`, `NOI_ACTIVOS/RR_ACTIVOS`, `SHEET_CFG`, `SERIES_CONFIG`) con valores inconsistentes entre sí, pese a existir `dim_fondo`/`dim_serie`.
3. **`app.py` reimplementa el loop de `agent.py`** (ya divergieron); `BASE_PROMPT` duplicado en `patch_prompts.py` obsoleto.
4. **`gestion_renta_tools.py`** hardcodea `sheet15/16/17.xml`: reordenar una hoja del CDG corrompe datos en silencio. Único camino de escritura al CDG.
5. **Skill financiera externa ausente** — TIR, LTV, duration (la mitad del factsheet) se calculan con código fuera del repo, no versionado, con rutas absolutas de Windows en 4 scripts.
6. **Tab EEFF de la web roto** desde 2026-07-20: `NameError` en `ingest_eeff_validated.py:317` (`existing_hash` no definido); sin tests para ese path ni para rent roll.
7. Sin orquestación de KPIs: orden de ejecución tácito; el rebuild post-commit refresca el HTML **sin** recalcular derivados.
8. ~1,5 MB de artefactos muertos commiteados en la raíz (`patch_*.py`, `script_test.js`, `test_funds.js`, `factsheet_debug.html`, `CUsers...noi_tools_old.py`, `fondo_diagrama.html` huérfano); `factsheet.html` (5,2 MB regenerable) versionado.
9. `.claude/settings.json` con rutas Windows de otra máquina y referencia a la DB v1.
10. Exportación **DB→Excel no existe** (grep `to_excel|Workbook()|xlsxwriter` = 0) siendo Excel el medio de trabajo del equipo.

## 10. Divergencias documentación ↔ código ↔ DB (las que inducen a error)

| Fuente | Dice | Realidad |
|---|---|---|
| `wiki/db.md` | UNIQUE(file_hash,source_row) garantiza idempotencia | no existe en producción; hay duplicados masivos |
| `wiki/db.md` | migraciones se aplican al importar `memory_tools` | falso; se invocan manualmente |
| `wiki/db.md` | rent roll 10.122 filas 2025-09..2026-03 | 119 filas, solo 2026-05 |
| `docs/ingest_pipeline.md` | DB `agente_toesca.db`, ingesta vía CLI/agente | DB es `_v2`; la vía real es la web (que el doc no menciona) |
| `repo_fondo.upsert_cuenta`, `repo_audit.*publish_run` | operan sobre `dim_cuenta`/`publish_run` | tablas inexistentes → `no such table` |
| `ROADMAP.md` (abril 2026) | próximos pasos centrados en enseñar planillas al agente | el desarrollo real pivoteó a DB + web + factsheet |
| `CLAUDE.md` §DB | — | **es la referencia más actualizada y correcta** |

## 11. Incertidumbres y supuestos pendientes de validación

- **Skill `real-estate-finance-expert`:** ¿existe una copia en la máquina Windows? Sin ella no se pueden recalcular TIR/LTV. Los valores actuales en `derived_kpi` son los últimos computados allí.
- **`memory/agente_state.db`** no existe en esta máquina (se crea on-demand); el historial de chat por usuario está efectivamente vacío aquí.
- **PPTX factsheet:** ¿sigue siendo el entregable oficial a aportantes? Determina la prioridad de migrarlo a la DB.
- **Uso multi-usuario real:** `config.yaml` tiene 4 usuarios, pero no hay evidencia de uso más allá del autor.
- **`raw_er_activo_line` de Apo/PT guarda UF en `monto_clp`** por convención heredada — documentado, pero cualquier agregación cross-activo que mezcle unidades es un riesgo latente permanente.
- Discrepancias de datos aceptadas por el usuario (4 en `raw_caja`; exclusión PT 2019-12) — registradas, no corregidas.

## 12. Preparación para las fases siguientes (visión "Financial Intelligence Platform")

| Fase de la visión | Estado real |
|---|---|
| **F1 — DB fuente de verdad + ingesta web + factsheets template** | ~70%. La DB y la ingesta existen y el diseño validate/commit es sólido, pero: integridad con deudas serias (§6), EEFF web roto, factsheet con páginas placeholder y sin parametrización por fecha de cierre, presentación mensual **inexistente**, PPTX cliente fuera de la DB |
| **F2 — Asistente IA financiero** | ~40% ya construido (adelantado a la visión): el chat text-to-SQL existe y es read-only, pero sin auth, sin logging/trazabilidad (viola el Principio 3), sin gráficos, sin export Excel, sin permisos |
| **F3 — Capa de conocimiento organizacional** | 0%. No hay tablas de eventos/observaciones/explicaciones, ni detección de anomalías, ni flujo de validación de comentarios |
| **F4 — Copilot** | 0%. Depende de F2+F3 |

**Conclusión:** los cimientos conceptuales (SQL como verdad, validación humana, templates rígidos, LLM solo como extractor/traductor) ya están adoptados en la práctica. Lo que falta antes de crecer es **consolidar la base**: integridad de la DB, seguridad del servidor, un solo pipeline de KPIs, un solo factsheet canónico, y trazabilidad del asistente. Ese es el punto de partida del `ROADMAP.md`.
