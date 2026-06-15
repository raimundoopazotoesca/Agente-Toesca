-- Migration 028: fix v_capital_suscrito_serie (sin fact_uf) + extiende v_serie_patrimonio para PT

-- 1. v_capital_suscrito_serie: usa raw_valor_cuota_line.uf_dia en vez de fact_uf (que no existe en esta DB)
DROP VIEW IF EXISTS v_capital_suscrito_serie;
CREATE VIEW v_capital_suscrito_serie AS
WITH base AS (
    SELECT
        c.nemotecnico,
        c.fondo_key,
        c.fecha,
        c.periodo,
        MAX(c.cuotas)      AS cuotas,
        v.precio_clp       AS valor_cuota_clp,
        v.uf_dia           AS uf_dia
    FROM raw_cuota_en_circulacion_line c
    JOIN raw_valor_cuota_line v
        ON  c.nemotecnico = v.nemotecnico
        AND c.fecha       = v.fecha
        AND v.tipo        = 'contable'
        AND v.superseded_at IS NULL
    GROUP BY c.nemotecnico, c.fondo_key, c.fecha, v.precio_clp, v.uf_dia
)
SELECT
    nemotecnico,
    fondo_key,
    fecha,
    periodo,
    cuotas,
    valor_cuota_clp,
    uf_dia,
    ROUND(cuotas * valor_cuota_clp)           AS capital_suscrito_clp,
    ROUND(cuotas * valor_cuota_clp / uf_dia)  AS capital_suscrito_uf
FROM base;

-- 2. v_serie_patrimonio: extiende para PT usando v_capital_suscrito_serie como fallback
--    TRI sigue usando raw_capital_suscrito_line (LOCF); PT usa cuotas × valor_cuota (patrimonio libro)
DROP VIEW IF EXISTS v_serie_patrimonio;
CREATE VIEW v_serie_patrimonio AS
WITH
cs_hist AS (
    SELECT nemotecnico, MAX(capital_suscrito_uf) AS capital_suscrito_uf
    FROM raw_capital_suscrito_line
    GROUP BY nemotecnico
),
val AS (
    SELECT
        fondo_key,
        nemotecnico,
        periodo,
        MAX(CASE WHEN tipo = 'contable' THEN precio_uf  END) AS valor_libro_uf,
        MAX(CASE WHEN tipo = 'contable' THEN precio_clp END) AS valor_libro_clp,
        MAX(CASE WHEN tipo = 'bursatil' THEN precio_uf  END) AS valor_bursatil_uf,
        MAX(CASE WHEN tipo = 'bursatil' THEN precio_clp END) AS valor_bursatil_clp,
        MAX(cuotas)                                           AS cuotas
    FROM raw_valor_cuota_line
    WHERE superseded_at IS NULL
    GROUP BY fondo_key, nemotecnico, periodo
)
SELECT
    v.fondo_key,
    v.nemotecnico,
    v.periodo,
    v.cuotas,
    v.valor_libro_uf,
    v.valor_libro_clp,
    v.valor_bursatil_uf,
    v.valor_bursatil_clp,
    v.valor_libro_uf   * v.cuotas        AS patrimonio_libro_uf,
    v.valor_libro_clp  * v.cuotas / 1e6  AS patrimonio_libro_mclp,
    v.valor_bursatil_uf * v.cuotas       AS patrimonio_bursatil_uf,
    v.valor_bursatil_clp * v.cuotas / 1e6 AS patrimonio_bursatil_mclp,
    -- Capital suscrito: histórico CDG para TRI; cuotas×vc (≈patrimonio libro) para PT
    COALESCE(cs_hist.capital_suscrito_uf, cs_calc.capital_suscrito_uf) AS capital_suscrito_uf
FROM val v
LEFT JOIN cs_hist   ON cs_hist.nemotecnico = v.nemotecnico
LEFT JOIN v_capital_suscrito_serie cs_calc
       ON cs_calc.nemotecnico = v.nemotecnico
      AND cs_calc.periodo     = v.periodo
ORDER BY v.fondo_key, v.nemotecnico, v.periodo;
