"""
SQLite persistence for Gann Analysis results (cook-once pattern).
Nightly pipeline writes; page reads instantly from DB.

Table: gann_cache — one row per (symbol, scan_date)
  atr_json   : ATR signals + backtest rows
  deg_json   : Degree level rows + bounce-rate rows
  proj_json  : Date projection rows (top & bottom)
  pts_json   : Price-Time square signals
  dates_json : Upcoming Gann natural dates + hit-rate backtest
"""
import sqlite3
import json
import numpy as np
from datetime import date
from config import DB_PATH


def _json_dumps(obj) -> str:
    """json.dumps that converts numpy scalars to Python native types."""
    class _NpEncoder(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, np.bool_):    return bool(o)
            if isinstance(o, np.integer):  return int(o)
            if isinstance(o, np.floating): return float(o)
            if isinstance(o, np.ndarray):  return o.tolist()
            return super().default(o)
    return json.dumps(obj, cls=_NpEncoder)


def _conn():
    return sqlite3.connect(DB_PATH)


def ensure_table():
    con = _conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS gann_cache (
            symbol            TEXT NOT NULL,
            scan_date         TEXT NOT NULL,
            atr_json          TEXT,
            deg_json          TEXT,
            proj_json         TEXT,
            pts_json          TEXT,
            dates_json        TEXT,
            updated_at        TEXT,
            atr_accuracy_pct  REAL,
            atr_signals       INTEGER,
            deg_accuracy_pct  REAL,
            deg_signals       INTEGER,
            proj_accuracy_pct REAL,
            proj_signals      INTEGER,
            pts_accuracy_pct  REAL,
            pts_signals       INTEGER,
            nat_accuracy_pct  REAL,
            nat_signals       INTEGER,
            PRIMARY KEY (symbol, scan_date)
        )
    """)
    # Migrate existing tables that pre-date accuracy columns
    existing = {row[1] for row in con.execute("PRAGMA table_info(gann_cache)").fetchall()}
    for col, typ in [
        ("atr_accuracy_pct", "REAL"), ("atr_signals", "INTEGER"),
        ("deg_accuracy_pct", "REAL"), ("deg_signals", "INTEGER"),
        ("proj_accuracy_pct", "REAL"), ("proj_signals", "INTEGER"),
        ("pts_accuracy_pct", "REAL"), ("pts_signals", "INTEGER"),
        ("nat_accuracy_pct", "REAL"), ("nat_signals", "INTEGER"),
    ]:
        if col not in existing:
            con.execute(f"ALTER TABLE gann_cache ADD COLUMN {col} {typ}")
    con.commit()
    con.close()


ensure_table()


def store_gann(symbol: str, result: dict, scan_date: str | None = None,
               accuracy: dict | None = None) -> None:
    """Upsert Gann analysis for one stock for today (or given date).
    accuracy: optional dict from compute_accuracy() — pre-aggregated per-method metrics.
    """
    today = scan_date or date.today().isoformat()
    acc = accuracy or {}

    def _slim(d: dict, drop_keys=("bt_rows",)) -> dict:
        """Remove large backtest arrays before storing — summary stats already in accuracy cols."""
        return {k: v for k, v in d.items() if k not in drop_keys}

    con = _conn()
    con.execute("""
        INSERT OR REPLACE INTO gann_cache (
            symbol, scan_date, atr_json, deg_json, proj_json, pts_json, dates_json, updated_at,
            atr_accuracy_pct, atr_signals,
            deg_accuracy_pct, deg_signals,
            proj_accuracy_pct, proj_signals,
            pts_accuracy_pct, pts_signals,
            nat_accuracy_pct, nat_signals
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, today,
        _json_dumps(_slim(result.get("atr") or {})),
        _json_dumps(_slim(result.get("deg") or {})),
        _json_dumps(_slim(result.get("proj") or {})),
        _json_dumps(_slim(result.get("pts") or {})),
        _json_dumps(_slim(result.get("dates") or {})),
        result.get("updated_at", today),
        acc.get("atr_accuracy_pct"), acc.get("atr_signals", 0),
        acc.get("deg_accuracy_pct"), acc.get("deg_signals", 0),
        acc.get("proj_accuracy_pct"), acc.get("proj_signals", 0),
        acc.get("pts_accuracy_pct"), acc.get("pts_signals", 0),
        acc.get("nat_accuracy_pct"), acc.get("nat_signals", 0),
    ))
    con.commit()
    con.close()


def load_gann(symbol: str) -> tuple[dict | None, str | None]:
    """
    Load the latest cached Gann result for one symbol.
    Returns (result_dict, scan_date_str) or (None, None) if never cached.
    """
    con = _conn()
    try:
        row = con.execute("""
            SELECT scan_date, atr_json, deg_json, proj_json, pts_json, dates_json
            FROM gann_cache
            WHERE symbol = ?
            ORDER BY scan_date DESC LIMIT 1
        """, (symbol,)).fetchone()
        if not row:
            return None, None
        return {
            "atr":   json.loads(row[1] or "{}"),
            "deg":   json.loads(row[2] or "{}"),
            "proj":  json.loads(row[3] or "{}"),
            "pts":   json.loads(row[4] or "{}"),
            "dates": json.loads(row[5] or "{}"),
        }, row[0]
    finally:
        con.close()


def load_all_summary() -> list[dict]:
    """Load summary row for every symbol at the latest scan date (for health check)."""
    con = _conn()
    try:
        latest = con.execute(
            "SELECT MAX(scan_date) FROM gann_cache"
        ).fetchone()[0]
        if not latest:
            return []
        rows = con.execute("""
            SELECT symbol, scan_date, updated_at FROM gann_cache
            WHERE scan_date = ?
        """, (latest,)).fetchall()
        return [{"symbol": r[0], "scan_date": r[1], "updated_at": r[2]} for r in rows]
    finally:
        con.close()


def load_all_accuracy() -> "pd.DataFrame":
    """
    Return a DataFrame of all symbols at the latest scan_date with pre-computed
    accuracy columns. Used by the Gann Analysis page to show cross-stock tables
    without re-parsing any JSON.
    Returns empty DataFrame if accuracy columns have not been populated yet
    (i.e., pipeline ran before this feature was deployed).
    """
    import pandas as pd
    con = _conn()
    try:
        latest = con.execute("SELECT MAX(scan_date) FROM gann_cache").fetchone()[0]
        if not latest:
            return pd.DataFrame()
        rows = con.execute("""
            SELECT symbol,
                   atr_accuracy_pct,  atr_signals,
                   deg_accuracy_pct,  deg_signals,
                   proj_accuracy_pct, proj_signals,
                   pts_accuracy_pct,  pts_signals,
                   nat_accuracy_pct,  nat_signals
            FROM gann_cache
            WHERE scan_date = ?
            ORDER BY symbol
        """, (latest,)).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=[
            "symbol",
            "atr_accuracy_pct", "atr_signals",
            "deg_accuracy_pct", "deg_signals",
            "proj_accuracy_pct", "proj_signals",
            "pts_accuracy_pct", "pts_signals",
            "nat_accuracy_pct", "nat_signals",
        ])
    finally:
        con.close()


def cache_age_days() -> int | None:
    """Days since last cache run. None if never run."""
    con = _conn()
    try:
        row = con.execute("SELECT MAX(scan_date) FROM gann_cache").fetchone()
        if not row or not row[0]:
            return None
        return (date.today() - date.fromisoformat(row[0])).days
    finally:
        con.close()


def purge_old(days: int = 7) -> int:
    """Delete gann_cache rows older than `days`. Returns rows deleted."""
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    con = _conn()
    try:
        cur = con.execute("DELETE FROM gann_cache WHERE scan_date < ?", (cutoff,))
        con.commit()
        return cur.rowcount
    finally:
        con.close()
