"""
Supabase (Postgres) persistence for the ETF Dukan 3 page's live tracked book.
Cook-once pattern: the scheduler job (backend/data_ingestion/etf_dukan3_pipeline.py)
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
            SELECT symbol, units, avg_price, last_buy_price, invested_cost, first_buy_date, n_buys, updated_at
            FROM etf_dukan3_open_positions ORDER BY first_buy_date ASC
        """).fetchall()
        return [
            {"symbol": r[0], "units": r[1], "avg_price": r[2], "last_buy_price": r[3],
             "invested_cost": r[4], "first_buy_date": str(r[5]), "n_buys": r[6], "updated_at": str(r[7])}
            for r in rows
        ]
    finally:
        con.close()


def upsert_open_position(symbol: str, units: float, avg_price: float, last_buy_price: float,
                          invested_cost: float, first_buy_date: str, n_buys: int) -> None:
    con = _conn()
    con.execute("""
        INSERT INTO etf_dukan3_open_positions
            (symbol, units, avg_price, last_buy_price, invested_cost, first_buy_date, n_buys)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            units=EXCLUDED.units, avg_price=EXCLUDED.avg_price, last_buy_price=EXCLUDED.last_buy_price,
            invested_cost=EXCLUDED.invested_cost, n_buys=EXCLUDED.n_buys, updated_at=now()
    """, (symbol, units, avg_price, last_buy_price, invested_cost, first_buy_date, n_buys))
    con.commit()
    con.close()


def remove_open_position(symbol: str) -> None:
    con = _conn()
    con.execute("DELETE FROM etf_dukan3_open_positions WHERE symbol = %s", (symbol,))
    con.commit()
    con.close()


def record_closed_trade(symbol: str, entry_date: str, exit_date: str, units: float,
                         avg_entry_price: float, exit_price: float, gross_profit_pct: float,
                         gross_profit_rs: float, net_profit_rs: float, self_dividend_rs: float,
                         n_buys: int) -> None:
    con = _conn()
    con.execute("""
        INSERT INTO etf_dukan3_closed_trades
            (symbol, entry_date, exit_date, units, avg_entry_price, exit_price,
             gross_profit_pct, gross_profit_rs, net_profit_rs, self_dividend_withdrawn, n_buys)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (symbol, entry_date, exit_date, units, avg_entry_price, exit_price,
          gross_profit_pct, gross_profit_rs, net_profit_rs, self_dividend_rs, n_buys))
    con.commit()
    con.close()


def list_closed_trades(limit: int | None = None) -> list[dict]:
    con = _conn()
    try:
        sql = """
            SELECT symbol, entry_date, exit_date, units, avg_entry_price, exit_price,
                   gross_profit_pct, gross_profit_rs, net_profit_rs, self_dividend_withdrawn, n_buys
            FROM etf_dukan3_closed_trades ORDER BY exit_date DESC
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = con.execute(sql).fetchall()
        return [
            {"symbol": r[0], "entry_date": str(r[1]), "exit_date": str(r[2]), "units": r[3],
             "avg_entry_price": r[4], "exit_price": r[5], "gross_profit_pct": r[6], "gross_profit_rs": r[7],
             "net_profit_rs": r[8], "self_dividend_withdrawn": r[9], "n_buys": r[10]}
            for r in rows
        ]
    finally:
        con.close()


def get_config() -> dict:
    con = _conn()
    try:
        row = con.execute("""
            SELECT total_capital_rs, capital_parts, target_pct, average_drop_pct,
                   apply_tax_dividend, self_dividend_bank_rs
            FROM etf_dukan3_config WHERE id = 'default'
        """).fetchone()
        if not row:
            return {"total_capital_rs": 500000.0, "capital_parts": 50, "target_pct": 4.71,
                    "average_drop_pct": 3.0, "apply_tax_dividend": False, "self_dividend_bank_rs": 0.0}
        return {"total_capital_rs": row[0], "capital_parts": row[1], "target_pct": row[2],
                "average_drop_pct": row[3], "apply_tax_dividend": row[4], "self_dividend_bank_rs": row[5]}
    finally:
        con.close()


def update_config(**kwargs) -> None:
    if not kwargs:
        return
    con = _conn()
    cols = ", ".join(f"{k}=%s" for k in kwargs)
    con.execute(f"UPDATE etf_dukan3_config SET {cols} WHERE id = 'default'", tuple(kwargs.values()))
    con.commit()
    con.close()


def add_self_dividend(amount_rs: float) -> None:
    con = _conn()
    con.execute("""
        UPDATE etf_dukan3_config SET self_dividend_bank_rs = self_dividend_bank_rs + %s WHERE id = 'default'
    """, (amount_rs,))
    con.commit()
    con.close()


def last_update_age_days() -> int | None:
    con = _conn()
    try:
        row = con.execute("""
            SELECT MAX(d) FROM (
                SELECT MAX(updated_at::date) AS d FROM etf_dukan3_open_positions
                UNION ALL
                SELECT MAX(closed_at::date) FROM etf_dukan3_closed_trades
            ) x
        """).fetchone()
        if not row or not row[0]:
            return None
        return (date.today() - row[0]).days
    finally:
        con.close()
