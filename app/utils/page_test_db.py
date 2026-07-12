"""Page test result storage — page_test_log table (Supabase/Postgres)."""
import json
import logging
from datetime import datetime, timezone

from backend.storage.db import get_conn

_log = logging.getLogger(__name__)


def _db():
    return get_conn()


def store_test_results(run_id: int, results: list[dict]) -> None:
    """Insert one row per page for a given run_id."""
    now = datetime.now(timezone.utc)
    con = _db()
    for r in results:
        con.execute(
            "INSERT INTO page_test_log "
            "(run_id, page_name, page_file, status, load_time_s, tabs_count, errors_json, tested_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                run_id,
                r["page"],
                r["file"],
                r["status"],
                r.get("elapsed"),
                r.get("tabs", 0),
                json.dumps(r.get("errors", [])),
                now,
            ),
        )
    con.commit()
    con.close()
    _log.info("Stored %d page test results for run_id=%s", len(results), run_id)


def load_latest_run() -> list[dict]:
    """Return all page rows from the most recent run, or empty list."""
    try:
        con = _db()
        run_id_row = con.execute(
            "SELECT run_id FROM page_test_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not run_id_row:
            con.close()
            return []
        run_id = run_id_row[0]
        rows = con.execute(
            "SELECT page_name, page_file, status, load_time_s, tabs_count, errors_json, tested_at "
            "FROM page_test_log WHERE run_id = %s ORDER BY id",
            (run_id,),
        ).fetchall()
        con.close()
        return [
            {
                "page":    row[0],
                "file":    row[1],
                "status":  row[2],
                "elapsed": row[3],
                "tabs":    row[4],
                "errors":  json.loads(row[5] or "[]"),
                "tested_at": str(row[6]),
            }
            for row in rows
        ]
    except Exception as e:
        _log.error("load_latest_run failed: %s", e)
        return []
