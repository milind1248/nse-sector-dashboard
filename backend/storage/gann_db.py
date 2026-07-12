"""
Supabase (Postgres) persistence for Gann Analysis results (cook-once pattern).
Nightly pipeline writes; page reads instantly from DB. Schema lives in
scripts/supabase_schema.sql.

Table: gann_cache — one row per (symbol, scan_date)
  atr_json   : ATR signals + backtest rows
  deg_json   : Degree level rows + bounce-rate rows
  proj_json  : Date projection rows (top & bottom)
  pts_json   : Price-Time square signals
  dates_json : Upcoming Gann natural dates + hit-rate backtest
"""
import json
import numpy as np
from datetime import date

from backend.storage.db import get_conn


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
    return get_conn()


def store_gann(symbol: str, result: dict, scan_date: str | None = None,
               accuracy: dict | None = None) -> None:
    """Upsert Gann analysis for one stock for today (or given date).
    accuracy: optional dict from compute_accuracy() — pre-aggregated per-method metrics.
    """
    today = scan_date or date.today().isoformat()
    acc = accuracy or {}

    def _slim(d: dict) -> dict:
        """Strip all backtest row arrays — page recomputes them from price data; never read from cache."""
        _drop = {"bt_rows", "bt_highs", "bt_lows", "bt_high", "bt_low", "hist_rows"}
        return {k: v for k, v in d.items() if k not in _drop}

    con = _conn()
    con.execute("""
        INSERT INTO gann_cache (
            symbol, scan_date, atr_json, deg_json, proj_json, pts_json, dates_json, updated_at,
            atr_accuracy_pct, atr_signals,
            deg_accuracy_pct, deg_signals,
            proj_accuracy_pct, proj_signals,
            pts_accuracy_pct, pts_signals,
            nat_accuracy_pct, nat_signals
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, scan_date) DO UPDATE SET
            atr_json=EXCLUDED.atr_json, deg_json=EXCLUDED.deg_json, proj_json=EXCLUDED.proj_json,
            pts_json=EXCLUDED.pts_json, dates_json=EXCLUDED.dates_json, updated_at=EXCLUDED.updated_at,
            atr_accuracy_pct=EXCLUDED.atr_accuracy_pct, atr_signals=EXCLUDED.atr_signals,
            deg_accuracy_pct=EXCLUDED.deg_accuracy_pct, deg_signals=EXCLUDED.deg_signals,
            proj_accuracy_pct=EXCLUDED.proj_accuracy_pct, proj_signals=EXCLUDED.proj_signals,
            pts_accuracy_pct=EXCLUDED.pts_accuracy_pct, pts_signals=EXCLUDED.pts_signals,
            nat_accuracy_pct=EXCLUDED.nat_accuracy_pct, nat_signals=EXCLUDED.nat_signals
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
            WHERE symbol = %s
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
        }, str(row[0])
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
            WHERE scan_date = %s
        """, (latest,)).fetchall()
        return [{"symbol": r[0], "scan_date": str(r[1]), "updated_at": r[2]} for r in rows]
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
            WHERE scan_date = %s
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
        return (date.today() - row[0]).days
    finally:
        con.close()


def purge_old(days: int = 7) -> int:
    """Delete gann_cache rows older than `days`. Returns rows deleted."""
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    con = _conn()
    try:
        cur = con.execute("DELETE FROM gann_cache WHERE scan_date < %s", (cutoff,))
        con.commit()
        return cur.rowcount
    finally:
        con.close()
