-- B4: Separar tablas de estado del agente (historial, contexto, kpis por usuario)
-- de la DB de negocio. Ahora viven en memory/agente_state.db.
--
-- Data migrada previamente:
--   historial_chat: 161 filas
--   contexto:        0 filas
--   kpis (legacy):   0 filas
--
-- memory_tools.py refactorizado con STATE_DB_PATH separado de BIZ_DB_PATH.

DROP TABLE IF EXISTS historial_chat;
DROP TABLE IF EXISTS contexto;
DROP TABLE IF EXISTS kpis;
