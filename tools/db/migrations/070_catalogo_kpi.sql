-- 070: catálogo de KPIs con estado de vigencia.
--
-- Hoy no hay forma de decir "este KPI existe pero ya no es canónico". El
-- pipeline lo recalcularía como cualquier otro y el Asistente podría ofrecerlo
-- como indicador vigente.
--
-- Caso que lo motiva: `ltc` y `dscr` tienen 750 y 649 filas calculadas por la
-- skill financiera, pero **ninguna metodología escrita** y **ningún output que
-- los use**. No se borran —sus valores podrían recuperarse junto con el código
-- original de la skill— pero tampoco deben tratarse como indicadores vigentes.
--
-- Estados:
--   vigente     se calcula, se publica, se puede citar
--   legacy      valores históricos conservados; NO se recalcula ni se publica
--               como indicador canónico. Se reactiva solo si aparece un caso de
--               uso real y su metodología se define y valida formalmente.
--   deprecado   reemplazado por otro KPI (se registra cuál en `reemplazado_por`)
--
-- `metodologia` apunta a dónde está escrita la fórmula. NULL significa que
-- depende de recuperar el código de la skill — no que no exista.

CREATE TABLE IF NOT EXISTS dim_kpi (
    kpi             TEXT PRIMARY KEY,
    estado          TEXT NOT NULL DEFAULT 'vigente'
                    CHECK (estado IN ('vigente', 'legacy', 'deprecado')),
    descripcion     TEXT,
    metodologia     TEXT,   -- ruta al documento que define la fórmula
    reemplazado_por TEXT,
    consumidores    TEXT,   -- quién lo usa hoy: factsheet, asistente, …
    nota            TEXT,
    actualizado_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO dim_kpi (kpi, estado, descripcion, metodologia, consumidores, nota) VALUES
  -- ── Legacy: sin metodología escrita y sin consumidores ────────────────────
  ('ltc',  'legacy', 'Loan to cost', NULL, NULL,
   'Sin metodología documentada y sin consumidores. 750 filas conservadas. No recalcular. Podría recuperarse con el código original de la skill real-estate-finance-expert (ROADMAP F0.6).'),
  ('dscr', 'legacy', 'Debt Service Coverage Ratio', NULL, NULL,
   'Sin metodología documentada y sin consumidores. 649 filas conservadas. No recalcular. Ídem ltc.'),

  -- ── Vigentes con metodología escrita ──────────────────────────────────────
  ('dy', 'vigente', 'Dividend yield U12M', 'wiki/kpis_rentabilidad_fondos.md',
   'factsheet', NULL),
  ('dy_amort', 'vigente', 'Dividend yield + amortización', 'wiki/kpis_rentabilidad_fondos.md',
   'factsheet', 'Tiene 3 variantes de receta.'),
  ('tir_bursatil_desde_inicio', 'vigente', 'TIR XIRR bursátil desde el primer aporte',
   'wiki/tir_contable_desde_inicio.md', 'asistente', NULL),
  ('tir_contable_desde_inicio', 'vigente', 'TIR XIRR contable desde el primer aporte',
   'wiki/tir_contable_desde_inicio.md', 'asistente', NULL),
  ('tir_bursatil_u12m', 'vigente', 'TIR bursátil últimos 12 meses',
   'wiki/kpis_rentabilidad_fondos.md', 'asistente', NULL),
  ('tir_contable_u12m', 'vigente', 'TIR contable últimos 12 meses',
   'wiki/kpis_rentabilidad_fondos.md', 'asistente', NULL),
  ('tir_contable_ytd', 'vigente', 'TIR contable YTD anualizada',
   'wiki/kpis_rentabilidad_fondos.md', 'asistente', NULL),
  ('rent_ytd_bursatil', 'vigente', 'Rentabilidad YTD anualizada, bursátil',
   'wiki/kpis_rentabilidad_fondos.md', 'asistente', NULL),
  ('rent_ytd_contable', 'vigente', 'Rentabilidad YTD anualizada, contable',
   'wiki/kpis_rentabilidad_fondos.md', 'asistente', NULL),
  ('noi_mensual', 'vigente', 'NOI mensual por activo', 'wiki/kpis_noi_cap_rate_apo.md',
   'factsheet, asistente', NULL),
  ('ingresos_mensual', 'vigente', 'Ingresos mensuales por activo',
   'wiki/kpis_noi_cap_rate_apo.md', 'factsheet, asistente', NULL),
  ('noi_u12m', 'vigente', 'NOI U12M del fondo', 'wiki/kpis_noi_cap_rate_apo.md',
   'factsheet', NULL),
  ('ingresos_u12m', 'vigente', 'Ingresos U12M del fondo', 'wiki/kpis_noi_cap_rate_apo.md',
   'factsheet', NULL),
  ('m2_vacantes', 'vigente', 'Superficie vacante', NULL, 'factsheet',
   'Receta cdg_vacancia_v1: la fuente es el CDG, en decomiso. Debe recalcularse desde raw_rent_roll_line tras el backfill (ROADMAP F1.6).'),

  -- ── Vigentes CON consumidores pero SIN metodología escrita ────────────────
  -- No pueden quedar congelados: si entra un período nuevo, no hay quién los
  -- calcule. Prioridad de recuperación junto con la skill (ROADMAP F0.6/F7).
  ('ltv', 'vigente', 'Loan to value', NULL, 'factsheet',
   'SIN metodología escrita. Depende de recuperar la skill o de documentarla.'),
  ('duration_deuda', 'vigente', 'Duration de la deuda', NULL, 'factsheet',
   'SIN metodología escrita. Ídem ltv.'),
  ('perfil_vencimiento', 'vigente', 'Perfil de vencimiento de la deuda', NULL, 'factsheet',
   'SIN metodología escrita. Ídem ltv. Tiene 4 variantes.'),
  ('leverage_financiero', 'vigente', 'Leverage financiero', NULL, 'factsheet',
   'SIN metodología escrita. Ídem ltv.');
