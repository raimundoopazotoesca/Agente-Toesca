# Toesca Analyst Benchmark — Holdout Set v1, diseño corregido

Este documento reemplaza la propuesta preliminar (aprobada en principio,
con 6 correcciones obligatorias pedidas antes de escribir casos). Registra
el diseño final tras esas correcciones. El contenido real de los casos
vive fuera de este repo — ver `cases/holdout/README.md`. Este documento
en sí no contiene preguntas, `forbidden_claims` ni SQL de ningún caso.

## Identidad heredada del Dev Set

- `BENCHMARK_VERSION = v1`, `BENCHMARK_TODAY = 2026-08-13`
- Snapshot pinneado: sha256 `592399a8e34c7111e4a9aaa84dd0002532d7a24ffb26f27c90e186647294125c`,
  commit fuente `c9b1dd543b275b8d1ac7c7569bc95b126b319e4c` — el holdout usa
  el mismo snapshot que Dev, no uno nuevo.
- Rubric v1.3, Judge Impl 1.2.0, `case.schema.json` sin modificar.

## A. Tamaño y primary/secondary behavior (corregido)

**21 casos exactos: 14 TAE + 7 TCE.** Cada caso tiene **exactamente un**
`primary_behavior`. Comportamientos adicionales genuinos se registran como
`secondary_behaviors` (lista, puede ser vacía) — ninguno de los dos campos
vive en el YAML del caso (rompería `additionalProperties: false` del
schema); ambos viven únicamente en `HOLDOUT_MANIFEST.yaml`.

### TAE (14) — primary_behavior por nivel

| Level | # casos | primary_behavior asignado |
|---|---|---|
| L1 | 3 | factual_retrieval ×3 |
| L2 | 1 | comparison ×1 |
| L3 | 2 | temporal_reasoning ×2 |
| L4 | 3 | diagnosis ×2, investigation ×1 |
| L5 | 2 | investigation ×2 |
| L6 | 1 | decision_support ×1 |
| L8 | 2 | insufficient_information ×1, entity_traps ×1 |

Suma: 3+1+2+3+2+1+2 = 14. L7 excluido (sin capability `xlsx_export` real,
igual que en Dev).

### TCE (7) — primary_behavior por categoría

| # casos | primary_behavior | turnos |
|---|---|---|
| 1 | ambiguity_handling | 2 |
| 2 | corrections_context_inheritance (entity + metric/period) | 2+2 |
| 2 | multi_turn_analytical_reasoning | 3+3 |
| 1 | challenge_revision_of_judgment | 3 |
| 1 | causal_restraint | 3 |

Suma casos: 1+2+2+1+1 = 7. Suma turnos: 2+2+2+3+3+3+3 = 18 (ver sección C).

### Cobertura total (13/13 categorías pedidas, cada una ≥1 vez)

`factual_retrieval, comparison, temporal_reasoning, diagnosis,
investigation, decision_support, insufficient_information, entity_traps`
(TAE, 8 categorías) + `ambiguity_handling,
corrections_context_inheritance, multi_turn_analytical_reasoning,
challenge_revision_of_judgment, causal_restraint` (TCE, 5 categorías) = 13
categorías, cada una con al menos un caso primario. No se fuerza ninguna
categoría en un caso donde quedaría artificial (ver Batch 1: `causal
restraint` y `entity traps` no aparecen ahí porque los slots naturales
para esas categorías caen en L8/TCE, no en L1–L3).

## B. Aislamiento físico del holdout (implementado)

**Ubicación real de los 21 casos:**
`C:\Users\raimundo.opazo\toesca-benchmark-holdout-private\cases\holdout\{tae,tce}\*.yaml`
— repositorio Git local **separado**, sin remoto, sin submódulo, sin
mount ni working-directory listado para agentes de desarrollo.

**Qué queda en `automation_agent` (este repo):**
- `cases/holdout/README.md` — política de aislamiento y contaminación.
- `cases/holdout/{tae,tce}/.gitkeep` — directorios vacíos a propósito;
  `cases_loader._check_semantics` sigue exigiendo que todo `split:
  holdout` viva bajo una ruta que contenga `holdout` en sus partes, así
  que la estructura de directorios es real, solo que sin contenido.
- `HOLDOUT_MANIFEST.yaml` — **minimizado** (corrección post Batch-1-review):
  solo `case_id, split, level, category, status, batch` por caso, más
  agregados no ligados a un caso individual. Sin entidad, período,
  métrica, tablas, `primary_behavior`/`secondary_behaviors` ni
  `similarity_reason` — esa metadata semántica case-level se movió al
  repo privado (`MANIFEST_FULL.yaml`), porque dejarla aquí derrotaba
  parcialmente el aislamiento físico (permitía reconstruir de qué trata
  cada caso sin tocar el repo privado).
- `HOLDOUT_FREEZE_MANIFEST_SPEC.md` + `EVALUATION_RUN_MANIFEST_SPEC.md`
  + `compute_freeze_manifest.py` — infraestructura de freeze
  reproducible, con la identidad del contenido separada de la identidad
  de cada corrida (ver §D).
- `holdout_runs.md` — bitácora de corridas autorizadas (vacía hasta la
  primera corrida real).
- `tests/test_holdout_not_leaked.py` — capa lógica (segunda capa, no
  sustituto de la física): (1) falla si aparece un `*.yaml` real bajo
  `cases/holdout/`; (2) falla si una entrada de `cases:` en el manifest
  tiene algún campo fuera del set mínimo de gobernanza; (3) escaneo de
  todo el archivo (no solo `cases:`) contra una lista negra de claves
  semánticas/de contenido, para bloquear una fuga futura por un bloque
  nuevo (ej. un resumen agregado por entidad); (4) falla si un `case_id`
  de holdout aparece en superficies de tuning (prompts, few-shots,
  verified queries, synonyms, entity resolver).

**No se modificó `cases_loader.py`**: `load_cases(root=...)` ya acepta
una raíz arbitraria, así que montar el holdout real durante una corrida
autorizada es pasar `root=Path(r"...\toesca-benchmark-holdout-private\cases")`
— sin tocar código de producción. Ver el snippet completo en
`cases/holdout/README.md`.

**Qué NO se hizo (y por qué):** no se creó submódulo git, no se cifró el
directorio, no se restringieron permisos de filesystem. La separación es
por *ubicación y ausencia de referencia*, no por control de acceso a nivel
OS — suficiente para el objetivo declarado (evitar que agentes de
desarrollo lo tengan disponible por defecto), no para resistir un
atacante con acceso al filesystem del usuario.

## C. Tamaño TCE precomprometido (fijo, no se revisa post-hoc)

- **7 casos TCE, 18 turnos evaluables totales.**
- **Batch 4: 3 casos × 2 turnos = 6 turnos.**
- **Batch 5: 4 casos × 3 turnos = 12 turnos.**
- 6 + 12 = 18. Esta cifra no se ajusta después de ver resultados de
  ninguna corrida.

## D. Freeze reproducible — Freeze Manifest vs Evaluation Run Manifest (corregido)

**Corrección post Batch-1-review**: el freeze del *contenido* del Holdout
Set y la identidad de *cada corrida* de evaluación son ahora dos
documentos formalmente separados, no un único spec de 10 campos:

- **`HOLDOUT_FREEZE_MANIFEST_SPEC.md`** — identidad del contenido:
  `holdout_id`, conteo/lista de `case_ids`, `snapshot_sha256` +
  `snapshot_source_commit`, `case_schema_sha256`,
  `private_repo_commit_sha` + `private_repo_content_sha256`,
  `frozen_at`, `human_signoff`. **No incluye modelo evaluado, modelo
  juez, parámetros de inferencia ni fecha de evaluación** — el mismo
  `holdout_id` se corre contra múltiples modelos/jueces a lo largo del
  tiempo sin volver a congelarse.
- **`EVALUATION_RUN_MANIFEST_SPEC.md`** — identidad de una corrida:
  referencia obligatoria a un `holdout_id` ya congelado, más
  `code_commit_sha`, `evaluated_model`, `judge_model_resolved` (versión
  resuelta, nunca un alias `-latest` sin resolver), hashes de
  `judge.py`/`rubric.yaml`/`runner.py`/adapters (el motor de scoring sí
  puede cambiar entre corridas del mismo holdout), parámetros de
  inferencia, `eval_date`, `purpose`, `tuning_contamination_flag`.

`compute_freeze_manifest.py` implementa ambos como funciones separadas
(`build_holdout_freeze_manifest()` / `build_evaluation_run_manifest()`) y
subcomandos de CLI (`freeze` / `run`); ninguno ejecuta una evaluación.
Probado con datos de humo (no un freeze real) — ver reporte de esta
corrección.

El freeze de **contenido** real (`HOLDOUT_SET_V1_FREEZE.md`, análogo a
`DEV_SET_V1_FREEZE.md`, que produce el primer `holdout_id`) se crea
cuando los 21 casos estén completos y aprobados — ver criterio en
§Freeze final más abajo.

## E. Manifest de cobertura (implementado, corregido post Batch-1-review)

Dos manifests, no uno:

- **`HOLDOUT_MANIFEST.yaml`** (repo principal, minimizado) — campos por
  caso: `case_id, split, level, category, status, batch`. Solo lo
  necesario para gobernanza (progreso por batch, estado de revisión,
  distribución estructural por nivel). No permite reconstruir de qué
  trata ningún caso.
- **`MANIFEST_FULL.yaml`** (repo privado, junto al contenido real) —
  todo lo anterior más `primary_behavior, secondary_behaviors, domain,
  entities, periods, metrics, source_tables,
  dev_case_checked_against, most_similar_dev_case, similarity_reason`.
  Es el manifest que efectivamente sirve para auditar solapamiento
  Dev vs Holdout con detalle — vive donde vive el contenido, no en
  `automation_agent`.

Ninguno de los dos extiende `case.schema.json`. `status`: `draft` →
`reviewed` → `frozen`, sincronizado entre ambos manifests manualmente
(no hay automatización de sync todavía — riesgo conocido, ver
`PENDING.md`-equivalente si se agrega).

## F. Slots ex-ante (sin decisiones post-hoc)

Se elimina el slot condicional "parking / mercado si sale natural" de la
propuesta preliminar. Reasignado ex-ante a **portfolio / drill-down de 3
fondos** (gap documentado en el Dev Set freeze, mejor soportado por el
snapshot que parking/mercado, que solo tenía un caso Dev L1-008 vía JLL
submercado y sin dato propio del portfolio).

### Dominios fijos por batch (ex-ante, 21 casos, no se ajustan post-hoc)

| Dominio | # casos (algunos multi-dominio) |
|---|---|
| EEFF (incl. TCE conversacional profundo) | 4 |
| Portfolio / drill-down 3 fondos | 4 |
| Valor cuota / TIR | 3 |
| NOI / ER | 3 |
| Activos / sociedades / jerarquía | 2 |
| Desinversiones | 2 |
| Vacancia | 2 |
| Deuda / LTV | 2 |
| Rent roll (solo 2026-05/06) | 2 |

Reglas fijas para rent roll: solo se permiten lookups puntuales de mayo o
junio 2026, o una comparación explícita mayo-vs-junio. **Nunca** se
presenta esa comparación de 2 meses como "tendencia" — no hay tercer punto
para sostener esa palabra, y extrapolar más allá de junio 2026 con datos
de rent roll está prohibido (`forbidden_claims` explícito en cualquier
caso que use `raw_rent_roll_line`).

## Estrategia de diversidad temporal

- Junio 2026 (57% de Dev) aparece en ≤5 de los 21 casos holdout (~24%).
- Batch 1 ya cumple esto: de 6 casos, **0** usan 2026-06 como período
  exacto; los períodos usados son 2025-02, 2026-03, 2025-12, y una
  ventana 2024-12→2026-06 donde 2026-06 es solo el punto final de una
  serie de 3, no el foco aislado de la pregunta.
- Al menos 1 caso de comparación/temporal genuina multi-período por
  batch cuando el nivel lo permite (Batch 1 entrega 2: L3h-001 con 3
  puntos no consecutivos, L3h-002 con agregación trimestral YoY).
- Ningún dato usado es posterior a `BENCHMARK_TODAY = 2026-08-13`.
  Fechas contractuales futuras (ej. `fecha_vencimiento` de créditos) se
  permiten como dato observado del contrato, nunca como dato proyectado
  presentado como hecho (`raw_saldo_deuda.is_proyeccion` se filtra
  explícitamente a `0` en los casos de deuda de Batch 1).

## Estrategia anti-paráfrasis / anti-contaminación

1. **Test de independencia** documentado en el campo `notes` de cada
   caso: por qué existiría sin haber visto el Dev case correspondiente.
2. Ningún caso reutiliza `entidad + período + métrica` de un caso Dev
   cambiando solo redacción — ver `HOLDOUT_MANIFEST.yaml` campo
   `similarity_reason` por caso, comparación explícita contra el `dev
   case` más parecido.
3. IDs en namespace visualmente distinto: `tae-l{N}h-NNN` /
   `tce-{categoria}h-NNN` (el infijo `h` no colisiona con el patrón
   `^(tae|tce)-[a-z0-9]+-[0-9]{3}$` del schema, y es una segunda señal
   además del campo `split`).
4. Aislamiento físico (§B) — la salvaguarda principal contra
   contaminación accidental por *desarrollo* (no contra paráfrasis, que
   es un problema de diseño, no de fuga).
5. `holdout_runs.md` registra cada corrida y su propósito declarado;
   cualquier uso para tuning marca esos casos como contaminados.

## Batches (5, precomprometidos en la propuesta original, sin cambios)

1. **Batch 1** — TAE L1–L3 (6 casos): factual retrieval, comparison,
   temporal reasoning. **Completado, este commit.**
2. **Batch 2** — TAE L4–L6 (6 casos): diagnosis, investigation, decision
   support.
3. **Batch 3** — TAE L8 (2 casos): insufficient information, entity
   traps.
4. **Batch 4** — TCE corrección/ambigüedad (3 casos × 2 turnos = 6
   turnos): entity/metric/period correction, ambiguity handling.
5. **Batch 5** — TCE investigación/decisión/causal (4 casos × 3 turnos =
   12 turnos): multi-turn analytical reasoning, challenge/revision,
   causal restraint.

Cada batch se detiene para human review antes de iniciar el siguiente
(ver reglas abajo). Esta ejecución entrega **solo Batch 1**.

## Reglas de human review (por caso, antes de aceptar)

1. Test de independencia (¿existiría sin haber visto el Dev case
   correspondiente?).
2. SQL de `ground_truth_refs` ejecutado contra el snapshot pinneado,
   resultado determinístico (una fila, no NULL) — verificado
   programáticamente, no a ojo.
3. Comparación explícita contra el inventario Dev — combinación de
   level+domain+behavior+entity+period+metrics, no solo "misma
   entidad, otro mes".
4. Disciplina epistemológica: sin DSCR como ground truth, sin CapEx
   reconstruido, sin datos posteriores a `BENCHMARK_TODAY`, sin
   causalidad desde coincidencia temporal, sin arbitrar discrepancias
   de fuentes, sin convertir afirmaciones previas del usuario/asistente
   en verdad.
5. Validación de schema + semántica cruzada (`cases_loader.load_case`).
6. Registro en `HOLDOUT_MANIFEST.yaml` con `status: draft` hasta que un
   humano lo revise (`status: reviewed`).

## Criterio de freeze final (Holdout Set completo, no aplica a Batch 1)

- 21/21 casos validan contra `case.schema.json` + `cases_loader`
  semántica cruzada.
- 21/21 `ground_truth_refs` (todas las refs de todos los turnos)
  ejecutan contra el snapshot pinneado sin error y sin NULL.
- 21/21 casos con `status: reviewed` en el manifest y sign-off humano
  por batch registrado.
- Sin overlap no documentado contra Dev — `similarity_reason` completo
  para cada caso.
- Se genera `HOLDOUT_SET_V1_FREEZE.md` (análogo a `DEV_SET_V1_FREEZE.md`)
  fijando los campos de `HOLDOUT_FREEZE_MANIFEST_SPEC.md` y produciendo
  el primer `holdout_id` real.
- Post-freeze: toda corrida holdout produce su propio Evaluation Run
  Manifest (`EVALUATION_RUN_MANIFEST_SPEC.md`, referenciando ese
  `holdout_id`) y se registra en `holdout_runs.md`; cualquier uso para
  tuning contamina los casos usados y obliga a su reemplazo en v2.
