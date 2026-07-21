-- Agrega periodo_declarado y fecha_publicacion a ingest_run, declarados a mano
-- por el usuario en la pantalla de ingesta EEFF (web/ingesta.html) para poder
-- auditar/cruzar contra los periodos que el JSON de ChatGPT realmente trae.
ALTER TABLE ingest_run ADD COLUMN periodo_declarado TEXT;
ALTER TABLE ingest_run ADD COLUMN fecha_publicacion TEXT;
