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


def start_publish_run(
    conn: sqlite3.Connection,
    tool: str,
    target_excel: str,
    target_sheet: str,
    periodo: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO publish_run (tool, target_excel, target_sheet, periodo, status)
           VALUES (?, ?, ?, ?, 'started')""",
        (tool, target_excel, target_sheet, periodo),
    )
    conn.commit()
    return cur.lastrowid


def finish_publish_run(
    conn: sqlite3.Connection,
    run_id: int,
    rows_written: int,
    status: str = "ok",
) -> None:
    conn.execute(
        """UPDATE publish_run
              SET rows_written = ?, status = ?, ended_at = datetime('now')
            WHERE id = ?""",
        (rows_written, status, run_id),
    )
    conn.commit()


def fail_publish_run(conn: sqlite3.Connection, run_id: int, error: str) -> None:
    conn.execute(
        """UPDATE publish_run
              SET status = 'failed', error = ?, ended_at = datetime('now')
            WHERE id = ?""",
        (error, run_id),
    )
    conn.commit()
