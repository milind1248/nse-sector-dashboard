"""
Supabase (Postgres) persistence for the ETF Shop page's live tracked book.
Cook-once pattern: the scheduler job (backend/data_ingestion/etf_shop_pipeline.py)
writes daily; the page reads instantly. Schema in scripts/supabase_schema.sql.
"""
from datetime import date

from backend.storage.db import get_conn


def _conn():
    return get_conn()


def list_open_positions() -> list[dict]:
    con = _conn()
    try:
        rows = con.execute("""
            SELECT symbol, units, avg_price, last_buy_price, first_buy_date, n_buys, updated_at
            FROM etf_shop_open_positions ORDER BY first_buy_date ASC
        """).fetchall()
        return [
            {"symbol": r[0], "units": r[1], "avg_price": r[2], "last_buy_price": r[3],
             "first_buy_date": str(r[4]), "n_buys": r[5], "updated_at": str(r[6])}
            for r in rows
        ]
    finally:
        con.close()


def upsert_open_position(symbol: str, units: float, avg_price: float, last_buy_price: float,
                          first_buy_date: str, n_buys: int) -> None:
    con = _conn()
    con.execute("""
        INSERT INTO etf_shop_open_positions (symbol, units, avg_price, last_buy_price, first_buy_date, n_buys)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            units=EXCLUDED.units, avg_price=EXCLUDED.avg_price, last_buy_price=EXCLUDED.last_buy_price,
            n_buys=EXCLUDED.n_buys, updated_at=now()
    """, (symbol, units, avg_price, last_buy_price, first_buy_date, n_buys))
    con.commit()
    con.close()


def remove_open_position(symbol: str) -> None:
    con = _conn()
    con.execute("DELETE FROM etf_shop_open_positions WHERE symbol = %s", (symbol,))
    con.commit()
    con.close()


def record_closed_trade(symbol: str, entry_date: str, exit_date: str, units: float,
                         avg_entry_price: float, exit_price: float, pnl_pct: float, pnl_rs: float,
                         hold_days: int, n_buys: int) -> None:
    con = _conn()
    con.execute("""
        INSERT INTO etf_shop_closed_trades
            (symbol, entry_date, exit_date, units, avg_entry_price, exit_price, pnl_pct, pnl_rs, hold_days, n_buys)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (symbol, entry_date, exit_date, units, avg_entry_price, exit_price, pnl_pct, pnl_rs, hold_days, n_buys))
    con.commit()
    con.close()


def list_closed_trades(limit: int | None = None) -> list[dict]:
    con = _conn()
    try:
        sql = """
            SELECT symbol, entry_date, exit_date, units, avg_entry_price, exit_price,
                   pnl_pct, pnl_rs, hold_days, n_buys
            FROM etf_shop_closed_trades ORDER BY exit_date DESC
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = con.execute(sql).fetchall()
        return [
            {"symbol": r[0], "entry_date": str(r[1]), "exit_date": str(r[2]), "units": r[3],
             "avg_entry_price": r[4], "exit_price": r[5], "pnl_pct": r[6], "pnl_rs": r[7],
             "hold_days": r[8], "n_buys": r[9]}
            for r in rows
        ]
    finally:
        con.close()


def last_update_age_days() -> int | None:
    con = _conn()
    try:
        row = con.execute("""
            SELECT MAX(d) FROM (
                SELECT MAX(updated_at::date) AS d FROM etf_shop_open_positions
                UNION ALL
                SELECT MAX(closed_at::date) FROM etf_shop_closed_trades
            ) x
        """).fetchone()
        if not row or not row[0]:
            return None
        return (date.today() - row[0]).days
    finally:
        con.close()
