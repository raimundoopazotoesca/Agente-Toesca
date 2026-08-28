-- 087: reglas internas de ER (contribuciones y seguros), versionadas.
--
-- Confirmado con el usuario 2026-08-28.
--
-- CONTRIBUCIONES Y SEGUROS NO LOS ENTREGA JLL: se manejan internamente. Cuando
-- JLL sí trae el rubro (contribuciones de Apo4501/4700), manda lo interno y el
-- valor de JLL queda como control cruzado. El usuario ya consultó a JLL por la
-- diferencia; respuesta pendiente.
--
-- PARÁMETROS SON DATOS, LA FÓRMULA ES CÓDIGO. `parametros_json` guarda solo
-- valores ({factor, base_clp, frecuencia, uf_convencion}); nunca expresiones
-- evaluables. La aritmética vive en tools/db/er_reglas.py, versionada y testeada.
--
-- REGLAS INMUTABLES. Cambiar una regla NO es un UPDATE de parametros_json: se
-- cierra la fila vigente con vigente_hasta y se inserta una versión nueva. Una
-- regla ya usada para derivar filas de ER no se modifica jamás, porque eso
-- reescribiría el ER retrospectivamente sin dejar rastro. raw_er_activo_line
-- apunta a la versión concreta que usó (ver 088).

CREATE TABLE dim_er_regla_interna (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key      TEXT NOT NULL REFERENCES dim_activo(activo_key),
    cuenta_codigo   TEXT NOT NULL,
    tipo            TEXT NOT NULL
                    CHECK (tipo IN ('formula_contribuciones', 'monto_fijo_uf')),
    parametros_json TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    vigente_desde   TEXT,             -- YYYY-MM inclusive; NULL = desde siempre
    vigente_hasta   TEXT,             -- YYYY-MM inclusive; NULL = vigente
    nota            TEXT,
    loaded_at       TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX uq_er_regla_version
    ON dim_er_regla_interna(activo_key, cuenta_codigo, version);
CREATE INDEX idx_er_regla_lookup
    ON dim_er_regla_interna(activo_key, cuenta_codigo, vigente_desde, vigente_hasta);

-- VIGENCIA RESPALDADA POR EVIDENCIA, no ilimitada. `vigente_desde` se fija
-- donde la regla efectivamente reproduce el ER historico ya cargado; hacia
-- atras los avaluos eran otros y aplicarla seria inventar datos:
--
--   desviacion media de la formula de contribuciones vs ER, por año
--   activo       2021    2022    2023    2024    2025    2026
--   Apo4501     72.3%   42.7%    8.2%    2.2%    1.0%    0.3%
--   Apo4700     74.6%   42.7%    8.2%    2.2%    1.0%    0.3%
--   Apo3001     38.2%   24.1%    2.7%    3.1%    6.2%    7.7%
--   Boulevard   55.9%   34.0%    9.0%    5.4%    1.0%    0.5%
--   Torre A     66.0%   38.3%   11.3%    7.2%    1.0%    0.6%
--
-- De ahi vigente_desde='2025-01' para contribuciones. Para los seguros, el
-- monto sembrado coincide EXACTO con el ER en 2024-01..2026-06 (30 periodos
-- consecutivos) y difiere antes, de ahi vigente_desde='2024-01'.

-- Contribuciones: base_clp se suma, se divide por `divisor` (trimestral -> 3) y
-- por la UF del período, y se pondera por `factor`. Los CLP son los avalúos que
-- entregó el usuario 2026-08-28; actualizar uno es insertar version=2, no editar.
--
-- Validación contra raw_er_activo_line con UF del día 5:
--   Apo4501  -1.419 vs -1.431 (-0,9%)    Boulevard -608 vs -621 (-2,0%)
--   Apo4700    -473 vs   -477 (-0,9%)    Torre A -1.230 vs -1.257 (-2,1%)
--   Apo3001    -208 vs   -227 (-8,4%)  <-- fuera de umbral, ver nota
INSERT INTO dim_er_regla_interna
    (activo_key, cuenta_codigo, tipo, parametros_json, version, vigente_desde, nota)
VALUES
    ('Apo4501', 'APO_CONTRIB', 'formula_contribuciones',
     '{"factor": 0.75, "base_clp": [-165941575, -62167695], "divisor": 3, "uf_convencion": "dia_5"}',
     1, '2025-01', 'Avalúo combinado Apo4501+4700, split 75%. Confirmado 2026-08-28.'),
    ('Apo4700', 'APO_CONTRIB', 'formula_contribuciones',
     '{"factor": 0.25, "base_clp": [-165941575, -62167695], "divisor": 3, "uf_convencion": "dia_5"}',
     1, '2025-01', 'Avalúo combinado Apo4501+4700, split 25%. Confirmado 2026-08-28.'),
    ('Apo3001', 'APO3001_CONTRIB_SOBRETASA', 'formula_contribuciones',
     '{"factor": 1.0, "base_clp": [-19740468, -5306357], "divisor": 3, "uf_convencion": "dia_5"}',
     1, '2025-01', 'Contribución + sobretasa. Se desvía 6-8% del ER incluso dentro de su vigencia: revisar antes de usar en producción.'),
    ('Boulevard', 'PT_CONTRIB', 'formula_contribuciones',
     '{"factor": 1.0, "base_clp": [-54388202, -19886599], "divisor": 3, "uf_convencion": "dia_5"}',
     1, '2025-01', 'Confirmado 2026-08-28.'),
    ('Torre A', 'PT_CONTRIB', 'formula_contribuciones',
     '{"factor": 1.0, "base_clp": [-110660042, -39543299], "divisor": 3, "uf_convencion": "dia_5"}',
     1, '2025-01', 'Confirmado 2026-08-28.');

-- Seguros: monto fijo UF/mes. Apo4501 y Apo4700 no tienen seguros internos
-- (su última data es de 2019 y en cero). Apo3001 lo entrega JLL, pero la
-- planilla v2 actual no trae rubro de seguros: pendiente pedírselo.
INSERT INTO dim_er_regla_interna
    (activo_key, cuenta_codigo, tipo, parametros_json, version, vigente_desde, nota)
VALUES
    ('Boulevard', 'PT_SEG', 'monto_fijo_uf',
     '{"monto_uf": -63.46}', 1, '2024-01', 'Confirmado 2026-08-28; coincide exacto con el ER desde 2024-01.'),
    ('Torre A', 'PT_SEG', 'monto_fijo_uf',
     '{"monto_uf": -173.464166666667}', 1, '2024-01', 'Confirmado 2026-08-28; coincide exacto con el ER desde 2024-01.');
