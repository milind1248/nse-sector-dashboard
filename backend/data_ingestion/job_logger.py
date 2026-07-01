"""
Shared job run logging utility.
Records start/finish of every scheduled and admin-triggered pipeline run
into the job_run_log SQLite table.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from config import DB_PATH as _DB_PATH


def _db():
    return sqlite3.connect(_DB_PATH)


def ensure_table():
    con = _db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS job_run_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id       TEXT    NOT NULL,
            job_name     TEXT    NOT NULL,
            triggered_by TEXT    NOT NULL DEFAULT 'scheduler',
            started_at   TEXT    NOT NULL,
            finished_at  TEXT,
            status       TEXT    NOT NULL DEFAULT 'running',
            records_done INTEGER DEFAULT 0,
            error_msg    TEXT
        )
    """)
    con.commit()
    con.close()


def purge_old_logs(days: int = 7):
    """Delete job_run_log rows older than `days` days."""
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    con = _db()
    con.execute("DELETE FROM job_run_log WHERE started_at < ?", (cutoff,))
    con.commit()
    con.close()


ensure_table()


def log_start(job_id: str, job_name: str, triggered_by: str = "scheduler") -> int:
    """Insert a 'running' row and return its row id."""
    started = datetime.utcnow().isoformat()
    con = _db()
    cur = con.execute(
        "INSERT INTO job_run_log (job_id, job_name, triggered_by, started_at, status) "
        "VALUES (?, ?, ?, ?, 'running')",
        (job_id, job_name, triggered_by, started),
    )
    row_id = cur.lastrowid
    con.commit()
    con.close()
    return row_id


def log_finish(row_id: int, status: str, records_done: int = 0, error_msg: str | None = None):
    """Update the row when a job finishes."""
    finished = datetime.utcnow().isoformat()
    con = _db()
    con.execute(
        "UPDATE job_run_log SET finished_at=?, status=?, records_done=?, error_msg=? WHERE id=?",
        (finished, status, records_done, error_msg, row_id),
    )
    con.commit()
    con.close()
