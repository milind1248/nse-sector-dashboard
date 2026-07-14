from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

st.set_page_config(page_title="H-M Scanner | NSE Market Sector", layout="wide")

from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.seo import inject_seo
inject_seo("HMScanner")
from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("HM Scanner")

import numpy as np
import pandas as pd
import yfinance as yf
import pytz as _pytz

from backend.calculations.hm_indicators import add_indicators, generate_signals, attach_htf_regime
from backend.calculations.hm_backtest import backtest_signals, backtest_top_signals, summarize_backtests
from backend.calculations.hm_tv_chart import render_tv_chart, tv_chart_url, to_tv_symbol

_IST = _pytz.timezone("Asia/Kolkata")

INTERVAL_CONFIG = {
    "15m": {"period": "60d",  "hold": 20},
    "30m": {"period": "60d",  "hold": 16},
    "1h":  {"period": "730d", "hold": 10},
    "1d":  {"period": "5y",   "hold": 10},
    "1wk": {"period": "10y",  "hold": 8},
    "1mo": {"period": "max",  "hold": 6},
}
HIGHER_TIMEFRAME = {
    "15m": "1h", "30m": "1h", "1h": "1d",
    "1d": "1wk", "1wk": "1mo", "1mo": "1mo",
}

FALLBACK_NIFTY50 = [
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "AXISBANK.NS",
    "BAJAJ-AUTO.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "BEL.NS", "BHARTIARTL.NS",
    "CIPLA.NS", "COALINDIA.NS", "DRREDDY.NS", "EICHERMOT.NS", "ETERNAL.NS",
    "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS", "HEROMOTOCO.NS",
    "HINDALCO.NS", "HINDUNILVR.NS", "ICICIBANK.NS", "ITC.NS", "INDUSINDBK.NS",
    "INFY.NS", "JSWSTEEL.NS", "JIOFIN.NS", "KOTAKBANK.NS", "LT.NS",
    "M&M.NS", "MARUTI.NS", "NTPC.NS", "NESTLEIND.NS", "ONGC.NS",
    "POWERGRID.NS", "RELIANCE.NS", "SBILIFE.NS", "SHRIRAMFIN.NS", "SBIN.NS",
    "SUNPHARMA.NS", "TCS.NS", "TATACONSUM.NS", "TATAMOTORS.NS", "TATASTEEL.NS",
    "TECHM.NS", "TITAN.NS", "TRENT.NS", "ULTRACEMCO.NS", "WIPRO.NS",
]


def _load_symbols(universe: str) -> list[str]:
    if universe == "Nifty 50":
        return FALLBACK_NIFTY50
    try:
        from io import StringIO
        import requests
        url = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*",
                   "Referer": "https://www.niftyindices.com/"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        col = "Symbol" if "Symbol" in df.columns else df.columns[0]
        syms = [str(s).strip().upper() + ".NS" for s in df[col].dropna().tolist()]
        if len(syms) >= 400:
            return syms
    except Exception:
        pass
    return FALLBACK_NIFTY50


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_batch(symbols: tuple, interval: str, period: str) -> dict:
    raw = yf.download(list(symbols), period=period, interval=interval,
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
def _fetch_single(symbol: str, interval: str, period: str) -> pd.DataFrame:
    raw = yf.download(symbol, period=period, interval=interval,
                      auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]
    return raw.dropna(how="all")


@st.cache_data(ttl=1800, show_spinner=False)
def _run_scan(symbols: tuple, interval: str, min_score: int, mode: str, use_htf: bool) -> tuple:
    cfg = INTERVAL_CONFIG.get(interval, INTERVAL_CONFIG["1d"])
    period = cfg["period"]
    htf_interval = HIGHER_TIMEFRAME.get(interval, "1d")

    raw_data = _fetch_batch(symbols, interval, period)
    htf_data: dict = {}
    if use_htf and htf_interval != interval:
        htf_data = _fetch_batch(symbols, htf_interval, INTERVAL_CONFIG.get(htf_interval, {}).get("period", "5y"))

    rows = []
    for sym in symbols:
        df_raw = raw_data.get(sym)
        if df_raw is None or df_raw.empty:
            continue
        try:
            df = add_indicators(df_raw)
            if df.empty:
                continue
            if use_htf and sym in htf_data and not htf_data[sym].empty:
                htf_ind = add_indicators(htf_data[sym])
                df = attach_htf_regime(df, htf_ind)
            df = generate_signals(df, min_score=min_score, confirmation_mode=mode,
                                  use_htf_filter=use_htf)
            last = df.iloc[-1]
            recent_bottom = df["BOTTOM_SIGNAL"].iloc[-5:].any() if len(df) >= 5 else False
            recent_top = df["TOP_SIGNAL"].iloc[-5:].any() if len(df) >= 5 else False
            last_bot_date = df.index[df["BOTTOM_SIGNAL"].fillna(False)][-1] if df["BOTTOM_SIGNAL"].any() else None
            last_top_date = df.index[df["TOP_SIGNAL"].fillna(False)][-1] if df["TOP_SIGNAL"].any() else None

            if bool(last["BOTTOM_SIGNAL"]):
                sig = "BOTTOM"
                sig_type = "Current"
            elif bool(last["TOP_SIGNAL"]):
                sig = "TOP"
                sig_type = "Current"
            elif recent_bottom:
                sig = "BOTTOM"
                sig_type = "Recent (≤5 bars)"
            elif recent_top:
                sig = "TOP"
                sig_type = "Recent (≤5 bars)"
            else:
                sig = "—"
                sig_type = "—"

            rows.append({
                "Symbol": tv_chart_url(sym, interval),
                "Close": round(float(last["Close"]), 1),
                "RSI": round(float(last["RSI"]), 1) if not pd.isna(last["RSI"]) else None,
                "HM_EMA": round(float(last["HM_EMA"]), 1) if not pd.isna(last["HM_EMA"]) else None,
                "HM_WMA": round(float(last["HM_WMA"]), 1) if not pd.isna(last["HM_WMA"]) else None,
                "Bottom Score": round(float(last["BOTTOM_SCORE"]), 1),
                "Top Score": round(float(last["TOP_SCORE"]), 1),
                "Signal": sig,
                "Type": sig_type,
                "Last Bottom": last_bot_date.strftime("%d-%b-%y") if last_bot_date is not None else "—",
                "Last Top": last_top_date.strftime("%d-%b-%y") if last_top_date is not None else "—",
                "Range Pos": round(float(last["RANGE_POS"]), 1) if not pd.isna(last.get("RANGE_POS", float("nan"))) else None,
                "Vol Ratio": round(float(last["VOL_RATIO"]), 1) if not pd.isna(last.get("VOL_RATIO", float("nan"))) else None,
                "Reason": str(last.get("SIGNAL_REASON", "")),
            })
        except Exception:
            continue

    fetch_ts = pd.Timestamp.now(tz=_IST)
    return pd.DataFrame(rows), fetch_ts


@st.cache_data(ttl=1800, show_spinner=False)
def _analyze_single(symbol: str, interval: str, min_score: int, mode: str, use_htf: bool) -> tuple:
    cfg = INTERVAL_CONFIG.get(interval, INTERVAL_CONFIG["1d"])
    period = cfg["period"]
    htf_interval = HIGHER_TIMEFRAME.get(interval, "1d")

    df_raw = _fetch_single(symbol, interval, period)
    if df_raw.empty:
        return pd.DataFrame(), None

    df = add_indicators(df_raw)
    if df.empty:
        return pd.DataFrame(), None

    if use_htf and htf_interval != interval:
        htf_raw = _fetch_single(symbol, htf_interval, INTERVAL_CONFIG.get(htf_interval, {}).get("period", "5y"))
        if not htf_raw.empty:
            htf_ind = add_indicators(htf_raw)
            df = attach_htf_regime(df, htf_ind)

    df = generate_signals(df, min_score=min_score, confirmation_mode=mode, use_htf_filter=use_htf)
    fetch_ts = pd.Timestamp.now(tz=_IST)
    return df, fetch_ts


@st.cache_data(ttl=1800, show_spinner=False)
def _run_backtest(symbols: tuple, interval: str, min_score: int, mode: str,
                  hold_bars: int, stop_atr: float, target_atr: float) -> tuple:
    cfg = INTERVAL_CONFIG.get(interval, INTERVAL_CONFIG["1d"])
    period = cfg["period"]

    raw_data = _fetch_batch(symbols, interval, period)
    all_trades: list[pd.DataFrame] = []
    all_top_trades: list[pd.DataFrame] = []

    for sym in symbols:
        df_raw = raw_data.get(sym)
        if df_raw is None or df_raw.empty:
            continue
        try:
            df = add_indicators(df_raw)
            if df.empty:
                continue
            df = generate_signals(df, min_score=min_score, confirmation_mode=mode)
            bot_trades = backtest_signals(df, sym, hold_bars=hold_bars,
                                          stop_atr=stop_atr, target_atr=target_atr)
            top_trades = backtest_top_signals(df, sym, hold_bars=hold_bars,
                                              stop_atr=stop_atr, target_atr=target_atr)
            if not bot_trades.empty:
                all_trades.append(bot_trades)
            if not top_trades.empty:
                all_top_trades.append(top_trades)
        except Exception:
            continue

    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    top_trades = pd.concat(all_top_trades, ignore_index=True) if all_top_trades else pd.DataFrame()
    summary = summarize_backtests(trades) if not trades.empty else pd.DataFrame()
    top_summary = summarize_backtests(top_trades) if not top_trades.empty else pd.DataFrame()
    fetch_ts = pd.Timestamp.now(tz=_IST)
    return trades, summary, top_trades, top_summary, fetch_ts


def _color_signal_row(row):
    sig = str(row.get("Signal", ""))
    typ = str(row.get("Type", ""))
    if sig == "BOTTOM" and typ == "Current":
        return ["background-color:#052e16; color:#4ade80"] * len(row)
    if sig == "TOP" and typ == "Current":
        return ["background-color:#450a0a; color:#f87171"] * len(row)
    if sig == "BOTTOM" and "Recent" in typ:
        return ["background-color:#1c3a1c; color:#86efac"] * len(row)
    if sig == "TOP" and "Recent" in typ:
        return ["background-color:#3b1515; color:#fca5a5"] * len(row)
    return [""] * len(row)


def _color_outcome(val):
    v = str(val)
    if v == "target":
        return "color:#4ade80"
    if v == "stop":
        return "color:#f87171"
    if v == "time_exit":
        return "color:#fbbf24"
    return ""



# ─── Page title & disclaimer ─────────────────────────────────────────────────
st.title("🔭 H-M Scanner")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption("Hilega-Milega System — RSI(9)/WMA(21)/EMA(3) signal scanner. Educational use only.")

tab_scan, tab_single, tab_bt = st.tabs(["📡 Live Scan", "🔍 Single Stock", "📈 Backtest"])

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — LIVE SCAN
# ═════════════════════════════════════════════════════════════════════════════
with tab_scan:
    with st.expander("⚙️ Scan Settings", expanded=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        universe = c1.selectbox("Universe", ["Nifty 50", "Nifty 500"], key="scan_univ")
        interval = c2.selectbox("Timeframe", list(INTERVAL_CONFIG.keys()), index=3, key="scan_tf")
        min_score = c3.slider("Min Score", 50, 95, 70, key="scan_score")
        mode = c4.selectbox("Mode", ["Early", "Balanced", "Strict"], index=1, key="scan_mode")
        use_htf = c5.checkbox("HTF Filter", value=False, key="scan_htf")
        sig_filter = st.multiselect(
            "Show signals", ["BOTTOM", "TOP", "—"], default=["BOTTOM", "TOP"],
            key="scan_sig_filter",
        )

    run_scan = st.button("▶ Run H-M Scan", type="primary", key="run_scan_btn")

    if run_scan:
        syms = tuple(_load_symbols(universe))
        _run_scan.clear()
        with st.spinner(f"Scanning {len(syms)} symbols…"):
            df_scan, fetch_ts = _run_scan(syms, interval, min_score, mode, use_htf)
        st.session_state["hm_scan_df"] = df_scan
        st.session_state["hm_scan_fetch_ts"] = fetch_ts

    df_scan = st.session_state.get("hm_scan_df")
    fetch_ts = st.session_state.get("hm_scan_fetch_ts")

    if fetch_ts is not None:
        now_ist = pd.Timestamp.now(tz=_IST)
        age_mins = int((now_ist - fetch_ts).total_seconds() // 60)
        age_str = f"{age_mins} min ago" if age_mins > 0 else "just now"
        st.caption(f"📡 Data fetched at **{fetch_ts.strftime('%d-%b-%Y %H:%M:%S')} IST** · {age_str} · Cache refreshes every 30 min on next Run")

    if df_scan is not None and not df_scan.empty:
        n_bottom = (df_scan["Signal"] == "BOTTOM").sum()
        n_top = (df_scan["Signal"] == "TOP").sum()
        n_none = (df_scan["Signal"] == "—").sum()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Scanned", len(df_scan))
        m2.metric("Bottom Signals", n_bottom)
        m3.metric("Top Signals", n_top)
        m4.metric("No Signal", n_none)

        show_df = df_scan[df_scan["Signal"].isin(sig_filter)] if sig_filter else df_scan
        show_df = show_df.sort_values(
            by=["Signal", "Bottom Score"],
            key=lambda col: col.map({"BOTTOM": 0, "TOP": 1, "—": 2}) if col.name == "Signal" else col,
            ascending=[True, False],
        )
        _fmt = {c: "{:.1f}" for c in ["Close", "RSI", "HM_EMA", "HM_WMA", "Range Pos", "Vol Ratio"]
                if c in show_df.columns}
        _fmt.update({c: "{:.0f}" for c in ["Bottom Score", "Top Score"] if c in show_df.columns})
        styled = show_df.style.apply(_color_signal_row, axis=1).format(_fmt, na_rep="—")
        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Symbol": st.column_config.LinkColumn(
                    "Symbol",
                    display_text=r"symbol=NSE:([^&]+)",
                ),
            },
        )


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — SINGLE STOCK
# ═════════════════════════════════════════════════════════════════════════════
with tab_single:
    c1, c2, c3, c4, c5 = st.columns(5)
    symbol_input = c1.text_input("Symbol (.NS)", value="RELIANCE.NS", key="single_sym").strip().upper()
    interval_s = c2.selectbox("Timeframe", list(INTERVAL_CONFIG.keys()), index=3, key="single_tf")
    min_score_s = c3.slider("Min Score", 50, 95, 70, key="single_score")
    mode_s = c4.selectbox("Mode", ["Early", "Balanced", "Strict"], index=1, key="single_mode")
    use_htf_s = c5.checkbox("HTF Filter", value=False, key="single_htf")

    run_single = st.button("▶ Analyse", type="primary", key="run_single_btn")

    if run_single:
        if not symbol_input.endswith(".NS"):
            symbol_input += ".NS"
        _analyze_single.clear()
        with st.spinner(f"Fetching {symbol_input}…"):
            df_s, fetch_ts_s = _analyze_single(symbol_input, interval_s, min_score_s, mode_s, use_htf_s)
        st.session_state["hm_single_df"] = df_s
        st.session_state["hm_single_sym"] = symbol_input
        st.session_state["hm_single_ts"] = fetch_ts_s

    df_s = st.session_state.get("hm_single_df")
    sym_s = st.session_state.get("hm_single_sym", symbol_input)
    fetch_ts_s = st.session_state.get("hm_single_ts")

    if df_s is not None and not df_s.empty:
        if fetch_ts_s is not None:
            now_ist = pd.Timestamp.now(tz=_IST)
            age_mins = int((now_ist - fetch_ts_s).total_seconds() // 60)
            age_str = f"{age_mins} min ago" if age_mins > 0 else "just now"
            st.caption(f"📡 Data fetched at **{fetch_ts_s.strftime('%d-%b-%Y %H:%M:%S')} IST** · {age_str}")

        last = df_s.iloc[-1]
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Bottom Score", f"{last.get('BOTTOM_SCORE', 0):.1f}")
        m2.metric("Top Score", f"{last.get('TOP_SCORE', 0):.1f}")
        m3.metric("RSI(9)", f"{last.get('RSI', 0):.1f}")
        m4.metric("HM_EMA", f"{last.get('HM_EMA', 0):.1f}")
        m5.metric("HM_WMA", f"{last.get('HM_WMA', 0):.1f}")

        # Signals per year table
        df_s_copy = df_s.copy()
        df_s_copy["Year"] = df_s_copy.index.year
        per_year = df_s_copy.groupby("Year").agg(
            Bottom_Signals=("BOTTOM_SIGNAL", "sum"),
            Top_Signals=("TOP_SIGNAL", "sum"),
        ).reset_index().rename(columns={"Bottom_Signals": "Bottom Signals", "Top_Signals": "Top Signals"})
        per_year["Year"] = per_year["Year"].astype(str)

        with st.expander("📅 Signals per Year", expanded=False):
            st.dataframe(per_year, use_container_width=True, hide_index=True)

        # TradingView link
        tv_url = tv_chart_url(sym_s, interval_s)
        st.link_button("📈 Open on TradingView", tv_url)

        # TradingView Lightweight Chart
        render_tv_chart(df_s, sym_s, main_height=460, osc_height=200, max_bars=500)

        # Recent signal tables
        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("##### 🟢 Recent Bottom Signals")
            bot_sigs = df_s[df_s["BOTTOM_SIGNAL"].fillna(False)].tail(20)[
                ["Close", "RSI", "HM_EMA", "HM_WMA", "BOTTOM_SCORE", "SIGNAL_REASON"]
            ].copy()
            bot_sigs.index = bot_sigs.index.strftime("%d-%b-%y")
            bot_sigs.columns = ["Close", "RSI", "EMA3", "WMA21", "Score", "Reason"]
            if not bot_sigs.empty:
                _fmt_s = {c: ("{:.0f}" if c == "Score" else "{:.1f}") for c in bot_sigs.columns if bot_sigs[c].dtype.kind == "f"}
                st.dataframe(bot_sigs.sort_index(ascending=False).style.format(_fmt_s, na_rep="—"),
                             use_container_width=True)
            else:
                st.info("No bottom signals in this period.")

        with col_r:
            st.markdown("##### 🔴 Recent Top Signals")
            top_sigs = df_s[df_s["TOP_SIGNAL"].fillna(False)].tail(20)[
                ["Close", "RSI", "HM_EMA", "HM_WMA", "TOP_SCORE", "TOP_SIGNAL_REASON"]
            ].copy()
            top_sigs.index = top_sigs.index.strftime("%d-%b-%y")
            top_sigs.columns = ["Close", "RSI", "EMA3", "WMA21", "Score", "Reason"]
            if not top_sigs.empty:
                _fmt_s = {c: "{:.1f}" for c in top_sigs.columns if top_sigs[c].dtype.kind == "f"}
                st.dataframe(top_sigs.sort_index(ascending=False).style.format(_fmt_s, na_rep="—"),
                             use_container_width=True)
            else:
                st.info("No top signals in this period.")
    elif run_single:
        st.warning(f"No data returned for {sym_s}. Check the symbol and try again.")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — BACKTEST
# ═════════════════════════════════════════════════════════════════════════════
with tab_bt:
    with st.expander("⚙️ Backtest Settings", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        bt_universe = c1.selectbox("Universe", ["Nifty 50", "Nifty 500"], key="bt_univ")
        bt_interval = c2.selectbox("Timeframe", list(INTERVAL_CONFIG.keys()), index=3, key="bt_tf")
        bt_score = c3.slider("Min Score", 50, 95, 70, key="bt_score")
        bt_mode = c4.selectbox("Mode", ["Early", "Balanced", "Strict"], index=1, key="bt_mode")

        c5, c6, c7 = st.columns(3)
        bt_hold = c5.slider("Hold Bars", 3, 30, 10, key="bt_hold",
                             help="Bars to hold after entry before time exit")
        bt_stop_atr = c6.number_input("Stop ATR ×", min_value=0.5, max_value=5.0,
                                       value=1.5, step=0.25, key="bt_stop_atr")
        bt_target_atr = c7.number_input("Target ATR ×", min_value=0.5, max_value=8.0,
                                         value=2.0, step=0.25, key="bt_target_atr")

    run_bt = st.button("▶ Run Backtest", type="primary", key="run_bt_btn")

    if run_bt:
        bt_syms = tuple(_load_symbols(bt_universe))
        _run_backtest.clear()
        with st.spinner(f"Backtesting {len(bt_syms)} symbols…"):
            bt_trades, bt_summary, bt_top_trades, bt_top_summary, bt_ts = _run_backtest(
                bt_syms, bt_interval, bt_score, bt_mode,
                bt_hold, float(bt_stop_atr), float(bt_target_atr),
            )
        st.session_state["hm_bt_trades"] = bt_trades
        st.session_state["hm_bt_summary"] = bt_summary
        st.session_state["hm_bt_top_trades"] = bt_top_trades
        st.session_state["hm_bt_top_summary"] = bt_top_summary
        st.session_state["hm_bt_ts"] = bt_ts

    bt_trades = st.session_state.get("hm_bt_trades")
    bt_summary = st.session_state.get("hm_bt_summary")
    bt_top_trades = st.session_state.get("hm_bt_top_trades")
    bt_top_summary = st.session_state.get("hm_bt_top_summary")
    bt_ts = st.session_state.get("hm_bt_ts")

    if bt_ts is not None:
        now_ist = pd.Timestamp.now(tz=_IST)
        age_mins = int((now_ist - bt_ts).total_seconds() // 60)
        age_str = f"{age_mins} min ago" if age_mins > 0 else "just now"
        st.caption(f"📡 Data fetched at **{bt_ts.strftime('%d-%b-%Y %H:%M:%S')} IST** · {age_str} · Cache refreshes every 30 min on next Run")

    if bt_summary is not None and not bt_summary.empty:
        st.markdown("#### 🟢 Bottom Signal Backtest")

        total_trades = len(bt_trades)
        win_rate = (bt_trades["return_pct"] > 0).mean() * 100 if total_trades > 0 else 0
        avg_ret = bt_trades["return_pct"].mean() if total_trades > 0 else 0
        best_sym = bt_summary.iloc[0]["symbol"] if not bt_summary.empty else "—"

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Trades", total_trades)
        m2.metric("Overall Win Rate", f"{win_rate:.1f}%")
        m3.metric("Avg Return", f"{avg_ret:.2f}%")
        m4.metric("Best Stock (Response Score)", best_sym)

        # Summary table
        disp_cols = ["symbol", "signals", "win_rate_%", "target_rate_%",
                     "avg_return_%", "median_mfe_%", "avg_score", "response_score"]
        cols_rename = {
            "symbol": "Symbol", "signals": "Signals",
            "win_rate_%": "Win Rate%", "target_rate_%": "Target Rate%",
            "avg_return_%": "Avg Return%", "median_mfe_%": "Median MFE%",
            "avg_score": "Avg Score", "response_score": "Response Score",
        }
        show_summary = bt_summary[disp_cols].rename(columns=cols_rename)
        _fmt_sum = {c: ("{:.0f}" if c == "Signals" else "{:.1f}") for c in show_summary.columns if show_summary[c].dtype.kind in ("f", "i") and c != "Symbol"}
        st.dataframe(show_summary.style.format(_fmt_sum, na_rep="—"), use_container_width=True, hide_index=True)

        # Trade log
        with st.expander("📋 Trade Log (Bottom Signals)", expanded=False):
            if not bt_trades.empty:
                tl = bt_trades.copy()
                tl["signal_time"] = pd.to_datetime(tl["signal_time"]).dt.strftime("%d-%b-%y")
                tl["entry_time"] = pd.to_datetime(tl["entry_time"]).dt.strftime("%d-%b-%y")
                tl["exit_time"] = pd.to_datetime(tl["exit_time"]).dt.strftime("%d-%b-%y")
                for col in ["entry", "exit", "return_pct", "mfe_pct", "mae_pct", "score", "rsi"]:
                    if col in tl.columns:
                        tl[col] = tl[col].round(1)
                tl = tl.rename(columns={
                    "symbol": "Symbol", "signal_time": "Signal Date",
                    "entry_time": "Entry Date", "exit_time": "Exit Date",
                    "entry": "Entry", "exit": "Exit",
                    "return_pct": "Return%", "mfe_pct": "MFE%", "mae_pct": "MAE%",
                    "outcome": "Outcome", "score": "Score", "rsi": "RSI", "reason": "Reason",
                })
                _fmt_tl = {c: "{:.1f}" for c in tl.columns if tl[c].dtype.kind == "f"}
                styled_tl = tl.style.map(_color_outcome, subset=["Outcome"]).format(_fmt_tl, na_rep="—")
                st.dataframe(styled_tl, use_container_width=True, hide_index=True)
                csv_data = tl.to_csv(index=False).encode("utf-8")
                st.download_button("⬇ Download CSV", csv_data, "hm_bottom_backtest.csv", "text/csv")

    if bt_top_summary is not None and not bt_top_summary.empty:
        st.markdown("#### 🔴 Top Signal Backtest (Short)")

        total_top = len(bt_top_trades)
        win_rate_top = (bt_top_trades["return_pct"] > 0).mean() * 100 if total_top > 0 else 0
        avg_ret_top = bt_top_trades["return_pct"].mean() if total_top > 0 else 0
        best_top = bt_top_summary.iloc[0]["symbol"] if not bt_top_summary.empty else "—"

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Trades", total_top)
        m2.metric("Overall Win Rate", f"{win_rate_top:.1f}%")
        m3.metric("Avg Return", f"{avg_ret_top:.2f}%")
        m4.metric("Best Stock (Response Score)", best_top)

        disp_cols = ["symbol", "signals", "win_rate_%", "target_rate_%",
                     "avg_return_%", "median_mfe_%", "avg_score", "response_score"]
        show_top_summary = bt_top_summary[disp_cols].rename(columns={
            "symbol": "Symbol", "signals": "Signals",
            "win_rate_%": "Win Rate%", "target_rate_%": "Target Rate%",
            "avg_return_%": "Avg Return%", "median_mfe_%": "Median MFE%",
            "avg_score": "Avg Score", "response_score": "Response Score",
        })
        st.dataframe(show_top_summary, use_container_width=True, hide_index=True)

        with st.expander("📋 Trade Log (Top Signals)", expanded=False):
            if not bt_top_trades.empty:
                tl = bt_top_trades.copy()
                tl["signal_time"] = pd.to_datetime(tl["signal_time"]).dt.strftime("%d-%b-%y")
                tl["entry_time"] = pd.to_datetime(tl["entry_time"]).dt.strftime("%d-%b-%y")
                tl["exit_time"] = pd.to_datetime(tl["exit_time"]).dt.strftime("%d-%b-%y")
                tl["return_pct"] = tl["return_pct"].round(2)
                tl = tl.rename(columns={
                    "symbol": "Symbol", "signal_time": "Signal Date",
                    "entry_time": "Entry Date", "exit_time": "Exit Date",
                    "entry": "Entry", "exit": "Exit",
                    "return_pct": "Return%", "mfe_pct": "MFE%", "mae_pct": "MAE%",
                    "outcome": "Outcome", "score": "Score", "rsi": "RSI", "reason": "Reason",
                })
                _fmt_tl = {c: "{:.1f}" for c in tl.columns if tl[c].dtype.kind == "f"}
                styled_tl = tl.style.map(_color_outcome, subset=["Outcome"]).format(_fmt_tl, na_rep="—")
                st.dataframe(styled_tl, use_container_width=True, hide_index=True)
                csv_data = tl.to_csv(index=False).encode("utf-8")
                st.download_button("⬇ Download CSV", csv_data, "hm_top_backtest.csv", "text/csv")

    elif run_bt and (bt_summary is None or bt_summary.empty):
        st.warning("No signals found for the selected settings. Try lowering Min Score or switching to Early mode.")
