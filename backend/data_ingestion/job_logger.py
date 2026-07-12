"""
Shared job run logging utility.
Records start/finish of every scheduled and admin-triggered pipeline run
into the job_run_log table (Supabase/Postgres) AND the rotating app.log file.
"""
import logging
from datetime import datetime

from backend.storage.db import get_conn

_log = logging.getLogger(__name__)


def _db():
    return get_conn()


def purge_old_logs(days: int = 7):
    """Delete job_run_log rows older than `days` days."""
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    con = _db()
    con.execute("DELETE FROM job_run_log WHERE started_at < %s", (cutoff,))
    con.commit()
    con.close()


def log_start(job_id: str, job_name: str, triggered_by: str = "scheduler") -> int:
    """Insert a 'running' row, log to file, and return its row id."""
    started = datetime.utcnow()
    _log.info("JOB START  | %-30s | triggered_by=%-9s | %s", job_id, triggered_by, started)
    con = _db()
    cur = con.execute(
        "INSERT INTO job_run_log (job_id, job_name, triggered_by, started_at, status) "
        "VALUES (%s, %s, %s, %s, 'running') RETURNING id",
        (job_id, job_name, triggered_by, started),
    )
    row_id = cur.fetchone()[0]
    con.commit()
    con.close()
    return row_id


def log_finish(row_id: int, status: str, records_done: int = 0, error_msg: str | None = None):
    """Update the row when a job finishes and log result to file."""
    finished = datetime.utcnow()
    if status == "success":
        _log.info(
            "JOB FINISH | row=%-4s | status=%-8s | records=%s | %s",
            row_id, status, records_done, finished,
        )
    else:
        _log.error(
            "JOB FINISH | row=%-4s | status=%-8s | error=%s | %s",
            row_id, status, error_msg or "", finished,
        )
    con = _db()
    con.execute(
        "UPDATE job_run_log SET finished_at=%s, status=%s, records_done=%s, error_msg=%s WHERE id=%s",
        (finished, status, records_done, error_msg, row_id),
    )
    con.commit()
    con.close()
