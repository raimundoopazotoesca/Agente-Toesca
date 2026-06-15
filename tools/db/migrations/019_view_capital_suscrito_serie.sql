-- Vista: capital suscrito por serie, calculado desde cuotas × valor_cuota_libro / uf
-- Fuente canónica: raw_cuota_en_circulacion_line + raw_valor_cuota_line + fact_uf
-- Deduplicación: MAX(cuotas) por (nemotecnico, fecha) para evitar duplicados de fuentes múltiples

DROP VIEW IF EXISTS v_capital_suscrito_serie;

CREATE VIEW v_capital_suscrito_serie AS
WITH base AS (
    SELECT
        c.nemotecnico,
        c.fondo_key,
        c.fecha,
        c.periodo,
        MAX(c.cuotas)                          AS cuotas,
        v.precio_clp                           AS valor_cuota_clp,
        u.valor_clp                            AS uf_dia
    FROM raw_cuota_en_circulacion_line c
    JOIN raw_valor_cuota_line v
        ON  c.nemotecnico = v.nemotecnico
        AND c.fecha       = v.fecha
        AND v.tipo        = 'contable'
        AND v.superseded_at IS NULL
    JOIN fact_uf u ON u.fecha = c.fecha
    GROUP BY c.nemotecnico, c.fecha, v.precio_clp, u.valor_clp
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
