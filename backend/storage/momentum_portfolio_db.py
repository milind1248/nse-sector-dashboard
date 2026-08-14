"""
Supabase (Postgres) persistence for the Momentum Scanner's virtual portfolio
tracker ("Performance Breakdown" tab). Cook-once pattern: the scheduler job
(backend/data_ingestion/momentum_portfolio_pipeline.py) writes one NAV row +
a full holdings snapshot per trading day; the page reads instantly, zero
live yfinance calls at page-load. Schema in scripts/supabase_schema.sql.
"""
from datetime import date

from backend.storage.db import get_conn


def _conn():
    return get_conn()


def store_snapshot(snapshot_date: str, fund_nav: float, benchmark_nav: float,
                    is_rebalance_day: bool, holdings: list[dict]) -> None:
    """Write one day's NAV row + full holdings snapshot. Idempotent re-run."""
    con = _conn()
    con.execute("""
        INSERT INTO momentum_portfolio_nav (snapshot_date, fund_nav, benchmark_nav, is_rebalance_day)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (snapshot_date) DO UPDATE SET
            fund_nav=EXCLUDED.fund_nav, benchmark_nav=EXCLUDED.benchmark_nav,
            is_rebalance_day=EXCLUDED.is_rebalance_day
    """, (snapshot_date, fund_nav, benchmark_nav, is_rebalance_day))

    con.execute("DELETE FROM momentum_portfolio_holdings WHERE snapshot_date = %s", (snapshot_date,))
    for h in holdings:
        con.execute("""
            INSERT INTO momentum_portfolio_holdings
                (snapshot_date, symbol, category, weight_pct, return_pct, alpha_pct, em_rank)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (snapshot_date, h["symbol"], h["category"], h["weight_pct"],
              h.get("return_pct"), h.get("alpha_pct"), h.get("em_rank")))
    con.commit()
    con.close()


def load_latest_holdings() -> tuple[list[dict], str | None]:
    """Most recent full holdings snapshot. Returns ([], None) if never run."""
    con = _conn()
    try:
        row = con.execute("SELECT MAX(snapshot_date) FROM momentum_portfolio_holdings").fetchone()
        if not row or not row[0]:
            return [], None
        latest = row[0]
        rows = con.execute("""
            SELECT symbol, category, weight_pct, return_pct, alpha_pct, em_rank
            FROM momentum_portfolio_holdings
            WHERE snapshot_date = %s
            ORDER BY em_rank ASC NULLS LAST
        """, (latest,)).fetchall()
        holdings = [
            {"symbol": r[0], "category": r[1], "weight_pct": r[2],
             "return_pct": r[3], "alpha_pct": r[4], "em_rank": r[5]}
            for r in rows
        ]
        return holdings, str(latest)
    finally:
        con.close()


def load_latest_nav_row() -> dict | None:
    """Most recent NAV row (for mark_to_market's prev_nav baseline)."""
    con = _conn()
    try:
        row = con.execute("""
            SELECT snapshot_date, fund_nav, benchmark_nav, is_rebalance_day
            FROM momentum_portfolio_nav
            ORDER BY snapshot_date DESC LIMIT 1
        """).fetchone()
        if not row:
            return None
        return {"snapshot_date": str(row[0]), "fund_nav": row[1],
                "benchmark_nav": row[2], "is_rebalance_day": row[3]}
    finally:
        con.close()


def load_nav_history(since_date: str | None = None) -> list[dict]:
    """NAV time series, optionally from a given date (e.g. last rebalance) onward."""
    con = _conn()
    try:
        if since_date:
            rows = con.execute("""
                SELECT snapshot_date, fund_nav, benchmark_nav, is_rebalance_day
                FROM momentum_portfolio_nav
                WHERE snapshot_date >= %s
                ORDER BY snapshot_date ASC
            """, (since_date,)).fetchall()
        else:
            rows = con.execute("""
                SELECT snapshot_date, fund_nav, benchmark_nav, is_rebalance_day
                FROM momentum_portfolio_nav
                ORDER BY snapshot_date ASC
            """).fetchall()
        return [{"snapshot_date": str(r[0]), "fund_nav": r[1],
                 "benchmark_nav": r[2], "is_rebalance_day": r[3]} for r in rows]
    finally:
        con.close()


def last_rebalance_date() -> str | None:
    con = _conn()
    try:
        row = con.execute("""
            SELECT MAX(snapshot_date) FROM momentum_portfolio_nav WHERE is_rebalance_day = TRUE
        """).fetchone()
        return str(row[0]) if row and row[0] else None
    finally:
        con.close()


def snapshot_age_days() -> int | None:
    con = _conn()
    try:
        row = con.execute("SELECT MAX(snapshot_date) FROM momentum_portfolio_nav").fetchone()
        if not row or not row[0]:
            return None
        return (date.today() - row[0]).days
    finally:
        con.close()
