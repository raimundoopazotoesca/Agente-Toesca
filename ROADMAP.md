# Roadmap Técnico — Financial Intelligence Platform

**Versión:** 2.0 · 2026-07-24
**Reemplaza** el roadmap de abril 2026 (histórico en git: `git show e4626cf:ROADMAP.md`), que quedó superado por el pivote a DB-first.
**Base:** diagnóstico verificado en `system_architecture.md`; principios en `ai_principles.md`; visión estratégica en el documento "Financial Intelligence Platform" (fases 1–4).

---

## 1. Diagnóstico (resumen)

Detalle completo en `system_architecture.md`. Lo que condiciona este roadmap:

- La arquitectura objetivo ya está adoptada en la práctica: DB canónica, ingesta con validate→commit humano, factsheet template 100% SQL, chat read-only. **No hay que rediseñar; hay que consolidar.**
- Deudas que bloquean crecer: (a) schema de producción divergente de las migraciones (los tests prueban otro schema); (b) duplicados e inconsistencias reales en la DB (`APO`/`Apo`, ~12.300 filas duplicadas, FKs violadas, `derived_kpi` no trazable); (c) servidor web sin autenticación con `debug=True`; (d) tab EEFF roto (`NameError`) sin tests; (e) KPIs de TIR/LTV dependen de código externo no versionado y ausente; (f) el factsheet existe 3 veces con 3 fuentes y el único entregable a clientes (PPTX) no lee la DB; (g) sin logging del asistente; (h) sin export DB→Excel ni presentación mensual.

## 2. Brecha estado actual → visión

| Visión | Estado | Brecha principal |
|---|---|---|
| F1: DB + ingesta web + outputs template | ~70% | integridad DB, EEFF web roto, factsheet incompleto/no parametrizado por fecha, presentación mensual inexistente, PPTX fuera de la DB |
| F2: Asistente IA financiero | ~40% (adelantado) | sin auth, sin trazabilidad (viola P3), sin allowlist, sin gráficos/Excel, sin permisos |
| F3: Capa de conocimiento | 0% | modelo de datos, detección de anomalías, flujo de validación |
| F4: Copilot | 0% | depende de F2+F3 |

**Regla de secuencia:** no se construye una fase sobre cimientos con deuda crítica. Por eso este roadmap antepone una **Fase 0** que la visión no contempla.

---

## 3. Fases

Convención de etiquetas por tarea: **[D]** determinístico/reglas · **[SQL]** consulta o cálculo SQL · **[GEN]** generación de archivos por código · **[IA-O]** orquestación IA · **[IA-X]** extracción IA con validación · **[H]** validación/decisión humana.

---

### FASE 0 — Consolidación de cimientos (integridad, seguridad, verdad única)

**Problema que resuelve:** la "fuente única de verdad" hoy tiene duplicados, claves inconsistentes y un schema no reproducible; la plataforma web es insegura; el flujo EEFF está roto. Todo lo posterior hereda estos defectos.
**Valor:** confiabilidad — que un número de la DB sea defendible ante un comité; que un desarrollo nuevo no se pruebe contra un schema ficticio.
**Reutiliza:** migraciones + runner transaccional, `ingest_run`/`superseded_at`, scripts de dedup existentes, `path_security`, patrón validate/commit.
**No requiere IA en ninguna tarea.**

**Tareas (orden interno):**

1. **[D] Arreglar ingesta EEFF web** — `ingest_eeff_validated.py:317`: `existing_hash` → `bool(periodos_existentes)` (patrón de rent roll). Test de regresión del endpoint `/api/validate` + `/api/ingest` con payload real.
2. **[D] Re-baseline del schema** — generar `schema_baseline.sql` desde la DB productiva real (`.schema`), convertirlo en migración 058 "baseline" para DBs nuevas, hacer que los tests partan de ese baseline, y marcar `schema_v2.sql` como histórico. Decidir por cada objeto faltante de las migraciones 1–22 (UNIQUE, índices, `publish_run`, `dim_cuenta`) si se aplica a producción o se descarta formalmente.
3. **[SQL][H] Saneamiento de datos** (con backup previo, como `snapshot_pre_049.py`):
   - Unificar `fondo_key` `APO`→`Apo` en `raw_eeff_line` (18.009 filas) **o** decidir formalmente la clave canónica — decisión humana, toca scripts y queries con `UPPER()` defensivo.
   - Dedup de `raw_eeff_line`/`raw_er_activo_line` con los scripts existentes, luego **aplicar `UNIQUE(file_hash, source_row)`** para que no vuelva a pasar.
   - Reparar `ingest_run_id` de texto (2.378 filas) y NULL donde sea reconstruible; `file_hash` NULL → hash sintético trazable.
   - Test de invariantes (`tests/db/test_invariantes.py`, flaw 12): FKs limpias, sin duplicados lógicos vivos, sin `A&R%`, sin Machalí post-2025-08, `vacancia ∈ [0,1]`.
4. **[D] Seguridad del servidor de ingesta** — token/sesión obligatoria (mismo patrón que `agent.py --server`), `debug=False`, CORS restringido, `MAX_CONTENT_LENGTH`, try/except en los `validate` (errores legibles, no 500), validación de extensión server-side.
5. **[D] Internalizar la skill financiera** — traer `real-estate-finance-expert` (TIR, LTV, duration, rentabilidades) al repo (`tools/finance/`), versionada y testeada contra los valores de referencia congelados del wiki (`kpis_rentabilidad_fondos`, MAR-26). Eliminar rutas absolutas Windows.
6. **[D] Higiene de repo** — borrar artefactos muertos (`patch_*.py`, `script_*.js/txt`, `test_funds.js`, `factsheet_debug.html`, `CUsers...noi_tools_old.py`), `.gitignore` para `factsheet.html`, limpiar `.claude/settings.json` de rutas de otra máquina.
7. **[D] Botón de re-ingesta en la web** — exponer `mark_superseded` con confirmación (hoy corregir un período requiere SQL a mano).

**Tablas/datos:** ninguna nueva (salvo lo que se decida en 0.2). **Endpoints:** `/api/*/supersede` (0.7).
**Tests de salida:** invariantes verdes sobre la DB real; suite completa verde contra el baseline; tests de endpoints EEFF y rent roll (hoy inexistentes).
**Riesgos:** el saneamiento `APO`→`Apo` puede romper scripts que asumen mayúsculas (mitigación: grep exhaustivo + invariantes); dedup borra filas equivocadas (mitigación: backup + conteos antes/después contra totales conocidos).
**Condición para avanzar:** ningún hallazgo crítico de `system_architecture.md` §6-7 abierto.
**Verificación:** `PRAGMA foreign_key_check` = 0; `pytest` verde; ingesta EEFF end-to-end con un trimestre real; servidor rechaza requests sin token.

---

### FASE 1 — Completar la plataforma determinística (la "Fase 1" real de la visión)

**Problema:** los outputs estandarizados están incompletos o triplicados; los KPIs se recalculan por scripts sueltos; no hay export a Excel ni presentación mensual.
**Valor:** eliminar el trabajo manual mensual restante y dejar **un** camino canónico por output.
**Reutiliza:** `build_factsheet.py` (+`KPI_META`), `consolidate_*`, `derived_kpi`, `estado_ingesta`, dims de la DB.
**Sin IA** (todo [D]/[SQL]/[GEN], decisiones [H]).

**Tareas:**

1. **[SQL] Orquestador de KPIs** — un solo pipeline (`tools/db/kpi_pipeline.py`) que conozca dependencias (activo→fondo→bursátil), registre `ingest_run_id` en `derived_kpi`, implemente **invalidación** (`stale_at` al re-ingerir raw — flaw 3) y una función única `es_periodo_cerrado()` (flaw 6). El commit de ingesta encola recálculo (asíncrono, no dentro del request) y el rebuild del factsheet pasa a ser post-KPIs, con error visible en la UI (no `print(WARN)`).
2. **[SQL] Catálogo `dim_recipe`/`dim_kpi`** (flaw 2) — definición canónica, fórmula, inputs, estado (activa/deprecada) por KPI+variante; `KPI_META` del factsheet se genera desde aquí (hoy es copia manual que puede divergir del SQL real).
3. **[SQL] Config de fondos desde la DB** — `FONDOS_CFG`/`SERIES_CONFIG`/`NOI_ACTIVOS` etc. leen `dim_fondo`/`dim_serie`/`dim_activo` (+ nueva `dim_fondo_ficha` para los datos estáticos de ficha: fechas de inicio, remuneraciones, comité, contactos). Una sola fuente para cuotas emitidas/en circulación.
4. **[GEN] Factsheet parametrizado y completo** — `build_factsheet.py --periodo YYYY-MM`; completar `_fetch_perf_data` para Apo/TRI (requiere rent roll histórico — ver 1.6); assets fuera del template (no 4 copias base64 del logo).
5. **[GEN] Export DB→Excel** — módulo `tools/export_excel.py` (openpyxl write): serie de KPIs, ER por activo, rent roll, dividendos, con hoja de metadatos (períodos, fecha de generación, fuentes). Botón en la web y herramienta para el asistente (Fase 2).
6. **[SQL][H] Backfill rent roll histórico** — hoy solo hay 2026-05; sin historia no hay vacancia ni absorción en factsheet/presentación. Reingestar por la vía validated (con supersede de Fase 0.7).
7. **[GEN][H] Presentación mensual** — no existe; construirla como template rígido parametrizado por fecha. **Decisión humana previa:** formato (PPTX python-pptx vs HTML imprimible) y contenido de referencia. La IA no participa.
8. **[GEN][H] Un solo factsheet canónico** — decidir destino de los 3 existentes. Recomendación: HTML = canónico interno; PPTX cliente se **puebla desde la DB** (reusar `factsheet_tools.py` como capa de escritura PPTX pero con datos de `fetch_fondo`, no de PDFs/scraping); deprecar dashboards Streamlit duplicados (mantener solo si aportan interactividad que el HTML no da).

**Tablas nuevas:** `dim_recipe` (o `dim_kpi`), `dim_fondo_ficha`; columna `derived_kpi.stale_at`.
**Endpoints:** `/api/export/excel`, `/api/rebuild` (estado del pipeline).
**Tests:** pipeline de KPIs con fixture de re-ingesta (verifica invalidación); golden files de export Excel; snapshot del factsheet por período; paridad PPTX↔HTML en KPIs compartidos.
**Riesgos:** consolidar config puede cambiar valores que hoy difieren entre copias (ej. cuotas 1.585.000 vs 1.800.000 — resolver con el usuario qué significa cada una); backfill rent roll depende de conseguir archivos históricos de proveedores.
**Condición para avanzar:** cierre mensual completo ejecutado solo con la plataforma (ingesta → KPIs → factsheet → presentación → export) para un mes real, cuadrado contra el CDG.
**Verificación:** los mismos KPIs en HTML, PPTX y Excel con idéntico valor; `derived_kpi` 100% trazable a corrida y receta.

---

### FASE 2 — Asistente financiero IA endurecido (visión F2)

**Problema:** el chat existe pero viola P3 (sin trazabilidad), P-seguridad (sin auth, historial del cliente, sin allowlist) y le faltan capacidades (gráficos, Excel, comparaciones guiadas).
**Valor:** consultas ad-hoc confiables y auditables para todo el equipo, sin abrir Excel.
**Reutiliza:** `db_chat.py` (validación SQL + `mode=ro` + fallback de proveedores), `chat_bubble.js`, `query_tools`/`noi_query`, export Excel de Fase 1, `dim_recipe`.
**Naturaleza:** [IA-O] orquestación sobre herramientas [SQL]/[GEN] deterministas.

**Tareas:**

1. **[D] Identidad y sesión** — el chat hereda la autenticación de la plataforma (Fase 0.4); toda petición lleva usuario. El **historial vive server-side** (tabla `chat_session`/`chat_message`) — se elimina el historial fabricado por el cliente (vector de injection).
2. **[SQL] Trazabilidad** — tabla `chat_query_log` (usuario, pregunta, SQL, proveedor/modelo, `prompt_version`, filas, duración, error, timestamp). Prompts de `db_chat` versionados (`db-chat-v2`, registrado en el log).
3. **[D] Capa semántica con allowlist** — el generador SQL solo ve vistas curadas + `derived_kpi` + dims (allowlist explícita de tablas/columnas, validada post-generación contra el AST del SQL, p.ej. con `sqlglot`); timeout de ejecución; cláusula anti-injection para filas con texto libre. KPIs canónicos se responden desde `derived_kpi`, nunca recalculados por el modelo (P1/P3).
4. **[IA-O] Herramientas tipadas además de SQL libre** — el modelo elige entre: `consultar_kpi`, `comparar_periodos`, `cobertura`, `generar_tabla`, `generar_grafico` ([GEN] — spec declarativa → render determinístico, no código del modelo), `generar_excel` ([GEN], reusa 1.5), `explicar_kpi` (desde `dim_recipe`). SQL libre queda como fallback con la allowlist.
5. **[D][H] Permisos** — tabla `usuario` + permisos por fondo/tipo de información, aplicados server-side sobre las herramientas y la allowlist. (Diseño simple: hoy son ≤4 usuarios; no construir RBAC elaborado todavía.)
6. **[D] Manejo explícito de faltantes** — antes de responder series/comparaciones, el asistente consulta cobertura y antepone advertencias de períodos incompletos (P1).

**Tablas nuevas:** `usuario`, `chat_session`, `chat_message`, `chat_query_log`, `prompt_version` (o registro en código con id).
**Endpoints:** `/api/chat` autenticado + `/api/chat/history`; `/api/chart` si el render es server-side.
**Tests:** allowlist (SQL a tabla no permitida → rechazo); inyección vía historial y vía datos con texto malicioso → sin efecto; log completo por cada respuesta; permisos (usuario sin acceso a un fondo no obtiene sus datos); golden tests de preguntas frecuentes (los 11 few-shots actuales como suite).
**Riesgos:** dependencia de proveedores LLM gratuitos (cuotas, cambios de API — el fallback ya lo mitiga); latencia del pipeline pregunta→SQL→síntesis; **política de datos a terceros pendiente de decisión humana**.
**Condición para avanzar:** 1 mes de uso real con log auditado y tasa de respuestas incorrectas medida y aceptada por el usuario.
**Verificación:** cualquier respuesta del asistente es reproducible desde `chat_query_log` (re-ejecutar el SQL da las mismas filas).

---

### FASE 3 — Capa de conocimiento organizacional (visión F3)

**Problema:** la DB dice *qué* pasó; nadie registra *por qué*. Las explicaciones viven en correos y memoria de las personas.
**Valor:** el "por qué" de cada movimiento relevante queda persistido, validado y citable.
**Reutiliza:** pipeline de KPIs (para detectar), chat autenticado (para conversar), estados/flujo de validación del patrón validate/commit.
**Naturaleza:** [SQL] detección + [IA-O] conversación guiada + [H] validación obligatoria.

**Tareas:**

1. **[SQL] Detección determinística de anomalías** — reglas versionadas en `dim_regla_anomalia` (ej.: |Δ MoM| > umbral por KPI, gasto nuevo sin histórico, vacancia que salta, dividendo fuera de calendario, descuadre fondo↔activos). Corre post-cierre del pipeline de KPIs y persiste en `anomalia_detectada` (kpi, entidad, período, valor, valor_esperado, regla, severidad). **El modelo no decide qué es anómalo; las reglas sí.**
2. **[IA-O][H] Conversación de cierre mensual** — al terminar la ingesta, el asistente presenta las anomalías abiertas y pregunta por ellas; el usuario explica; el modelo **redacta borradores** de explicación con referencia a la anomalía y a las cifras SQL.
3. **[SQL][H] Modelo de conocimiento** — tablas `evento` (hechos objetivos fechados: venta de activo, refinanciamiento, siniestro; entidad+período+fuente), `observacion`/`explicacion` (texto, autor, `anomalia_id`/entidad/período/kpi, **estado: borrador → validado | rechazado; obsoleto**, validador, timestamps, versión). Nada sale de `borrador` sin acción humana explícita (P5).
4. **[D] Uso seguro del conocimiento** — el asistente puede citar solo `estado='validado'`, siempre etiquetado como "explicación validada por {autor}" y separado de las cifras (P-separación); el texto almacenado se trata como dato no confiable al interpolarse en prompts (anti-injection sobre conocimiento persistido).
5. **[GEN] Integración en outputs** — la presentación mensual/factsheet pueden incluir sección "comentarios del período" **solo** con conocimiento validado.

**Tablas nuevas:** `dim_regla_anomalia`, `anomalia_detectada`, `evento`, `explicacion` (con historial de estados o tabla `explicacion_version`).
**Endpoints:** `/api/anomalias`, `/api/conocimiento` (CRUD con transición de estados), UI de revisión en la web de ingesta.
**Tests:** reglas de anomalías con fixtures (casos borde de períodos incompletos); máquina de estados (transiciones ilegales rechazadas); el asistente no cita borradores; injection almacenada en una explicación no altera respuestas.
**Riesgos:** fatiga de validación si las reglas generan ruido (mitigación: umbrales ajustables + severidades, empezar con 3-5 reglas); conocimiento que envejece (mitigación: estado `obsoleto` + vínculo a período).
**Condición para avanzar:** 2-3 cierres mensuales con el flujo completo y conocimiento validado real acumulado.
**Verificación:** ante "¿por qué cayó el NOI de X en marzo?", el asistente responde cifra SQL + explicación validada citada, o declara que no hay explicación registrada.

---

### FASE 4 — Copilot de inteligencia financiera (visión F4)

Solo cuando F2 y F3 estén maduras. Capacidades: resúmenes ejecutivos [IA-O sobre datos SQL + conocimiento validado, siempre como borrador [H]], detección de patrones recurrentes [SQL sobre `anomalia_detectada`/`explicacion`], soporte a comités (paquete de datos + explicaciones por fondo/período [GEN]), alertas de riesgo [D reglas]. No se detalla más aquí a propósito: su diseño debe salir de lo aprendido en F2/F3.

---

## 4. Dependencias y orden

```
F0 (todo) ──▶ F1.1-1.3 (pipeline+catálogo+config) ──▶ F1.4-1.8 (outputs)
F0.4 (auth) ──▶ F2.1 ──▶ F2.2-2.6
F1.1 (pipeline) y F1.2 (dim_recipe) ──▶ F2.3/F2.4 (allowlist, explicar_kpi)
F1.5 (export excel) ──▶ F2.4 (generar_excel)
F1.1 + F2 (chat auth) ──▶ F3
F2 + F3 ──▶ F4
```

Paralelizable: F1.6 (backfill rent roll) y F1.7 (presentación) pueden avanzar mientras se hace F1.1-1.3; la internalización de la skill (F0.5) es independiente del saneamiento (F0.3).

## 5. Qué NO implementar todavía

- **Frameworks multi-agente** (LangGraph/CrewAI): el router por regex + tools cubre el caso; añadiría complejidad sin resolver ningún problema actual.
- **RAG / base vectorial** para contratos: no hay caso de uso activo; la capa de conocimiento (F3) es estructurada, no vectorial.
- **Migración a Microsoft Graph / nube / SSO**: la plataforma es local y single-tenant; primero auth básica (F0.4) y permisos simples (F2.5).
- **Reemplazo total del CDG**: mantener el flujo XML actual congelado hasta cumplir un criterio de corte medible (propuesto: paridad <1% entre KPIs de la DB y el CDG durante 3 meses — flaw 15). No invertir en mejorarlo, solo en no romperlo.
- **RBAC elaborado, colas de mensajes, PostgreSQL**: SQLite + WAL aguanta esta escala; migrar solo si aparece concurrencia real multi-usuario.
- **IA generando layouts o documentos** (P4): nunca.

## 6. Estrategias transversales

- **Pruebas:** cada fase entrega sus tests como parte de la tarea (no después). Prioridad permanente: invariantes de negocio sobre la DB real + endpoints de ingesta + golden tests de KPIs contra valores validados del wiki. CI local mínima: `pytest` + `ruff` antes de commit.
- **Trazabilidad:** linaje raw (existente) → `derived_kpi` con corrida+receta (F1) → log de chat (F2) → estados de conocimiento (F3). Regla: si no se puede reconstruir de dónde salió un número o un texto, no se muestra.
- **Validación humana:** ingesta (existente), correcciones de datos (F0.7), explicaciones (F3), resúmenes ejecutivos (F4). El botón de confirmación siempre es posterior a un preview con lo que se va a persistir.
- **Anti-alucinación:** ver `ai_principles.md` — read-only por construcción, validadores que recalculan, allowlist, prompts versionados, faltantes explícitos.
- **Seguridad:** auth en todo endpoint que lea o escriba; secretos fuera del repo (incluye sacar `config.yaml` con hashes del historial); política explícita de proveedores LLM.

## 7. Criterios de aceptación globales

1. **F0:** DB íntegra (0 violaciones FK, 0 duplicados lógicos vivos), schema reproducible, servidor autenticado, EEFF web funcionando, suite verde.
2. **F1:** cierre mensual completo sin tocar Excel a mano (salvo fuentes), un solo valor por KPI en todos los outputs, todo KPI trazable.
3. **F2:** toda respuesta del asistente reproducible desde el log; cero escrituras posibles desde el chat; permisos aplicados.
4. **F3:** conocimiento validado citable y separado de los hechos; anomalías con dueño y estado.
5. **Siempre:** ningún número mostrado a un usuario se originó en un modelo.

---

## 8. Decisiones que requieren validación humana

Ninguna de estas debe tomarla el agente unilateralmente:

**Datos y dominio**
1. Clave canónica de Apoquindo (`Apo` vs `APO`) y ejecución de la corrección masiva de 18.009 filas.
2. Política de duplicados: qué versión sobrevive en cada grupo duplicado de `raw_eeff_line` (¿la de mayor `loaded_at`?) — afecta cifras históricas.
3. Significado y valor correcto de las cuotas hardcodeadas divergentes (1.585.000/1.640.000 en `SHEET_CFG` vs 1.800.000/2.000.000/4.000.000 en `FONDOS_CFG`).
4. Discrepancias aceptadas (4 filas `raw_caja`, exclusión PT 2019-12): ¿se corrigen o se documentan como definitivas?
5. Convención `monto_clp` conteniendo UF en ER de Apo/PT: ¿se migra a columna `monto`+`unidad` o se congela documentada?
6. Criterio de corte del CDG (¿paridad <1% × 3 meses?) y fecha objetivo para dejar de mantener `gestion_renta_tools.py`.

**Outputs**
7. Cuál factsheet es canónico y el destino de los otros dos (propuesta en F1.8); si el PPTX cliente pasa a poblarse desde la DB.
8. Formato y contenido de referencia de la presentación mensual (PPTX vs HTML; qué secciones).
9. Si los dashboards Streamlit se deprecan o se mantienen.

**Asistente y seguridad**
10. Política de proveedores LLM: ¿pueden datos financieros de los fondos ir a DeepSeek/Groq además de Google? ¿Se paga un proveedor con términos de no-entrenamiento?
11. Modelo de usuarios y permisos: quiénes usarán la plataforma, qué puede ver cada uno por fondo/tipo de dato, y si `/api/chat` se expone más allá de localhost.
12. Sacar `config.yaml` (hashes bcrypt de 4 usuarios) del repo y de su historial (requiere rewrite de historia git o rotación de credenciales).

**Conocimiento (F3)**
13. Quién puede validar explicaciones (¿solo Raimundo? ¿cualquier usuario con rol?) y si un comentario validado puede aparecer en documentos que salen a aportantes.
14. Umbrales iniciales de las reglas de anomalías por KPI (definen cuánto ruido recibe el usuario).

**Alcance**
15. Prioridad relativa entre completar F1 (presentación mensual, rent roll histórico) y endurecer F2 (el chat ya se usa) — este roadmap propone F0 → F1 → F2, pero F2.1-2.3 (auth+log+allowlist) podría adelantarse si el chat va a mostrarse a terceros.
