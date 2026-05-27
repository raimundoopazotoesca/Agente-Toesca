-- Índices de performance para queries frecuentes del nuevo enfoque DB-centric.

-- NOI: filtra por activo + periodo + flag operacional (es_operacional agregado en 009)
CREATE INDEX IF NOT EXISTS idx_raw_er_activo_noi
    ON raw_er_activo_line(activo_key, periodo, es_operacional);

-- Idempotencia rápida: buscar si file_hash ya fue ingestado
CREATE INDEX IF NOT EXISTS idx_raw_eeff_hash
    ON raw_eeff_line(file_hash);

CREATE INDEX IF NOT EXISTS idx_raw_er_activo_hash
    ON raw_er_activo_line(file_hash);

CREATE INDEX IF NOT EXISTS idx_raw_flujo_hash
    ON raw_flujo_line(file_hash);

-- Queries por cuenta contable (EEFF y ER activo)
CREATE INDEX IF NOT EXISTS idx_raw_eeff_cuenta
    ON raw_eeff_line(cuenta_codigo);

CREATE INDEX IF NOT EXISTS idx_raw_er_cuenta
    ON raw_er_activo_line(cuenta_codigo);

-- Cobertura: qué períodos hay por fondo/activo
CREATE INDEX IF NOT EXISTS idx_raw_eeff_periodo
    ON raw_eeff_line(periodo);

CREATE INDEX IF NOT EXISTS idx_raw_er_periodo
    ON raw_er_activo_line(periodo);
