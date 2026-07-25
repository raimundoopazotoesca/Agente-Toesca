# Plan de migración — Claves de Apoquindo

**Fecha:** 2026-07-24 · **Estado:** análisis entregado, ejecución pendiente de aprobación humana
**Regla rectora (decisión del usuario):** no se ejecutan reemplazos globales de texto; la estabilidad prima sobre la limpieza de nombres; la relación activo↔fondo va siempre por `fondo_key`, nunca inferida del nombre; detener el proceso ante cualquier ambigüedad fondo↔activo.

## 1. Las cuatro entidades (no confundir)

| Entidad | Tipo | Fondo dueño | Clave en `dim_*` hoy |
|---|---|---|---|
| Fondo Toesca Rentas Inmob Apoquindo | fondo | — | `dim_fondo.fondo_key = 'Apo'` |
| Apoquindo 4501 | activo | Apo | `dim_activo.activo_key = 'Apo4501'` (fondo_key `Apo` ✓) |
| Apoquindo 4700 | activo | Apo | `dim_activo.activo_key = 'Apo4700'` (fondo_key `Apo` ✓) |
| Apoquindo 3001 | activo | **TRI** | `dim_activo.activo_key = 'Apo3001'` (fondo_key `TRI` ✓) |

La relación activo→fondo **ya es explícita por FK** en `dim_activo.fondo_key` — correcto, se preserva.
Existe además la serie única del fondo: `dim_serie.nemotecnico = 'Apo'` (mismo literal que el fondo, entidad distinta).

## 2. Inventario de valores actuales (DB, verificado 2026-07-24)

### 2.1 Referencias al FONDO

| Tabla | Valor | Filas | Nota |
|---|---|---:|---|
| `dim_fondo` | `Apo` | 1 | canónico |
| `raw_eeff_line` | **`APO`** | 18.009 (14.725 vivas) | 2019-03→2026-03, ingestas históricas `scripts/ingest_eeff.py --fondo APO` |
| `raw_eeff_line` | `Apo` | 3 | 2026-03, ingestor nuevo — **el mismo período tiene ambas claves** |
| `raw_valor_cuota_contable` | **`APO`** | 15 | 2025-01→2026-03 |
| `raw_valor_cuota_contable` | `Apo` | 30 | 2019-01→2026-03 — **solapa con las 15 `APO`** |
| `raw_caja`, `raw_dividendo`, `raw_capital_suscrito`, `raw_cuota_en_circulacion`, `derived_kpi (fondo)`, `dim_serie` | `Apo` | — | consistentes |

### 2.2 Referencias a ACTIVOS

| Tabla | Claves | Estado |
|---|---|---|
| `dim_activo`, `raw_er_activo_line` | `Apo4501` / `Apo4700` / `Apo3001` | consistentes |
| `derived_kpi (activo)` | **duplicidad de esquemas**: `Apo3001` (294) **y** `Apoquindo 3001` (74) · `Apo4501` (234) **y** `Apoquindo 4501` (86) · `Apo4700` (114) **y** `Apoquindo 4700` (86) | dos generaciones de recetas escribieron con claves distintas |
| `derived_kpi (activo)` | `Apoquindo` (178) | ⚠️ ambigua: presumiblemente agregado 4501+4700, **pendiente de validación humana** |
| `derived_kpi (activo)` | `Fondo Apoquindo` (91) | ⚠️ presumiblemente la participación de TRI en el fondo Apo vista como "activo" (look-through), **pendiente de validación humana** |

### 2.3 Referencias en código (fondo)

`'APO'` como clave de fondo: `scripts/ingest_eeff.py:313`, `scripts/ingest_from_json.py:215`, `scripts/ingesta_server.py:64` (`FONDO_FILE`), `tools/db/ingest_eeff_validated.py:36` (`FONDOS_VALIDOS`), `tools/db/estado_ingesta.py:55,63`, `tools/db/ingest_gastos_pdf.py:284`, `tools/finance_tools.py:79,147` (docstrings), `tools/registry.py:2075,2107` (descripciones de tools), `tools/eeff_tools.py:25` (mapea `"Apo"`→dir). `tools/db_chat.py:164` ya normaliza todas las variantes a `Apo`.
**No confundir:** los códigos `APO_*` de `ingest_er_apoquindo.py` (cuentas ER: `APO_ING_ARR`, `APO_CONTRIB`, …) y de `ingest_financing.py` (créditos: `APO_APO_BTG`, `APO_APO_EUROAMERICA`) son códigos de cuenta/crédito, **no** claves de fondo — quedan fuera de esta migración.

## 3. Tabla de mapeo propuesta

**Etapa A (F0 — saneamiento de datos, sin cambio de esquema):** consolidar sobre las claves cortas existentes, que ya son las de `dim_*`:

| Valor actual | Entidad | → Clave canónica | Alias aceptado en entrada (UI/CLI/prompts) |
|---|---|---|---|
| `APO` (fondo_key en raw) | fondo | `Apo` | `APO`, `Apoquindo` |
| `Apoquindo 4501` (derived_kpi) | activo | `Apo4501` | `Apoquindo 4501` |
| `Apoquindo 4700` (derived_kpi) | activo | `Apo4700` | `Apoquindo 4700` |
| `Apoquindo 3001` (derived_kpi) | activo | `Apo3001` | `Apoquindo 3001` |
| `Apoquindo` (derived_kpi) | ¿agregado 4501+4700? | **DETENIDO — validar con usuario** | — |
| `Fondo Apoquindo` (derived_kpi) | ¿look-through TRI→Apo? | **DETENIDO — validar con usuario** | — |

**Etapa B (posterior, opcional — IDs técnicos):** introducir identificadores técnicos estables separando fondo de activos, según el esquema propuesto por el usuario: fondo `FTRI_APO`, activos `ACT_APOQUINDO_4501`, `ACT_APOQUINDO_4700`, `ACT_APOQUINDO_3001`; `APO` queda como `codigo_visible` del fondo y `Apo` como alias histórico. Implementación recomendada: columnas `id_tecnico` + tabla `dim_alias(entidad_tipo, alias, clave_canonica)` en `dim_fondo`/`dim_activo`, migrando consumidores gradualmente **sin** renombrar las PKs de golpe (33 tablas dependen de ellas). Solo se ejecuta si la plataforma multi-usuario lo justifica; no bloquea F0–F2.

## 4. Impacto de la Etapa A

- **Tablas:** `raw_eeff_line` (18.009 filas `APO`→`Apo`), `raw_valor_cuota_contable` (15 filas; ojo con el solape 2025-01→2026-03 con las filas `Apo` existentes — verificar duplicados lógicos post-unificación y resolver por `superseded_at`), `derived_kpi` (claves de activo duplicadas: decidir si se re-etiquetan las filas viejas o se marcan obsoletas y se recalcula).
- **Vistas:** ninguna filtra por `'APO'` literal (verificar en dry-run con grep sobre `sqlite_master.sql`).
- **Scripts/código:** los listados en §2.3 — tras la migración deben aceptar `APO` como *entrada* (alias) pero escribir siempre `Apo`. `estado_ingesta.CONFIG` unificar a `Apo` (hoy el tab EEFF exige `APO` y el de balance `Apo`).
- **Outputs:** `build_factsheet.fetch_fondo` consulta por clave de `FONDOS_CFG` — verificar qué clave usa para EEFF de Apo hoy (si usa `APO`, ajustar al unificar). Asistente: `db_chat` ya normaliza, sin cambio.
- **Tests:** actualizar fixtures que usen `APO` y agregar invariante "una sola clave por fondo en cada tabla raw".

## 5. Plan de ejecución reversible (checklist)

1. Backup físico: `cp memory/agente_toesca_v2.db memory/backups/agente_toesca_v2.pre-apo-fix.db` (patrón `snapshot_pre_049.py`).
2. Copia de trabajo: ejecutar toda la migración primero sobre una copia y correr la suite + generación de factsheet contra ella.
3. Dry-run con conteos: por tabla, `COUNT(*)` por clave antes/después; el total de filas no cambia; `APO` termina en 0; sin nuevos duplicados lógicos (query de grupos duplicados de `dedup_raw_eeff.py`).
4. Migración como archivo numerado (058+) en una sola transacción: `UPDATE raw_eeff_line SET fondo_key='Apo' WHERE fondo_key='APO'; UPDATE raw_valor_cuota_contable ...` + re-etiquetado/obsolescencia acordado para `derived_kpi`.
5. Verificación: `PRAGMA foreign_key_check` (deben desaparecer las 18.009 violaciones), invariantes, `pytest`, regenerar `factsheet.html` y comparar KPIs de Apo antes/después (deben ser idénticos salvo los casos que hoy se pierden por la clave partida — documentar cualquier cambio de valor y validarlo con el usuario antes de dar por buena la migración).
6. Comparar respuestas del Asistente a un set fijo de preguntas sobre Apo antes/después.
7. Rollback: restaurar el backup; la migración no borra filas, solo re-etiqueta, así que también es reversible por UPDATE inverso mientras no se recalculen derivados encima.
8. **Condición de término:** tests verdes + conteos cuadrados + factsheet/asistente sin cambios inesperados + las dos ambigüedades de §3 resueltas por el usuario.

## 6. Ambigüedades que detienen la ejecución (requieren respuesta humana)

1. ¿Qué representa exactamente `derived_kpi.entidad_key='Apoquindo'` (178 filas) y cuál es su clave destino? (¿agregado de edificios → mantener como entidad propia con clave `ApoEdificios`/similar, o re-etiquetar?)
2. ¿Qué representa `'Fondo Apoquindo'` (91 filas) como `entidad_tipo='activo'`? (¿participación de TRI en Apo → debería modelarse como look-through vía `v_activo_fondo_efectivo` en vez de entidad ad-hoc?)
3. Para `derived_kpi` con claves duplicadas (`Apo4501` vs `Apoquindo 4501`): ¿re-etiquetar filas históricas o marcarlas obsoletas y recalcular con el pipeline nuevo (F1.1)?
