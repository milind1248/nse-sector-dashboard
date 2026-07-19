"""
Supabase (Postgres) persistence for nightly news-sentiment scan results.
Cook-once pattern (same as ai_forecast_db.py): nightly pipeline writes;
AI Forecast page reads instantly from DB — zero live Google News RSS calls
at page-load time, so a slow/rate-limited feed can never stall or crash
a page render.

Table: sentiment_cache — one row per (symbol, scan_date).
Schema lives in scripts/supabase_schema.sql.
"""
import json
from datetime import date

from backend.storage.db import get_conn


def _conn():
    return get_conn()


def store_sentiment(symbol: str, sector: str, summary: dict, headlines: "list[dict]",
                    scan_date: str | None = None) -> None:
    """Upsert one stock's sentiment result for today (or given date)."""
    today = scan_date or date.today().isoformat()
    con = _conn()
    con.execute("""
        INSERT INTO sentiment_cache
            (symbol, sector, scan_date, score, label, n_headlines,
             n_pos, n_neg, n_neu, engine, headlines_json, computed_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (symbol, scan_date) DO UPDATE SET
            sector=EXCLUDED.sector, score=EXCLUDED.score, label=EXCLUDED.label,
            n_headlines=EXCLUDED.n_headlines, n_pos=EXCLUDED.n_pos,
            n_neg=EXCLUDED.n_neg, n_neu=EXCLUDED.n_neu, engine=EXCLUDED.engine,
            headlines_json=EXCLUDED.headlines_json, computed_at=EXCLUDED.computed_at
    """, (
        symbol, sector, today,
        summary.get("score"), summary.get("label"), summary.get("n", 0),
        summary.get("pos", 0), summary.get("neg", 0), summary.get("neu", 0),
        summary.get("engine"), json.dumps(headlines or []),
        summary.get("computed_at"),
    ))
    con.commit()
    con.close()


def load_sentiment(symbol: str) -> tuple[dict | None, str | None]:
    """Load the latest cached sentiment result for one symbol.
    Returns ({summary, headlines}, scan_date_str) or (None, None) if never cached."""
    con = _conn()
    try:
        row = con.execute("""
            SELECT scan_date, score, label, n_headlines, n_pos, n_neg, n_neu,
                   engine, headlines_json
            FROM sentiment_cache
            WHERE symbol = %s
            ORDER BY scan_date DESC LIMIT 1
        """, (symbol,)).fetchone()
        if not row:
            return None, None
        result = {
            "summary": {
                "score": row[1], "label": row[2], "n": row[3],
                "pos": row[4], "neg": row[5], "neu": row[6], "engine": row[7],
            },
            "headlines": json.loads(row[8] or "[]"),
        }
        return result, str(row[0])
    finally:
        con.close()


def load_all_latest() -> list[dict]:
    """Load latest cached sentiment summary for all symbols — used by the
    Nifty 50 sentiment table on the AI Forecast page."""
    con = _conn()
    try:
        latest = con.execute("SELECT MAX(scan_date) FROM sentiment_cache").fetchone()[0]
        if not latest:
            return []
        rows = con.execute("""
            SELECT symbol, sector, score, label, n_headlines, n_pos, n_neg, n_neu, scan_date
            FROM sentiment_cache
            WHERE scan_date = %s
            ORDER BY score DESC
        """, (latest,)).fetchall()
        return [
            {
                "Symbol": r[0], "Sector": r[1], "Score": r[2], "Sentiment": r[3],
                "Headlines": r[4], "Positive": r[5], "Negative": r[6], "Neutral": r[7],
                "scan_date": str(r[8]),
            }
            for r in rows
        ]
    finally:
        con.close()


def cache_age_days() -> int | None:
    """Days since last full sentiment scan. None if never run."""
    con = _conn()
    try:
        row = con.execute("SELECT MAX(scan_date) FROM sentiment_cache").fetchone()
        if not row or not row[0]:
            return None
        return (date.today() - row[0]).days
    finally:
        con.close()


def truncate_sentiment() -> None:
    """Delete all rows before a fresh nightly load — table stays at exactly
    one row per stock."""
    con = _conn()
    try:
        con.execute("DELETE FROM sentiment_cache")
        con.commit()
    finally:
        con.close()
