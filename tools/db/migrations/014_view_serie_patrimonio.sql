-- Migration 014: vista v_serie_patrimonio
-- Calcula valor libro, bursátil, patrimonio libro/bursátil y capital suscrito
-- por serie (A/C/I) para cualquier período, sin depender del CDG.
-- Capital suscrito usa LOCF: último valor conocido (CDG hasta 2019, EEFF PDF en adelante).

DROP VIEW IF EXISTS v_serie_patrimonio;

CREATE VIEW v_serie_patrimonio AS
WITH
-- Capital suscrito LOCF: MAX global = último estado conocido
cs_last AS (
    SELECT nemotecnico, MAX(capital_suscrito_uf) AS capital_suscrito_uf
    FROM raw_capital_suscrito_line
    GROUP BY nemotecnico
),
-- Pivot valor_cuota: contable y bursatil en la misma fila
val AS (
    SELECT
        nemotecnico,
        periodo,
        MAX(CASE WHEN tipo = 'contable' THEN precio_uf END)   AS valor_libro_uf,
        MAX(CASE WHEN tipo = 'contable' THEN precio_clp END)  AS valor_libro_clp,
        MAX(CASE WHEN tipo = 'bursatil' THEN precio_uf END)   AS valor_bursatil_uf,
        MAX(CASE WHEN tipo = 'bursatil' THEN precio_clp END)  AS valor_bursatil_clp,
        MAX(cuotas)                                            AS cuotas
    FROM raw_valor_cuota_line
    WHERE superseded_at IS NULL
    GROUP BY nemotecnico, periodo
)
SELECT
    v.nemotecnico,
    v.periodo,
    v.cuotas,
    -- Valor por cuota
    v.valor_libro_uf                             AS valor_libro_uf,
    v.valor_libro_clp                            AS valor_libro_clp,
    v.valor_bursatil_uf                          AS valor_bursatil_uf,
    v.valor_bursatil_clp                         AS valor_bursatil_clp,
    -- Patrimonios totales
    v.valor_libro_uf   * v.cuotas               AS patrimonio_libro_uf,
    v.valor_libro_clp  * v.cuotas / 1e6         AS patrimonio_libro_mclp,
    v.valor_bursatil_uf * v.cuotas              AS patrimonio_bursatil_uf,
    v.valor_bursatil_clp * v.cuotas / 1e6       AS patrimonio_bursatil_mclp,
    -- Capital suscrito (LOCF desde CDG/EEFF)
    cs.capital_suscrito_uf
FROM val v
LEFT JOIN cs_last cs ON cs.nemotecnico = v.nemotecnico
ORDER BY v.nemotecnico, v.periodo;
