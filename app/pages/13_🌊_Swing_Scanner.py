from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

st.set_page_config(page_title="Swing Scanner | NSE Market Sector", layout="wide")

from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.seo import inject_seo
inject_seo("SwingScanner")
from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("Swing Scanner")

import pandas as pd
import yfinance as yf
import pytz as _pytz
import plotly.graph_objects as go

from backend.calculations.swing_scanner import add_swing_indicators, compute_swing_signal, SwingParams
from backend.calculations.hm_tv_chart import tv_chart_url
from backend.calculations.universe import load_symbols

_IST = _pytz.timezone("Asia/Kolkata")
_PERIOD = "2y"  # enough warm-up for SMA200; this strategy is daily-only, no timeframe selector


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_batch(symbols: tuple) -> dict:
    raw = yf.download(list(symbols), period=_PERIOD, interval="1d",
                      group_by="column", auto_adjust=True, progress=False, threads=True)
    result = {}
    if raw.empty:
        return result
    if isinstance(raw.columns, pd.MultiIndex):
        for sym in symbols:
            try:
                df_sym = raw.xs(sym, axis=1, level=1).dropna(how="all")
                if not df_sym.empty:
                    result[sym] = df_sym
            except Exception:
                pass
    else:
        if len(symbols) == 1:
            result[symbols[0]] = raw.dropna(how="all")
    return result


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_single(symbol: str) -> pd.DataFrame:
    raw = yf.download(symbol, period=_PERIOD, interval="1d", auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]
    return raw.dropna(how="all")


@st.cache_data(ttl=1800, show_spinner=False)
def _run_scan(symbols: tuple) -> tuple:
    raw_data = _fetch_batch(symbols)
    params = SwingParams()
    rows = []
    for sym in symbols:
        df_raw = raw_data.get(sym)
        if df_raw is None or df_raw.empty or len(df_raw) < params.sma_long + 20:
            continue
        try:
            df = compute_swing_signal(add_swing_indicators(df_raw, params), params)
            last = df.iloc[-1]
            if not bool(last["Stock_Pass"]):
                continue
            rows.append({
                "Symbol": tv_chart_url(sym, "1d"),
                "Close": round(float(last["Close"]), 2),
                "RSI": round(float(last["RSI"]), 1),
                "Score": int(last["Stock_Score"]),
                "Stop Loss": round(float(last["Stop_Loss"]), 2),
                "Target": round(float(last["Target"]), 2),
                "Vol Ratio": round(float(last["Volume"] / last["Volume_Avg"]), 2) if last["Volume_Avg"] else None,
            })
        except Exception:
            continue

    fetch_ts = pd.Timestamp.now(tz=_IST)
    return pd.DataFrame(rows), fetch_ts


def _render_price_chart(df: pd.DataFrame, symbol: str) -> None:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name=symbol, increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    ))
    for col, color in [("SMA_Short", "#60a5fa"), ("SMA_Med", "#fbbf24"), ("SMA_Long", "#f87171")]:
        fig.add_trace(go.Scatter(x=df.index, y=df[col], mode="lines", name=col.replace("_", " "),
                                  line=dict(color=color, width=1.3)))
    fig.update_layout(
        height=460, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, width='stretch', key="swing_price_chart")

    vol_fig = go.Figure()
    vol_fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume", marker_color="#64748b"))
    vol_fig.add_trace(go.Scatter(x=df.index, y=df["Volume_Avg"], mode="lines", name="Vol Avg(20)",
                                  line=dict(color="#fbbf24", width=1.3)))
    vol_fig.update_layout(height=160, margin=dict(l=10, r=10, t=10, b=10), template="plotly_dark",
                           showlegend=False)
    st.plotly_chart(vol_fig, width='stretch', key="swing_volume_chart")


# ─── Page title & disclaimer ─────────────────────────────────────────────────
st.title("🌊 Swing Scanner")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption(
    "Trend-pullback swing setup: uptrend (Close > SMA50 > SMA200) pulling back from overbought RSI "
    "into a 40-55 band near EMA20, on above-average volume with a bullish candle. This is the "
    "single variant that actually validated in a real Nifty 500 backtest (2020-2025: 526 trades, "
    "41.4% win rate, 25.5% CAGR, 1.27 Sharpe) — a sector/relative-strength-filtered version was also "
    "tested and performed worse, so it isn't offered here. Educational discovery tool, not a "
    "recommendation to buy or sell."
)

tab_scan, tab_single = st.tabs(["📡 Live Scan", "🔍 Single Stock"])

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — LIVE SCAN
# ═════════════════════════════════════════════════════════════════════════════
with tab_scan:
    universe = st.selectbox("Universe", ["Nifty 50", "Nifty 500"], key="swing_univ")
    run_scan = st.button("▶ Run Swing Scan", type="primary", key="run_swing_scan_btn")

    if run_scan:
        syms = tuple(load_symbols(universe))
        _run_scan.clear()
        with st.spinner(f"Scanning {len(syms)} symbols…"):
            df_scan, fetch_ts = _run_scan(syms)
        st.session_state["swing_scan_df"] = df_scan
        st.session_state["swing_scan_ts"] = fetch_ts

    df_scan = st.session_state.get("swing_scan_df")
    fetch_ts = st.session_state.get("swing_scan_ts")

    if fetch_ts is not None:
        now_ist = pd.Timestamp.now(tz=_IST)
        age_mins = int((now_ist - fetch_ts).total_seconds() // 60)
        age_str = f"{age_mins} min ago" if age_mins > 0 else "just now"
        st.caption(f"📡 Data fetched at **{fetch_ts.strftime('%d-%b-%Y %H:%M:%S')} IST** · {age_str} · Cache refreshes every 30 min on next Run")

    if df_scan is not None and not df_scan.empty:
        st.metric("Matches Found", len(df_scan))
        show_df = df_scan.sort_values(by="Score", ascending=False)
        _fmt = {c: "{:.2f}" for c in ["Close", "Stop Loss", "Target"]}
        _fmt.update({"RSI": "{:.1f}", "Vol Ratio": "{:.2f}"})
        st.dataframe(
            show_df.style.format(_fmt, na_rep="—"),
            width='stretch',
            hide_index=True,
            column_config={
                "Symbol": st.column_config.LinkColumn("Symbol", display_text=r"symbol=NSE:([^&]+)"),
            },
        )
    elif run_scan:
        st.info("No stocks matched this pattern today. Try switching to Nifty 500 for a larger universe.")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — SINGLE STOCK
# ═════════════════════════════════════════════════════════════════════════════
with tab_single:
    symbol_input = st.text_input("Symbol (.NS)", value="RELIANCE.NS", key="swing_single_sym_input").strip().upper()
    run_single = st.button("▶ Analyse", type="primary", key="run_swing_single_btn")

    if run_single:
        if not symbol_input.endswith(".NS"):
            symbol_input += ".NS"
        _fetch_single.clear()
        with st.spinner(f"Fetching {symbol_input}…"):
            df_raw = _fetch_single(symbol_input)
        if not df_raw.empty:
            params = SwingParams()
            df_s = compute_swing_signal(add_swing_indicators(df_raw, params), params)
            st.session_state["swing_single_df"] = df_s
            st.session_state["swing_single_sym"] = symbol_input
        else:
            st.warning(f"No data returned for {symbol_input}.")

    df_s = st.session_state.get("swing_single_df")
    sym_s = st.session_state.get("swing_single_sym", symbol_input)

    if df_s is not None and not df_s.empty:
        last = df_s.iloc[-1]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Close", f"₹{last['Close']:,.2f}")
        m2.metric("RSI(14)", f"{last['RSI']:.1f}")
        m3.metric("Score", f"{int(last['Stock_Score'])}/6")
        m4.metric("Status", "✅ Pass" if bool(last["Stock_Pass"]) else "❌ No match")

        _render_price_chart(df_s, sym_s)

        st.markdown("##### Condition breakdown (today)")
        cond_labels = {
            "Stock_Trend": "Uptrend (Close > SMA50 > SMA200)",
            "RSI_Pullback": "RSI pullback from overbought into 40-55",
            "EMA_Prox": "Price within 2% of EMA20",
            "Volume_Spike": "Volume above 20-day average",
            "Bullish_Candle": "Bullish candle (close>open, lower wick > upper wick)",
            "Liquidity": "Liquidity floor (price ≥ ₹50, avg volume ≥ 100k)",
        }
        cc1, cc2 = st.columns(2)
        for i, (col, label) in enumerate(cond_labels.items()):
            target = cc1 if i % 2 == 0 else cc2
            target.markdown(f"{'✅' if bool(last[col]) else '❌'} {label}")

        if bool(last["Stock_Pass"]):
            s1, s2 = st.columns(2)
            s1.metric("Reference Stop Loss", f"₹{last['Stop_Loss']:,.2f}")
            s2.metric("Reference Target (1:2 R:R)", f"₹{last['Target']:,.2f}")
            st.caption("Reference levels only, derived from today's Close/ATR — not a trade instruction.")

        tv_url = tv_chart_url(sym_s, "1d")
        st.link_button("📈 Open on TradingView", tv_url)
    elif run_single:
        st.warning(f"No data returned for {sym_s}. Check the symbol and try again.")
