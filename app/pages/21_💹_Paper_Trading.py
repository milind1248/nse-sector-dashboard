"""Paper Trading — simulated Stock / Option / Future orders, no real money or broker involved."""
import sys
import uuid
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

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("Paper Trading")

st.title("💹 Paper Trading")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption("Simulated trading for practice — no real money, no real orders placed with any broker.")

ALL_STOCK_SYMBOLS = sorted({s.replace(".NS", "") for stocks in SECTOR_STOCKS.values() for s in stocks})
FNO_UNDERLYINGS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"] + ALL_STOCK_SYMBOLS


@st.cache_data(ttl=20, show_spinner=False)
def _cached_live_price_hit(symbol: str) -> float:
    """Cache only successful lookups (raises on failure so nothing is cached)."""
    price = get_live_price(symbol)
    if price is None:
        raise ValueError("no price")
    return price


def _cached_live_price(symbol: str):
    """Live price, cached for 20s — but a failed fetch is never cached, so the next
    rerun (or the row's manual override) can recover immediately instead of being
    stuck on a stale None for the full TTL."""
    try:
        return _cached_live_price_hit(symbol)
    except Exception:
        return None


# ── Login — uses the site-wide Supabase Auth session (sidebar), not a
# separate page-local login: Paper Trading data is scoped to the same
# account a visitor already signs into anywhere else on the site.
from app.utils.user_session import is_logged_in, current_user

if not is_logged_in():
    st.info("🔒 Please sign in from the sidebar to use Paper Trading.")
    st.stop()

trader_id = current_user()["id"]


def _color_pnl(val):
    if isinstance(val, (int, float)) and val == val:
        return "color:#00C853;font-weight:600" if val >= 0 else "color:#FF5252;font-weight:600"
    return ""


def _color_status(val):
    return {"FILLED": "color:#00C853", "PENDING": "color:#FFD600", "CANCELLED": "color:#8899bb"}.get(val, "")


def _rows_key(segment):
    return f"order_rows_{segment}"


def _ensure_rows(segment):
    key = _rows_key(segment)
    if key not in st.session_state or not st.session_state[key]:
        st.session_state[key] = [uuid.uuid4().hex[:8]]
    return st.session_state[key]


def render_order_row(segment: str, uid: str, show_labels: bool):
    """One quick-entry row. Returns a dict of the row's current values + a 'remove' flag."""
    lv = "visible" if show_labels else "collapsed"

    if segment == "STOCK":
        cols = st.columns([2.2, 1.3, 1.3, 1.1, 1.0, 1.2, 1.2, 0.5])
        symbol = cols[0].selectbox("Symbol", ALL_STOCK_SYMBOLS, index=None, placeholder="Type symbol…",
                                    key=f"sym_{uid}", accept_new_options=True, filter_mode="fuzzy",
                                    label_visibility=lv)
        live_px = _cached_live_price(symbol) if symbol else None
        with cols[1]:
            if show_labels:
                st.markdown("**Live Price**")
            if symbol and live_px is None:
                st.markdown(":red[unavailable]")
            else:
                st.markdown(f"₹{live_px:,.2f}" if live_px is not None else "—")
        with cols[2]:
            price_override = st.number_input("Price ₹ (override)", min_value=0.0, value=0.0, step=0.05,
                                               key=f"pxover_{uid}", label_visibility=lv,
                                               help="Leave 0 to use the live price above.")
        effective_px = price_override if price_override > 0 else live_px
        side = cols[3].radio("Side", ["BUY", "SELL"], horizontal=True, key=f"side_{uid}", label_visibility=lv)
        qty = cols[4].number_input("Qty", min_value=1, value=1, step=1, key=f"qty_{uid}", label_visibility=lv)
        order_type = cols[5].selectbox("Order Type", ["MARKET", "LIMIT"], key=f"otype_{uid}", label_visibility=lv)
        limit_price = None
        with cols[6]:
            if order_type == "LIMIT":
                limit_price = st.number_input("Limit ₹", min_value=0.0, value=float(effective_px or 0.0),
                                               step=0.05, key=f"limit_{uid}", label_visibility=lv)
            else:
                if show_labels:
                    st.markdown("**Limit ₹**")
                st.markdown("—")
        with cols[7]:
            if show_labels:
                st.markdown("**&nbsp;**", unsafe_allow_html=True)
            remove = st.button("✕", key=f"rm_{uid}")
        mark_price = effective_px
        expiry = strike = option_type = None

    elif segment == "OPTION":
        cols = st.columns([1.8, 1.1, 1.0, 0.7, 1.1, 1.1, 0.8, 1.1, 1.1, 0.5])
        symbol = cols[0].selectbox("Symbol", FNO_UNDERLYINGS, index=None, placeholder="Underlying…",
                                    key=f"sym_{uid}", accept_new_options=True, filter_mode="fuzzy",
                                    label_visibility=lv)
        expiry = str(cols[1].date_input("Expiry", value=date.today() + timedelta(days=7), key=f"exp_{uid}",
                                         label_visibility=lv))
        strike = cols[2].number_input("Strike", min_value=0.0, value=0.0, step=50.0, key=f"strk_{uid}",
                                       label_visibility=lv)
        option_type = cols[3].selectbox("Type", ["CE", "PE"], key=f"otyp_{uid}", label_visibility=lv)
        mark_price = cols[4].number_input("Mark ₹", min_value=0.0, value=0.0, step=0.05, key=f"mark_{uid}",
                                           label_visibility=lv)
        mark_price = mark_price if mark_price > 0 else None
        side = cols[5].radio("Side", ["BUY", "SELL"], horizontal=True, key=f"side_{uid}", label_visibility=lv)
        qty = cols[6].number_input("Qty", min_value=1, value=1, step=1, key=f"qty_{uid}", label_visibility=lv)
        order_type = cols[7].selectbox("Order Type", ["MARKET", "LIMIT"], key=f"otype_{uid}", label_visibility=lv)
        limit_price = None
        with cols[8]:
            if order_type == "LIMIT":
                limit_price = st.number_input("Limit ₹", min_value=0.0, value=float(mark_price or 0.0),
                                               step=0.05, key=f"limit_{uid}", label_visibility=lv)
            else:
                if show_labels:
                    st.markdown("**Limit ₹**")
                st.markdown("—")
        with cols[9]:
            if show_labels:
                st.markdown("**&nbsp;**", unsafe_allow_html=True)
            remove = st.button("✕", key=f"rm_{uid}")

    else:  # FUTURE
        cols = st.columns([2.0, 1.4, 1.3, 1.3, 1.0, 1.3, 1.3, 0.5])
        symbol = cols[0].selectbox("Symbol", FNO_UNDERLYINGS, index=None, placeholder="Underlying…",
                                    key=f"sym_{uid}", accept_new_options=True, filter_mode="fuzzy",
                                    label_visibility=lv)
        expiry = str(cols[1].date_input("Expiry", value=date.today() + timedelta(days=30), key=f"exp_{uid}",
                                         label_visibility=lv))
        mark_price = cols[2].number_input("Mark ₹", min_value=0.0, value=0.0, step=0.05, key=f"mark_{uid}",
                                           label_visibility=lv)
        mark_price = mark_price if mark_price > 0 else None
        side = cols[3].radio("Side", ["BUY", "SELL"], horizontal=True, key=f"side_{uid}", label_visibility=lv)
        qty = cols[4].number_input("Qty", min_value=1, value=1, step=1, key=f"qty_{uid}", label_visibility=lv)
        order_type = cols[5].selectbox("Order Type", ["MARKET", "LIMIT"], key=f"otype_{uid}", label_visibility=lv)
        limit_price = None
        with cols[6]:
            if order_type == "LIMIT":
                limit_price = st.number_input("Limit ₹", min_value=0.0, value=float(mark_price or 0.0),
                                               step=0.05, key=f"limit_{uid}", label_visibility=lv)
            else:
                if show_labels:
                    st.markdown("**Limit ₹**")
                st.markdown("—")
        with cols[7]:
            if show_labels:
                st.markdown("**&nbsp;**", unsafe_allow_html=True)
            remove = st.button("✕", key=f"rm_{uid}")
        strike = option_type = None

    return {
        "uid": uid, "symbol": symbol, "side": side, "qty": qty, "order_type": order_type,
        "limit_price": limit_price, "mark_price": mark_price, "expiry": expiry, "strike": strike,
        "option_type": option_type, "remove": remove,
    }


def render_segment_tab(segment: str):
    """Shared render for the Stock / Option / Future tabs: quick order ticket + positions + order book."""

    def price_lookup(sym):
        if segment == "STOCK":
            return _cached_live_price(sym)
        for h in db.list_holdings(trader_id, segment):
            if h["symbol"] == sym:
                return h.get("mark_price")
        return None

    filled = process_pending_limit_orders(trader_id, segment, price_lookup)
    if filled:
        st.toast(f"{filled} pending {segment.lower()} order(s) filled.", icon="✅")

    # ── Quick order ticket (one row per trade; add as many as you like) ────────
    st.markdown("##### 🎫 Quick Order Ticket")
    with st.expander("ℹ️ ⚡ Market vs 🎯 Limit — when does an order fill?"):
        st.markdown(
            "- **⚡ Market** — fills **immediately** at the current live/mark price shown in the row.\n"
            "- **🎯 Limit** — stays **PENDING** in the Order Book until the price reaches your limit: "
            "a BUY limit fills once the price drops **to or below** your limit, a SELL limit fills once "
            "the price rises **to or above** it.\n"
            "- This is a simulator, not a live broker feed — pending limit orders are only checked "
            "**when you open or refresh this page/tab**, not continuously in real time. If the price "
            "touches your limit between visits, it will fill the next time you load this tab."
        )
    row_uids = _ensure_rows(segment)
    rows = [render_order_row(segment, uid, show_labels=(i == 0)) for i, uid in enumerate(row_uids)]

    to_remove = [r["uid"] for r in rows if r["remove"]]
    if to_remove:
        st.session_state[_rows_key(segment)] = [u for u in row_uids if u not in to_remove]
        st.rerun()

    bc1, bc2 = st.columns([1, 1])
    with bc1:
        if st.button("➕ Add Row", key=f"add_row_{segment}"):
            st.session_state[_rows_key(segment)].append(uuid.uuid4().hex[:8])
            st.rerun()
    with bc2:
        if st.button("▶ Place Order(s)", type="primary", key=f"place_all_{segment}"):
            placed, errors = 0, []
            for r in rows:
                if not r["symbol"]:
                    continue
                if r["order_type"] == "MARKET" and r["mark_price"] is None:
                    errors.append(f"{r['symbol']}: no price available to fill a MARKET order.")
                    continue
                db.place_order(
                    trader_id=trader_id, segment=segment, symbol=r["symbol"], side=r["side"],
                    qty=int(r["qty"]), order_type=r["order_type"], limit_price=r["limit_price"],
                    mark_price=r["mark_price"], expiry=r["expiry"], strike=r["strike"],
                    option_type=r["option_type"],
                )
                placed += 1
            for e in errors:
                st.error(e)
            if placed:
                st.success(f"{placed} order(s) submitted.")
                st.session_state[_rows_key(segment)] = [uuid.uuid4().hex[:8]]
                st.rerun()
            elif not errors:
                st.warning("Enter at least one symbol before placing an order.")

    st.markdown("---")

    # ── Open positions ──────────────────────────────────────────────────────
    holdings = db.list_holdings(trader_id, segment)
    st.subheader("📂 Open Positions")
    if holdings:
        st.caption("**Order** shows how the position's most recent fill was opened/added to — "
                   "🎯 Limit or ⚡ Market.")

    total_invested = total_value = total_pnl = 0.0

    if not holdings:
        st.info("No open positions in this segment.")
    else:
        display_rows = []
        for h in holdings:
            if segment == "STOCK":
                live = _cached_live_price(h["symbol"])
                if live is not None and live != h.get("mark_price"):
                    db.update_mark_price(h["id"], live)
                    h["mark_price"] = live
            pnl = compute_pnl(h)
            invested = h["avg_price"] * abs(h["qty"])
            value = (h.get("mark_price") or h["avg_price"]) * abs(h["qty"])
            total_invested += invested
            total_value += value
            total_pnl += pnl or 0.0
            order_icon = {"LIMIT": "🎯 Limit", "MARKET": "⚡ Market"}.get(h.get("last_order_type"), "— Unknown")
            display_rows.append({
                "Order": order_icon, "Symbol": h["symbol"], "Qty": h["qty"], "Avg Price": h["avg_price"],
                "Mark Price": h.get("mark_price"), "P&L": pnl, "id": h["id"],
            })

        df_hold = pd.DataFrame(display_rows)
        display_df = df_hold.drop(columns=["id"])
        st.dataframe(
            display_df.style.map(_color_pnl, subset=["P&L"]).format({
                "Avg Price": "₹{:.2f}", "Mark Price": lambda v: f"₹{v:.2f}" if isinstance(v, (int, float)) else "—",
                "P&L": lambda v: f"₹{v:+.2f}" if isinstance(v, (int, float)) else "—",
            }),
            width='stretch', hide_index=True
        )

        close_cols = st.columns(min(len(display_rows), 4) or 1)
        for i, h in enumerate(display_rows):
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
                width='stretch', hide_index=True
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
    st.caption("Type a symbol to see suggestions and its live price — pick it or keep typing your own.")
    render_segment_tab("STOCK")

with tab_option:
    st.caption(
        "⚠️ No live options-chain data source is wired up — enter the current market (mark) price for each "
        "contract yourself. P&L is computed against that entered price."
    )
    render_segment_tab("OPTION")

with tab_future:
    st.caption(
        "⚠️ No live futures data source is wired up — enter the current market (mark) price for each "
        "contract yourself. P&L is computed against that entered price."
    )
    render_segment_tab("FUTURE")

from app.utils.disclaimer import show_footer
show_footer()
