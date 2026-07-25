# Roadmap Técnico — Financial Intelligence Platform

**Versión:** 2.1 · 2026-07-24 (v2.0 mismo día; incorpora las 6 decisiones del usuario + directriz sobre el Asistente)
**Reemplaza** el roadmap de abril 2026 (histórico: `git show e4626cf:ROADMAP.md`).
**Base:** diagnóstico en `system_architecture.md`; principios en `ai_principles.md`; visión "Financial Intelligence Platform"; análisis entregados en `docs/plan-migracion-claves-apoquindo.md` y `docs/analisis-cuotas-fondos.md`.

**Decisiones ya tomadas por el usuario (2026-07-24), incorporadas aquí:**
1. Claves Apoquindo: 4 entidades separadas, relación por `fondo_id`, migración solo con protocolo reversible (ver doc de plan); IDs técnicos como etapa posterior opcional.
2. Cuotas: no cambiar cifras hasta validar semántica; modelo explícito por tipo de cuota (ver doc de análisis). *Resultado del análisis: no hay contradicción — circulación vs emitidas.*
3. Factsheet **HTML es el único canónico**. PPTX y dashboards Streamlit: eliminación controlada, sin migración ni paridad. Arquitectura: `SQL → capa canónica de KPIs → factsheet HTML`.
4. Proveedores LLM: fallback actual se mantiene como **configuración de desarrollo**; política formal es requisito de **salida a producción**, no bloqueo de F0/F1.
5. `config.yaml`/usuarios Streamlit: eliminar si se confirma que pertenecen solo a la app obsoleta (verificación hecha: `config.yaml` lo lee únicamente `app.py:153`; pero `app.py` recibió un commit cosmético el 2026-07-23 — falta confirmación del usuario de que la app Streamlit no se usa; sin rewrite de historial git salvo credenciales reutilizadas).
6. CDG: **cortar la relación por completo** — sin integraciones, sin paridad, sin criterio de corte basado en él; decomiso controlado. La plataforma se valida contra fuentes originales + reglas aprobadas + revisión humana.
7. Presentación mensual: capacidad futura **pendiente de definición humana** — no diseñar formato/contenido ahora; nunca reutilizar el PPTX viejo como base.
8. El **Asistente Virtual Inmobiliario Toesca ya existe como producto**: la Fase 2 lo fortalece y expande sobre la implementación actual, sin crear asistentes paralelos.

---

## 1. Diagnóstico (resumen)

Detalle en `system_architecture.md`. Lo que condiciona el plan: la arquitectura objetivo ya está adoptada (DB canónica, validate→commit humano, factsheet template SQL, chat read-only); las deudas que bloquean crecer son integridad de la DB (schema no reproducible, duplicados, claves `APO`/`Apo`, `derived_kpi` no trazable), seguridad del servidor (sin auth, `debug=True`), el tab EEFF roto, la skill financiera externa ausente, y outputs/asistente sin trazabilidad de consultas.

## 2. Brecha estado actual → visión

| Visión | Estado | Brecha principal |
|---|---|---|
| F1: DB + ingesta web + outputs template | ~70% | integridad DB, EEFF web roto, factsheet incompleto/no parametrizado por fecha de cierre, legacy sin decomisar |
| F2: Asistente IA financiero | ~40% (ya existe el producto) | sin auth, sin trazabilidad (viola P3), sin allowlist, sin gráficos/Excel, sin permisos |
| F3: Capa de conocimiento | 0% | modelo de datos, anomalías, flujo de validación |
| F4: Copilot | 0% | depende de F2+F3 |

---

## 3. Fases

Etiquetas: **[D]** determinístico · **[SQL]** consulta/cálculo SQL · **[GEN]** generación de archivos por código · **[IA-O]** orquestación IA · **[IA-X]** extracción IA validada · **[H]** validación/decisión humana.

---

### FASE 0 — Consolidación de cimientos

**Problema:** la fuente única de verdad tiene duplicados e inconsistencias; la web es insegura; el flujo EEFF está roto. **Valor:** confiabilidad defendible. **Sin IA.**

1. **[D] Arreglar ingesta EEFF web** — `ingest_eeff_validated.py:317` (`existing_hash` → `bool(periodos_existentes)`) + tests de regresión de `/api/validate` y `/api/ingest` (hoy inexistentes) y del path rent roll.
2. **[D] Re-baseline del schema** — `schema_baseline.sql` desde la DB productiva; migración 058 "baseline" para DBs nuevas; tests contra ese baseline; `schema_v2.sql` marcado histórico. Decidir formalmente el destino de cada objeto de las migraciones 1–22 nunca aplicadas (UNIQUE, índices, `publish_run`, `dim_cuenta`).
3. **[SQL][H] Migración de claves Apoquindo — Etapa A** según `docs/plan-migracion-claves-apoquindo.md`: backup + copia de prueba + dry-run con conteos + migración transaccional **solo del `fondo_key`** (`APO`→`Apo` en `raw_eeff_line` y `raw_valor_cuota_contable`) + comparación de factsheet y respuestas del Asistente antes/después + rollback disponible. Prohibido el reemplazo global de texto. **Las claves de `derived_kpi` quedan explícitamente FUERA de esta tarea** (ver 1.9): análisis entregado en `docs/matriz-claves-ambiguas-apoquindo.md`; no se modifican hasta que el usuario elija el modelo del agregado y exista el pipeline canónico. Resultado del análisis que desbloquea la parte de fondo: no hay solapamiento ni doble conteo entre convenciones de nombres, así que el `fondo_key` puede consolidarse sin tocar `derived_kpi`.
4. **[SQL][H] Saneamiento restante** — dedup `raw_eeff_line`/`raw_er_activo_line` + aplicar `UNIQUE(file_hash, source_row)`; reparar `ingest_run_id` de texto y `file_hash` NULL; `tests/db/test_invariantes.py` (FKs limpias, sin duplicados vivos, sin Machalí post-2025-08, vacancia ∈ [0,1], una sola clave por fondo por tabla).
5. **[D] Seguridad del servidor** — token/sesión obligatoria (patrón `agent.py --server`), `debug=False`, CORS restringido, `MAX_CONTENT_LENGTH`, try/except en `validate` (errores legibles), validación server-side de extensión.
6. **[D] Internalizar la skill financiera** — `real-estate-finance-expert` → `tools/finance/` versionada, testeada contra los valores de referencia congelados del wiki; eliminar rutas absolutas Windows. *Riesgo: si no existe copia recuperable en la máquina Windows, hay que reimplementar desde la metodología del wiki (está completa).*
7. **[D] ~~Cluster Streamlit legacy~~ — ✅ COMPLETADO 2026-07-24.** Autorizado por el usuario. Eliminados con `git rm` (historial preservado): `app.py`, `config.yaml`, `login_template.html`, `style.css`, `.streamlit/config.toml`, `dashboards/{fondos,eeff_tri,tir_tri}.py`, `wiki/agente/dashboard-fondos.md`; retiradas de `requirements.txt` las deps que solo ellos usaban (`streamlit-authenticator`, `bcrypt`, `plotly`); `AUTH_COOKIE_KEY` fuera de `.env.example` y README. Análisis de dependencias previo: nadie importaba `app.py` ni `dashboards/`; `config.yaml`/`login_template`/`style.css` solo los leía `app.py`; `config/cuenta_eeff_map.yaml` (usado por `eeff_cuenta_mapper`) vive en `config/`, no en `dashboards/` — no se tocó. Conservados por seguir en uso: `streamlit` como librería (`tools/memory_tools.py` lee `st.session_state`), `pandas` (`excel_tools`), `tools/ask_tools.py` completo (`registry` importa `preguntar_usuario`; `set_streamlit_mode` queda vestigial a propósito — estabilidad sobre limpieza). Verificación: suite **idéntica antes/después** (286 passed, 3 failed preexistentes, 5 skipped); `factsheet.html` regenerado **byte-idéntico**; `ingesta_server` (25 rutas), `registry` (102 tools), `agent` y `db_chat` (incl. rechazo de SQL destructivo) importan y operan. Efecto colateral a registrar: sin Streamlit, `memory_tools._get_user()` siempre cae a `"general"` → la memoria del agente es global (ya lo era en CLI/server).
8. **[D] Higiene de repo** — borrar artefactos muertos (`patch_*.py`, `script_*.js/txt`, `test_funds.js`, `factsheet_debug.html`, `CUsers...noi_tools_old.py`, `fondo_diagrama.html` si nadie lo usa), `.gitignore` para `factsheet.html`, limpiar `.claude/settings.json`.
9. **[D] Botón de re-ingesta (supersede) en la web** — hoy corregir un período requiere SQL a mano.

**Salida de fase:** invariantes y suite verdes sobre la DB real; `foreign_key_check` = 0; ingesta EEFF end-to-end funcionando; servidor autenticado.

---

### FASE 1 — Completar la plataforma determinística y decomisar el legacy

**Problema:** KPIs por scripts sueltos sin invalidación; factsheet incompleto; legacy (CDG, PPTX, Streamlit) compite con la arquitectura canónica. **Valor:** un solo camino por output: `SQL → capa canónica de KPIs → factsheet HTML`. **Sin IA.**

1. **[SQL] Orquestador de KPIs** — `tools/db/kpi_pipeline.py`: dependencias (activo→fondo→bursátil), `ingest_run_id` en `derived_kpi`, invalidación `stale_at` al re-ingerir, `es_periodo_cerrado()` única. Commit de ingesta encola recálculo (no dentro del request); rebuild del factsheet post-KPIs con error visible.
2. **[SQL] Catálogo `dim_recipe`/`dim_kpi`** — definición canónica por KPI+variante; `KPI_META` del factsheet generado desde aquí.
3. **[SQL] Config de fondos desde la DB** — `FONDOS_CFG` y equivalentes leen `dim_fondo`/`dim_serie`/`dim_activo` + nueva `dim_fondo_ficha` (datos de ficha con fuente documentada) + `fact_cuotas` por tipo (`docs/analisis-cuotas-fondos.md` §3). Las cifras de `cuotas_emitidas` no se tocan hasta validarlas contra reglamento/CMF (**[H]**).
4. **[GEN] Factsheet parametrizado y completo** — `--periodo`, `_fetch_perf_data` para Apo/TRI, assets sin cuadruplicar.
5. **[GEN] Export DB→Excel** — `tools/export_excel.py` con hoja de metadatos (períodos, generación, fuentes); botón en la web; luego herramienta del Asistente (F2).
6. **[SQL][H] Backfill rent roll histórico** — hoy solo 2026-05; prerequisito de vacancia/absorción en el factsheet.
7. **[D][H] Decomiso del CDG** — decisión: cortar la relación por completo; no se construye nada más sobre él y no es referencia de validación. Protocolo: (a) inventario de componentes CDG: `tools/gestion_renta_tools.py` (20 tools de escritura), grupo `_TOOLS_CDG` y `PROMPT_CDG` en `agent.py`/`registry.py`, correos de solicitud CDG, `wiki/procesos/cdg-mensual.md`; (b) verificar qué datos/reglas del CDG aún no existen en la DB (p.ej. `cdg_extract.xlsx` ya fue ingerido como fuente histórica — se conserva como dato, no como integración); (c) migrar o documentar solo lo necesario; (d) eliminar las tools de escritura CDG del agente y archivar el proceso en el wiki como histórico; (e) tests + verificación de que ingesta/KPIs/factsheet/Asistente no cambian. Los archivos Excel originales quedan en SharePoint como referencia histórica, fuera de la arquitectura activa.
8. **[D][H] Eliminación controlada del factsheet PPTX** — `tools/factsheet_tools.py` (1.326 líneas) + sus 14 tools en `registry.py` + el grupo de intent `_TOOLS_FACTSHEET`. **Queda en F1 y no en F0** porque está acoplado al agente: eliminarlo toca `registry.py` y los prompts, y depende de la decisión pendiente sobre qué sobrevive de `agent.py` (§8 punto 4). Protocolo: análisis de dependencias → confirmar que ningún flujo vigente lo usa → conservar lo compartido (`eeff_tools`, `web_bursatil_tools`, `sharepoint_paths` los usan otros flujos) → eliminar → tests + validación del factsheet HTML y del Asistente. Historial en git. Un futuro PPTX se construye desde cero sobre la capa canónica. *(Los dashboards Streamlit ya se eliminaron en F0.7.)*

9. **[SQL][H] Normalizar el agregado de Apoquindo en `derived_kpi`** — según `docs/matriz-claves-ambiguas-apoquindo.md`: `Apoquindo` (178 filas, NOI/ingresos desde ER) y `Fondo Apoquindo` (91 filas, vacancia desde CDG) son ambas el agregado Apo4501+Apo4700, verificado con coincidencia exacta; ninguna es el look-through de TRI (ese ya está bien resuelto en `v_activo_fondo_efectivo`). Ambas están mal etiquetadas como `entidad_tipo='activo'`. Pendiente: elegir modelo (fondo vs `dim_grupo_activo`). Criterio del usuario para el histórico: **preservar filas, marcarlas legacy/reemplazadas, no mezclar bajo una sola clave, recalcular desde raw con el pipeline canónico**; lo que no se pueda recalcular queda pendiente y documentado. Requiere: columnas `estado`/`reemplazado_por` en `derived_kpi` (propuesta en §5 del doc) + actualizar `noi_query.py:24` y el catálogo del Asistente en `db_chat.py:247,252` **en el mismo commit** (hoy ambos exponen la clave `Apoquindo` — cambiarla sin ellos rompe el Asistente) + golden tests del contrato (F2.0). La vacancia legacy (`cdg_vacancia_v1`, fuente CDG en decomiso) solo puede reemplazarse tras el backfill de rent roll (F1.6).

**Salida de fase:** cierre mensual completo ejecutado solo con la plataforma (ingesta → KPIs → factsheet HTML → export), con `derived_kpi` 100% trazable; legacy decomisado sin regresiones.

---

### FASE 2 — Fortalecimiento y expansión del Asistente Virtual Inmobiliario Toesca

**Directriz:** el Asistente **ya existe** (superficie actual: burbuja `web/chat_bubble.js` + `POST /api/chat` + `tools/db_chat.py`). Toda evolución es **incremental sobre esa implementación**, reutilizando sus interfaces, prompts, validación SQL y fallback donde son correctos. No se crea un asistente nuevo ni una implementación paralela.

0. **[D] Documentar el contrato actual** (primera tarea, antes de tocar nada): capacidades, límites (solo SELECT, LIMIT 200, `clarify`, few-shots), dependencias (proveedores, `_BUSINESS_CONTEXT`), comportamiento esperado — como doc + suite de regresión con las preguntas gold (los 11 few-shots + casos reales). Todo cambio posterior corre esa suite. *Nota a resolver aquí ([H]): relación con `agent.py` (el agente operativo de 102 tools) — tras decomisar CDG gran parte de sus tools queda obsoleta; definir qué capacidades operativas sobreviven y dónde viven.*
1. **[D] Identidad y sesión** — hereda la auth de la plataforma (F0.5); historial **server-side** (`chat_session`/`chat_message`); se elimina el historial fabricado por el cliente.
2. **[SQL] Trazabilidad** — `chat_query_log` (usuario, pregunta, SQL, proveedor/modelo, `prompt_version`, filas, duración, error); prompts versionados (`db-chat-v2`).
3. **[D] Capa semántica con allowlist** — vistas curadas + `derived_kpi` + dims; validación post-generación del SQL contra la allowlist (AST, p.ej. `sqlglot`); timeout de ejecución; cláusula anti-injection; KPIs canónicos siempre desde `derived_kpi`.
4. **[IA-O] Herramientas tipadas** además del SQL libre: `consultar_kpi`, `comparar_periodos`, `cobertura`, `generar_tabla`, `generar_grafico` ([GEN] spec declarativa → render determinístico), `generar_excel` (reusa F1.5), `explicar_kpi` (desde `dim_recipe`).
5. **[D][H] Permisos simples** — tabla `usuario` + visibilidad por fondo/tipo de dato, server-side. Sin RBAC complejo.
6. **[D] Faltantes explícitos** — advertencias de cobertura/período incompleto antes de responder series.

**Salida de fase:** 1 mes de uso real con log auditado y tasa de error medida y aceptada; toda respuesta reproducible desde `chat_query_log`; suite de regresión del contrato verde en cada cambio.

---

### FASE 3 — Capa de conocimiento organizacional

Sin cambios de alcance respecto de v2.0: anomalías por **reglas SQL versionadas** (`dim_regla_anomalia` → `anomalia_detectada`), conversación de cierre donde el Asistente redacta **borradores**, modelo `evento`/`explicacion` con estados `borrador → validado | rechazado; obsoleto`, solo lo validado es citable y siempre etiquetado y separado de las cifras, anti-injection sobre texto almacenado, integración en outputs solo con conocimiento validado. Umbrales iniciales y quién valida: **[H]** pendientes.

**Salida de fase:** 2–3 cierres mensuales con el flujo completo; ante "¿por qué cayó X?", cifra SQL + explicación validada citada, o "no hay explicación registrada".

### FASE 4 — Copilot de inteligencia financiera

Solo tras madurar F2+F3; diseño se especifica entonces (resúmenes ejecutivos como borrador [H], patrones sobre anomalías/explicaciones [SQL], paquetes para comités [GEN], alertas por reglas [D]).

### Capacidades futuras pendientes de definición humana (sin fecha ni fase)

- **Presentación mensual**: se registra como capacidad futura. No se define ahora formato, contenido, diseño ni herramienta; cuando exista la necesidad se evaluarán caso de uso, usuarios, formato, estructura, edición, plantilla de referencia y su relación con la capa canónica. Se construirá desde cero como template rígido determinístico; queda prohibido partir del PPTX obsoleto.
- **Nuevo output PPTX** (si aparece necesidad concreta): desde cero, sobre la capa canónica.

---

## 4. Dependencias y orden

```
F0.1-0.2 ──▶ F0.3-0.4 (saneamiento) ──▶ F1.1-1.3 (pipeline+catálogo+config) ──▶ F1.4-1.6
F0.5 (auth) ──▶ F2.1
F1.7 (decomiso CDG) ──▶ F2.0 (define qué queda del agente operativo)
F1.1-1.2 ──▶ F2.3/F2.4 · F1.5 ──▶ F2.4 · F2 ──▶ F3 ──▶ F4
Paralelizables: F0.6 (skill), F0.7-0.8 (legacy/higiene), F1.6 (backfill RR), F1.8 (outputs obsoletos)
```

## 5. Qué NO implementar todavía

- Frameworks multi-agente (LangGraph/CrewAI), RAG/base vectorial, Graph API/nube/SSO, PostgreSQL, RBAC elaborado.
- **Nada nuevo sobre el CDG** — está en decomiso, no en mantención evolutiva.
- Presentación mensual y nuevos PPTX — pendientes de definición humana (ver arriba).
- Política corporativa completa de proveedores LLM / clasificación avanzada de datos / capa extensa de compliance — se difiere a la salida a producción (ver §6).
- IA generando layouts o documentos (P4): nunca.

## 6. Estrategias transversales

- **Pruebas:** cada fase entrega sus tests; prioridad: invariantes de negocio + endpoints de ingesta + golden tests de KPIs + suite de contrato del Asistente. `pytest` + `ruff` antes de commit.
- **Trazabilidad:** linaje raw (existente) → KPIs con corrida+receta (F1) → log del Asistente (F2) → estados de conocimiento (F3). Si no se puede reconstruir el origen, no se muestra.
- **Validación humana:** ingesta (existente), correcciones (F0.9), migraciones de datos (protocolo Apoquindo), eliminaciones de legacy (protocolos F0.7/F1.7/F1.8), explicaciones (F3), resúmenes (F4).
- **Proveedores LLM (configuración de desarrollo, decisión 2026-07-24):** el fallback DeepSeek→Groq→Gemini se mantiene durante el desarrollo controlado, claramente identificado como configuración de desarrollo, con arquitectura desacoplada para cambiar proveedor. Controles mínimos vigentes: no enviar secretos/credenciales/variables de entorno; minimizar datos enviados; datos sintéticos en pruebas cuando sea razonable. El inventario de puntos de llamada LLM está en `system_architecture.md` §5. **Requisito de salida a producción (gate, no bloqueo):** decisión humana explícita sobre proveedores autorizados, cuentas, retención, entrenamiento, fallback permitido, minimización, logging/auditoría y tratamiento de información financiera.
- **Seguridad:** auth en todo endpoint; secretos fuera del repo; eliminaciones solo con análisis de dependencias + tests.

## 7. Criterios de aceptación globales

1. **F0:** DB íntegra y schema reproducible; servidor autenticado; EEFF web funcionando; suite verde; migración Apoquindo terminada solo con tests verdes, conteos cuadrados y sin cambios de comportamiento inesperados.
2. **F1:** cierre mensual sin tocar Excel a mano (salvo fuentes); un solo valor por KPI; todo KPI trazable; CDG/PPTX/Streamlit decomisados sin regresiones.
3. **F2:** toda respuesta del Asistente reproducible desde el log; cero escrituras posibles desde el chat; permisos aplicados; contrato con suite de regresión.
4. **F3:** conocimiento validado citable y separado de los hechos.
5. **Siempre:** ningún número mostrado a un usuario se originó en un modelo.

---

## 8. Decisiones que requieren validación humana

### Resueltas (2026-07-24) — registradas al inicio de este documento
Claves Apoquindo (protocolo), cuotas (investigar antes de cambiar — hecho, sin contradicción), factsheet HTML canónico + eliminación de PPTX/Streamlit, política LLM diferida como gate de producción, `config.yaml` (eliminar si se confirma obsoleto), decomiso total del CDG, presentación mensual pospuesta, Fase 2 sobre el Asistente existente.

### Pendientes
1. **Apoquindo — modelo del agregado** (`docs/matriz-claves-ambiguas-apoquindo.md` §6): (a) Opción A (`entidad_tipo='fondo'`, key `Apo`) vs Opción B (`dim_grupo_activo`, útil si vas a modelar subgrupos como "Centros Comerciales" de TRI); (b) si las 178 filas se recalculan con la misma receta o con una nueva versionada; (c) si el `2026-07 = 0,0` de vacancia es dato real o artefacto del CDG; (d) si/cuándo ejecutar la Etapa B de IDs técnicos (`FTRI_APO`/`ACT_APOQUINDO_*`). *Ya resuelto por el análisis: ambas claves son el agregado 4501+4700, ninguna es el look-through de TRI, y no hay doble conteo.*
2. **Cuotas emitidas:** confirmar 4.000.000 / 1.800.000 / 2.000.000 contra reglamento/CMF (`docs/analisis-cuotas-fondos.md` §5) y el significado exacto de "emitidas". *No bloquea F0 (decisión del usuario).*
3. **Agente operativo (`agent.py`, 102 tools):** tras el decomiso del CDG, definir qué capacidades sobreviven (correo, SharePoint, consultas a la DB) y cómo se relacionan con el Asistente (F2.0). Es prerequisito de F1.8. Nota: al eliminarse Streamlit, el agente solo tiene entrada CLI y `--server` (que hoy no arranca porque falta `AGENT_SERVER_API_TOKEN` en el `.env`) — conviene decidir si conserva interfaz de usuario o queda como backend de tareas.
5. **Duplicados EEFF:** política de qué versión sobrevive en cada grupo duplicado (¿mayor `loaded_at`?) — afecta cifras históricas.
6. Discrepancias aceptadas (4 filas `raw_caja`, exclusión PT 2019-12): ¿definitivas?
7. Convención UF en `monto_clp` (ER Apo/PT): ¿migrar a `monto`+`unidad` o congelar documentada?
8. **Usuarios y permisos** (F2.5): quiénes, qué ve cada uno, y si el Asistente se expone fuera de localhost.
9. **F3:** umbrales iniciales de anomalías por KPI; quién valida explicaciones; si comentarios validados pueden salir a aportantes.
10. **Gate de producción LLM** (§6) cuando se acerque la exposición a más usuarios.
