-- Audit: trazabilidad de cargas y publicaciones.

CREATE TABLE ingest_run (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tool          TEXT NOT NULL,
    source_file   TEXT,
    file_hash     TEXT,
    rows_in       INTEGER,
    rows_loaded   INTEGER,
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at      TEXT,
    status        TEXT NOT NULL DEFAULT 'started',
    error         TEXT
);

CREATE INDEX idx_ingest_run_hash ON ingest_run(file_hash);

CREATE TABLE publish_run (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tool            TEXT NOT NULL,
    target_excel    TEXT,
    target_sheet    TEXT,
    periodo         TEXT,
    rows_written    INTEGER,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at        TEXT,
    status          TEXT NOT NULL DEFAULT 'started',
    error           TEXT
);
