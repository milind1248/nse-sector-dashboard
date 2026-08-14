from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

st.set_page_config(page_title="Momentum Scanner | NSE Market Sector", layout="wide")

from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.seo import inject_seo
inject_seo("MomentumScanner")
from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("Momentum Scanner")

import pandas as pd
import pytz as _pytz
import plotly.graph_objects as go

from backend.calculations.momentum_alltimehigh import (
    run_momentum_scan, universe_symbols, DEFAULT_ATH_TOLERANCE_PCT, DEFAULT_TOP_N,
)
from backend.calculations.sector_rotation import monthly_sector_returns, sector_leadership_rank, monthly_leaders

_IST = _pytz.timezone("Asia/Kolkata")


@st.cache_data(ttl=1800, show_spinner=False)
def _run_scan(symbols: tuple, ath_tolerance_pct: float, top_n: int) -> tuple:
    df = run_momentum_scan(symbols, ath_tolerance_pct=ath_tolerance_pct, top_n=top_n)
    fetch_ts = pd.Timestamp.now(tz=_IST)
    return df, fetch_ts


@st.cache_data(ttl=1800, show_spinner=False)
def _run_sector_rotation(months: int) -> tuple:
    grid = monthly_sector_returns(months=months)
    fetch_ts = pd.Timestamp.now(tz=_IST)
    return grid, fetch_ts


def _decision_color(val):
    if val == "BUY":
        return "color:#00C853;font-weight:700"
    if val == "HOLD":
        return "color:#FFD600"
    if val == "AVOID":
        return "color:#D50000"
    return ""


# ─── Page title & disclaimer ─────────────────────────────────────────────────
st.title("🚀 Momentum Scanner")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption(
    "Rohan Mehta's 3-criteria 'buy at all-time-high' momentum framework: (1) price at/near all-time "
    "high, (2) trailing 12-month profit at its own all-time high, (3) 52-week return beats both "
    "Nifty 500 and the stock's own sector index. Score 3/3 = BUY, 2/3 = HOLD, ≤1/3 = AVOID. "
    "**Honest backtest disclosure (2016-2026, sector-mapped universe):** +6.6pt gross alpha vs "
    "Nifty 500, but only +1.4pt net of estimated transaction costs — the framework rebalances "
    "~76% of holdings every month, and that churn erodes most of the gross edge. Educational "
    "discovery tool, not a recommendation to buy or sell."
)

tab_scan, tab_ath, tab_sector = st.tabs(["🎯 Momentum Scan", "🚀 All-Time-High Stocks", "📅 Sector Rotation Map"])

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — MOMENTUM SCAN (3-criteria)
# ═════════════════════════════════════════════════════════════════════════════
with tab_scan:
    c1, c2 = st.columns(2)
    with c1:
        ath_tol = st.slider("ATH tolerance %", min_value=0.0, max_value=10.0,
                             value=DEFAULT_ATH_TOLERANCE_PCT, step=0.5, key="mom_ath_tol",
                             help="How close to its own all-time high a stock's price must be. "
                                  "Backtested sweep showed loosening this (5-10%) improved both "
                                  "returns and drawdown vs a strict 0% — default kept at 2% as a "
                                  "middle ground, adjust and re-scan to compare.")
    with c2:
        top_n = st.number_input("Top-N holdings", min_value=5, max_value=50, value=DEFAULT_TOP_N,
                                 step=5, key="mom_top_n",
                                 help="Portfolio-sized shortlist size, by 52-week return rank. "
                                      "Backtest showed top-5 roughly doubled alpha vs top-15, at "
                                      "somewhat higher single-stock concentration risk.")

    run_scan = st.button("▶ Run Momentum Scan", type="primary", key="run_mom_scan_btn")

    if run_scan:
        syms = tuple(universe_symbols())
        _run_scan.clear()
        with st.spinner(f"Scanning {len(syms)} symbols across all 3 criteria "
                         f"(profit check runs only on stocks passing price + outperformance)…"):
            df_scan, fetch_ts = _run_scan(syms, ath_tol, int(top_n))
        st.session_state["mom_scan_df"] = df_scan
        st.session_state["mom_scan_ts"] = fetch_ts

    df_scan = st.session_state.get("mom_scan_df")
    fetch_ts = st.session_state.get("mom_scan_ts")

    if fetch_ts is not None:
        now_ist = pd.Timestamp.now(tz=_IST)
        age_mins = int((now_ist - fetch_ts).total_seconds() // 60)
        age_str = f"{age_mins} min ago" if age_mins > 0 else "just now"
        st.caption(f"📡 Scanned at **{fetch_ts.strftime('%d-%b-%Y %H:%M:%S')} IST** · {age_str} · "
                   f"Cache refreshes every 30 min on next Run")

    if df_scan is not None and not df_scan.empty:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Scanned", len(df_scan))
        m2.metric("BUY (3/3)", int((df_scan["decision"] == "BUY").sum()))
        m3.metric("HOLD (2/3)", int((df_scan["decision"] == "HOLD").sum()))
        m4.metric("AVOID (≤1/3)", int((df_scan["decision"] == "AVOID").sum()))

        show_cols = ["symbol", "sector", "price", "ret_1y_pct", "sector_ret_1y_pct", "bench_ret_1y_pct",
                     "score", "decision", "em_rank", "in_top_n"]
        st.dataframe(
            df_scan[show_cols].style
                .map(_decision_color, subset=["decision"])
                .format({"price": "₹{:,.2f}", "ret_1y_pct": "{:+.2f}%", "sector_ret_1y_pct": "{:+.2f}%",
                         "bench_ret_1y_pct": "{:+.2f}%"}, na_rep="—"),
            width='stretch', hide_index=True,
        )
    elif run_scan:
        st.info("No stocks scanned — check that the universe fetch succeeded and try again.")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — ALL-TIME-HIGH STOCKS (slices Tab 1's cached result, no re-scan)
# ═════════════════════════════════════════════════════════════════════════════
with tab_ath:
    st.caption("Criterion 1 only — stocks currently at/near their own all-time high, regardless of "
               "profit or relative-strength status. Reuses the Momentum Scan tab's results; run a "
               "scan there first if this is empty.")
    df_scan = st.session_state.get("mom_scan_df")
    if df_scan is not None and not df_scan.empty:
        ath_df = df_scan[df_scan["crit1_price_ath"]].sort_values("ret_1y_pct", ascending=False)
        if ath_df.empty:
            st.info("No stocks in the scanned universe are currently at/near an all-time high.")
        else:
            st.metric("Stocks at/near All-Time High", len(ath_df))
            show_cols2 = ["symbol", "sector", "price", "ret_1y_pct", "score", "decision", "em_rank"]
            st.dataframe(
                ath_df[show_cols2].style
                    .map(_decision_color, subset=["decision"])
                    .format({"price": "₹{:,.2f}", "ret_1y_pct": "{:+.2f}%"}, na_rep="—"),
                width='stretch', hide_index=True,
            )
    else:
        st.info("Run a scan on the **Momentum Scan** tab first — this tab reuses that result rather "
                "than fetching data twice.")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — SECTOR ROTATION MAP
# ═════════════════════════════════════════════════════════════════════════════
with tab_sector:
    st.caption("Reproduces the video's 'a different sector leads every period' point — no single "
               "sector held the #1 spot for long historically. Green = strongest sector that month, "
               "red = weakest.")
    months_back = st.slider("Months of history", min_value=6, max_value=36, value=24, step=6, key="mom_sector_months")
    run_sector = st.button("▶ Load Sector Rotation Map", type="primary", key="run_mom_sector_btn")

    if run_sector:
        _run_sector_rotation.clear()
        with st.spinner("Fetching sector index monthly returns…"):
            grid, fetch_ts_s = _run_sector_rotation(int(months_back))
        st.session_state["mom_sector_grid"] = grid
        st.session_state["mom_sector_ts"] = fetch_ts_s

    grid = st.session_state.get("mom_sector_grid")
    fetch_ts_s = st.session_state.get("mom_sector_ts")

    if fetch_ts_s is not None:
        st.caption(f"📡 Fetched at **{fetch_ts_s.strftime('%d-%b-%Y %H:%M:%S')} IST**")

    if grid is not None and not grid.empty:
        rank_grid = sector_leadership_rank(grid)
        fig = go.Figure(data=go.Heatmap(
            z=rank_grid.values,
            x=[c.strftime("%b %Y") for c in rank_grid.columns],
            y=rank_grid.index.tolist(),
            colorscale=[[0, "#00C853"], [0.5, "#FFD600"], [1, "#D50000"]],
            reversescale=False,
            colorbar=dict(title="Rank (1=best)"),
            hovertemplate="Sector: %{y}<br>Month: %{x}<br>Rank: %{z}<extra></extra>",
        ))
        fig.update_layout(height=560, margin=dict(l=10, r=10, t=30, b=10), template="plotly_dark")
        st.plotly_chart(fig, width='stretch', key="mom_sector_heatmap")

        st.markdown("##### Monthly #1 Sector")
        leaders = monthly_leaders(grid, top_k=1).sort_values("month", ascending=False)
        st.dataframe(leaders, width='stretch', hide_index=True)
    elif run_sector:
        st.info("No sector index data available — some SECTOR_INDICES tickers are known to be "
                "unavailable on yfinance (see config.py comments).")
