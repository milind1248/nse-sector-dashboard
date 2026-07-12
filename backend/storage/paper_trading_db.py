"""
SQLite persistence for the Paper Trading page — simulated orders and holdings.

No login system exists yet: `trader_id` is a free-text placeholder key entered
by the user in-page (see app/pages/19_💹_Paper_Trading.py) and will be replaced
by a real account id once authentication is added.

Tables
------
paper_orders   : full order/trade log (MARKET fills immediately, LIMIT waits)
paper_holdings : current net open position per (trader_id, segment, instrument)
"""
import sqlite3
from datetime import datetime, date
from config import DB_PATH


def _conn():
    return sqlite3.connect(DB_PATH)


def ensure_table():
    con = _conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS paper_orders (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            trader_id     TEXT    NOT NULL,
            segment       TEXT    NOT NULL,   -- STOCK | OPTION | FUTURE
            symbol        TEXT    NOT NULL,
            side          TEXT    NOT NULL,   -- BUY | SELL
            qty           INTEGER NOT NULL,
            order_type    TEXT    NOT NULL,   -- MARKET | LIMIT
            limit_price   REAL,
            status        TEXT    NOT NULL,   -- PENDING | FILLED | CANCELLED
            fill_price    REAL,
            realized_pnl  REAL,
            order_time    TEXT    NOT NULL,
            fill_time     TEXT,
            expiry        TEXT,
            strike        REAL,
            option_type   TEXT                -- CE | PE
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS paper_holdings (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            trader_id     TEXT    NOT NULL,
            segment       TEXT    NOT NULL,
            symbol        TEXT    NOT NULL,
            qty           INTEGER NOT NULL,
            avg_price     REAL    NOT NULL,
            mark_price    REAL,
            expiry        TEXT,
            strike        REAL,
            option_type   TEXT,
            UNIQUE(trader_id, segment, symbol, expiry, strike, option_type)
        )
    """)
    con.commit()
    con.close()


ensure_table()


def _holding_key(order: dict) -> tuple:
    return (order["trader_id"], order["segment"], order["symbol"],
            order.get("expiry"), order.get("strike"), order.get("option_type"))


def _get_holding(con, key: tuple):
    row = con.execute("""
        SELECT id, qty, avg_price, mark_price FROM paper_holdings
        WHERE trader_id=? AND segment=? AND symbol=?
          AND expiry IS ? AND strike IS ? AND option_type IS ?
    """, key).fetchone()
    return row  # (id, qty, avg_price, mark_price) or None


def _apply_fill(con, order: dict, fill_price: float) -> float:
    """Update paper_holdings for a filled order. Returns realized P&L (0 for opening/adding trades)."""
    key = _holding_key(order)
    existing = _get_holding(con, key)
    side_qty = order["qty"] if order["side"] == "BUY" else -order["qty"]
    realized = 0.0

    if existing is None:
        con.execute("""
            INSERT INTO paper_holdings (trader_id, segment, symbol, qty, avg_price, mark_price,
                                          expiry, strike, option_type)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (*key[:3], side_qty, fill_price, fill_price, *key[3:]))
        return realized

    hid, cur_qty, cur_avg, mark_price = existing
    new_qty = cur_qty + side_qty

    if cur_qty == 0 or (cur_qty > 0) == (side_qty > 0):
        # Adding to (or opening from flat) a position in the same direction: weighted avg
        new_avg = ((abs(cur_qty) * cur_avg) + (abs(side_qty) * fill_price)) / (abs(cur_qty) + abs(side_qty)) \
            if (cur_qty + side_qty) != 0 else fill_price
    elif abs(side_qty) <= abs(cur_qty):
        # Reducing (or exactly closing) the position: realize P&L on the closed portion
        closed_qty = abs(side_qty)
        realized = (fill_price - cur_avg) * closed_qty * (1 if cur_qty > 0 else -1)
        new_avg = cur_avg  # remaining qty keeps original avg price
    else:
        # Flipping direction: realize P&L on the old qty, remainder opens at fill_price
        realized = (fill_price - cur_avg) * abs(cur_qty) * (1 if cur_qty > 0 else -1)
        new_avg = fill_price

    if new_qty == 0:
        con.execute("DELETE FROM paper_holdings WHERE id=?", (hid,))
    else:
        con.execute("""
            UPDATE paper_holdings SET qty=?, avg_price=?, mark_price=? WHERE id=?
        """, (new_qty, new_avg, fill_price, hid))

    return realized


def place_order(trader_id: str, segment: str, symbol: str, side: str, qty: int,
                 order_type: str, limit_price: float | None = None,
                 mark_price: float | None = None,
                 expiry: str | None = None, strike: float | None = None,
                 option_type: str | None = None) -> dict:
    """Place a MARKET or LIMIT order. MARKET fills immediately at mark_price (required for MARKET)."""
    now = datetime.now().isoformat(timespec="seconds")
    order = {
        "trader_id": trader_id, "segment": segment, "symbol": symbol,
        "side": side, "qty": qty, "expiry": expiry, "strike": strike, "option_type": option_type,
    }

    con = _conn()
    if order_type == "MARKET":
        if mark_price is None:
            con.close()
            raise ValueError("mark_price is required to fill a MARKET order")
        realized = _apply_fill(con, order, mark_price)
        con.execute("""
            INSERT INTO paper_orders (trader_id, segment, symbol, side, qty, order_type, limit_price,
                                       status, fill_price, realized_pnl, order_time, fill_time,
                                       expiry, strike, option_type)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (trader_id, segment, symbol, side, qty, order_type, None,
              "FILLED", mark_price, realized, now, now, expiry, strike, option_type))
    else:  # LIMIT
        if limit_price is None:
            con.close()
            raise ValueError("limit_price is required for a LIMIT order")
        con.execute("""
            INSERT INTO paper_orders (trader_id, segment, symbol, side, qty, order_type, limit_price,
                                       status, fill_price, realized_pnl, order_time, fill_time,
                                       expiry, strike, option_type)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (trader_id, segment, symbol, side, qty, order_type, limit_price,
              "PENDING", None, None, now, None, expiry, strike, option_type))
    con.commit()
    con.close()
    return order


def fill_pending_order(order_id: int, fill_price: float) -> None:
    """Fill a PENDING limit order at the given price and update holdings."""
    con = _conn()
    row = con.execute("""
        SELECT trader_id, segment, symbol, side, qty, expiry, strike, option_type
        FROM paper_orders WHERE id=? AND status='PENDING'
    """, (order_id,)).fetchone()
    if row is None:
        con.close()
        return
    order = dict(zip(
        ["trader_id", "segment", "symbol", "side", "qty", "expiry", "strike", "option_type"], row
    ))
    realized = _apply_fill(con, order, fill_price)
    now = datetime.now().isoformat(timespec="seconds")
    con.execute("""
        UPDATE paper_orders SET status='FILLED', fill_price=?, realized_pnl=?, fill_time=?
        WHERE id=?
    """, (fill_price, realized, now, order_id))
    con.commit()
    con.close()


def cancel_order(order_id: int) -> None:
    con = _conn()
    con.execute("UPDATE paper_orders SET status='CANCELLED' WHERE id=? AND status='PENDING'", (order_id,))
    con.commit()
    con.close()


def list_pending_orders(trader_id: str, segment: str) -> list[dict]:
    con = _conn()
    rows = con.execute("""
        SELECT id, symbol, side, qty, limit_price, expiry, strike, option_type
        FROM paper_orders WHERE trader_id=? AND segment=? AND status='PENDING'
        ORDER BY order_time
    """, (trader_id, segment)).fetchall()
    con.close()
    cols = ["id", "symbol", "side", "qty", "limit_price", "expiry", "strike", "option_type"]
    return [dict(zip(cols, r)) for r in rows]


def list_orders(trader_id: str, segment: str, limit: int = 200) -> list[dict]:
    con = _conn()
    rows = con.execute("""
        SELECT id, symbol, side, qty, order_type, limit_price, status, fill_price,
               realized_pnl, order_time, fill_time, expiry, strike, option_type
        FROM paper_orders WHERE trader_id=? AND segment=?
        ORDER BY order_time DESC LIMIT ?
    """, (trader_id, segment, limit)).fetchall()
    con.close()
    cols = ["id", "symbol", "side", "qty", "order_type", "limit_price", "status", "fill_price",
            "realized_pnl", "order_time", "fill_time", "expiry", "strike", "option_type"]
    return [dict(zip(cols, r)) for r in rows]


def list_holdings(trader_id: str, segment: str) -> list[dict]:
    con = _conn()
    rows = con.execute("""
        SELECT id, symbol, qty, avg_price, mark_price, expiry, strike, option_type
        FROM paper_holdings WHERE trader_id=? AND segment=? AND qty != 0
        ORDER BY symbol
    """, (trader_id, segment)).fetchall()
    con.close()
    cols = ["id", "symbol", "qty", "avg_price", "mark_price", "expiry", "strike", "option_type"]
    return [dict(zip(cols, r)) for r in rows]


def update_mark_price(holding_id: int, mark_price: float) -> None:
    con = _conn()
    con.execute("UPDATE paper_holdings SET mark_price=? WHERE id=?", (mark_price, holding_id))
    con.commit()
    con.close()
