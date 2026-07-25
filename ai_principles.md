# Principios de IA — Financial Intelligence Platform

**Versión:** 1.0 · 2026-07-24
**Alcance:** todas las superficies de IA del sistema — agente conversacional (`agent.py`/`app.py`), chat DB (`tools/db_chat.py`), extracción de documentos (EEFF y futuros), y cualquier capacidad futura (conocimiento organizacional, copilot).

Estos principios provienen del documento de visión de la plataforma y se hacen operativos aquí: cada uno tiene enunciado, mecanismos concretos exigidos, y su estado de cumplimiento actual verificado (2026-07-24). Un principio sin mecanismo que lo fuerce no cuenta como implementado.

---

## P1 — SQL es la única fuente de verdad

Toda respuesta numérica debe originarse en una consulta a `memory/agente_toesca_v2.db`. Nunca de la memoria del modelo, razonamiento, supuestos o aproximaciones. Si la DB no tiene el dato, la respuesta obligatoria es "No existe información para esta consulta" — jamás completar.

**Mecanismos exigidos:**
- El asistente responde cifras únicamente vía ejecución real de SQL o herramientas de consulta parametrizadas (`query_tools`, `noi_query`); nunca desde el texto del prompt o del historial.
- Datos faltantes y períodos incompletos se declaran explícitamente (usar `estado_ingesta`/`coverage` para distinguir "no hay dato" de "el período aún no cierra").
- Los outputs estandarizados (factsheet, presentación mensual, exports) se generan por código sin IA.

**Estado:** ✅ en el chat DB (no hay camino de respuesta que no pase por `_run_sql` o `clarify`). ⚠️ el agente conversacional mezcla DB, Excel y correos — aceptable para tareas operativas, pero cifras financieras deben venir de la DB (regla "DB primero" de `AGENTS.md`). ❌ el factsheet PPTX se alimenta de PDF+scraping, no de la DB.

## P2 — La IA nunca inventa números

Puede interpretar, comparar, resumir y explicar. No puede estimar valores, completar información faltante, asumir causas ni inferir cifras financieras.

**Mecanismos exigidos:**
- Temperatura 0 en generación de SQL y extracción estructurada.
- Todo valor extraído por LLM de un documento se **recalcula/valida server-side** antes de persistir (patrón actual: cuadratura de gastos con tolerancia 2.000 CLP, validación de esquema, `prompt_version` chequeado). El campo "cuadra" que afirme el LLM no se cree nunca.
- Prohibido persistir en la DB cualquier número producido por un modelo sin pasar por un validador determinístico + confirmación humana.
- Prompts de síntesis con instrucción explícita de usar solo las filas entregadas y declarar resultados vacíos.

**Estado:** ✅ implementado en ingesta EEFF y chat DB (prompts `R5. NUNCA inventes numeros...`). ⚠️ sin verificación posterior posible porque no hay logging (ver P3).

## P3 — Trazabilidad completa

Toda respuesta debe ser reproducible: qué SQL se ejecutó, qué tablas se consultaron, qué cálculos se hicieron, con qué versión de prompt, para qué usuario y sobre datos de qué fecha.

**Mecanismos exigidos:**
- **Log de consultas del asistente** (tabla `chat_query_log`: timestamp, usuario, pregunta, SQL generado, proveedor/modelo, versión de prompt, nº filas, duración, error). *Hoy no existe — es requisito de la Fase 2 del roadmap; sin esto el asistente no puede crecer.*
- Versionado de prompts: todo prompt productivo lleva identificador de versión (patrón existente: `prompt_version: "eeff-v1"`); cambiar el prompt = nueva versión, nunca edición silenciosa.
- Datos: linaje completo en raw (`source_file/sheet/row`, `file_hash`, `ingest_run_id`, `loaded_at`, `superseded_at`); KPIs derivados con `formula` y referencia a la corrida que los produjo.
- UI: el SQL ejecutado es visible para el usuario (ya ocurre: "Ver detalle técnico" en la burbuja; `KPI_META` en modo admin del factsheet).

**Estado:** ✅ linaje de ingesta y `KPI_META`. ❌ cero logging del chat; ❌ `derived_kpi` 99,8% sin `ingest_run_id` y sin invalidación al re-ingerir; ❌ sin versionado de los prompts del chat/agente.

## P4 — Plantillas antes que IA

Todo documento con formato estandarizado (fact sheet, presentación mensual, export Excel, dashboard) tiene estructura fija definida por código. La IA nunca diseña estos documentos; a lo sumo los puebla con datos SQL o redacta secciones narrativas claramente delimitadas y validadas por un humano.

**Mecanismos exigidos:**
- Generadores determinísticos parametrizados por fecha de cierre.
- Si en el futuro la IA redacta comentarios dentro de un template (ej. "aspectos del mes"), esos textos entran como **borrador** y siguen el ciclo de validación de P5; el layout no se toca.
- No usar IA donde una solución determinística sea más confiable (regla ya aplicada: `ingest_gastos_pdf.py` reemplazó extracción LLM por extracción posicional).

**Estado:** ✅ factsheet HTML, diagrama DB, dashboards. ⚠️ presentación mensual aún no existe (se construirá como template rígido, no con IA).

## P5 — Validación humana

Toda información subjetiva (comentarios, causas, observaciones, explicaciones) y toda escritura a la DB originada en extracción por IA requiere validación humana explícita antes de persistir o publicarse.

**Mecanismos exigidos:**
- Patrón validate → preview → confirmación → commit (ya implementado en la ingesta; el commit re-valida server-side y no confía en el cliente).
- Conocimiento organizacional futuro (Fase 3): estados `borrador → validado | rechazado`, más `obsoleto`; solo lo **validado** puede citarse en respuestas o informes, siempre distinguido de los datos duros; autor, validador y timestamps registrados.
- Las sugerencias/hipótesis del modelo se etiquetan como tales y nunca se mezclan tipográficamente con hechos SQL.

**Estado:** ✅ en ingesta. ❌ capa de conocimiento inexistente aún (el principio queda definido antes de construirla, a propósito).

---

## Reglas operativas de seguridad del asistente

Derivadas de los principios; son condiciones de diseño para toda superficie de IA presente o futura:

1. **Solo lectura por construcción.** El asistente consulta la DB exclusivamente por conexión read-only real (`mode=ro` de SQLite — la garantía es del motor, no del prompt). Las escrituras (ingesta, conocimiento validado) van por endpoints separados, deterministas, con validación y confirmación humana. Nunca por SQL generado por el modelo.
2. **Validación de SQL antes de ejecutar:** una sola sentencia, solo `SELECT`/`WITH`, lista de operaciones prohibidas, `LIMIT` forzado (hoy 200 filas), y **timeout de ejecución** (pendiente — hoy un `WITH RECURSIVE` puede colgar el servidor; usar `sqlite3.Connection.set_progress_handler` o interrupt).
3. **Allowlist en vez de acceso irrestricto.** El asistente debe consultar una **capa semántica de vistas curadas** (`v_*` + tablas aprobadadas), no el esquema completo. Métricas con definición canónica (TIR, DY, NOI, cap rate) se responden desde `derived_kpi`/vistas, jamás recalculadas ad-hoc por el modelo.
4. **Identidad y permisos.** Toda consulta lleva usuario identificado; los permisos por fondo/activo/tipo de información se resuelven server-side (no en el prompt).

   **Estado (2026-07-24) — el token de `/api/*` es una protección de desarrollo local, aceptada como tal.** Qué es y qué no es:

   | | |
   |---|---|
   | **Sí protege de** | que cualquier proceso local o página abierta en el navegador lea la DB por `/api/chat` o escriba por `/api/*/commit`; el CORS ya no refleja orígenes arbitrarios |
   | **No es** | autenticación multiusuario: hay **un solo token compartido**, sin identidad, sin sesión, sin roles |
   | **No es** | suficiente para exposición productiva: sin TLS, sin rotación, sin expiración, sin registro de quién hizo qué |
   | **No aporta** | trazabilidad por usuario (P3): las consultas siguen sin quedar registradas |

   La autenticación real, la identidad por usuario y los permisos por fondo/tipo de dato se resuelven en la Fase 2 (F2.1 y F2.5) y son **requisito de salida a producción**, junto con el gate de proveedores LLM de la regla 6.

   **Flujo vigente para usar el Asistente:** abrir el factsheet desde `http://127.0.0.1:8765/factsheet`. Abrirlo con doble clic sobre el archivo (`file://`) no recibe el token y el Asistente responde 401 con esa instrucción.
5. **Prompt injection.** Todo texto no generado por el sistema es dato no confiable: contenido de correos/documentos, filas de la DB con texto libre (glosas, arrendatarios, `source_file`, futuros comentarios humanos), y el historial de chat. El historial lo reconstruye el **servidor** (no se acepta historial fabricado por el cliente); el texto almacenado se interpola en prompts con delimitadores y sin capacidad de instruir. La cláusula anti-injection existente en `BASE_PROMPT` debe replicarse en `db_chat`.
6. **Datos sensibles y proveedores LLM.** El fallback actual (DeepSeek → Groq → Gemini) es una **configuración de desarrollo controlado**, no la política de producción (decisión del usuario, 2026-07-24). Mientras dure el desarrollo: arquitectura desacoplada para cambiar de proveedor, inventario de puntos de llamada documentado (`system_architecture.md` §5), minimización de lo enviado, datos sintéticos en pruebas cuando sea razonable, y jamás secretos (.env, tokens, hashes) en prompts ni en el repo. Aunque sea desarrollo, las llamadas externas sacan datos reales de la infraestructura local — mantener los controles mínimos. **Gate de salida a producción:** decisión humana explícita sobre proveedores autorizados, tipo de cuentas, retención, uso para entrenamiento, fallback permitido, minimización, logging/auditoría y tratamiento de información financiera confidencial.
7. **Separación de tipos de contenido en toda respuesta:** hecho SQL ≠ cálculo derivado ≠ inferencia del modelo ≠ comentario humano validado. Las cuatro categorías se citan con su origen.
8. **Registro y auditoría** (P3): sin log de consultas no hay asistente en producción.

## Anti-patrones (prohibidos)

- Dar al modelo una conexión de escritura a la DB de negocio "porque es más simple".
- Re-calcular en el LLM un KPI que ya existe en `derived_kpi` con metodología validada.
- Aceptar del cliente HTTP historial de conversación, roles o instrucciones de sistema.
- Persistir texto del modelo como conocimiento sin estado `borrador` y validación humana.
- Reemplazar con IA un proceso determinístico que funciona (CDG, factsheet, validaciones) por novedad y no por necesidad.
- Editar prompts productivos sin subir la versión ni registrar el cambio.
