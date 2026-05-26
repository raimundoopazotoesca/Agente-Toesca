# Handoff — Migración Excel → DB del agente

**Fecha:** 2026-05-25
**Estado:** Fases 0, 1, 2, 4 avanzadas. DB poblada y consultable. Falta cerrar split de categorías NOI y pulir.

Spec: `docs/superpowers/specs/2026-05-25-db-migration-design.md`
Plan Fase 0: `docs/superpowers/plans/2026-05-25-db-fase0-esqueleto.md`
Mapa de la DB: `wiki/db.md` (LEER ESTO PRIMERO)

## Qué está hecho

DB SQLite en `memory/agente_toesca.db`, capa de acceso en `tools/db/` (repos por dominio, nunca SQL crudo fuera de ahí). Migraciones en `tools/db/migrations/` se aplican solas al importar `tools/memory_tools.py`.

**Escritura (dual-write, best-effort, nunca rompe el Excel):**
- precios cuota → `fact_precio_cuota` (`web_bursatil_tools`)
- valor cuota libro EEFF → `derived_kpi` (`eeff_tools`)
- ER Viña/Curicó → `raw_er_activo_line` (`noi_tools`)
- flujos INMOSA → `raw_flujo_line` (`noi_tools`)
- rent roll → `raw_rent_roll_line` (`rentroll_tools.consolidar_rent_rolls`)
- vacancia → `derived_kpi` kpi='m2_vacantes' (`vacancia_tools.actualizar_vacancia`)

**Backfill histórico:** `python -X utf8 -m tools.db.backfill [dominio...]`
Dominios: rent_roll, er, inmosa, uf, eeff, precios, dividendos, vacancia, noi.
Ya poblado: rent_roll 10k (2025-09+), er 400, flujo 46, uf 5182 (2012+), precios 100,
dividendos 108, vacancia ~1000 (2018+), noi 642 (2018+).

**Lectura (tools registradas en `tools/registry.py`, siempre disponibles):**
`consultar_db_cobertura`, `consultar_db_kpi`, `consultar_db_precio`, `consultar_db_rent_roll`,
`consultar_db_er`, `consultar_db_flujo`, `consultar_db_dividendos`, `consultar_noi`, `generar_dashboard`.

**Dashboard:** `python -X utf8 -m tools.db.dashboard` → `dashboard.html` (abrir en navegador).
Cobertura por activo/período, gaps, series de mercado, vacancia, NOI por activo/categoría, KPIs.

**NOI:** `tools/noi_query.py` (tool `consultar_noi`). NOI mensual real al 100% por activo
(desde sección "NOI Real" del NOI- RCSD). Calcula anual, anualizado (YTD real + promedio
histórico de meses faltantes), U12M, MoM, YoY; por activo/fondo/categoria/total; 100% o ponderado.
Participación y categoría en `dim_activo` (migración 007). Machalí EXCLUIDO (ya no existe).

## EN PROGRESO al cerrar la sesión (TERMINAR ESTO)

~~**Split de PT para la categoría "Comercial".**~~ ✅ CERRADO 2026-05-25.

**Fix adicional aplicado:** `backfill_noi` ahora detecta el período de cierre real del CDG
leyendo la última fila con valor positivo de PT (fila 382 del NOI- RCSD), en vez de usar
`date.today()`. Esto evita guardar proyecciones de meses futuros que el CDG incluye para
activos como Apo3001, Sucden o Viña. Commit: `6d53dca`.

**Pasos ejecutados:**
1. ✅ Backfill NOI corrido — split PT Torre A / PT Boulevard escritos en DB (98 meses, 2018-01..2026-02)
2. ✅ 8 proyecciones contaminadas (> 2026-02) eliminadas de derived_kpi
3. ✅ `consultar_noi('categoria','Comercial')` y `consultar_noi('categoria','Oficinas')` devuelven datos limpios
4. ✅ Dashboard regenerado
5. ✅ 91/91 tests pasan
6. ✅ Commit + push. Actualizar `wiki/db.md` (quitar "PENDIENTE split PT").

## Siguiente prioridad: derivar TODO desde raw (no del CDG consolidado)

Tanto vacancia como NOI deben computarse desde los datos raw que ya están en la DB, no leerse del
CDG. Esto cierra el camino hacia "reemplazar el CDG" ([[vision-reemplazar-cdg]]).

**Caching inteligente** ([[noi-desde-eerr-y-caching-inteligente]]):
- Resultados baratos (sumas, agregaciones, anual/anualizado/U12M/MoM/YoY) → recalcular al pedirlo.
- Resultados costosos sobre meses cerrados → persistir en `derived_kpi` con recipe propia.
- Resultados sobre el mes en curso → recalcular (input puede cambiar).
- Invalidación: comparar `computed_at` del derived contra `loaded_at` del raw fuente.

### Vacancia desde rent roll

Decidido 2026-05-25: la vacancia se debe **calcular desde `raw_rent_roll_line`**, no leer de la hoja
"Vacancia" del CDG. Ver memoria `feedback_vacancia_desde_rr.md`. Implementar:
- `tools/vacancia_query.py` con `compute_vacancia(periodo)` que cuenta m² vacantes/totales por segmento.
- Marcador: `arrendatario` contiene "vacante" (insensible a mayúsculas).
- Sub-segmentación: PT (Torre A/Locales/Bodegas), Apoquindo (4501/4700) — usar las columnas Activo1/
  Activo2/Detalle del rent roll JLL (ver `rentroll_tools._read_source_data`).
- Almacenar como `derived_kpi` kpi='m2_vacantes' recipe='rr_calculado_v1'.
- Exponer tool `consultar_vacancia_calculada` y agregarla al dashboard como vista alternativa.
- Mantener `backfill_vacancia` actual como legacy/cross-check, no fuente primaria.

### NOI desde EERR (no del NOI-RCSD)

`compute_noi_activo(activo, periodo)` debe sumar líneas de `raw_er_activo_line` y `raw_flujo_line`:
- NOI = Σ (monto × signo) de cuentas con `tipo_eeff IN ('ingreso_operacional', 'gasto_operacional')`.
- Requiere poblar `dim_cuenta.tipo_eeff` y `dim_cuenta.signo` (hoy vacíos para la mayoría).
- Recipe nueva: `eerr_calculado_v1`. Mantener `cdg_noi_real_v1` como cross-check legacy.
- Política de caching: persistir si el mes está cerrado (input estable); recalcular si mes en curso
  o si el derived es barato (anual = suma de mensuales).

Paso preparatorio: poblar `dim_cuenta` con la clasificación contable. Cada `cuenta_codigo` ↔ `tipo_eeff`
y `signo`. Esto necesita el plan de cuentas del cliente — pedírselo o derivar de los EEFF (cuentas que
empiezan con "(+) Ingresos..." y "(-) Gastos...").

## Pendientes / gaps conocidos (en `wiki/db.md`)
- NOI vs Resumen NOI no reconcilian por factor simple (se usó NOI- RCSD Real como fuente al 100%, verificado con Viña 100% y Apoquindo ×0.3). Reconciliar con Resumen NOI queda pendiente si se necesita.
- EEFF valor cuota: extracción regex parcial (a veces no captura serie I).
- INMOSA marzo "Senior Assist": estructura distinta, lo cubre el flujo en vivo.
- RR noviembre 2025: hoja 'Rent Roll' vacía.
- dividendos Apoquindo van a derived_kpi (sin nemotécnico).

## Convenciones críticas
- CDG carga lento (~12s, 87 hojas) → comandos se auto-mandan a background; esperar notificación.
- En `read_only`, NUNCA usar `ws.cell(row,col)` (O(n) por llamada, cuelga con max_column=16384).
  Iterar `iter_rows(min_row, max_row)` UNA vez e indexar tuplas.
- Usar `python -X utf8` siempre (consola cp1252 rompe con tildes/flechas).
- `dashboard.html`, `memory/backups/*.db`, `.pytest_cache/` están en `.gitignore`.
- Toda función de dual-write/backfill es best-effort: nunca debe romper el flujo de Excel.
