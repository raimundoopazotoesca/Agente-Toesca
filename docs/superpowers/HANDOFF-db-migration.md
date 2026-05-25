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

**Split de PT para la categoría "Comercial".** Confirmado por el usuario: el "NOI CDC"
(Inmobiliaria Centro de Convenciones, fila 388 del NOI- RCSD) = "Boulevard" = parte comercial de PT.
PT(382) ≈ Torre A(387) + CDC(388) verificado (dif <0,04%).

Cambios YA escritos en código (commit pendiente de verificación):
- `tools/db/backfill.py`: `_NOI_SPLIT_ROWS` = {PT Torre A:387, PT Boulevard:388}, recipe `cdg_noi_split_v1`.
  `backfill_noi` ahora guarda también los splits.
- `tools/noi_query.py`: `_CATEGORIA_FUENTE` define categorías por fuentes (Oficinas usa PT Torre A;
  Comercial = Centros Comerciales + PT Boulevard). `_activos_de` filtra recipe real para que
  fondo/total NO dupliquen PT. serie_mensual(categoria) usa el mapa.
- `tools/db/dashboard.py`: categorías del dashboard usan el mismo mapa.

**Pasos para cerrar (en orden):**
1. Correr el backfill del split (escribe PT Torre A / PT Boulevard a la DB):
   `python -X utf8 -m tools.db.backfill noi`
   Luego borrar proyecciones futuras: `DELETE FROM derived_kpi WHERE kpi='noi_mensual' AND periodo > '<YYYY-MM actual>'`
   (el backfill_noi ya topa al mes actual, pero verificar).
2. Verificar: `consultar_noi('categoria','Comercial')` y `consultar_noi('categoria','Oficinas')` devuelven datos;
   `consultar_noi('activo','PT')` ≈ Oficinas-PT + Comercial-PT.
3. Regenerar dashboard: `python -X utf8 -m tools.db.dashboard`.
4. Correr suite: `python -m pytest tests/db/ -q` (deben pasar 89; agregar tests del split en
   `tests/db/test_noi_query.py` para 'Comercial' y que fondo/total no dupliquen PT).
5. Commit + push. Actualizar `wiki/db.md` (quitar el "PENDIENTE split PT" de la sección noi).

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
