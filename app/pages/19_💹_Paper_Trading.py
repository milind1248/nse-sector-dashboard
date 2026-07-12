"""Paper Trading — simulated Stock / Option / Future orders, no real money or broker involved."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
from datetime import date, timedelta
from config import SECTOR_STOCKS
from backend.storage import paper_trading_db as db
from backend.calculations.paper_trading import get_live_price, process_pending_limit_orders, compute_pnl

st.set_page_config(page_title="Paper Trading | NSE Swing Trading | Market Sector Analysis", layout="wide")
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()
from app.utils.seo import inject_seo
inject_seo("Paper Trading")
from app.utils.logo import show_logo
show_logo()

st.title("💹 Paper Trading")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption("Simulated trading for practice — no real money, no real orders placed with any broker.")

# ── Trader ID (placeholder until account login exists) ─────────────────────────
tid_col, _ = st.columns([2, 3])
with tid_col:
    trader_id = st.text_input("Trader ID", key="paper_trader_id", placeholder="e.g. your email or a nickname")
st.caption(
    "⚠️ Temporary identifier until account login is added — orders are only visible under the same "
    "Trader ID in this browser. Anyone who enters the same Trader ID sees the same book."
)

if not trader_id.strip():
    st.info("Enter a Trader ID above to start placing simulated orders.")
    st.stop()

trader_id = trader_id.strip()


def _color_pnl(val):
    if isinstance(val, (int, float)) and val == val:
        return "color:#00C853;font-weight:600" if val >= 0 else "color:#FF5252;font-weight:600"
    return ""


def _color_status(val):
    return {"FILLED": "color:#00C853", "PENDING": "color:#FFD600", "CANCELLED": "color:#8899bb"}.get(val, "")


def render_segment_tab(segment: str, symbol: str, mark_price: float | None,
                        expiry: str | None = None, strike: float | None = None,
                        option_type: str | None = None):
    """Shared render for the Stock / Option / Future tabs."""

    def price_lookup(sym):
        if segment == "STOCK":
            return get_live_price(sym)
        return mark_price  # Option/Future: manually entered mark price applies to all pending orders this run

    filled = process_pending_limit_orders(trader_id, segment, price_lookup)
    if filled:
        st.toast(f"{filled} pending {segment.lower()} order(s) filled.", icon="✅")

    # ── Order entry form ────────────────────────────────────────────────────
    with st.form(f"paper_order_form_{segment}", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            side = st.radio("Side", ["BUY", "SELL"], horizontal=True, key=f"side_{segment}")
        with c2:
            qty = st.number_input("Quantity", min_value=1, value=1, step=1, key=f"qty_{segment}")
        with c3:
            order_type = st.radio("Order Type", ["MARKET", "LIMIT"], horizontal=True, key=f"otype_{segment}")
        with c4:
            limit_price = None
            if order_type == "LIMIT":
                default_px = mark_price if mark_price else 0.0
                limit_price = st.number_input("Limit Price (₹)", min_value=0.0, value=float(default_px),
                                               step=0.05, key=f"limit_{segment}")

        submitted = st.form_submit_button("▶ Place Order", type="primary")
        if submitted:
            if not symbol:
                st.error("Enter/select a symbol first.")
            elif order_type == "MARKET" and mark_price is None:
                st.error("No price available to fill a MARKET order — try a LIMIT order or set a mark price.")
            else:
                db.place_order(
                    trader_id=trader_id, segment=segment, symbol=symbol, side=side, qty=int(qty),
                    order_type=order_type, limit_price=limit_price, mark_price=mark_price,
                    expiry=expiry, strike=strike, option_type=option_type,
                )
                st.success(f"{side} order for {qty} × {symbol} submitted.")
                st.rerun()

    st.markdown("---")

    # ── Open positions ──────────────────────────────────────────────────────
    holdings = db.list_holdings(trader_id, segment)
    st.subheader("📂 Open Positions")

    total_invested = total_value = total_pnl = 0.0

    if not holdings:
        st.info("No open positions in this segment.")
    else:
        rows = []
        for h in holdings:
            live = get_live_price(h["symbol"]) if segment == "STOCK" else h.get("mark_price")
            if segment != "STOCK" and mark_price is not None and h["symbol"] == symbol:
                live = mark_price  # refresh with the price just entered for this instrument
            if live is not None and live != h.get("mark_price"):
                db.update_mark_price(h["id"], live)
                h["mark_price"] = live
            pnl = compute_pnl(h)
            invested = h["avg_price"] * abs(h["qty"])
            value = (live or h["avg_price"]) * abs(h["qty"])
            total_invested += invested
            total_value += value
            total_pnl += pnl or 0.0
            rows.append({
                "Symbol": h["symbol"], "Qty": h["qty"], "Avg Price": h["avg_price"],
                "Mark Price": h.get("mark_price"), "P&L": pnl, "id": h["id"],
            })

        df_hold = pd.DataFrame(rows)
        display_df = df_hold.drop(columns=["id"])
        st.dataframe(
            display_df.style.map(_color_pnl, subset=["P&L"]).format({
                "Avg Price": "₹{:.2f}", "Mark Price": lambda v: f"₹{v:.2f}" if isinstance(v, (int, float)) else "—",
                "P&L": lambda v: f"₹{v:+.2f}" if isinstance(v, (int, float)) else "—",
            }),
            use_container_width=True, hide_index=True
        )

        close_cols = st.columns(min(len(rows), 4) or 1)
        for i, h in enumerate(rows):
            with close_cols[i % len(close_cols)]:
                if st.button(f"✕ Close {h['Symbol']}", key=f"close_{segment}_{h['id']}"):
                    close_side = "SELL" if h["Qty"] > 0 else "BUY"
                    close_price = h["Mark Price"] if h["Mark Price"] is not None else h["Avg Price"]
                    db.place_order(
                        trader_id=trader_id, segment=segment, symbol=h["Symbol"], side=close_side,
                        qty=abs(h["Qty"]), order_type="MARKET", mark_price=close_price,
                    )
                    st.success(f"Closed {h['Symbol']}.")
                    st.rerun()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Open Positions", len(holdings))
    m2.metric("Invested", f"₹{total_invested:,.2f}")
    m3.metric("Current Value", f"₹{total_value:,.2f}")
    m4.metric("Unrealized P&L", f"₹{total_pnl:+,.2f}")

    st.markdown("---")

    # ── Order book ───────────────────────────────────────────────────────────
    with st.expander("📜 Order Book / Trade Log"):
        orders = db.list_orders(trader_id, segment)
        if not orders:
            st.info("No orders placed yet.")
        else:
            df_orders = pd.DataFrame(orders)[
                ["symbol", "side", "qty", "order_type", "limit_price", "status",
                 "fill_price", "realized_pnl", "order_time", "fill_time"]
            ]
            st.dataframe(
                df_orders.style.map(_color_status, subset=["status"]).format({
                    "limit_price": lambda v: f"₹{v:.2f}" if isinstance(v, (int, float)) else "—",
                    "fill_price": lambda v: f"₹{v:.2f}" if isinstance(v, (int, float)) else "—",
                    "realized_pnl": lambda v: f"₹{v:+.2f}" if isinstance(v, (int, float)) else "—",
                }),
                use_container_width=True, hide_index=True
            )

            pending = [o for o in orders if o["status"] == "PENDING"]
            if pending:
                st.caption("Cancel a pending order:")
                cancel_cols = st.columns(min(len(pending), 4) or 1)
                for i, o in enumerate(pending):
                    with cancel_cols[i % len(cancel_cols)]:
                        if st.button(f"Cancel #{o['id']} ({o['symbol']})", key=f"cancel_{segment}_{o['id']}"):
                            db.cancel_order(o["id"])
                            st.rerun()


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_stock, tab_option, tab_future = st.tabs(["📈 Stock", "🎯 Option", "📉 Future"])

with tab_stock:
    st.caption("Live price sourced automatically for NSE-listed stocks.")
    sc1, sc2 = st.columns(2)
    with sc1:
        sector = st.selectbox("Sector", sorted(SECTOR_STOCKS.keys()), key="stock_sector")
    with sc2:
        stock_choice = st.selectbox("Stock", [s.replace(".NS", "") for s in SECTOR_STOCKS.get(sector, [])],
                                     key="stock_symbol")
    live_px = get_live_price(stock_choice) if stock_choice else None
    if live_px is not None:
        st.metric(f"{stock_choice} — Live Price", f"₹{live_px:,.2f}")
    else:
        st.warning("Could not fetch a live price for this symbol right now.")
    render_segment_tab("STOCK", stock_choice, live_px)

with tab_option:
    st.caption(
        "⚠️ No live options-chain data source is wired up — enter the current market price for this "
        "contract manually each time you update it. P&L is computed against that entered price."
    )
    oc1, oc2, oc3, oc4 = st.columns(4)
    with oc1:
        opt_symbol = st.text_input("Underlying Symbol", value="NIFTY", key="opt_symbol").strip().upper()
    with oc2:
        opt_expiry = st.date_input("Expiry", value=date.today() + timedelta(days=7), key="opt_expiry")
    with oc3:
        opt_strike = st.number_input("Strike", min_value=0.0, value=0.0, step=50.0, key="opt_strike")
    with oc4:
        opt_type = st.selectbox("Type", ["CE", "PE"], key="opt_type")
    opt_mark = st.number_input("Mark Price (₹)", min_value=0.0, value=0.0, step=0.05, key="opt_mark")
    opt_mark = opt_mark if opt_mark > 0 else None
    render_segment_tab("OPTION", opt_symbol, opt_mark,
                        expiry=str(opt_expiry), strike=opt_strike, option_type=opt_type)

with tab_future:
    st.caption(
        "⚠️ No live futures data source is wired up — enter the current market price for this "
        "contract manually each time you update it. P&L is computed against that entered price."
    )
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        fut_symbol = st.text_input("Symbol", value="NIFTY", key="fut_symbol").strip().upper()
    with fc2:
        fut_expiry = st.date_input("Expiry", value=date.today() + timedelta(days=30), key="fut_expiry")
    with fc3:
        fut_mark = st.number_input("Mark Price (₹)", min_value=0.0, value=0.0, step=0.05, key="fut_mark")
    fut_mark = fut_mark if fut_mark > 0 else None
    render_segment_tab("FUTURE", fut_symbol, fut_mark, expiry=str(fut_expiry))

from app.utils.disclaimer import show_footer
show_footer()
