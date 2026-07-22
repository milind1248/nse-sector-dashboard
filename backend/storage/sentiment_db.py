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


def market_sentiment_summary() -> dict:
    """Aggregate view across the latest scan — overall score, bullish/
    bearish/neutral counts, and the trend vs. the previous scan date.
    Returns {} if no scan has ever run."""
    con = _conn()
    try:
        dates = con.execute(
            "SELECT DISTINCT scan_date FROM sentiment_cache ORDER BY scan_date DESC LIMIT 2"
        ).fetchall()
        if not dates:
            return {}
        latest = dates[0][0]

        row = con.execute("""
            SELECT AVG(score), COUNT(*),
                   SUM(CASE WHEN label = 'Bullish' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN label = 'Bearish' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN label = 'Neutral' THEN 1 ELSE 0 END)
            FROM sentiment_cache WHERE scan_date = %s
        """, (latest,)).fetchone()
        avg_score, total, bullish, bearish, neutral = row
        avg_score = float(avg_score) if avg_score is not None else 0.0

        prev_avg = None
        if len(dates) > 1:
            prev = dates[1][0]
            prev_row = con.execute(
                "SELECT AVG(score) FROM sentiment_cache WHERE scan_date = %s", (prev,)
            ).fetchone()
            if prev_row and prev_row[0] is not None:
                prev_avg = float(prev_row[0])

        label = "Bullish" if avg_score > 0.15 else "Bearish" if avg_score < -0.15 else "Neutral"
        return {
            "scan_date": str(latest),
            "avg_score": round(avg_score, 3),
            "label": label,
            "total": total or 0,
            "bullish": bullish or 0,
            "bearish": bearish or 0,
            "neutral": neutral or 0,
            "bullish_pct": round((bullish or 0) / total * 100, 1) if total else 0.0,
            "bearish_pct": round((bearish or 0) / total * 100, 1) if total else 0.0,
            "neutral_pct": round((neutral or 0) / total * 100, 1) if total else 0.0,
            "prev_avg_score": round(prev_avg, 3) if prev_avg is not None else None,
            "score_change": round(avg_score - prev_avg, 3) if prev_avg is not None else None,
        }
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
    one row per stock. NOTE: kept for backward compatibility, but the nightly
    pipeline now calls purge_old_sentiment() instead — a full truncate means
    only ever one scan_date exists at a time, which makes a "vs yesterday"
    trend comparison impossible (found and fixed while building the market
    sentiment summary panel)."""
    con = _conn()
    try:
        con.execute("DELETE FROM sentiment_cache")
        con.commit()
    finally:
        con.close()


def purge_old_sentiment(keep_days: int = 8) -> None:
    """Delete rows older than keep_days, preserving a rolling history window
    instead of wiping everything — needed so market_sentiment_summary() can
    compare today's aggregate against a prior scan date. Same-day re-runs
    stay idempotent via store_sentiment()'s ON CONFLICT upsert."""
    con = _conn()
    try:
        con.execute(
            "DELETE FROM sentiment_cache WHERE scan_date < CURRENT_DATE - %s::int",
            (keep_days,),
        )
        con.commit()
    finally:
        con.close()
