"""
Supabase (Postgres) persistence for the Home page announcement banner.
Schema lives in scripts/supabase_schema.sql; this module only does CRUD
against the already-created `announcement` table (single row, id='home_page').

Replaces data/announcement.json — same reason as schedule_config_db.py:
a file in the git working tree gets wiped out on every Streamlit Cloud
redeploy (fresh checkout from git), so admin edits never survived a push.
"""
from datetime import datetime

from backend.storage.db import get_conn

_ROW_ID = "home_page"


def get_announcement() -> dict:
    """Returns {"enabled": bool, "text": str}. Defaults to disabled/empty if
    the row is missing or the DB is unreachable."""
    try:
        con = get_conn()
        row = con.execute(
            "SELECT enabled, text FROM announcement WHERE id = %s", (_ROW_ID,)
        ).fetchone()
        con.close()
    except Exception:
        return {"enabled": False, "text": ""}
    if row is None:
        return {"enabled": False, "text": ""}
    return {"enabled": row[0], "text": row[1]}


def set_announcement(enabled: bool, text: str) -> None:
    con = get_conn()
    con.execute("""
        INSERT INTO announcement (id, enabled, text, updated_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            enabled = EXCLUDED.enabled, text = EXCLUDED.text, updated_at = EXCLUDED.updated_at
    """, (_ROW_ID, enabled, text.strip(), datetime.now()))
    con.commit()
    con.close()
