-- Migration 037: eliminar raw_valor_cuota_line, datos a sus tablas canónicas
-- tipo='contable' → raw_valor_cuota_contable_line (nueva tabla)
-- tipo='bursatil' → raw_valor_cuota_bursatil_line (ya existe, completar con rows faltantes)

-- 1. Crear tabla contable
CREATE TABLE IF NOT EXISTS raw_valor_cuota_contable_line (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key     TEXT,
    nemotecnico   TEXT NOT NULL,
    fecha         TEXT NOT NULL,
    precio_clp    REAL,
    precio_uf     REAL,
    uf_dia        REAL,
    cuotas        REAL,
    periodo       TEXT,
    source_file   TEXT,
    file_hash     TEXT,
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT,
    UNIQUE(nemotecnico, fecha, source_file)
);
CREATE INDEX IF NOT EXISTS idx_raw_vc_contable_nemo_fecha
    ON raw_valor_cuota_contable_line(nemotecnico, fecha);

-- 2. Copiar rows contable
INSERT OR IGNORE INTO raw_valor_cuota_contable_line
    (fondo_key, nemotecnico, fecha, precio_clp, precio_uf, uf_dia, cuotas,
     periodo, source_file, file_hash, loaded_at, superseded_at)
SELECT fondo_key, nemotecnico, fecha, precio_clp, precio_uf, uf_dia, cuotas,
       periodo, source_file, file_hash, loaded_at, superseded_at
FROM raw_valor_cuota_line
WHERE tipo = 'contable';

-- 3. Copiar rows bursatil faltantes a raw_valor_cuota_bursatil_line
INSERT OR IGNORE INTO raw_valor_cuota_bursatil_line
    (nemotecnico, fecha, precio_clp, uf_dia, precio_uf, n_cuotas, patrimonio_bursatil_uf, fuente, loaded_at)
SELECT
    v.nemotecnico,
    v.fecha,
    v.precio_clp,
    v.uf_dia,
    v.precio_uf,
    (SELECT cuotas FROM raw_cuota_en_circulacion_line c
     WHERE c.nemotecnico = v.nemotecnico AND c.fecha <= v.fecha
     ORDER BY c.fecha DESC LIMIT 1),
    v.precio_uf * (SELECT cuotas FROM raw_cuota_en_circulacion_line c
                   WHERE c.nemotecnico = v.nemotecnico AND c.fecha <= v.fecha
                   ORDER BY c.fecha DESC LIMIT 1),
    'cdg_historico',
    v.loaded_at
FROM raw_valor_cuota_line v
WHERE v.tipo = 'bursatil';

-- 4. Actualizar views afectadas
DROP VIEW IF EXISTS fact_uf;
CREATE VIEW fact_uf AS
SELECT DISTINCT fecha, uf_dia AS valor
FROM raw_valor_cuota_contable_line
WHERE uf_dia IS NOT NULL
ORDER BY fecha;

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
    JOIN raw_valor_cuota_contable_line v
        ON  c.nemotecnico = v.nemotecnico
        AND c.fecha       = v.fecha
        AND v.superseded_at IS NULL
    WHERE c.superseded_at IS NULL
    GROUP BY c.nemotecnico, c.fondo_key, c.fecha, c.periodo,
             v.precio_clp, v.uf_dia
),
cs AS (
    SELECT nemotecnico, MAX(capital_suscrito_uf) AS capital_suscrito_uf
    FROM raw_capital_suscrito_line
    GROUP BY nemotecnico
)
SELECT
    b.nemotecnico,
    b.fondo_key,
    b.fecha,
    b.periodo,
    b.cuotas,
    b.valor_cuota_clp,
    b.uf_dia,
    ROUND(b.cuotas * b.valor_cuota_clp / NULLIF(b.uf_dia, 0), 4) AS patrimonio_contable_uf,
    cs.capital_suscrito_uf
FROM base b
LEFT JOIN cs ON cs.nemotecnico = b.nemotecnico;

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
        MAX(precio_uf)  AS valor_libro_uf,
        MAX(precio_clp) AS valor_libro_clp,
        MAX(uf_dia)     AS uf_dia,
        MAX(cuotas)     AS cuotas
    FROM raw_valor_cuota_contable_line
    WHERE superseded_at IS NULL
    GROUP BY fondo_key, nemotecnico, periodo
),
div_acc AS (
    SELECT nemotecnico,
           SUM(monto_uf_cuota) AS divs_acum_uf
    FROM raw_dividendo_line
    WHERE superseded_at IS NULL
    GROUP BY nemotecnico
)
SELECT
    v.fondo_key,
    v.nemotecnico,
    v.periodo,
    v.valor_libro_uf,
    v.valor_libro_clp,
    v.uf_dia,
    v.cuotas,
    ROUND(v.cuotas * v.valor_libro_uf, 2) AS patrimonio_libro_uf,
    cs.capital_suscrito_uf,
    da.divs_acum_uf
FROM val v
LEFT JOIN cs_hist cs ON cs.nemotecnico = v.nemotecnico
LEFT JOIN div_acc da ON da.nemotecnico = v.nemotecnico;

-- 5. Drop tabla original
DROP TABLE raw_valor_cuota_line;
