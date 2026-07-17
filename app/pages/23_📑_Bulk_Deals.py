"""Bulk & Block Deals — large institutional/promoter trades, sourced from NSE daily archive CSVs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from app.utils.auth import is_admin
from backend.storage.db import get_conn

st.set_page_config(
    page_title="Bulk & Block Deals | Large Institutional Trades | Market Sector Analysis",
    layout="wide",
)
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.seo import inject_seo
inject_seo("Bulk_Deals")

from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("Bulk Deals")

from app.utils.disclaimer import show_sebi_notice, show_footer


def _db():
    return get_conn()


@st.cache_data(ttl=1800, show_spinner=False)
def _load_deals(table: str, days: int) -> pd.DataFrame:
    since = (date.today() - timedelta(days=days)).isoformat()
    con = _db()
    rows = con.execute(
        f"SELECT trade_date, symbol, security_name, client_name, deal_type, quantity, price "
        f"FROM {table} WHERE trade_date >= %s ORDER BY trade_date DESC, id DESC",
        (since,),
    ).fetchall()
    con.close()
    if not rows:
        return pd.DataFrame(columns=["Date", "Symbol", "Security", "Client", "Type", "Quantity", "Price", "Value (₹)"])
    df = pd.DataFrame(rows, columns=["Date", "Symbol", "Security", "Client", "Type", "Quantity", "Price"])
    df["Value (₹)"] = df["Quantity"] * df["Price"]
    return df


@st.cache_data(ttl=1800, show_spinner=False)
def _last_refresh() -> str:
    con = _db()
    row = con.execute(
        "SELECT finished_at FROM job_run_log WHERE job_id = %s AND status = 'success' "
        "ORDER BY finished_at DESC LIMIT 1",
        ("bulk_deals_daily",),
    ).fetchone()
    con.close()
    return str(row[0])[:16] if row and row[0] else "Never"


def _color_type(val):
    if val == "BUY":
        return "color:#2ecc71;font-weight:600;"
    if val == "SELL":
        return "color:#e74c3c;font-weight:600;"
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# PAGE
# ══════════════════════════════════════════════════════════════════════════════
show_sebi_notice()

st.title("📑 Bulk & Block Deals")
st.caption(
    "Large trades (bulk: ≥0.5% of listed shares; block: executed via the dedicated block window) "
    "disclosed daily by NSE. **For research and educational reference only — not investment advice.**"
)

col_info, col_btn = st.columns([3, 1])
with col_info:
    st.markdown(
        f"<div style='background:#1a3a4a;border-left:4px solid #4da6d4;padding:10px 14px;"
        f"border-radius:4px;font-size:0.78rem;line-height:1.6'>"
        f"Last refresh: <b>{_last_refresh()}</b><br>"
        f"Auto-refreshes daily (weekdays) after market close. NSE only publishes today's deals — "
        f"history accumulates in the database over time from each day's run."
        f"</div>",
        unsafe_allow_html=True,
    )
with col_btn:
    if is_admin():
        refresh = st.button("🔄 Refresh Data", type="primary", width="stretch",
                             help="Re-fetches today's Bulk & Block Deals CSVs from NSE.")
    else:
        st.caption("🔒 Data refresh is admin-only.")
        refresh = False

if refresh:
    from backend.data_ingestion.job_logger import log_start, log_finish
    from backend.data_ingestion.bulk_deals_pipeline import run_bulk_deals_pipeline
    _job_row = log_start("bulk_deals_daily", "Bulk & Block Deals Sync (Admin)", triggered_by="admin")
    with st.spinner("Fetching today's Bulk & Block Deals from NSE..."):
        try:
            result = run_bulk_deals_pipeline()
            log_finish(_job_row, "success", records_done=result["bulk_saved"] + result["block_saved"])
            st.cache_data.clear()
            st.success(
                f"Refreshed — {result['bulk_fetched']} bulk deal rows, "
                f"{result['block_fetched']} block deal rows fetched."
            )
        except Exception as e:
            log_finish(_job_row, "failed", error_msg=str(e))
            st.error(f"Refresh failed: {e}")
    st.rerun()

st.markdown("---")

tab_bulk, tab_block = st.tabs(["📦 Bulk Deals", "🧱 Block Deals"])

for tab, table_name, label in [(tab_bulk, "bulk_deals", "Bulk"), (tab_block, "block_deals", "Block")]:
    with tab:
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            lookback = st.selectbox("Lookback period", [7, 15, 30, 90], index=1, key=f"lb_{table_name}")
        with fc2:
            sym_filter = st.text_input("Filter by symbol", key=f"sym_{table_name}",
                                        placeholder="e.g. RELIANCE").strip().upper()
        with fc3:
            type_filter = st.selectbox("Buy/Sell", ["All", "BUY", "SELL"], key=f"type_{table_name}")

        df = _load_deals(table_name, lookback)

        if df.empty:
            st.info(f"No {label} Deals recorded in the last {lookback} days.")
            continue

        disp = df.copy()
        if sym_filter:
            disp = disp[disp["Symbol"].str.contains(sym_filter, case=False, na=False)]
        if type_filter != "All":
            disp = disp[disp["Type"] == type_filter]

        m1, m2, m3 = st.columns(3)
        m1.metric(f"{label} deals shown", len(disp))
        m2.metric("Buy trades", int((disp["Type"] == "BUY").sum()))
        m3.metric("Sell trades", int((disp["Type"] == "SELL").sum()))

        st.caption(f"Showing {len(disp)} of {len(df)} {label.lower()} deals in the last {lookback} days.")

        styled = (
            disp.style
            .map(_color_type, subset=["Type"])
            .format({
                "Quantity": "{:,.0f}",
                "Price": "₹{:,.2f}",
                "Value (₹)": "₹{:,.0f}",
            })
        )
        st.dataframe(styled, width="stretch", height=460, hide_index=True)

        st.caption(
            f"{label} Deals data sourced from NSE's daily archive CSV "
            f"(archives.nseindia.com/content/equities/{table_name.replace('_deals', '')}.csv). "
            "Not investment advice."
        )

show_footer()
