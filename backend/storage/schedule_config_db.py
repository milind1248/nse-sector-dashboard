"""
Supabase (Postgres) persistence for scheduler job times. Schema lives in
scripts/supabase_schema.sql; this module only does CRUD against the
already-created `schedule_config` table.

Replaces data/schedule_config.json: that file lived inside the git working
tree, so any edit made via the Admin page while running on Streamlit Cloud
was wiped out on the next deploy (Cloud's filesystem rebuilds fresh from git
on every push) — a DB row survives that rebuild.
"""
from datetime import datetime

from backend.storage.db import get_conn

_DEFAULTS = {
    "sector_snapshot":       {"hour": 18, "minute": 0},
    "stock_snapshot":        {"hour": 18, "minute": 30},
    "smart_money":           {"hour": 19, "minute": 0},
    "market_pulse_snapshot": {"hour": 20, "minute": 0},
    "ai_scan_daily":         {"hour": 21, "minute": 0},
    "gann_daily":            {"hour": 21, "minute": 30},
    "nsdl_sync":             {"hour": 17, "minute": 30},
    "sector_factsheet_sync": {"hour": 17, "minute": 45},
    "bulk_deals_daily":      {"hour": 18, "minute": 45},
}


def get_schedule_config() -> dict:
    """Returns {job_id: {"hour": int, "minute": int}}. Falls back to the
    hardcoded defaults if the table is empty or unreachable."""
    try:
        con = get_conn()
        rows = con.execute("SELECT job_id, hour, minute FROM schedule_config").fetchall()
        con.close()
    except Exception:
        return dict(_DEFAULTS)
    if not rows:
        return dict(_DEFAULTS)
    cfg = {job_id: {"hour": hour, "minute": minute} for job_id, hour, minute in rows}
    for job_id, times in _DEFAULTS.items():
        cfg.setdefault(job_id, times)
    return cfg


def set_job_time(job_id: str, hour: int, minute: int) -> None:
    con = get_conn()
    con.execute("""
        INSERT INTO schedule_config (job_id, hour, minute, updated_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (job_id) DO UPDATE SET
            hour = EXCLUDED.hour, minute = EXCLUDED.minute, updated_at = EXCLUDED.updated_at
    """, (job_id, hour, minute, datetime.now()))
    con.commit()
    con.close()
