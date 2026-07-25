# Análisis — Valores de "cuotas" en el sistema

**Fecha:** 2026-07-24 · **Conclusión anticipada:** los valores de `SHEET_CFG` y `FONDOS_CFG` **no se contradicen** — son dos conceptos distintos (cuotas *en circulación* vs cuotas *emitidas*). No se requiere corrección de cifras; sí una desambiguación de modelo y nombres.

## 1. Matriz comparativa de todos los valores existentes

| Valor | Definido en | Fondo / serie | Concepto verificado | Evidencia | Quién lo usa | Etiqueta al usuario |
|---:|---|---|---|---|---|---|
| 1.585.000 | `tools/gestion_renta_tools.py:33` (`SHEET_CFG["Apo"].cuotas`) | fondo Apo, serie única | **cuotas en circulación** | coincide exacto con `raw_cuota_en_circulacion` Apo al 2025-12-31 (1.585.000,0) | escritura CDG: col J (cuotas) y H (Monto$ = precio×cuotas) al agregar VR bursátil/contable | no visible (interno CDG) |
| 1.640.000 | `gestion_renta_tools.py:42` (`SHEET_CFG["PT"]`) | fondo PT, CFITRIPT-E | **cuotas en circulación** | = `raw_cuota_en_circulacion` PT 2025-12-31 | ídem CDG | interno |
| 475.667 / 1.252.928 / 1.091.101 | `gestion_renta_tools.py:52` (`SHEET_CFG["TRI"]`, series A/C/I) | fondo TRI por serie | **cuotas en circulación por serie** | = `raw_cuota_en_circulacion` TRI 2025-12-31 (A/C/I) | ídem CDG | interno |
| 4.000.000 | `scripts/build_factsheet.py:93` (`FONDOS_CFG["TRI"].cuotas_emitidas`) | fondo TRI | **cuotas emitidas** (dato de ficha, presumiblemente del reglamento interno) | etiqueta explícita; ≥ circulación (2.819.696 = A+C+I) ✓ | ficha del fondo, página 1 del factsheet HTML | "Cuotas Emitidas" |
| 1.800.000 | `build_factsheet.py:219` (`FONDOS_CFG["PT"]`) | fondo PT | **cuotas emitidas** | ≥ 1.640.000 en circulación ✓ | ídem | "Cuotas Emitidas" |
| 2.000.000 | `build_factsheet.py:328` (`FONDOS_CFG["Apo"]`) | fondo Apo | **cuotas emitidas** | ≥ 1.585.000 en circulación ✓ | ídem | "Cuotas Emitidas" |

**Datos dinámicos en DB (los que alimentan KPIs):**

| Tabla | Contenido | Rango | Consumidores |
|---|---|---|---|
| `raw_cuota_en_circulacion` | cuotas en circulación por fondo/nemotécnico/fecha | 2017-12-31 → 2025-12-31 | `build_factsheet.py:554` (patrimonio contable), scripts de KPIs bursátiles (market cap por serie), skill financiera |
| `raw_valor_cuota_bursatil.cuotas` | cuotas del snapshot bursátil | 2017-11 → 2026-06 | `build_factsheet.py:508-522` |
| `raw_capital_suscrito` | capital suscrito UF por fondo/nemo/fecha_fin_periodo | TRI 64 filas, Apo 1 | `v_capital_suscrito_serie`, DY Apo (`dy_amort` usa capital suscrito por cuota) |

## 2. Seguimiento de flujo (¿algún KPI usa los hardcodes?)

- Los KPIs bursátiles/contables (market cap, patrimonio, DY, TIR) leen **siempre de la DB** (`raw_cuota_en_circulacion`, `raw_valor_cuota_bursatil`), no de los hardcodes. Verificado en `build_factsheet.fetch_fondo` y `consolidate_kpis_bursatil_{pt,tri}.py`.
- `SHEET_CFG.cuotas` solo alimenta la **escritura del CDG** (flujo legado, con decisión de decomiso — ver ROADMAP F1). Riesgo actual: son constantes congeladas al 2025-12-31; si hubiera un canje/emisión, el CDG escrito quedaría desactualizado. Muere con el decomiso del CDG.
- `FONDOS_CFG.cuotas_emitidas` es solo texto de ficha (no entra en cálculos).

## 3. Modelo propuesto (evita la variable ambigua `cuotas`)

Tabla única de posiciones de cuotas, reemplazando gradualmente hardcodes y unificando las fuentes:

```sql
fact_cuotas(
  fondo_key      TEXT NOT NULL REFERENCES dim_fondo,
  nemotecnico    TEXT REFERENCES dim_serie,      -- NULL = nivel fondo
  periodo        TEXT NOT NULL,                   -- YYYY-MM (o fecha exacta si aplica)
  tipo           TEXT NOT NULL CHECK (tipo IN ('emitidas','suscritas','pagadas','en_circulacion')),
  cantidad       REAL NOT NULL,
  fuente         TEXT NOT NULL,                   -- 'reglamento', 'EEFF nota X', 'CMF', archivo
  source_file    TEXT, file_hash TEXT,
  ingest_run_id  INTEGER REFERENCES ingest_run(id),
  loaded_at      TEXT DEFAULT (datetime('now')),
  superseded_at  TEXT,
  UNIQUE (fondo_key, COALESCE(nemotecnico,''), periodo, tipo, COALESCE(superseded_at,''))
)
```

- `raw_cuota_en_circulacion` se conserva (o se vuelve vista sobre `fact_cuotas` con `tipo='en_circulacion'`).
- `cuotas_emitidas` de la ficha pasa a leerse de aquí (`tipo='emitidas'`, con `fuente` documentada) vía la futura `dim_fondo_ficha`/capa canónica (ROADMAP F1.3).
- Implementar solo dentro de F1.3 (config desde la DB), no como cambio aislado.

## 4. Tests de regresión exigidos antes de cualquier cambio

Golden tests con los valores vigentes validados: valor cuota contable/bursátil por serie, patrimonio, market cap por serie (TRI: cuotas totales × precio de la serie — metodología §9 de `wiki/kpis_noi_cap_rate_apo.md`), DY, y snapshot de la ficha del factsheet. Cualquier refactor de cuotas debe dejar estos tests idénticos.

## 5. Pendiente de validación humana

1. **Confirmar las cifras de `cuotas_emitidas`** (4.000.000 / 1.800.000 / 2.000.000) contra el reglamento interno o CMF de cada fondo — hoy están hardcodeadas sin fuente documentada. No se infirió su significado solo del nombre: la etiqueta del factsheet dice "Cuotas Emitidas" y las magnitudes son coherentes (emitidas ≥ en circulación en los 3 fondos), pero la fuente original no consta en el repo.
2. Confirmar si "emitidas" aquí significa emitidas según reglamento (autorizadas) o efectivamente colocadas — la distinción autorizadas/suscritas/pagadas queda modelada en `fact_cuotas.tipo` para cuando se documente.
3. `raw_capital_suscrito` de Apo tiene 1 sola fila (TRI: 64) — cobertura a completar si el DY de Apo la necesita históricamente.
