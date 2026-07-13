-- D1: Normaliza formato de loaded_at en fact_adquisicion y fact_tasacion.
-- El resto de tablas ya usa 'YYYY-MM-DD HH:MM:SS' (via datetime('now')).
-- Solo estas dos usaban ISO con 'T' (via strftime('%Y-%m-%dT%H:%M:%S', 'now')).
--
-- Los DEFAULTs siguen como estaban (SQLite no permite ALTER DEFAULT sin recrear tabla),
-- por lo que INSERTs nuevos en esas dos tablas seguirán generando 'T' hasta que
-- se recreen. La documentación en CLAUDE.md registra la excepción.

UPDATE fact_adquisicion SET loaded_at = replace(loaded_at, 'T', ' ') WHERE loaded_at LIKE '%T%';
UPDATE fact_tasacion    SET loaded_at = replace(loaded_at, 'T', ' ') WHERE loaded_at LIKE '%T%';
