"""
Paper Trading logic — live price lookup, limit-order fill processing, P&L.
Streamlit-free so it can be unit tested independently of the page.
"""
from backend.data_ingestion.yfinance_fetcher import _get_close
from backend.storage import paper_trading_db as db


def get_live_price(symbol: str) -> float | None:
    """Last close for a stock symbol via yfinance. Returns None if unavailable."""
    import yfinance as yf
    ticker = symbol if symbol.upper().endswith(".NS") else f"{symbol.upper()}.NS"
    try:
        raw = yf.download(ticker, period="5d", interval="1d", progress=False, auto_adjust=True)
    except Exception:
        return None
    if raw is None or raw.empty:
        return None
    close = _get_close(raw)
    if close is None or close.empty:
        return None
    return float(close.iloc[-1])


def process_pending_limit_orders(trader_id: str, segment: str, price_lookup) -> int:
    """Fill any PENDING limit orders whose condition is met.

    price_lookup(symbol) -> float | None supplies the current price per order
    (live yfinance price for STOCK, manually-entered mark price for OPTION/FUTURE).
    Returns the number of orders filled.
    """
    filled = 0
    for order in db.list_pending_orders(trader_id, segment):
        price = price_lookup(order["symbol"])
        if price is None:
            continue
        limit_price = order["limit_price"]
        should_fill = (
            (order["side"] == "BUY" and price <= limit_price) or
            (order["side"] == "SELL" and price >= limit_price)
        )
        if should_fill:
            db.fill_pending_order(order["id"], price)
            filled += 1
    return filled


def compute_pnl(holding: dict) -> float | None:
    """Unrealized P&L for a holding dict (from paper_trading_db.list_holdings)."""
    mark = holding.get("mark_price")
    if mark is None:
        return None
    return (mark - holding["avg_price"]) * holding["qty"]
