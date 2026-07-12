"""
Supabase (Postgres) persistence for AI scan results.
Cook-once pattern: run_and_store_scan() writes to DB; load_latest_scan() reads instantly.
Schema lives in scripts/supabase_schema.sql.
"""
from datetime import date

from backend.storage.db import get_conn


def _conn():
    return get_conn()


def store_scan(results: list[dict], scan_date: str | None = None) -> None:
    """Write scan results to DB for today (or given date). Replaces today's rows."""
    today = scan_date or date.today().isoformat()
    con = _conn()
    # Remove today's old rows first (idempotent re-run)
    con.execute("DELETE FROM ai_scan_results WHERE scan_date = %s", (today,))
    for r in results:
        con.execute("""
            INSERT INTO ai_scan_results
                (scan_date, symbol, sector, price, xgb_prob, direction, trend, signal)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (scan_date, symbol) DO UPDATE SET
                sector=EXCLUDED.sector, price=EXCLUDED.price, xgb_prob=EXCLUDED.xgb_prob,
                direction=EXCLUDED.direction, trend=EXCLUDED.trend, signal=EXCLUDED.signal
        """, (today, r["Symbol"], r["Sector"], r["Price (₹)"],
              r["XGB Prob"], r["Direction"], r["Trend"], r["Signal"]))
    con.commit()
    con.close()


def load_latest_scan() -> tuple[list[dict], str | None]:
    """
    Load the most recent scan from DB.
    Returns (list_of_rows, scan_date_str) or ([], None) if no data.
    """
    con = _conn()
    try:
        row = con.execute(
            "SELECT MAX(scan_date) FROM ai_scan_results"
        ).fetchone()
        if not row or not row[0]:
            return [], None
        latest_date = row[0]
        rows = con.execute("""
            SELECT symbol, sector, price, xgb_prob, direction, trend, signal
            FROM ai_scan_results
            WHERE scan_date = %s
            ORDER BY direction DESC, xgb_prob DESC
        """, (latest_date,)).fetchall()
        results = [
            {
                "Symbol":    r[0],
                "Sector":    r[1],
                "Price (₹)": r[2],
                "XGB Prob":  r[3],
                "Direction": r[4],
                "Trend":     r[5],
                "Signal":    r[6],
            }
            for r in rows
        ]
        return results, str(latest_date)
    finally:
        con.close()


def scan_age_days() -> int | None:
    """How many days ago was the last scan? None if never run."""
    con = _conn()
    try:
        row = con.execute("SELECT MAX(scan_date) FROM ai_scan_results").fetchone()
        if not row or not row[0]:
            return None
        return (date.today() - row[0]).days
    finally:
        con.close()
