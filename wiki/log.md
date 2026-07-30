## [2026-07-30] data | Vacancia Viña/Curicó persistida en derived_kpi (real + ponderada)

Insertadas 6 filas en `derived_kpi` (`formula='rentroll_vacancia_v1'`):
m2_vacantes/m2_total para Viña y Curicó (variante NULL = real), más
variante `ponderado_80` para Curicó (participación 0.8 confirmada en
`dim_sociedad.CuricoSpA`). Así ambos valores quedan disponibles sin
recalcular. Reemplaza en la práctica al viejo `cdg_vacancia_v1` (deprecado,
ver [[feedback_no_usar_cdg]]).

## [2026-07-30] doc | Vacancia Curicó — ponderación 80% (participación del fondo en el activo)

El fondo es dueño del 80% de Mall Curicó. Para reportar m² absolutos
(vacante/total) se multiplica por 0,8; el % de vacancia no cambia (se
pondera parejo). Vacante ponderado 2.414,30 m² / total ponderado
8.649,18 m². Detalle en [[activos/mall-curico]].

## [2026-07-30] doc | Vacancia Viña/Curicó — corrección: cuenta TODO (incluye módulos/parking)

Usuario había corregido a "solo locales, excluye módulos/parking" y luego se
retractó ("me confundí"): la regla correcta es contar todas las unidades
vacantes sin excluir nada. Viña 130,5/25.579,55 m² = 0,51%. Curicó
3.017,87/10.811,47 m² = 27,91%. Detalle en [[activos/vina-centro]] y
[[activos/mall-curico]].

## [2026-07-30] fix | ingest_er_pt.py — filtro de vigencia bloqueaba meses nuevos anteriores a RULES_EFFECTIVE_PERIOD

Al ingestar la corrección de `RAW/NOI PT.xlsx` (2026-06) aparecieron dos bugs:

1. **Fechas fantasma**: la fila de fechas del archivo tiene fórmula arrastrada
   hasta 2057-01, sin datos reales más allá de 2026-06. Como las cuentas fijas
   (`PT_CONTRIB`/`PT_SEG`/`PT_GC_VAC`) se calculan sin chequear si hay datos
   reales en esa columna, el ingest iba a insertar 30 años de costos fijos
   ficticios. Fix: `parse_planilla` ahora acota `period_by_col` a las columnas
   con al menos un valor fuente real (`max_data_col`).
2. **Filtro de vigencia con constante fija**: `_has_active_history` comparaba
   contra `RULES_EFFECTIVE_PERIOD` ("2026-07", fecha fija desde que se escribió
   el script en julio) en vez de contra lo realmente cargado. La DB llegó a
   mayo 2026 antes de esta corrección, así que junio (dato real nuevo) caía en
   el hueco entre "último cargado" y la constante fija, y se descartaba.
   Fix: nueva `_max_historic_period(conn)` calcula el máximo período < vigencia
   ya cargado; el filtro ahora acepta líneas si `periodo >= RULES_EFFECTIVE_PERIOD
   OR periodo > max_historic` — protege la historia congelada pre-vigencia pero
   permite llenar huecos de meses nuevos que aún no se habían cargado.

Regla de negocio confirmada por el usuario: las cuentas fijas de PT (Contrib,
Seguros, GC Vacancia Boulevard, Admin 0,2%) **siempre priman sobre el monto
que traiga la planilla fuente**, desde 2026-07 en adelante — no cambiar sin
confirmación nueva.

Pendiente: **Margen Energía** de PT (Torre A y Boulevard, filas idx 9/26) sigue
sin automatizar — el usuario mencionó que junio queda pendiente de ingresar
manualmente cuando esté disponible.

## [2026-07-27] ingesta | INMOSA agregado al menú de ingesta Ingresos/NOI Activos

Tercer activo del tab "Ingresos/NOI Activos" (después de Viña Centro y Mall
Curicó). A diferencia de esos dos (hoja `ESTADO DE RESULTADO`, cuenta_codigo
tipo `4-1-01-100`, CLP+UF), INMOSA usa una fuente distinta: `NUEVO ORDEN >
Renta Comercial > Ingresos Activos > inmosa > <año> > Flujo Caja MM.YY Senior
Assist.xlsx` — un Flujo de Caja mensual en UF pura (sin CLP), sin código de
cuenta, hoja única (ej. `FC 06.2026`). Nuevo parser
`tools/db/ingest_er_inmosa_mensual.py`: ancla `Ingresos operacionales`, 7
filas de gasto operacional (Remuneraciones/Adm, Aseo, Seguros,
Contribuciones, Oficina Central, Otros gastos, IVA), valida contra
`Costos Operacionales` y `Flujo operativo (antes de Leasing e Hipotecas)`,
corta en la fila `Leasing` (todo lo financiero/deuda queda fuera). Por
convención con el parser histórico `ingest_er_inmosa.py` (mismo
`activo_key='INMOSA'`), el valor UF se guarda en `monto_clp` y `monto_uf`
queda `None` — `ingest_er_activo_web.validate_mensual` tuvo que generalizarse
para tolerar ese caso (antes asumía `monto_uf` siempre poblado).

`ingest_er_activo_web.py` se generalizó: cada entrada de `_ACTIVOS` ahora
declara `modulo_mensual` (antes `ingest_er_mensual` estaba hardcodeado en
`validate_mensual`/`commit_mensual`), así cada activo puede traer su propio
parser mensual sin tocar el dispatcher. HTML/JS del tab ya eran genéricos
por `activo` key (`initErActivo('inmosa')`, ids `er-inmosa-*`) — no hizo
falta lógica nueva ahí, solo el bloque de markup y sumar `'inmosa'` a
`ER_ACTIVOS_RESUMEN`. Validado end-to-end (parse + validate_mensual) contra
`Flujo Caja Jun.26 Senior Assist.xlsx`, 2026-06: 8 filas, ingresos_uf=9013.2,
noi_uf=7216.4, integridad ok. No se corrió el commit real (no se ingestó en
la DB) — decisión de dejarlo para cuando el usuario confirme por la UI.

## [2026-07-27] fase0 | F0.6 cerrado: skill real-estate-finance-expert auditada y corregida

Bloqueo original resuelto: `~/.claude/skills/real-estate-finance-expert/` si existe en
esta maquina. Auditoria contra el golden congelado (7.226 valores): `dividend_yield`
coincidia exacto desde el principio; `cap_rate_implicito` a nivel fondo estaba roto
(stub `_get_market_cap` nunca implementado, devolvia `None` siempre). Corregido en
`scripts/cap_rate.py` con la formula canonica real (replicada de
`scripts/consolidate_kpis_bursatil_pt.py` del proyecto):
`noi_u12m / (market_cap_uf + deuda_financiera_neta_uf + caja_minima_uf)` — no
`noi_anual / market_cap` como decia la doc vieja de la skill. Validado exacto contra
el golden de PT 2026-05. De paso se arreglo `_common.get_uf()` (referenciaba
`fact_uf.valor_clp`, columna inexistente; la real es `fact_uf.valor`).

Tambien se agrego capa de alias (`resolve_entidad_key`, `canonical_kpi_cache_name`
en `_common.py`) porque los nombres de KPI y claves de entidad de la skill no eran
1:1 con el vocabulario real de `derived_kpi` (`dividend_yield` vs `dy`, `TRI-A` vs
nemotecnico `CFITOERI1A`, `Parque Titanium` vs `PT`).

Deuda menor no bloqueante: TRI calcula `cap_rate_implicito` a nivel serie (no
fondo agregado como PT) — variante distinta, no implementada. Detalle completo en
`wiki/skills/real-estate-finance-expert.md`.

## [2026-07-24] fase0 | Cierre de F0: FK en cero, Etapa 1 cumplida, catalogo de KPIs

**Indices unicos parciales (067-068).** Correccion de la propuesta anterior:
`UNIQUE(..., superseded_at)` NO protege nada porque SQLite trata cada NULL como
distinto — verificado empiricamente: dos INSERT en raw_parking_ingreso_line con la
misma clave y superseded_at NULL fueron aceptados. Las 4 restricciones de parking
eran decorativas. La forma correcta es `WHERE superseded_at IS NULL`. Ademas el
UNIQUE inline de parking SI estorbaba (rechaza dos filas anuladas en el mismo
segundo), asi que hubo que recrear las 4 tablas; el dry run detecto que las 5
vistas dependen de ellas y se recrean en la misma transaccion. 22 tests nuevos con
los 4 escenarios sobre 5 familias de tabla.

**Etapa 1 del mapeo canonico cerrada (069).** De los 15 huecos funcionales, **14
son ausencias legitimas** verificadas una por una contra la fuente: 'Costos de
transaccion' no figura en esos EEFF de Apo, y lo unico parecido a otros_gastos es
'Otros gastos de operacion PAGADOS', que es estado de FLUJOS y nunca se mapea a
ER (141 filas, ninguna mapeada). PT 2017-06 es anterior al inicio de operaciones
del fondo. Solo 1 era mapeable con respaldo de fuente y seccion. NO se mapearon en
bloque las otras 25 filas de PT con ese nombre: en la mayoria ya existe una
contraparte mapeada por carga manual, y mapearlas habria duplicado el gasto.
Cobertura funcional: 100% en los 3 fondos. El reporte ahora distingue "ausente del
documento" de "presente sin mapear".

**Catalogo dim_kpi + golden (070).** ltc y dscr -> legacy: sin metodologia escrita
ni consumidores, se conservan sus 1.399 filas pero no se recalculan ni se publican.
ltv, duration_deuda, perfil_vencimiento y leverage_financiero quedan marcados como
vigentes SIN metodologia escrita — tienen consumidores y no pueden congelarse.
Golden congelado de los 7.226 valores de los 15 KPIs de la skill, con tolerancias
por familia y modo --verificar (hoy: 0 divergencias).

**F0.6 (skill financiera) queda como PENDIENTE URGENTE bloqueado por acceso al
computador Windows.** No bloquea nada mas: el factsheet lee derived_kpi, no invoca
la skill. Lo unico imposible hoy es recalcular.

**Trasladado a F1.1:** supersede (depende de stale_at y del orquestador) y los
duplicados de raw_eeff_line (dependen de seccion y del mapeo canonico).

Suite: 386 passed, 1 xfailed (el de raw_eeff_line, que se mantiene hasta tener una
clave demostrada).

## [2026-07-24] fase0 | Migraciones 064-066 + reporte de cobertura + disenos

**Ejecutado:**
- 064: UNIQUE(file_hash, source_row, periodo, **activo_key**) en raw_er_activo_line.
  Sin saneamiento: cero sobrantes. Test verifica que el split 75/25 de contribuciones
  de Apoquindo sigue aceptandose (ratio 3.0 exacto).
- 065: validacion humana como eje separado del linaje (validado_por, validado_at,
  validacion_fuente). Apo 2020-12 ESF.total_activo = 42.343.358.000 registrado como
  confirmado por el usuario contra los EEFF; la fila manual queda vigente y conserva
  lineage_status='manual_sin_archivo'. Los dos solapados se resolvieron por politica de
  versionado (valores identicos, ninguna cifra cambia).
- 066: 1.424 filas 'Serie X - <metrica>' pasan a seccion='METRICA_SERIE'. Son metricas
  por serie que ya viven en raw_valor_cuota_* — sumarlas seria doble conteo. Fuera del
  mapeo canonico y de deduplicaciones.

**Hallazgo importante en el reporte de cobertura** (`scripts/reporte_cobertura_mapeo.py`):
mi primera version media las 10 cuentas ESF del factsheet contra `raw_eeff_line` y
reportaba **773 huecos**. Esas cuentas NO salen de ahi sino de
`raw_balance_consolidado_line`, que tiene ingesta propia; y `ER.recurrentes` se calcula
en el JS del factsheet (honorarios_custodia + remun_comite). Corregido: los huecos reales
son **15**. Cobertura funcional TRI 100%, PT 97,3%, Apo 94,8%; balance 100%. Es decir:
el mapeo canonico al 18,2% suena alarmante, pero **funcionalmente estamos al ~97%** — el
82% de filas sin mapear no lo usa ningun output. La Etapa 1 esta casi cumplida (faltan
ER.costos_transaccion en 5 cierres antiguos de Apo, ER.otros_gastos en 2, y PT 2017-06).

**Disenos entregados:**
- `docs/inventario-skill-financiera.md`: la skill NO existe en esta maquina
  (~/.claude/skills/ no existe). Pero su contrato es deducible del wrapper, sus 6.246
  resultados estan en derived_kpi con receta versionada, y la metodologia esta en el wiki
  con valores de referencia validados contra el CDG. Reimplementacion viable y
  verificable. El factsheet no invoca la skill (lee derived_kpi), por eso sigue
  funcionando: lo que no se puede es RECALCULAR. Sin metodologia escrita: ltc y dscr.
- `docs/diseno-supersede.md`: semantica fijada antes de implementar. Unidad de reemplazo
  = archivo/corrida, nunca fila suelta — la misma primitiva que el saneamiento historico.
  Detecta un conflicto real: los UNIQUE recien aplicados no incluyen superseded_at, asi
  que reingerir tras superseder fallaria; propone la opcion de parking (incluirlo en la
  clave). Depende de stale_at y del orquestador F1.1.

## [2026-07-24] fase0 | F0.4 ejecutado: FK a cero, seccion, uniques demostrados

**Ejecutado** (migraciones 061-063, con backup, dry run y transaccion unica):
- 061: reparado el linaje cruzado de raw_eeff_line. 2.478 filas tenian el hash del
  archivo en `ingest_run_id` y `file_hash` vacio. El hash vuelve a su columna,
  `ingest_run_id` queda NULL. **No se crearon corridas sinteticas** (decision del
  usuario: preferible ausencia explicita de trazabilidad que trazabilidad
  artificial). Nueva columna `lineage_status` con vocabulario cerrado
  ('legacy_untracked', 'manual_sin_archivo'). Identificador sintetico
  `manual:<fondo>:<periodo>:<naturaleza>:<fecha>` para las 6 filas manuales — que
  resultaron ser DOS grupos, no uno. **violaciones FK 2.478 -> 0**, file_hash NULL
  2.484 -> 0, cifras intactas. Invariante ahora exige cero, sin umbral.
- 062: columna `seccion` + `seccion_original` en raw_eeff_line, vocabulario
  ESF/ER/EFE/ECP/NOTA/OTRO. Backfill solo desde el prefijo del codigo canonico:
  12.970 filas pobladas, 23.823 quedan NULL a proposito (no se inventa seccion).
- 063: uniques SOLO donde estan demostrados — rent_roll (file_hash, source_row) y
  flujo (file_hash, source_row, periodo). El xfail(strict) de esos tests xpaso y se
  retiraron los marcadores, como se acordo. Quedan 3, de eeff y er_activo.

**Analisis entregados** (`docs/analisis-saneamiento-fase2.md`), todos con el mismo
patron: el detalle cambio la conclusion previa.
- Las "10 filas sobrantes" de raw_er_activo_line **no son duplicados**: son un split
  deliberado 75/25 de las contribuciones de Apoquindo entre Apo4501 y Apo4700, con la
  regla escrita en el propio cuenta_nombre (ratio 3.0 exacto). La clave correcta es
  (file_hash, source_row, periodo, **activo_key**) y no requiere saneamiento: 0 sobrantes.
- Caso 1: de los 346 grupos, **0 son ejecutables automaticamente** — los 346 tienen
  source_row NULL, ninguno tiene canonico ni seccion.
- Caso 2: 2.839 grupos, **0 son copia exacta del mismo archivo**, solo 2 tienen
  canonico (los de Apo 2020-12). Conclusion: no hay NADA ejecutable automaticamente
  en el saneamiento de duplicados de raw_eeff_line.
- Apo 2020-12: la "correccion manual" **no corrigio ningun valor** (los dos solapados
  son identicos al digito); lo que aporto fue `ESF.total_activo`, ausente en el JSON.
  Cuadra (405.468.000 + 41.937.890.000 = 42.343.358.000) y encaja en la serie. La foto
  que la respaldo no esta en el repo.
- Mapeo canonico: cobertura global **18,2%** (Apo solo 11,4%; peor en 2022 con 12,2%).
  1.986 nombres distintos sin mapear; el top 50 cubre el 27% y el top 200 el 52,6%.
  Hallazgo: los 1.264 `Serie UNICA - *` no son cuentas contables sino metricas de serie
  que ya viven en tablas propias — no hay que mapearlas.
- Rent roll JLL: **no hay archivos sincronizados en esta maquina**, asi que la
  estructura real queda pendiente de verificar en Windows. Pista concreta del codigo:
  `_read_rr_locals` ya prefiere `Activo2` sobre `Activo1`, y `Activo1` contiene el
  nombre del FONDO (por eso el mapeo genera las entidades artificiales 'PT' y
  'Apoquindo'). El activo real estaria en `Activo2`/`Detalle Activo`.

## [2026-07-24] fase0 | F0.2 re-baseline + analisis de integridad y duplicados

**F0.2 ejecutado.** `tools/db/baseline.sql` consolida 001..060 desde el esquema real
de produccion; `apply_migrations()` lo aplica a DBs vacias y registra 1..60 de forma
veraz. Migracion 059 recupera los 12 indices que las migraciones declaraban y
produccion nunca tuvo; 060 normaliza `schema_version.applied_at`. Excluidos con
justificacion: `dim_cuenta` (obsoleta; su FK sobre una tabla vacia hacia fallar TODA
ingesta con cuenta_codigo en una DB nueva) y `publish_run` (nunca usada). Verificado
objeto por objeto: **93 objetos, cero diferencias** entre DB nueva y produccion,
blindado por `tests/db/test_baseline.py` y `regenerar_baseline.py --check`.

Hallazgo: 8 tests de idempotencia afirmaban una garantia que produccion nunca tuvo
—pasaban porque la DB de test si tenia el UNIQUE—. Por eso los duplicados se
acumularon en silencio. Quedan como xfail(strict=True).

**Analisis entregados (sin ejecutar saneamiento):**

`docs/analisis-integridad-referencial.md`: las 2.478 violaciones son UNA sola FK
(`raw_eeff_line.ingest_run_id`), 25 grupos, todos de PT, periodos 2021-06..2025-12.
Causa verificada con tres comprobaciones: solape del **100%** entre filas huerfanas y
filas con `file_hash` NULL; el valor huerfano es un hash de 8 caracteres uniforme; no
existe ningun `ingest_run` correspondiente (esa tabla solo tiene registros desde
2026-05-25). Un cargador cruzo las columnas. Reparacion: un UPDATE que mueve el hash a
`file_hash` y deja `ingest_run_id` NULL -> violaciones a **cero**, sin tocar cifras, y
devolviendo esas filas al alcance de `mark_superseded` (hoy son inmortales).

`docs/analisis-duplicados-dry-run.md` + `scripts/dry_run_duplicados.py`: politica de 3
casos aplicada -> 346 exactos, 3.056 redundantes, 2 con precedencia demostrable, **1.098
detenidos para revision humana**. Dos hallazgos que cambian el plan:
(a) el `UNIQUE(file_hash, source_row)` de las migraciones es **inutil** en raw_eeff_line
(93% de source_row NULL, y SQLite trata cada NULL como distinto) y **daNino** en
raw_er_activo_line/raw_flujo_line, donde una fila de planilla genera legitimamente una
fila por mes (verificado: 104 filas con el mismo file_hash+source_row, una por periodo);
(b) **49% de los ambiguos son falsos positivos**: 537 grupos vienen del mismo archivo con
montos distintos y ninguno tiene codigo canonico — son partidas distintas que comparten
un nombre generico ('Otros' 102 veces, 'Total' 147). Deduplicarlos borraria datos reales.
**Impacto en outputs hoy: nulo** — solo 2 grupos duplicados tienen codigo canonico (la
correccion manual de Apo 2020-12) y ninguna cuenta de gasto del factsheet esta afectada.

Causa de fondo identificada: 23.823 de 29.130 filas vivas (82%) sin
`cuenta_codigo_canonical`. Sin completar ese mapeo no hay clave de negocio confiable.

# Log — Wiki Agente Toesca

> Log cronológico append-only. Una entrada por operación.
> Parsear últimas entradas: `grep "^## \[" wiki/log.md | tail -10`

## [2026-07-24] fase0 | Fase 0 ejecutada: EEFF reparado, servidor seguro, APO→Apo, repo limpio

Cuatro bloques, cada uno con su commit y verificación.

**1. Ingesta EEFF reparada (F0.1).** Eran DOS bugs, no uno:
(a) `NameError: existing_hash` en `ingest_eeff_validated.py:317` → rompía
`/api/validate` e `/api/ingest` con 500 para los 3 fondos. Reemplazado por
`_hash_ya_ingestado(fhash)`, mismo criterio que el corte `skipped_duplicate` de
`commit()` (no duplica `periodos_existentes`, que ya es su propia clave).
(b) **Descubierto al escribir los tests**: persistir Apoquindo fallaba con
`FOREIGN KEY constraint failed` porque el prompt/UI usan `APO` y `dim_fondo`
tiene `Apo`. Verificado contra copia de producción. O sea: aun arreglando el
NameError, Apoquindo no se podía ingerir.
Nuevo `tests/test_ingesta_server_eeff.py` (16 casos). Al escribirlos apareció
otra cara de la divergencia de schema: el schema migrado tiene FK
`raw_eeff_line.cuenta_codigo → dim_cuenta` con `dim_cuenta` vacía (producción no
tiene esa FK), así que los tests deben sembrarla para ejercitar el path real.

**2. Suite 100% verde (F0.1b).** Los 3 fallos preexistentes eran tests
desactualizados, no bugs: `test_estado_ingesta` esperaba 3 tipos y `CONFIG` ya
tiene 5 (balance, parking_pt); `test_ingest_er_inmosa` esperaba
`INGRESOS_OPERACION` para contribuciones, que `6d08f4b` reclasificó a
`GASTOS_OPERACION` a propósito ("siempre negativo, es un gasto") corrigiendo
también las 99 filas cargadas, sin actualizar el test.
También: `pytest` no estaba declarado ni instalado y faltaba `holidays`
(dependencia REAL de `ingest_parking_pt_mensual`, nunca declarada) → agregado a
`requirements.txt` + nuevo `requirements-dev.txt`.

**3. Servidor endurecido (F0.5).** Token obligatorio en todo `/api/*`
(`X-Ingesta-Token`, `hmac.compare_digest`), inyectado en las páginas que sirve el
servidor. CORS ya no refleja `Origin` arbitrario ni `null`. `debug=False`
(el debugger de Werkzeug expone consola interactiva). `MAX_CONTENT_LENGTH` 32 MB.
xlsx corrupto → error legible; error inesperado → sigue siendo 500 a propósito,
para que un bug real se vea como bug. 20 tests + verificación contra el servidor
real. **Cambio de flujo**: el factsheet abierto con doble clic (`file://`) ya no
puede usar el Asistente; hay que abrirlo desde `http://127.0.0.1:8765/factsheet`.

**4. Consolidación APO→Apo (F0.3, migración 058).** Solo `fondo_key`: 18.009
filas de `raw_eeff_line` + 15 de `raw_valor_cuota_contable`. Protocolo completo:
backup, dry-run sobre copia con conteos antes/después (total de filas, filas
vivas, suma de montos y nº de períodos SIN CAMBIO), y factsheet regenerado desde
la copia migrada con **0 diferencias en el JSON de datos** (los 463 bytes de
delta eran el cambio previo de `chat_bubble.js`, que se inlinea).
Violaciones de FK: **20.487 → 2.478**. Mecanismo por el que entraron las malas:
`scripts/ingest_eeff.py:268` usa `sqlite3.connect()` sin `PRAGMA foreign_keys=ON`.
Código coordinado en el mismo commit porque había lecturas con `'APO'` exacto que
habrían devuelto cero filas: nuevo `tools/db/fondo_keys.py` (fuente única),
`build_factsheet.py` (usaba `fondo_key.upper()`), `estado_ingesta.CONFIG` (la card
EEFF habría dicho "nunca ingestado"), y los 2 CLI de ingesta.
`derived_kpi` quedó FUERA a propósito (ver F1.9).
Nuevo `tests/db/test_invariantes.py` (22 casos sobre la DB real).

**5. Higiene (F0.8).** 13 archivos muertos (~1,7 MB), `factsheet.html`
desversionado, `.claude/settings.json` limpio. Conservados a propósito
`migrate_to_sqlite.py` y `fondo_diagrama.html`.

Suite final: **347 passed, 5 skipped, 0 failed** (partió en 286 passed/3 failed).
Deuda registrada: `memory_tools.py` sigue importando `streamlit` solo para
`st.session_state`; sin app, la memoria es global bajo `"general"`. Hay que
desacoplar `_get_user()` antes de habilitar múltiples usuarios.

## [2026-07-24] limpieza | Cluster Streamlit eliminado (app.py + dashboards) — F0.7 completado

Autorizado por el usuario. Eliminados con `git rm`: `app.py`, `config.yaml`,
`login_template.html`, `style.css`, `.streamlit/config.toml`,
`dashboards/{fondos,eeff_tri,tir_tri}.py`, `wiki/agente/dashboard-fondos.md`. Retiradas de
`requirements.txt` las deps exclusivas (`streamlit-authenticator`, `bcrypt`, `plotly`) y
`AUTH_COOKIE_KEY` de `.env.example`/README. Análisis previo: nadie importaba `app.py` ni
`dashboards/`; `config.yaml`/`login_template`/`style.css` solo los leía `app.py`. Ojo:
`config/cuenta_eeff_map.yaml` (usado por `eeff_cuenta_mapper`) vive en `config/`, NO en
`dashboards/` — no se tocó. Conservados por seguir en uso: `streamlit` como librería
(`memory_tools` lee `st.session_state`), `pandas` (`excel_tools`), `tools/ask_tools.py`
íntegro (`registry` usa `preguntar_usuario`; `set_streamlit_mode` queda vestigial a
propósito). Verificación: suite idéntica antes/después (**286 passed, 3 failed
preexistentes, 5 skipped**), `factsheet.html` regenerado **byte-idéntico**,
`ingesta_server` (25 rutas) / `registry` (102 tools) / `agent` / `db_chat` OK.

Hallazgo colateral: el entorno de tests no era reproducible — `pytest` no estaba declarado
ni instalado, y faltaban `holidays` (dep real de `ingest_parking_pt_mensual`, no declarada),
`flask`, `pyyaml`, `groq`. Agregado `holidays` a `requirements.txt` y creado
`requirements-dev.txt` con pytest. Los 3 fallos preexistentes son tests desactualizados:
`test_estado_ingesta` espera 3 tipos y `CONFIG` ya tiene 5; `test_ingest_er_inmosa` espera
`INGRESOS_OPERACION` donde el parser da `GASTOS_OPERACION`.

## [2026-07-24] análisis | Claves ambiguas de Apoquindo en derived_kpi resueltas

`docs/matriz-claves-ambiguas-apoquindo.md`. Verificado numéricamente contra la DB:
`Apoquindo` (178 filas: noi_mensual + ingresos_mensual, receta `raw_er_*_v1`, 2019-01→
2026-05, UF) = **agregado exacto de Apo4501+Apo4700** desde `raw_er_activo_line`; lo genera
el mapa explícito `"Apoquindo": ["Apo4501","Apo4700"]` de `consolidate_noi_tri.py:37`.
`Fondo Apoquindo` (91 filas: solo m2_vacantes, receta `cdg_vacancia_v1`) = **también el
agregado 4501+4700**, coincidencia exacta y excluyendo correctamente a Apo3001; su nombre
sale de un mapa de números de fila del CDG (`backfill.py:370`). **Corrección a un supuesto
previo: ninguna de las dos es el look-through de TRI** — ese está bien resuelto en
`v_activo_fondo_efectivo` (Apo4501/4700 → TRI 0,3). Ambas están mal etiquetadas como
`entidad_tipo='activo'` siendo datos de nivel fondo. Verificado también que **no hay
solapamiento ni doble conteo** entre las convenciones `Apo4501` y `Apoquindo 4501`: cada KPI
existe bajo una sola. ⚠️ `Apoquindo` es clave viva del Asistente (`db_chat.py:247,252`) y de
`noi_query.py:24` — cambiarla sin actualizarlos rompe el Asistente. Decisión de modelado
(fondo vs `dim_grupo_activo`) pendiente del usuario; ejecución junto al pipeline canónico.

## [2026-07-24] doc | Decisiones del usuario incorporadas al roadmap (v2.1) + análisis Apoquindo y cuotas

El usuario resolvió 6 decisiones del roadmap: (1) claves Apoquindo con protocolo de
migración reversible — análisis entregado en `docs/plan-migracion-claves-apoquindo.md`
(inventario: `APO` 18.009 filas en raw_eeff_line + 15 en raw_valor_cuota_contable;
derived_kpi tiene doble esquema de claves de activo `Apo4501`/`Apoquindo 4501` etc. y
2 entidades ambiguas `Apoquindo`/`Fondo Apoquindo` que detienen la ejecución);
(2) cuotas divergentes — análisis en `docs/analisis-cuotas-fondos.md`: NO hay
contradicción, `SHEET_CFG` = cuotas en circulación (coincide exacto con
`raw_cuota_en_circulacion` al 2025-12-31) y `FONDOS_CFG.cuotas_emitidas` = cuotas
emitidas de ficha (pendiente confirmar fuente reglamento/CMF); (3) factsheet HTML
único canónico, PPTX y dashboards Streamlit a eliminación controlada; (4) política
LLM diferida como gate de producción (fallback actual = config de desarrollo,
inventario de llamadas en system_architecture.md §5.1); (5) `config.yaml` solo lo lee
`app.py` — eliminación pendiente de confirmar que la app Streamlit no se usa (tuvo
commit 2026-07-23); (6) decomiso total del CDG, sin criterio de paridad. Extra: Fase 2
renombrada "Fortalecimiento y expansión del Asistente Virtual Inmobiliario Toesca" —
evolución incremental sobre la implementación existente, sin asistentes paralelos.

## [2026-07-24] doc | Diagnóstico integral + roadmap Financial Intelligence Platform

Auditoría completa del sistema real (código + DB productiva, 4 exploraciones paralelas) y
contraste con el documento de visión "Financial Intelligence Platform". Tres documentos
nuevos en la raíz: `system_architecture.md` (arquitectura as-is verificada, con divergencias
doc↔código↔DB), `ai_principles.md` (los 5 principios de la visión operacionalizados con
estado de cumplimiento) y `ROADMAP.md` v2.0 (reemplaza al de abril; fases F0-F4 partiendo
del estado real). Hallazgos críticos documentados: (1) la DB productiva no fue construida
por las migraciones — versiones 2-22 marcadas en lote sin ejecutarse; faltan los
UNIQUE(file_hash,source_row) → ~12.300 filas duplicadas vivas en `raw_eeff_line`;
(2) 20.487 violaciones FK (18.009 por `APO` vs `Apo` en `raw_eeff_line`, 2.378 filas con
file-hashes de texto en `ingest_run_id`); (3) tab EEFF de la web roto desde 2026-07-20
(`NameError existing_hash` en `ingest_eeff_validated.py:317`, sin tests de ese path);
(4) `ingesta_server.py` sin auth con `debug=True` y CORS laxo; (5) skill financiera
(TIR/LTV) externa al repo y ausente en esta máquina; (6) factsheet triplicado (HTML/
Streamlit/PPTX) — el PPTX cliente no lee la DB; (7) `derived_kpi` 99,8% sin
`ingest_run_id` y sin invalidación. Sin cambios de código — solo documentación.

## [2026-07-23] ingesta | Ingesta mensual Parking PT (planilla Liquidación SABA)

Nuevo flujo recurrente para cargar la planilla `MM-YYYY Liquidacion Parque Titanium.xlsx`:
`tools/db/ingest_parking_pt_mensual.py` + 3 endpoints en `scripts/ingesta_server.py`
(`/api/parking/{periodo_check,validate,commit}`) + tab "Parking PT" en `web/ingesta.html`.
Idempotencia por supersede sobre `(activo_key, periodo)` en las 4 tablas raw (no por
file_hash, porque el archivo se actualiza mes a mes). Feriados detectados automáticamente
con `holidays.CL()`. Deduplicación de conceptos ignorando `codigo` — los códigos internos
SABA de la mensual (988, 345) difieren de los del histórico (363, 253, 200) pero son
mismos conceptos de negocio; ejecutado merge de duplicados (`Notas de credito` id 7 → 4).
Test end-to-end contra 2026-05 OK: sumas cuadran con totales de planilla dentro de 1 CLP.

Preview del tab muestra 4 KPIs con Δ% vs mes anterior: **ingresos abonados UF**,
**ingresos variables UF**, **resultado neto UF**, **ocupación mensual** — reproducen las
fórmulas de `v_parking_resultado_uf` y `v_parking_ocupacion_mensual` en Python para poder
mostrar antes de commit; el mes anterior se lee directo de las vistas. Card "Parking PT"
agregado a la pantalla de Inicio vía `tools/db/estado_ingesta.py` (frecuencia mensual,
sin sub-ingestas, timeline de 6 meses).

## [2026-07-23] db | Ocupación Parking PT — metodología y vistas (migración 055)

Consolidado el histórico de tickets/ingresos del Parking PT (SABA) en migraciones 053/054. El
usuario definió la metodología de ocupación diaria/mensual: tiempo total del día = bruto_día/40
(tarifa CLP/min), tiempo disponible = 8h×60×estacionamientos_no_abonados, y
estacionamientos_no_abonados = (ingresos_variables_u12m/ingresos_totales_u12m)×502 (502 fijo,
ratio U12M fijo por ahora). Confirmado que ocupación mensual = sum/sum equivale al promedio
simple de diarias mientras el denominador sea constante intra-mes. Migración 055 agrega
`v_parking_ratio_no_abonados`, `v_parking_ocupacion_diaria`, `v_parking_ocupacion_mensual`. Ver
[[activos/parking-pt]].

## [2026-07-23] db | Resultados Parking PT en UF (migración 056)

Agregada vista `v_parking_resultado_uf`: resultado neto (ingresos_netos - gastos_netos)/UF,
ingresos variables/UF, ingresos abonados/UF. Confirmado con el usuario que "ingresos netos" y
"gastos netos" no son suma de dos filas de la planilla sino la misma cifra reportada dos veces
(fila 13 total ingresos == fila 33 liquidación neto; fila 27 total gastos == fila 29 SABA neto),
verificado exacto contra 2026-06. UF del periodo = último día con dato del mes en
`raw_uf_diaria`. Ver [[activos/parking-pt]].

## [2026-07-21] factsheet | Página 3 Apo — vuelta a estructura sin datos

El commit anterior (e2768a1) hardcodeó valores reales del snapshot Apo octubre 2025. El
usuario pidió que quedara igual al PDF en orden pero con las tablas construidas **sin
información** por ahora — y el PDF de referencia ya no estaba disponible en el contexto de la
sesión para verificar el orden pixel a pixel. Se revirtieron los valores de `cfg["page3"]` a
solo estructura (labels de filas/columnas, nombres de edificio) mientras se mantiene todo el
layout/CSS/JS ya construido (`renderDonut` vía conic-gradient, barras de ocupación
`.occ-bar`/`.occ-bar-fill`, tablas `.subtable-box` por edificio) — queda listo para poblarse
en cuanto se confirme el orden exacto y haya fuente de datos. Pendiente: (a) re-verificar el
orden de secciones contra el PDF, (b) fotos de los edificios (las va a proveer el usuario).
Ver [[procesos/fact-sheets]].

## [2026-07-21] factsheet | Página 3 Apo — gráficos y valores reales (snapshot oct-2025)

Usuario pidió que quedara "igual al PDF, mismos gráficos y misma organización" — la versión
anterior tenía la distribución correcta pero todo en placeholder "—"/gris. Reescrita con:
donuts reales GLA(m²)/Ingresos(UF/mes) vía CSS `conic-gradient` (función `renderDonut()`,
sin librería externa) con los % reales de la referencia (75/25); barras de ocupación
proporcional para Status Actual Oficinas/Locales por edificio (reemplazo deliberado del
treemap original — no tenemos m² por unidad de arrendatario modelados en la DB, así que se
usa el mismo % de ocupación agregado con una geometría más simple); Aspectos Relevantes con
los 6 campos completos; grid de fotos por edificio (`p3.fotos[edificio]`, en `None` — el
usuario las va a proveer en una próxima iteración); Aspectos del Mes, Gestión de Vacancia,
Resumen Anual y Tasaciones con los **valores reales** del fact sheet Apo octubre 2025
(snapshot fijo, no wired a la DB — un aviso bajo el título lo deja explícito). Ver
[[procesos/fact-sheets]].

## [2026-07-21] factsheet | Página 3 Apo — distribución corregida para calzar con el PDF

Primera versión de la página 3 colapsaba demasiado la estructura del fact sheet de
referencia (una sola sección "Status Actual", vacancia/resumen/tasaciones como texto
"Pendiente" plano). El usuario pidió copiar la distribución original. Reescrita para
reflejar el orden real de secciones: Aspectos Relevantes + donuts GLA/Ingresos en 2
columnas arriba, Status Actual Oficinas y Status Actual Locales en grids separados (uno
por edificio), caja gris "Aspectos del Mes" con sus 4 sub-bloques, Gestión de Vacancia y
Resumen Anual con una tabla por edificio lado a lado (mismas filas que la referencia:
Locales/Oficinas/Edificio para vacancia; Vencimientos/Renovados/No Renovaciones/Salidas/
Nuevos/Neto para resumen anual), y tabla de Tasaciones con fila por edificio + total.
Sigue sin datos reales (todo en placeholder "—") — el cambio fue solo de layout/distribución,
no de fuente de datos. Ver [[procesos/fact-sheets]].

## [2026-07-21] factsheet | Páginas 3 (Detalle de Activos) y 4 (Notas + Mercado) para Apo

Agregadas `cfg["page3"]`/`cfg["page4"]` de Apo en `FONDOS_CFG` (`scripts/build_factsheet.py`),
basadas en el fact sheet Apo octubre 2025 — única referencia disponible para estas páginas
(PT/TRI quedan con aviso "pendiente", como pasó con page2 hasta traer su propio fact sheet).
Mismo patrón config-driven que la página 2: HTML/JS genérico, solo cambia cfg por fondo.

Página 3: tabla "Aspectos Relevantes" (kv, solo campos estáticos: dirección, superficie,
administración) + grid de `chart-box` placeholder por edificio ("Status Actual por Activo").
Aspectos del mes, gestión de vacancia, resumen anual de vencimientos y tasaciones quedan como
placeholder fijo en el HTML (sin config por fondo todavía) — no tienen fuente de datos clara
aún (vacancia → `raw_rent_roll_line`, tasaciones → `fact_tasacion`).

Página 4: notas (i)-(x) generadas por `_notas_template(has_bursatil)`, texto metodológico
boilerplate sin fechas hardcodeadas (bifurca solo si el fondo tiene valor bursátil). La tabla
de análisis de mercado de oficinas (submercado JLL) se dejó fuera del layout genérico a
propósito: es un dato de mercado completo (mismo informe para PT/Apo, que comparten
submercado), no un dato del fondo — placeholder fijo hasta decidir dónde vive esa data.
Ver [[procesos/fact-sheets]].

## [2026-07-21] factsheet | Estructura página 2 para TRI (consolidado fondo paraguas)

Agregado `cfg["page2"]` de TRI en `FONDOS_CFG` (`scripts/build_factsheet.py`), basado en el
fact sheet TRI enero 2026: tabla "Resumen Performance Activos" con columnas planas (una por
activo/subfondo, sin subcolumnas) — Paseo Viña Centro, Paseo Curicó, Centros Comerciales
(subtotal), Residencias Adulto Mayor, Bodegas Sucden, Apoquindo 3001, Fondo Apoquindo (4501+
4700 consolidado), Fondo Rentas PT (Torre A+Boulevard consolidado) + Total; mismas filas de
m²/renta/absorción que PT/Apo. 6 gráficos con categorías propias (13 rubros de arrendatario,
4 tipos de activo). El renderizado ya era genérico — agregar TRI fue solo config, sin tocar
HTML/JS. Todo en placeholder: `_fetch_perf_data` sigue solo implementado para PT; TRI requiere
consolidar `raw_rent_roll_line` a nivel fondo paraguas (activos directos + los de PT/Apo según
participación) antes de poder rellenar valores. Ver [[procesos/fact-sheets]].

## [2026-07-21] factsheet | Estructura página 2 para Apo (agrupada por edificio)

Agregado `cfg["page2"]` de Apo en `FONDOS_CFG` (`scripts/build_factsheet.py`), basado en el
fact sheet Apo octubre 2025: tabla de performance agrupada por edificio (Apoquindo 4501 /
Apoquindo 4700, no por sociedad ya que ambos activos están bajo la misma Inmobiliaria
Apoquindo S.A.) con las mismas subcolumnas que PT (Oficinas/Locales/Total/Bodegas/Estac.);
6 gráficos con categorías propias de Apo (13 rubros de arrendatario, 4 tipos de activo). El
renderizado (`renderPerfActivosHeader`) ya era genérico — agregar el fondo fue solo config,
sin tocar HTML/JS. Todo en placeholder salvo headers: `_fetch_perf_data` sigue solo
implementado para PT, Apo queda pendiente de wire a `raw_rent_roll_line` agrupado por
edificio. Ver [[procesos/fact-sheets]].

## [2026-07-20] factsheet | Estructura página 2 (Resumen Performance + gráficos) para PT

Agregada la página 2 al fact sheet HTML dinámico (`scripts/build_factsheet.py` →
`factsheet.html`), replicando el layout del fact sheet PDF de PT octubre 2025: tabla de
performance por activo (columnas agrupadas Torre A / Inmob. Boulevard) + 6 gráficos (rubro
arrendatario, tipo de activo, evolución NOI/RCSD, evolución ingresos/NOI/vacancia, perfil
vencimiento contratos, recaudación consolidada). Todo en placeholder — sin datos aún. Layout
implementado vía `cfg["page2"]` por fondo (solo PT por ahora); **no generalizar a TRI/Apo**,
cada uno tiene su propio fact sheet de referencia con estructura distinta. Ver
[[procesos/fact-sheets]].

## [2026-07-20] kpi | Tasa arriendo/cap rate bursátil por serie TRI (A/C/I) + fact sheet

Nuevo indicador `tasa_arriendo_ajustada_bursatil`/`cap_rate_implicito_bursatil` a nivel
`entidad_tipo='serie'` (`CFITOERI1A/C/I`) para el fondo TRI, que sí transa 3 series distintas
(a diferencia de PT/Apo, ya cubiertos §8/§4 de [[kpis_noi_cap_rate_apo]]). Primer intento usó
`patrimonio_bursatil_uf` propio de cada serie como market cap → resultados ~2-6x más chicos que
el cálculo manual del usuario. Bug real: el market cap por serie debe ser **cuotas totales del
fondo (suma de las 3 series) × precio bursátil de esa serie**, no cuotas propias × precio propio
(eso da el market cap del fondo completo, no el "valor implícito por serie"). Validado exacto
contra tabla del usuario a 31-03-2026 (Serie A 10,668%, C 10,682%, I 8,940%). Detalle completo,
fórmula y validación en [[kpis_noi_cap_rate_apo]] §9. Script:
`scripts/consolidate_kpis_bursatil_tri.py`, 21 meses (2024-07 a 2026-03, acotado por
`ingresos_u12m`/`noi_u12m` de TRI). Reflejado en el fact sheet dinámico
(`scripts/build_factsheet.py`): tabla "Otros Indicadores" ahora muestra Tasa Arriendo/Cap Rate
Bursátil con una columna por serie cuando hay dato per-serie (TRI), en vez de la fila única
colapsada que usan Apo (contable) y PT (fondo único).

## [2026-07-14] ingesta | ER Apoquindo 3001 (fondo TRI) — 2020-01 a 2026-05

Último de los 5 activos pendientes del TRI consolidado en
`raw_er_activo_line` (después de INMOSA, Sucden, Viña Centro, Curicó).
`activo_key='Apo3001'`, 616 filas (77 periodos × 8 categorías). Hallazgo:
la fila agregada "(+) Ingresos por Arriendos" no siempre cuadra con sus
sub-detalles Taipei + Otros (redondeo obsoleto de 0.5 UF en 2026-03/04) —
el parser descarta el agregado y usa Taipei/Otros directamente, dando 0
discrepancias de integridad en los 77 periodos. Coexiste sin resolver con
el feed legacy vía RR JLL (`actualizar_noi_apo3001`). Módulo:
`tools/db/ingest_er_apo3001.py`. Tests: `tests/db/test_ingest_er_apo3001.py`
(18 tests, incluye integración contra archivo real).

## [2026-07-14] fix | Amortización U12M / DY+Amort TRI — bug refinanciamiento Sucden II→III

`raw_amortizacion` de `TRI_SUCDEN_BICE` modelaba el refinanciamiento Sucden II→III (dic-2025)
como si Sucden II se hubiera pagado en su totalidad (balloon ficticio ~UF 161.395) en vez de
solo transferir el saldo insoluto a Sucden III (pago real ~UF 272). El tramo ene-nov 2025
(Sucden II) también tenía un cronograma sintético (fórmula 3% anual) en vez de los valores
reales. Corregido con la planilla "Succden refinanciamiento DB.xlsx" (SharePoint/RAW) aportada
por el usuario, con `capital_uf`/`intereses_uf`/`saldo_uf` reales mes a mes para Sucden I/II/III.

Se propagó el delta a `CONSOLIDADO_TRI` (agregado de deuda del fondo) y a `raw_saldo_deuda`, y
se recalculó el cache `derived_kpi` (kpi=`dy_amort`, variantes bursátil y contable, series
CFITOERI1A/C/I) para todo periodo cuya ventana U12M incluye dic-2025 (dic-2025 a nov-2026).

El target de validación previo (bursátil MAR-26 A=34.644%/C=35.316%/I=20.184%, ver
`skills/real-estate-finance-expert/scripts/dividend_yield.py`) quedó obsoleto — el CDG oficial
usado para validar heredaba el mismo error de origen. Nuevo valor correcto MAR-26 bursátil:
A=21.05%/C=21.65%/I=12.42% — confirmado por el usuario como correcto. Ver
`[[feedback_dy_amort_congelada]]` en memoria del agente.

## [2026-07-14] feat | ER Viña Centro consolidado en raw_er_activo_line (parser cuenta-a-cuenta)

Parser nuevo `tools/db/ingest_er_vina.py`, 1768 filas, 34 meses (2023-08 a
2026-05). A diferencia de INMOSA/Sucden/PT/Apoquindo (fuente ya agregada en
UF), Viña Centro trae ~70 cuentas contables en pesos crudos con lista de
cuentas inestable en el tiempo — el `cuenta_codigo` se extrae por regex en
vez de un diccionario fijo, y la conversión CLP→UF se hace en el parser
usando `fact_uf` (UF fin de mes, decisión del usuario).

NOI definido como Ingreso Explotación + Gastos Admin y Ventas, SIN Ingreso
Fuera de Explotación — la planilla fuente no calcula esto bien en ninguna de
sus 2 filas propias de NOI (fila 87 se contamina con ingresos no
operacionales; fila 119 tiene un bug de referencias UF sep-2023/ene-2025
confirmado por el usuario). Se recalcula desde las cuentas crudas.

Se detectaron y corrigieron (con datos que el usuario proveyó) 2 gaps reales
de la fuente: cuenta `3-1-10-120` (SEGURIDAD PARKING) en blanco jul-nov 2025,
y `3-1-40-102` (CONTRIBUCIONES) en blanco abr-may 2026 — la fila de categoría
(header) traía el total correcto pero la cuenta hija estaba vacía. Overrides
permanentes en `_OVERRIDES_MONTO_CLP`, se aplican automáticamente en
re-ingestas futuras.

La ingesta marcó como `superseded` la data previa de `actualizar_er_vina`
(dual-write desde el CDG, 4 meses fragmentados dic-2025/mar-2026) — pendiente
decidir si ese dual-write se desactiva. Detalle completo en `wiki/db.md`.

## [2026-07-14] corrección | Sobretasa Sucden fija 140 UF desde 2026-01

Usuario confirmó que la Sobretasa del ER Sucden pasa a ser un monto fijo de
-140 UF desde enero 2026 en adelante, reemplazando el valor recalculado que
trae la planilla fuente (que ya no aplica). Corregidas 8 filas (2026-01 a
2026-08) vía `tools/db/correct_er_sucden_sobretasa_2026.py` — supersede +
reinserción con `ingest_run` propio, idempotente. Pendiente: re-aplicar tras
cada futura re-ingesta de `NOI Sucden.xlsx` hasta que la fuente refleje el
monto fijo directamente.

## [2026-07-14] ingesta | ER Sucden (fondo TRI) — 2018-01 a 2026-08

Segundo activo pendiente del fondo TRI consolidado (INMOSA, **Sucden**, Viña
Centro, Curicó, Apo3001), mismo patrón `raw_er_activo_line` que INMOSA.
`activo_key='Sucden'` fijo, 416 filas (104 periodos × 4 categorías:
Ingresos por Arriendos, Contribuciones, Sobretasa, Seguros), validación de
integridad contra "NOI Mensual" en 0 discrepancias. Diferencia estructural
vs INMOSA: header de fechas en la misma fila que la ancla (no 2 filas
arriba). Se ingestó todo el rango del archivo incluyendo meses futuros
(2026-04 a 2026-08) por decisión explícita del usuario — el arriendo es
fijo/UF-indexado, los valores planos no son error de arrastre. Módulo
`tools/db/ingest_er_sucden.py`, 18 tests en `tests/db/test_ingest_er_sucden.py`.

## [2026-07-14] ingesta | ER INMOSA (fondo TRI) — 2018-01 a 2026-03

Primer activo pendiente del fondo TRI consolidado (de los 5: INMOSA, Sucden,
Viña Centro, Curicó, Apo3001), siguiendo la arquitectura de `raw_er_activo_line`
ya usada para PT/Apo. `activo_key='INMOSA'` fijo, 792 filas (99 periodos × 8
categorías), validación de integridad contra "NOI Mensual" de la fuente
verificada en 0 discrepancias sobre el histórico completo. Módulo
`tools/db/ingest_er_inmosa.py`, 19 tests en `tests/db/test_ingest_er_inmosa.py`.

## [2026-07-14] db | Migración 049: dim_sociedad + fondo padre + vista look-through

Aditivo puro para consolidación TRI. Nueva tabla `dim_sociedad` con 7 holdings; nuevas columnas `dim_activo.sociedad_key`/`participacion_en_sociedad`, `dim_fondo.fondo_padre`/`participacion_en_padre`; vista `v_activo_fondo_efectivo`. La columna vieja `dim_activo.participacion_fondo_activo` queda deprecada pero intacta — `noi_query.py` sigue funcionando sin cambios (verificado con snapshot pre/post).

Habilita ingestas próximas de INMOSA, Sucden, Viña, Curicó, Apo3001 y consolidación TRI que incluye subfondos PT/Apo.

## [2026-07-13] doc+regla | Supuestos prospectivos ER/NOI Fondo PT

Definidos por usuario para cálculos futuros de ingresos/NOI PT, sin tocar la DB histórica:
desde 2026-07 en adelante `tools/db/ingest_er_pt.py` aplica administración como gasto de
0,2% de ingresos operacionales por activo; GC vacancia Boulevard/Inmob. CDC = 531 UF mensual;
contribuciones fijas Torre A = 1.257 UF mensual y Boulevard = 621 UF mensual; seguros fijos
Torre A = 173,464166666667 UF mensual y Boulevard = 63,46 UF mensual. Todos se guardan como
gastos negativos.

La ingesta queda protegida para no supersedear períodos históricos cuando ya existen filas PT
activas anteriores a 2026-07. Pendiente PT: Margen Energía.

## [2026-07-13] doc+validación | Cap rate/tasa arriendo bursátil PT — fórmula y cobertura cerradas

Confirmado en DB `memory/agente_toesca_v2.db`: `tasa_arriendo_ajustada_bursatil` y
`cap_rate_implicito_bursatil` para fondo PT están consolidados en `derived_kpi`, 90 meses
sin gaps (`2018-12` a `2026-05`).

Actualizada [[kpis_noi_cap_rate_apo]] §8 para dejar explícito que la caja que reduce el
denominador es `caja_usada = caja_consolidada − caja_minima`, no la caja bruta de `raw_caja`.
Fórmula canónica:

```
cap_rate_implicito_bursatil = noi_u12m / (deuda_uf + market_cap_uf − (caja_consolidada_uf − caja_minima_uf))
tasa_arriendo_ajustada_bursatil = ingresos_u12m / mismo_denominador
```

Validado contra tabla manual del usuario a MAR-2026: market cap 493.955 UF, deuda 2.367.897 UF,
caja usada 34.261 UF, renta anual 209.043 UF → tasa arriendo ajustada bursátil 7,39%; NOI DB
176.546 UF vs usuario 176.496 UF → cap rate 6,24% (redondea 6,2%).

## [2026-07-13] seguridad/fix | Auditoría integral de código, esquema e interfaces

Auditoría completa del estado actual. Se corrigió la cadena de migraciones para
DB nuevas y se hizo atómica por archivo; importar el agente ya no migra la DB de
negocio. Se preparó migración 048 para deduplicar `derived_kpi` cuando
`variante IS NULL`, sin aplicarla a la DB canónica (continúa en v46).

Se confinaron rutas de archivos a sus raíces autorizadas, se bloquearon las
herramientas de autoedición del modelo, se filtran herramientas mutables según
la intención original y se reforzó el prompt contra instrucciones embebidas en
correo/documentos. El servidor Flask ahora requiere bearer token, escucha en
localhost y limita tamaño/concurrencia; Streamlit exige `AUTH_COOKIE_KEY` externo.

También se corrigieron escrituras a vistas legacy (`fact_uf`, `fact_dividendo`,
tablas `_line`), idempotencia de ER/KPI/dividendos, conservación de fechas
diarias y migración v1→v2 segura. El extractor CDG antiguo que infería columnas
y nemotécnicos erróneos quedó deshabilitado. Dependencias directas completadas y
`lxml` actualizado a 6.1.0. Verificación: 124 tests pasan, 1 omitido; compilación,
Ruff F821, `git diff --check` y `pip-audit` sin hallazgos.

## [2026-07-13] feat | Tasa arriendo ajustada bursátil y cap rate implícito bursátil — Fondo PT

Nuevo script `scripts/consolidate_kpis_bursatil_pt.py`, réplica de la metodología ya validada
para Apo (contable, [[kpis_noi_cap_rate_apo]] §4) pero con `market_cap` bursátil en vez de
`patrimonio_libro` (Apo no transa en bolsa, PT sí). Denominador = market_cap + deuda_financiera_neta
+ caja_minima (signo confirmado con el usuario: se resta caja_consolidada − caja_minima, no al
revés — EV estándar).

Como parte del mismo trabajo se extendió `caja_minima` de PT: solo 10/34 trimestres estaban
persistidos, se completaron 23 más desde `ESF.total_activo` (`raw_eeff_line`, dedup de filas
corriente/no_corriente/total). Se excluyó 2019-12 por dato inconsistente (total activo salta 2x
y revierte, sin poder determinar la cifra correcta sin el EEFF fuente).

Persistido en `derived_kpi`: `tasa_arriendo_ajustada_bursatil` / `cap_rate_implicito_bursatil`,
fondo PT, 90 meses (2018-12 a 2026-05). Detalle completo en [[kpis_noi_cap_rate_apo]] §8.
Pendiente: misma variante para TRI cuando se consolide ingresos/NOI por activo de TRI.


## [2026-07-13] ingesta | ER/NOI Fondo PT (Torre A + Boulevard) desde NOI PT.xlsx

Nuevo ingestor `tools/db/ingest_er_pt.py`. Persiste 945 líneas en `raw_er_activo_line`
para activos `Torre A` y `Boulevard` (fondo PT), períodos 2018-01 a 2026-05.
Valores en UF, guardados en `monto_clp` por convención (igual que Apoquindo).
NOI derivado on-demand; ene-25 = 13.478,69 UF (imagen: 13.479 ✓).

Pendientes de automatización documentados en el ingestor:
- Margen Energía Torre A y Blvd: calculado internamente en Toesca (urgencia baja)
- Gasto Común Vacancia: fórmula pendiente de definición (urgencia media)
- Seguros: fórmula pendiente (urgencia media)
- Contribuciones: actualmente viene de la planilla; fórmula hardcoded documentada
  (Torre A: (-110660042-39543299)/UF/3, Blvd: (-54388202-19886599)/3/UF)


## [2026-07-09] doc+fix | Metodología NOI/caja mínima/tasa arriendo/cap rate consolidada (Apo) + cierre 2026-03

Nueva página [[kpis_noi_cap_rate_apo]] con toda la metodología aprendida en la sesión: fórmulas de
`ingresos_u12m`/`noi_u12m`/`ingresos_mes`/`noi_mes`/`caja_minima`/`tasa_arriendo_ajustada_contable`/
`cap_rate_implicito_contable`, más los 4 hallazgos de datos (bug versionado Apo 2020-12, 4 valores
de `raw_caja` no corregidos por decisión del usuario, origen no trazable de `raw_caja`, variantes
de nombre sin canonicalizar en `raw_eeff_line`). Enlazada desde `wiki/index.md`.

Con el EEFF Apo 2026-03 ya ingestado (ver entrada siguiente), se cerró el último trimestre
pendiente: `caja_minima` (65.121.454 CLP, usando la fila `TOTAL ACTIVO`=65.121.454.000 — el JSON
también trae una fila `Total activos`=187.625.357.000 que no cuadra con corriente+no_corriente y
se descartó) y recalculados `tasa_arriendo_ajustada_contable`/`cap_rate_implicito_contable` para
2026-03: **5,39% / 4,58%**, exacto contra el cálculo manual del usuario. Serie ahora completa:
26/26 trimestres, 2019-12 a 2026-03.

Desplegado en `factsheet.html`: tabla "Otros Indicadores" (antes 100% placeholder para los 3
fondos) ahora dinámica — Tasa Arriendo, Cap Rate, Ingresos U12M/mes, NOI U12M/mes, con trazabilidad
(modal formula/SQL). Fix incluido: el label "Ingresos/NOI [mes]" no mostraba el mes real porque el
reemplazo de `.oi-mes` corría antes de insertar esas filas en el DOM — resuelto interpolando el mes
directo en el template en vez de depender de un span reemplazado después.

## [2026-07-09] ingesta | Apo EEFF 2026-03 completa — ESF, valor cuota, capital suscrito

Ingestionado desde JSON parseado de PDF (ChatGPT):
- `raw_valor_cuota_contable`: valor_cuota_libro_uf=0.700085245, cuotas=1.585.000
- `raw_eeff_line` (ESF línea a línea): total_activo=CLP 65.121M, total_pasivo=CLP 20.911M, patrimonio=CLP 44.209M
- `raw_capital_suscrito`: capital_acumulado=980.794,96 UF

Sin dividendos ni disminuciones en el período (confirmado en notas del PDF).
**Pendiente aún**: ESF línea a línea TRI (7 períodos 2017-2023) + 2 períodos 2024-12/2025-06 con duplicados.

## [2026-07-09] fix+pendiente | caja_minima consolidada + gaps de balance EEFF (TRI, Apo 2026-03)

Consolidados en `derived_kpi`: `ingresos_u12m`/`noi_u12m`/`tasa_arriendo_ajustada_contable`/
`cap_rate_implicito_contable` para fondo Apo (26 trimestres, 2019-12 a 2026-03) y `caja_minima`
(% de activos totales: Apo 0.1%, PT/TRI 1%) para los 3 fondos donde `ESF.total_activo` existe limpio.
Validado exacto contra cálculo manual del usuario a mar-2026 (tasa arriendo 5,39%, cap rate 4,58%).

Al auditar cobertura de `ESF.total_activo` aparecieron 3 hallazgos:
1. **Bug de versionado en Apo 2020-12**: la fila correcta (comparativa en 4 reportes posteriores,
   42.343.358.000) quedó `superseded_at` mientras la incorrecta del reporte propio
   (125.087.458.000) quedó viva. Corregido con foto EEFF del usuario.
2. **raw_caja tiene 4 valores mal cargados** vs. tabla histórica del usuario: PT/TRI cruzados en
   2025-10-31, Apo 2020-07-27 y TRI 2023-05-31 con dígitos distintos. Usuario decidió NO corregirlos
   por ahora.
3. **TRI: 9 periodos pendientes** de `ESF.total_activo` — 7 sin parseo de balance completo
   (2017-03/06/09, 2021-03/06/09, 2023-09) y 2 con filas duplicadas sin resolver (2024-12, 2025-06).
   Detalle completo en [[db]] sección "Pendientes EEFF — balance histórico". **Apo 2026-03** también
   pendiente de ingesta.

## [2026-07-09] ingesta | ER Fondo Apoquindo (Apo4501, Apo4700) desde planilla local raw/NOI.xlsx

Mientras no llegan las respuestas de las APIs de JLL y Tres Asociados, se pobló `raw_er_activo_line`
con el ER histórico de Apo4501/Apo4700 (2019-01 a 2026-05, 1405 filas, 10 categorías por activo/mes).
Ingestor nuevo: `tools/db/ingest_er_apoquindo.py`. NOI verificado exacto contra CDG (dic-24 a jun-25).
Fix incluido: `dim_activo.participacion_fondo_activo` = 1.0 para Apo4501/Apo4700 (antes 0.3 por
confundir la relación fondo-fondo TRI→Apo con la relación fondo-activo; migración 047). Contribuciones
viene combinada (sin desglose por edificio) en 10 meses históricos (2019-01 a 2019-10; el resto del
histórico sí trae desglose real y se respetó tal cual) — split 25% Apo4700/75% Apo4501 aplicado solo
donde falta el desglose, misma proporción que la fórmula acordada para meses futuros sin dato: `(-165.941.575-62.167.695)/3/UF_mes`. Detalle en [[activos/apoquindo]] y
`docs/superpowers/specs/2026-07-09-apoquindo-er-ingesta-design.md`.

## [2026-07-02] feat | duration_deuda v2 — metodología Toesca validada, TRI look-through

Reescrita duration con la fórmula Excel de Toesca: [Σ(meses×cuota_total)/Σ(cuota_total)]/12 sobre
raw_amortizacion (cuota = capital+intereses, solo períodos futuros). Validado exacto: PT 3.391 ✓,
Apo 0.743 ✓ (CONSOLIDADO_{PT,Apo}). TRI usa look-through ponderado de créditos individuales
(no CONSOLIDADO_TRI — su capital_uf está congelado para dy_amort, no tocar): DB da 5.438 vs 5.450
de Toesca — diferencia explicada por 3 errores en el consolidado manual del usuario (hoja
'tabla tri': cuota Apo3001 duplicada 2×/3× jul-oct 2028, step-up Viña desfasado 1 mes, +1.7k
dic-2026). Los cronogramas bancarios individuales de la DB son la fuente correcta. Backfill v2
completo reemplazó v1: 932 filas (fondo 234 + activo 698), 2020-01→2026-06.

## [2026-07-02] feat | Backfill completo bloque leverage: dscr + duration_deuda historicos

Backfilleados los 2 KPIs restantes del bloque leverage en derived_kpi (2020-01..2026-06):
dscr fondo 234 + activo 415, duration_deuda fondo 234 + activo 698. Bloque completo:
ltv, ltc, deuda_consolidada, leverage_financiero, dscr, duration_deuda — todos con
historico en DB. Errores esperados en dscr activo: Apo4501/4700 sin NOI individual.

## [2026-07-02] feat | leverage_financiero (Deuda/Patrimonio) histórico + fix cuotas TRI en EEFF antiguos

Nuevo `kpi='leverage_financiero'` = deuda consolidada (look-through TRI) / patrimonio contable
(VNA×cuotas, Σ series). Solo fondo, solo cierres con VNA. Backfilleado: PT 25 pts (2020-03+),
Apo 35, TRI 9 (2021-12+). Valores 2026-03: PT 4.139, TRI 1.522, Apo 2.325.

**Fix datos**: los EEFF PDF de 2024-06/2025-03/2025-06 tenían cuotas TRI erróneas en
`raw_valor_cuota_contable` (160.000/242.161/223.948 — línea equivocada del PDF, desinflaba el
patrimonio ~5x). Corregidas a las canónicas validadas exacto contra `raw_ar_event`
(aportes−canjes): A 475.667, C 1.252.928, I 1.091.101. Además dedup de 26 filas duplicadas
(`superseded_at NULL`) en cierres de año; grupo A/2021-12 tenía una fila con cuotas pre-canje
(502.869) — conservada la post-canje (475.667). Sin duplicados restantes.

## [2026-07-02] feat | Leverage financiero consolidado: LTV, LTC, deuda_consolidada históricos en derived_kpi

Implementados en el skill real-estate-finance-expert (`scripts/leverage.py`) y backfilleados
2020-01→2026-06 en `derived_kpi`: `ltv` (fondo 234 + activo 516), `ltc` (fondo 234 + activo 516),
`deuda_consolidada` (fondo 234). También `dscr` y `duration_deuda` implementados (sin backfill aún).

**Metodología validada exacto vs Toesca 2026-03** (PT LTV 0.81225 ✓, PT LTC 0.60529 ✓, Apo LTC
0.59858 ✓): LTV = deuda / tasación (fact_tasacion, tasador='Promedio', año ≤ período);
LTC = deuda / precio compra 100% (fact_adquisicion.valor_activo_uf). PT/Apo: suma simple de sus
activos. **TRI: look-through ponderado** (`_TRI_LOOKTHROUGH`) — 0.43×INMOSA, 1×Sucden/Apo3001/Viña,
0.8×Curicó, 0.3×Apo4501/4700, ⅓ exacto×TorreA/Boulevard. INMOSA sin tasación propia → suma de 6
residencias; en adquisición → lump-sum 'INMOSA' (5 residencias) + fila Domingo Calderón aparte.

**Errores encontrados y corregidos**: (1) cifra Toesca TRI LTC 0.52990 incluía Machalí en el
sumaproducto por error (confirmado) — valor correcto sin Machalí: 0.54480; (2)
`fact_adquisicion.valor_activo_uf` estaba inflado ÷% para activos con participación <100%
(el precio fuente ya era 100%) — corregido desde hoja 'compra' de tablaflujos.xlsx, que también
pobló los faltantes (INMOSA, Apo3001, Mall Curicó, Dom. Calderón); (3) `dim_activo` Apo3001
participación 0.685→1.0 (vía Chañarcillo 100%); (4) ingesta de tasaciones pisaba con NULL las
columnas ltv/ltc/cap_rate al re-ingestar fuentes parciales — `repo_tasacion.upsert_tasacion`
ahora usa COALESCE en columnas opcionales; (5) parser `ingest_tasaciones.py` reescrito
header-driven (soporta hoja 'Tasaciones' de tablaflujos.xlsx y layout legado).

## [2026-07-02] feature | Dashboard fondos con fact sheets dinámicos

Creado `dashboards/fondos.py`: página Streamlit estética Toesca con vista Portfolio + fact sheet dinámico por fondo (TRI/PT/Apo). Bloques: rentabilidad (derived_kpi), valor cuota, repartos U12M, endeudamiento, NOI, vacancia, tasaciones/LTV. Ver [[agente/dashboard-fondos]]. Aprendido: fact_tasacion tiene fila tasador='Promedio'; raw_dividendo tiene duplicados por doble fuente; raw_valor_cuota_bursatil no tiene superseded_at.

## [2026-07-02] feat | DY + Amortización consolidado en derived_kpi (kpi='dy_amort'), todos los fondos

Consolidados 550 valores históricos de `dividend_yield_con_amort` (bursátil), `_contable` y
`_capital` (Apo) en `derived_kpi` bajo `kpi='dy_amort'`, `variante='bursatil'/'contable'/'capital'`
— mismos rangos ya validados para `kpi='dy'`. TRI/PT: 2018-03→2026-03/06 (33 contable, 97-98
bursátil por serie/fondo). Apo: 2019-03→2026-03 (29, variante='capital').

Ambas fórmulas quedaron corregidas antes de consolidar (ver `wiki/kpis_rentabilidad_fondos.md`
sección 4.1): se agregó la variante contable (antes solo existía bursátil), se agregó la variante
`_capital` específica para Apo (denominador = capital suscrito por cuota, no VNA — Apo está muy
lejos de la par y el CDG usa ese denominador para este fondo específicamente), y se revirtió un
intento de excluir pagos de refinanciamiento del cálculo de amortización (el CDG no los excluye).

De paso se corrigieron datos reales de deuda que afectaban el cálculo: saldo de `CONSOLIDADO_TRI`
(faltaba crédito Sucden refinanciado), cronograma de `APO_APO_BTG` desde ene-2026 (estaba
desactualizado, asumía amortización gradual cuando el crédito se pagó completo en mar-2026), y se
creó `CONSOLIDADO_Apo` (no existía). Sin duplicados verificado tras consolidar. Todas las fórmulas
quedan congeladas — ver `dividend_yield.py` para la implementación.

## [2026-07-02] fix | DY + Amortización — saldo CONSOLIDADO_TRI/Apo corregido, sin excluir refinanciamiento

Agregada variante `dividend_yield_con_amort_contable` (antes solo existía bursátil) en
`dividend_yield.py`. Ambas validadas EXACTAS contra CDG (corte MAR-26): A=34.644%/18.038%,
C=35.316%/18.065%, I=20.184%/18.088% (bursátil/libro).

**Datos de deuda corregidos**: `raw_amortizacion` tenía `CONSOLIDADO_TRI` con saldo desactualizado
(faltaba `TRI_SUCDEN_BICE`, crédito refinanciado en ene-2026 — el saldo real 31-mar-26 es
3.532.590 UF, la DB mostraba 3.371.105). Parchado sumando el saldo/capital de SUCDEN_BICE a
`CONSOLIDADO_TRI` para los 120 períodos donde existe (2018-02→2028-01) — saldo ahora exacto.
Creado `CONSOLIDADO_Apo` desde cero (no existía) sumando `APO_APO_BTG` + `APO_APO_EUROAMERICA`
(89 períodos) — también exacto vs foto real (2.602.856 UF).

**Importante — decisión revertida**: se intentó excluir el pago de refinanciamiento de Sucden
(161.395 UF, dic-2025) del cálculo de amortización para `dividend_yield_con_amort`, razonando que
un refinanciamiento no representa deleveraging real. El usuario confirmó inicialmente ese criterio,
pero al comparar contra el CDG real se determinó que el propio CDG **no excluye** ese pago — usa
`capital_uf` de `CONSOLIDADO_{fondo}` tal cual viene de la planilla fuente. Se revirtió la
exclusión: `capital_uf` de `CONSOLIDADO_TRI` quedó en su valor ORIGINAL (sin sumar ni restar
Sucden) — el saldo (`saldo_uf`) sí se mantiene corregido con Sucden incluido, porque para ESE
campo la corrección sí calzó exacto contra la foto real del usuario. Es decir: mismo crédito, dos
tratamientos distintos según el campo (saldo sí se corrige, flujo de capital no se toca) — contra-
intuitivo pero validado dígito por dígito. **No volver a excluir sin nueva validación explícita.**

Pendiente: el archivo fuente de `CONSOLIDADO_TRI`/`CONSOLIDADO_Apo` usado por
`tools/db/ingest_financing.py` sigue desactualizado (parche aplicado directo en DB, no en el
Excel origen) — si se re-corre la ingesta completa desde ese Excel sin actualizarlo primero, se
pierde este parche.

## [2026-07-02] fix | Dividend Yield — limpieza de datos Apo, sin cambio de fórmula

`dy_v2` (`scripts/compute_kpis_series.py`) ya estaba correcto y validado exacto contra CDG para
TRI y PT (A=2.152%/4.134%, C=2.375%/4.644%, I=2.468%/2.754% mar-26). Al revisar Apo se encontró
inconsistencia de datos (no de cálculo):

1. `SERIES_CONFIG` guardaba el DY de Apo bajo `entidad_key='APO-UNICA'`, distinto al resto de
   `derived_kpi` (TIR/YTD/U12M usan `entidad_key='Apo'`, igual a `dim_serie.nemotecnico`) —
   corregido en el script (ahora usa `'Apo'` directamente, sin `nemo_db` override).
2. Existían 34 filas viejas (`Apo`/`dividend_yield_contable`, `Apo`/`dividendo_por_cuota`) de un
   proceso anterior que SÍ incluía `tipo='disminucion'` en el numerador — la fórmula validada
   (`dy_v2`) filtra solo `tipo='dividendo'`, igual que el CDG. Estas filas daban valores
   distintos (ej. dic-2020: 5.418% vs 2.304% correcto) para el rango 2020-12→2022-09, donde Apo
   tuvo varios eventos de disminución. Borradas.

Migradas las 29 filas de `APO-UNICA`/`dy` a `entidad_key='Apo'`. Sin duplicados tras la limpieza.
Re-corrido `compute_kpis_series.py --kpi dy` para confirmar que el script corregido reproduce
exactamente lo mismo.

## [2026-07-02] feat | Rentabilidad U12M — validada (bug de Excel en PT confirmado, no se replica)

Verificado `tir_contable_u12m`/`tir_bursatil_u12m` (ya existían en `tir.py`, sin cambios de código)
para las 5 series/fondos, corte MAR-2026. TRI y Apo calzan exacto contra referencia previa
(wiki `kpis_rentabilidad_fondos.md`: A=9.12%/C=9.25%/I=9.30% libro). PT NO calzaba al inicio
(mío 20.989%/9.963% vs CDG 16.673%/5.830%) — se reconstruyó la fórmula de Excel (`P10`,
`XIRR(OFFSET(Libro 12M,...))`) celda por celda y se descubrió que el CDG **omite el dividendo
29-abr-2025 de PT por orden de filas** (mismo patrón que el bug ya documentado en Serie I:
un dividendo pagado poco después del VNA de inicio queda posicionado antes en la tabla y las
fórmulas basadas en offset de fila lo saltan). El usuario confirmó explícitamente: "eso es un
error mío. El cálculo correcto debería incluirlo" — se mantiene el valor completo (con el
dividendo), NO se replica el bug. Sin cambios de código necesarios.

Consolidado en `derived_kpi`: 512 filas (TRI contable 30/serie, TRI bursátil 89/serie, PT
contable 30 + bursátil 90, Apo contable 35). Mismo rango que YTD por fondo.

## [2026-07-02] fix | Rentabilidad YTD anualizada — fórmula corregida, congelada, consolidada

Corrección importante: la metodología "YTD acumulada" documentada previamente en
`wiki/kpis_rentabilidad_fondos.md` sección 2 estaba MAL — asumía retorno simple sin anualizar,
achacando el delta de ~0.017pp vs CDG a "ruido de planilla". Al pedir la fórmula real de Excel
al usuario se descubrió: `=(1+TIR.NO.PER(flujos;fechas))^(MES(fecha_corte)/12)-1` — un XIRR
estándar (T0=31-dic año anterior, dividendos reales, Tn=corte) seguido de un ajuste por MESES
CALENDARIO (no por días). El "ruido" era en realidad la diferencia entre exponente días/365
(≈0.2466 para marzo) y exponente meses/12 (0.25 exacto) — un error de método, no ruido de datos.

Implementada como `_calcular_rent_ytd` en `tir.py`, kpis `rent_ytd_contable`/`rent_ytd_bursatil`,
validada EXACTA contra el CDG (corte MAR-2026) para las 5 series/fondos (TRI A/C/I, PT, Apo).
Congelada — no volver a tocar sin nueva validación explícita del usuario.

Consolidado en `derived_kpi`: TRI contable 2018-03→2026-03 (33/serie), TRI bursátil
2018-03→2026-06 (96/serie), PT contable 33 + bursátil 96, Apo contable 2020-03→2026-03 (35).
Total 551 filas. Primer período de cada serie (2017-12) queda sin YTD porque no existe un
31-dic-2016 previo en la DB para usar como T0 — comportamiento esperado, no error.

## [2026-07-02] fix | TIR desde inicio PT y Apo — método agregado, corrección de datos faltantes

Extendida la metodología agregada (validada para TRI bursátil el mismo día) a PT y Apo, para
AMBOS trackeos (contable y bursátil) — ver `wiki/tir_contable_desde_inicio.md`. Validado exacto
contra planilla del usuario (hojas PT/APO de `tablaflujos.xlsx`, corte MAR-2026): PT
contable=-5.121%, PT bursátil=-6.322%, Apo contable=-1.912%.

Datos faltantes agregados a `raw_ar_event`: Apo no tenía NINGUNA fila (0 aportes registrados,
faltaba el aporte único 2019-01-02 de 1.585.000 UF); PT le faltaban 2 Disminuciones
(2019-10-09, 2019-12-30). Cuidado: varias Disminuciones de PT ya estaban fusionadas dentro de
filas `tipo='dividendo'` de `raw_dividendo_line` — insertarlas de nuevo en `raw_ar_event` duplicó
el flujo hasta que se detectó comparando contra la planilla fila por fila.

Bug de dispatch encontrado y corregido en `_calcular_tir_por_cuota`: la condición original
(`COUNT(Aporte WHERE fecha >= primer_VNA) == 0` → usar método simple) fallaba para Apo porque su
único aporte coincide exactamente con la fecha del primer VNA (`fecha >= ` lo cuenta como
"posterior"). Reemplazada por `COUNT(Aporte total) <= 1` — no afecta a TRI (16/14/7 aportes cada
serie).

Consolidado en `derived_kpi`: PT contable trimestral 2017-12→2026-03 (34), PT bursátil mensual
2017-12→2026-06 (97), Apo contable 2019-03→2026-03 (39, quarterly hasta 2024-12 luego mensual).
Apo bursátil no aplica (`transa_bolsa=0`).

## [2026-07-02] feat | TIR desde inicio (contable + bursátil) consolidada en derived_kpi, TRI A/C/I

Implementadas y validadas exacto contra CDG (planilla `tablaflujos.xlsx`, corte MAR-2026) dos metodologías
**distintas y congeladas** para `tir_contable_desde_inicio` / `tir_bursatil_desde_inicio` — ver
`wiki/tir_contable_desde_inicio.md`. Contable: `_calcular_tir_por_cuota` (UF/cuota, divisor fijo, ya
validada previamente). Bursátil: `_calcular_tir_bursatil_agregado` (UF agregadas de la serie, sin
divisor — reconstruye la fórmula real de Excel `TIR.NO.PER(Tabla1[Bolsa Inicio <serie>])`).
Bug encontrado en la planilla del usuario: Serie I bursátil omite un dividendo real (29-dic-2021) en su
columna `Bolsa Inicio I2` — mismo patrón que el bug ya conocido en TIR U12M serie I. Se persistió el
valor corregido (-0.733% en MAR-26), no el de la planilla (-0.883%).

Consolidado en `derived_kpi`: contable trimestral 2019-12→2026-03 (excluidos 2017-12→2019-09 por
divisor fijo antes de terminar rondas de aportes — ver metodología), bursátil mensual 2017-12→2026-06,
78+291 filas, series CFITOERI1A/C/I. Bug de duplicación encontrado y corregido en
`_common.py::upsert_derived_kpi` (SQLite no deduplica `UNIQUE` con `variante IS NULL`; ahora hace
DELETE+INSERT explícito). Nota: Serie I bursátil muestra una caída real de precio abr→may-2026
(0.7347→0.2709 UF/cuota, confirmada en 3 fechas de transacción) — no es error de datos, pendiente de
entender la causa.

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

## [2026-07-14] ingesta | ER Mall Curicó (fondo TRI) — 2023-08 a 2026-05

Segundo activo de Tres Asociados consolidado en `raw_er_activo_line`
(después de Viña Centro), mismo enfoque de código de cuenta por regex y NOI
recalculado desde cuentas crudas. `activo_key='Mall Curicó'`, 1496 filas
(34 periodos × 44 cuentas). Diferencia clave encontrada: 3 cuentas
huérfanas en Gastos de Administración y Ventas que la fuente excluye de sus
propios subtotales de categoría (hasta 5.7% del gasto en algunos meses) —
confirmado con el usuario que el NOI en la DB las incluye, con validación
de integridad blanda para ese bloque.
