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

1. **[D] ~~Arreglar ingesta EEFF web~~ — ✅ COMPLETADO 2026-07-24.** Eran **dos** bugs independientes: (a) el `NameError` de `existing_hash` (rompía `/api/validate` e `/api/ingest` con 500 para todos los fondos), resuelto con `_hash_ya_ingestado(fhash)` — mismo criterio que el corte `skipped_duplicate` de `commit()`, sin duplicar `periodos_existentes`; (b) **descubierto al escribir los tests**: persistir Apoquindo fallaba con `FOREIGN KEY constraint failed`, porque el prompt/UI usan `APO` y `dim_fondo` tiene `Apo` (verificado contra copia de producción). Resuelto en conjunto con F0.3. Nuevo `tests/test_ingesta_server_eeff.py` (16 casos).
2. **[D] ~~Re-baseline del schema~~ — ✅ COMPLETADO 2026-07-24.** `tools/db/baseline.sql` (esquema consolidado 001..060, generado desde producción por `scripts/regenerar_baseline.py`); `apply_migrations()` lo aplica a DBs vacías y registra 1..60 de forma **veraz**, porque el baseline sí incorpora sus efectos. Migración 059 recupera los 12 índices que las migraciones declaraban y producción nunca tuvo; 060 normaliza `schema_version`. Excluidos con justificación: `dim_cuenta` (obsoleta, reemplazada por `dim_cuenta_eeff`; su FK sobre una tabla vacía hacía fallar **toda** ingesta con `cuenta_codigo` en una DB nueva) y `publish_run` (nunca creada ni usada; sus helpers muertos eliminados de `repo_audit`/`repo_fondo`). **Verificación:** DB nueva vs producción comparadas objeto por objeto (columnas, FKs, UNIQUEs, índices, vistas) → **93 objetos, cero diferencias**, blindado por `tests/db/test_baseline.py` y por `regenerar_baseline.py --check`.
   *Hallazgo:* 8 tests de idempotencia afirmaban una garantía que producción **nunca tuvo** (pasaban porque la DB de test sí tenía el UNIQUE) — por eso los duplicados se acumularon en silencio. Quedan como `xfail(strict=True)`: cuando F0.4 imponga la restricción, pasarán y strict obligará a quitar el marcador.
3. **[SQL] ~~Migración de claves Apoquindo — Etapa A~~ — ✅ COMPLETADO 2026-07-24** (migración `058_consolidar_fondo_key_apo.sql`). Solo `fondo_key`: 18.009 filas de `raw_eeff_line` y 15 de `raw_valor_cuota_contable`, `APO`→`Apo`. Protocolo cumplido: backup (`memory/backups/agente_toesca_v2.pre-apo-consolidacion.db`), dry-run sobre copia con conteos antes/después (total de filas, filas vivas, suma de montos y nº de períodos **sin cambio**; cero filas `APO`), y factsheet regenerado desde la copia migrada con **0 diferencias en el JSON de datos**. Violaciones de FK: **20.487 → 2.478**. Reversible (solo reetiqueta). Código coordinado en el mismo commit porque había lecturas con `'APO'` exacto que habrían devuelto cero filas: `tools/db/fondo_keys.py` (fuente única del canónico), `build_factsheet.py` (usaba `fondo_key.upper()`), `estado_ingesta.CONFIG` (la card EEFF habría dicho "nunca ingestado"), `ingest_eeff.py` e `ingest_from_json.py` (ahora persisten el canónico; las carpetas de trabajo siguen usando el alias). **`derived_kpi` quedó fuera a propósito** → F1.9.
   *Duplicados lógicos que la consolidación hace visibles bajo una sola clave y que NO se dedujeron aquí (política pendiente, §8): `TOTAL ACTIVO` de 2026-03 desde dos fuentes con el mismo monto, y 4 cierres de 2025 de valor cuota con diferencias en el cuarto decimal.*
4. **[SQL] ~~Saneamiento de integridad~~ — ✅ COMPLETADO 2026-07-24** (migraciones 061–069).
   - **Integridad referencial en cero.** Las 2.478 violaciones eran una sola FK (`raw_eeff_line.ingest_run_id`): un cargador escribió el hash del archivo en esa columna y dejó `file_hash` vacío (solape del 100% entre ambos síntomas). El hash volvió a su columna, `ingest_run_id` quedó NULL y las filas se marcaron `lineage_status='legacy_untracked'` — sin inventar corridas sintéticas. **FK: 2.478 → 0**, `file_hash` NULL: 2.484 → 0, cifras intactas. El invariante ahora exige cero, sin umbral.
   - **Unicidad con la clave correcta y en la forma correcta.** Índices únicos **parciales** (`WHERE superseded_at IS NULL`) en er_activo, rent_roll, flujo y las 4 de parking: una sola versión vigente, historial ilimitado, reingesta posible sin depender del hash. Se descartaron dos formas incorrectas: el `UNIQUE(file_hash, source_row)` genérico (inútil en eeff, dañino en er_activo por el split 75/25) y `UNIQUE(..., superseded_at)`, que **no protege nada** porque SQLite trata cada NULL como distinto — verificado: las 4 restricciones de parking eran decorativas y se corrigieron recreando las tablas.
   - **Duplicados de `raw_eeff_line`: nada ejecutado, y con razón.** El análisis demostró que de los 346 grupos del caso 1, **cero** son ejecutables automáticamente (todos con `source_row` NULL, sin canónico ni sección), y de los 2.839 del caso 2 ninguno es copia exacta del mismo archivo. Se mantienen detenidos.
   - **`seccion` y `seccion_original`** en `raw_eeff_line`, con vocabulario normalizado; backfill solo donde es demostrable (12.970 filas), el resto NULL a propósito. **1.424 métricas de serie** separadas del perímetro contable (`METRICA_SERIE`).
   - **Validación humana como eje independiente del linaje** (`validado_por`, `validado_at`, `validacion_fuente`). Apo 2020-12 `ESF.total_activo` = 42.343.358.000 registrado como confirmado contra los EEFF.

5. **[D] ~~Seguridad del servidor~~ — ✅ COMPLETADO 2026-07-24.** Token obligatorio (`X-Ingesta-Token`, `hmac.compare_digest`) en todo `/api/*`, tomado de `INGESTA_TOKEN` o generado por sesión; se inyecta en las páginas que sirve el servidor, así que el flujo por navegador no cambia. CORS ya no refleja un `Origin` arbitrario ni `null` (solo localhost:8765). `debug=False` + `use_reloader=False`. `MAX_CONTENT_LENGTH` 32 MB con 413 en JSON. Los `validate` de archivo traducen un xlsx corrupto a error legible, pero un error inesperado sigue siendo 500 a propósito para que un bug real se vea como bug. `ingesta.bat` ya no abre el navegador antes de que Flask escuche. Nuevo `tests/test_ingesta_server_seguridad.py` (20 casos) + verificación contra el servidor real.
   **Cambio de flujo a comunicar:** abrir `factsheet.html` con doble clic (`file://`) ya no permite usar el Asistente; hay que abrirlo desde `http://127.0.0.1:8765/factsheet`. La burbuja lo explica en el 401.
6. **[D] Internalizar la skill financiera — ⏸ PENDIENTE URGENTE, bloqueado por acceso al computador Windows.**
   `~/.claude/skills/` no existe en esta máquina. La copia original probablemente sigue en `C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert`; revisarla es el primer paso, y **no debe incorporarse a ciegas**: primero inventario de funciones, fórmulas, dependencias y rutas absolutas, y comparación contra el golden.
   **No se reimplementa nada hasta entonces.** Tampoco se elimina `finance_tools.py`, ni se sobrescriben valores históricos de `derived_kpi`, ni se reconstruyen fórmulas ajustándolas al golden.
   ✅ **Trabajo previo ya hecho, útil en cualquier escenario:** golden congelado de los 7.226 valores de los 15 KPIs (`scripts/congelar_golden_kpis.py`, con tolerancias por familia y modo `--verificar`); contrato de `obtener(...)` documentado; inventario de consumidores por KPI; y catálogo `dim_kpi` que distingue qué KPIs tienen metodología escrita y cuáles dependen de recuperar el código.
   Este bloqueo **no impide** avanzar con el resto: el factsheet no invoca la skill, lee `derived_kpi`. Lo único que no se puede hacer es recalcular.

7. **[D] ~~Cluster Streamlit legacy~~ — ✅ COMPLETADO 2026-07-24.** Autorizado por el usuario. Eliminados con `git rm` (historial preservado): `app.py`, `config.yaml`, `login_template.html`, `style.css`, `.streamlit/config.toml`, `dashboards/{fondos,eeff_tri,tir_tri}.py`, `wiki/agente/dashboard-fondos.md`; retiradas de `requirements.txt` las deps que solo ellos usaban (`streamlit-authenticator`, `bcrypt`, `plotly`); `AUTH_COOKIE_KEY` fuera de `.env.example` y README. Análisis de dependencias previo: nadie importaba `app.py` ni `dashboards/`; `config.yaml`/`login_template`/`style.css` solo los leía `app.py`; `config/cuenta_eeff_map.yaml` (usado por `eeff_cuenta_mapper`) vive en `config/`, no en `dashboards/` — no se tocó. Conservados por seguir en uso: `streamlit` como librería (`tools/memory_tools.py` lee `st.session_state`), `pandas` (`excel_tools`), `tools/ask_tools.py` completo (`registry` importa `preguntar_usuario`; `set_streamlit_mode` queda vestigial a propósito — estabilidad sobre limpieza). Verificación: suite **idéntica antes/después** (286 passed, 3 failed preexistentes, 5 skipped); `factsheet.html` regenerado **byte-idéntico**; `ingesta_server` (25 rutas), `registry` (102 tools), `agent` y `db_chat` (incl. rechazo de SQL destructivo) importan y operan. Efecto colateral a registrar: sin Streamlit, `memory_tools._get_user()` siempre cae a `"general"` → la memoria del agente es global (ya lo era en CLI/server).
8. **[D] ~~Higiene de repo~~ — ✅ COMPLETADO 2026-07-24.** Eliminados 13 archivos sin referencias (~1,7 MB): los 3 `patch_*.py` (uno de ellos habría revertido `BASE_PROMPT` a la versión pre-rebranding), `fix.py`, los volcados de depuración del factsheet y el temporal de Windows. Conservados a propósito: `migrate_to_sqlite.py` (único camino para migrar `memory/historial.jsonl`) y `fondo_diagrama.html` (documento del usuario, no código). `factsheet.html` ya no se versiona. `.claude/settings.json` limpio de la DB v1 y de rutas de otra máquina.
9. **[D] ~~Botón de re-ingesta (supersede)~~ → TRASLADADO a F1.1.** Depende de `stale_at`, de la identificación de KPIs afectados y de un orquestador capaz de recalcular: un botón que deje KPIs desactualizados esperando un recálculo manual no se habilita. Diseño completo en `docs/diseno-supersede.md`. Puede prepararse antes (tabla `supersede_event`, primitiva transaccional, previews y tests de semántica) pero el flujo de uso final se habilita con el pipeline canónico.

10. **[D] Entorno de tests reproducible** — ✅ parcial: `holidays` estaba **sin declarar** siendo dependencia real de `ingest_parking_pt_mensual.py`, y `pytest` no estaba ni declarado ni instalado (de ahí que la suite no se pudiera correr en esta máquina). Agregados `holidays` a `requirements.txt` y `requirements-dev.txt` con pytest. Pendiente: CI local mínima.

### Estado de la Fase 0 (2026-07-24)

**Cerrado:** ingesta EEFF reparada · re-baseline del schema (DB nueva ≡ producción, 93 objetos sin diferencias) · claves de Apoquindo consolidadas · **integridad referencial en cero** · unicidad con índices parciales en 7 tablas · `seccion` incorporada · métricas de serie separadas · validación humana modelada · seguridad del servidor · cluster Streamlit eliminado · higiene de repo · entorno de tests reproducible · **Etapa 1 del mapeo canónico: 0 huecos funcionales**.

**Abierto dentro de F0:**
- **F0.6 skill financiera** — pendiente urgente, bloqueado por acceso al computador Windows. No bloquea nada más.

**Trasladado formalmente a F1:**
- **Supersede (ex F0.9) → F1.1**, por dependencia real del pipeline de KPIs.
- **Duplicados de `raw_eeff_line` (resto del ex F0.4) → F1.1**, porque su resolución depende de completar `seccion` y el mapeo canónico, no de un saneamiento aislado.
- **Recálculo de `m2_vacantes` → F1.6**, tras el backfill de rent roll (su receta actual depende del CDG, en decomiso).
- **Mapeo canónico etapas 2–4 → F1**, ya sin urgencia: la cobertura funcional está al 100% y el 82% de filas sin mapear no lo usa ningún output.

**Suite:** 386 passed, 5 skipped, 1 xfailed (el de `raw_eeff_line`, que se mantiene hasta que exista una clave demostrada — no se elimina imponiendo una restricción incompleta).

**Salida de fase:** invariantes y suite verdes sobre la DB real; `foreign_key_check` = 0; ingesta EEFF end-to-end funcionando; servidor autenticado.

---

### FASE 1 — Completar la plataforma determinística y decomisar el legacy

**Problema:** KPIs por scripts sueltos sin invalidación; factsheet incompleto; legacy (CDG, PPTX, Streamlit) compite con la arquitectura canónica. **Valor:** un solo camino por output: `SQL → capa canónica de KPIs → factsheet HTML`. **Sin IA.**

1. **[SQL] Orquestador de KPIs — incluye lo trasladado desde F0** — `tools/db/kpi_pipeline.py`: dependencias (activo→fondo→bursátil), `ingest_run_id` en `derived_kpi`, invalidación `stale_at` al re-ingerir, `es_periodo_cerrado()` única. Commit de ingesta encola recálculo (no dentro del request); rebuild del factsheet post-KPIs con error visible.
   **Trasladado desde F0, con su dependencia real:**
   - **Botón de supersede** (`docs/diseno-supersede.md`): la unidad de reemplazo es el archivo o la corrida, nunca la fila; misma primitiva que el saneamiento histórico. Alcance inicial en la UI: **EEFF y rent roll**. El backend resuelve la tabla server-side desde una allowlist cerrada — el cliente nunca envía un nombre de tabla. Mientras no haya identidad, `usuario = 'local_dev'`, que **no identifica a una persona ni sirve como auditoría multiusuario**: es una identidad técnica temporal que debe reemplazarse por el usuario autenticado (F2.1) antes de habilitar múltiples usuarios.
   - **Duplicados de `raw_eeff_line`**: se resuelven aquí, no antes, porque dependen de completar `seccion` y el mapeo canónico. Los 346 grupos del caso 1 y los 2.839 del caso 2 siguen detenidos.
   - **Invalidación**: `stale_at` en `derived_kpi`; superseder marca stale los KPIs de los períodos afectados y el orquestador los recalcula. Los KPIs `legacy` del catálogo (`ltc`, `dscr`) quedan excluidos del recálculo.

2. **[SQL] Catálogo `dim_recipe`/`dim_kpi`** — definición canónica por KPI+variante; `KPI_META` del factsheet generado desde aquí.
3. **[SQL] Config de fondos desde la DB** — `FONDOS_CFG` y equivalentes leen `dim_fondo`/`dim_serie`/`dim_activo` + nueva `dim_fondo_ficha` (datos de ficha con fuente documentada) + `fact_cuotas` por tipo (`docs/analisis-cuotas-fondos.md` §3). Las cifras de `cuotas_emitidas` no se tocan hasta validarlas contra reglamento/CMF (**[H]**).
4. **[GEN] Factsheet parametrizado y completo** — `--periodo`, `_fetch_perf_data` para Apo/TRI, assets sin cuadruplicar.
5. **[GEN] Export DB→Excel** — `tools/export_excel.py` con hoja de metadatos (períodos, generación, fuentes); botón en la web; luego herramienta del Asistente (F2).
6. **[SQL][H] Backfill rent roll histórico** — hoy solo 2026-05; prerequisito de vacancia/absorción en el factsheet.
7. **[D][H] Decomiso del CDG** — decisión: cortar la relación por completo; no se construye nada más sobre él y no es referencia de validación. Protocolo: (a) inventario de componentes CDG: `tools/gestion_renta_tools.py` (20 tools de escritura), grupo `_TOOLS_CDG` y `PROMPT_CDG` en `agent.py`/`registry.py`, correos de solicitud CDG, `wiki/procesos/cdg-mensual.md`; (b) verificar qué datos/reglas del CDG aún no existen en la DB (p.ej. `cdg_extract.xlsx` ya fue ingerido como fuente histórica — se conserva como dato, no como integración); (c) migrar o documentar solo lo necesario; (d) eliminar las tools de escritura CDG del agente y archivar el proceso en el wiki como histórico; (e) tests + verificación de que ingesta/KPIs/factsheet/Asistente no cambian. Los archivos Excel originales quedan en SharePoint como referencia histórica, fuera de la arquitectura activa.
8. **[D][H] Eliminación controlada del factsheet PPTX** — `tools/factsheet_tools.py` (1.326 líneas) + sus 14 tools en `registry.py` + el grupo de intent `_TOOLS_FACTSHEET`. **Queda en F1 y no en F0** porque está acoplado al agente: eliminarlo toca `registry.py` y los prompts, y depende de la decisión pendiente sobre qué sobrevive de `agent.py` (§8 punto 4). Protocolo: análisis de dependencias → confirmar que ningún flujo vigente lo usa → conservar lo compartido (`eeff_tools`, `web_bursatil_tools`, `sharepoint_paths` los usan otros flujos) → eliminar → tests + validación del factsheet HTML y del Asistente. Historial en git. Un futuro PPTX se construye desde cero sobre la capa canónica. *(Los dashboards Streamlit ya se eliminaron en F0.7.)*

9. **[SQL][H] Normalizar el agregado de Apoquindo en `derived_kpi`** — análisis en `docs/matriz-claves-ambiguas-apoquindo.md`. **Decisiones del usuario (2026-07-24), ya cerradas:**
   - **Modelo:** la representación canónica es `entidad_tipo='fondo'`, `entidad_key='Apo'`. **No** se modela como `dim_grupo_activo`: un fondo no es una agrupación analítica. El eventual subtotal "Centros Comerciales" de TRI *sí* sería un grupo de activos, y recién entonces se creará `dim_grupo_activo` con su relación de miembros — no se introduce esa estructura ahora ni se usa para representar un fondo.
   - **Recálculo:** no se reetiquetan las filas antiguas como si su identidad y metodología nunca hubieran cambiado. Se **preservan como legacy/obsoletas** y se recalcula desde las fuentes raw con una **receta nueva y versionada** que deje explícito: que agrega `Apo4501`+`Apo4700`, que el resultado corresponde al fondo `Apo`, las fuentes, la metodología, la versión y la corrida que lo produjo. Prohibido mezclar bajo la clave nueva resultados históricos no recalculados con el pipeline canónico.
   - **Vacancia 2026-07 = 0,0:** es artefacto del CDG / dato no válido, no una vacancia real (es posterior al último rent roll y julio-2026 aún no es un cierre completo). Se preserva el registro legacy para auditoría pero marcado inválido/no publicado, excluido de consultas, KPIs y outputs vigentes; ante esa consulta se devuelve **dato faltante / período sin cobertura**, nunca cero.
   - **Momento:** se ejecuta junto con el pipeline canónico (F1.1), recalculando KPIs, introduciendo las recetas versionadas y actualizando el catálogo del Asistente **en el mismo cambio**.

   Implementación: columnas `estado`/`reemplazado_por` en `derived_kpi` (§5 del doc) + actualizar `noi_query.py:24` y `db_chat.py:247,252` en el mismo commit — hoy ambos exponen la clave `Apoquindo` y cambiarla sin ellos **rompe el Asistente** — + golden tests del contrato (F2.0). La vacancia legacy (`cdg_vacancia_v1`, fuente CDG en decomiso) solo puede reemplazarse tras el backfill de rent roll (F1.6); hasta entonces queda pendiente y documentada.

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

### Deuda técnica registrada (no urgente, con condición de salida)

| Deuda | Detalle | Cuándo hay que resolverla |
|---|---|---|
| **Mapeo canónico incompleto (etapas 2–4)** | 18,2% de filas mapeadas, pero **cobertura funcional 100%**: el 82% restante no lo usa ningún output. Sigue siendo la causa de fondo de los duplicados ambiguos y de que `raw_eeff_line` no tenga clave de negocio. Sin urgencia. | F1, antes de resolver los ambiguos o imponer un UNIQUE en `raw_eeff_line`. |
| **KPIs vigentes sin metodología escrita** | `ltv`, `duration_deuda`, `perfil_vencimiento`, `leverage_financiero` alimentan el factsheet pero su fórmula solo existe en el código perdido de la skill. Hoy funcionan porque el factsheet lee `derived_kpi`; no se pueden **recalcular**. | Con F0.6 (recuperar la skill) o documentando cada uno contra el golden. |
| **UNIQUE inline vestigial** | Ninguno queda: se eliminaron al recrear las tablas de parking (068). | — |
| **`streamlit` en `memory_tools.py`** | Tras eliminar la app Streamlit, `tools/memory_tools.py:11` sigue importando `streamlit` solo para leer `st.session_state["username"]`. Sin app, `_get_user()` siempre cae a `"general"`: la memoria del agente es **global**, y el contexto que el propio modelo puede autoeditar (`actualizar_contexto`) se reinyecta al system prompt de todas las sesiones. | **Antes de habilitar múltiples usuarios**: desacoplar `_get_user()` de `st.session_state` (identidad inyectada por el llamador, alineada con `usuario` de F2.1/F2.5) y sacar la dependencia de `streamlit` de `requirements.txt`. |
| ~~`ingest_run_id` inválidos~~ | ✅ Resuelto (migración 061): FK en **cero**, invariante sin umbral. | — |
| Duplicados lógicos EEFF | Detenidos a propósito: **ninguno** es ejecutable automáticamente con la evidencia actual. Depende de `seccion` y del mapeo canónico. Sin impacto en cifras hoy. | F1.1 |
| ~~`schema_v2.sql` obsoleto y schema no reproducible~~ | ✅ Resuelto por el baseline (F0.2): DB nueva ≡ producción, 93 objetos sin diferencias. `schema_v2.sql` queda como artefacto histórico. | — |
| `_rebuild_factsheet()` silencioso | Regenera 5,2 MB dentro del request de commit y traga el error con un `print`; además no recalcula KPIs. | F1.1 (orquestador). |

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

### Resueltas (2026-07-24, segunda tanda)
Modelo del agregado de Apoquindo (fondo `Apo`, sin `dim_grupo_activo`), recálculo con receta nueva versionada preservando el histórico como legacy, vacancia 2026-07 tratada como dato faltante y no como cero, y ejecución junto al pipeline canónico de F1.1. Detalle en F1.9.

### Pendientes
1. **Cuotas emitidas:** confirmar 4.000.000 / 1.800.000 / 2.000.000 contra reglamento/CMF (`docs/analisis-cuotas-fondos.md` §5) y el significado exacto de "emitidas". *No bloquea F0.*
2. **Apoquindo — Etapa B (IDs técnicos):** si/cuándo introducir `FTRI_APO` / `ACT_APOQUINDO_*`. Hoy no es necesario: la Etapa A dejó una sola grafía por fondo y la relación activo→fondo ya va por FK.
3. **Agente operativo (`agent.py`, 102 tools):** tras el decomiso del CDG, definir qué capacidades sobreviven (correo, SharePoint, consultas a la DB) y cómo se relacionan con el Asistente (F2.0). Prerequisito de F1.8. Al eliminarse Streamlit, el agente solo tiene entrada CLI y `--server` (que hoy no arranca porque falta `AGENT_SERVER_API_TOKEN` en el `.env`): conviene decidir si conserva interfaz de usuario o queda como backend de tareas.
4. **Duplicados EEFF:** qué versión sobrevive en cada grupo duplicado (¿mayor `loaded_at`?), incluidos los que la consolidación de Apoquindo dejó visibles: `TOTAL ACTIVO` de 2026-03 por duplicado con el mismo monto, y 4 cierres de 2025 de valor cuota que difieren en el cuarto decimal (`apo_2026Q1.json` vs `cdg_extract.xlsx`).
5. **Duplicados EEFF:** política de qué versión sobrevive en cada grupo duplicado (¿mayor `loaded_at`?) — afecta cifras históricas.
6. Discrepancias aceptadas (4 filas `raw_caja`, exclusión PT 2019-12): ¿definitivas?
7. Convención UF en `monto_clp` (ER Apo/PT): ¿migrar a `monto`+`unidad` o congelar documentada?
8. **Usuarios y permisos** (F2.5): quiénes, qué ve cada uno, y si el Asistente se expone fuera de localhost.
9. **F3:** umbrales iniciales de anomalías por KPI; quién valida explicaciones; si comentarios validados pueden salir a aportantes.
10. **Gate de producción LLM** (§6) cuando se acerque la exposición a más usuarios.
