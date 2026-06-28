"""
SQLite persistence for AI scan results.
Cook-once pattern: run_and_store_scan() writes to DB; load_latest_scan() reads instantly.
"""
import sqlite3
import json
from datetime import date
from config import DB_PATH


def _conn():
    return sqlite3.connect(DB_PATH)


def ensure_table():
    con = _conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS ai_scan_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date   TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            sector      TEXT,
            price       REAL,
            xgb_prob    REAL,
            direction   TEXT,
            trend       TEXT,
            signal      TEXT,
            UNIQUE(scan_date, symbol)
        )
    """)
    con.commit()
    con.close()


def store_scan(results: list[dict], scan_date: str | None = None) -> None:
    """Write scan results to DB for today (or given date). Replaces today's rows."""
    ensure_table()
    today = scan_date or date.today().isoformat()
    con = _conn()
    # Remove today's old rows first (idempotent re-run)
    con.execute("DELETE FROM ai_scan_results WHERE scan_date = ?", (today,))
    for r in results:
        con.execute("""
            INSERT OR REPLACE INTO ai_scan_results
                (scan_date, symbol, sector, price, xgb_prob, direction, trend, signal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (today, r["Symbol"], r["Sector"], r["Price (₹)"],
              r["XGB Prob"], r["Direction"], r["Trend"], r["Signal"]))
    con.commit()
    con.close()


def load_latest_scan() -> tuple[list[dict], str | None]:
    """
    Load the most recent scan from DB.
    Returns (list_of_rows, scan_date_str) or ([], None) if no data.
    """
    ensure_table()
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
            WHERE scan_date = ?
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
        return results, latest_date
    finally:
        con.close()


def scan_age_days() -> int | None:
    """How many days ago was the last scan? None if never run."""
    _, last_date = load_latest_scan()
    if not last_date:
        return None
    delta = (date.today() - date.fromisoformat(last_date)).days
    return delta
