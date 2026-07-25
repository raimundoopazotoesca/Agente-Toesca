"""Repo de audit: ingest_run / publish_run."""
import sqlite3


def start_ingest_run(
    conn: sqlite3.Connection,
    tool: str,
    source_file: str | None,
    file_hash: str | None,
) -> int:
    cur = conn.execute(
        """INSERT INTO ingest_run (tool, source_file, file_hash, status)
           VALUES (?, ?, ?, 'started')""",
        (tool, source_file, file_hash),
    )
    conn.commit()
    return cur.lastrowid


def finish_ingest_run(
    conn: sqlite3.Connection,
    run_id: int,
    rows_in: int,
    rows_loaded: int,
    status: str = "ok",
) -> None:
    conn.execute(
        """UPDATE ingest_run
              SET rows_in = ?, rows_loaded = ?, status = ?, ended_at = datetime('now')
            WHERE id = ?""",
        (rows_in, rows_loaded, status, run_id),
    )
    conn.commit()


def fail_ingest_run(conn: sqlite3.Connection, run_id: int, error: str) -> None:
    conn.execute(
        """UPDATE ingest_run
              SET status = 'failed', error = ?, ended_at = datetime('now')
            WHERE id = ?""",
        (error, run_id),
    )
    conn.commit()

# Nota: `publish_run` nunca se creó en producción y sus helpers fallaban con
# "no such table". Se eliminaron junto con la tabla al construir el baseline
# (ver tools/db/baseline.sql).
