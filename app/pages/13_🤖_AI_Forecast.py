"""AI Stock Price Forecasting — Prophet trend + XGBoost direction ensemble."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import datetime
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import SECTOR_STOCKS

st.set_page_config(page_title="AI Forecast | NSE Stock Prediction | Market Sector Analysis", page_icon="🤖", layout="wide")
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()
from app.utils.seo import inject_seo
inject_seo("AI_Forecast")
from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("AI Forecast")

st.title("🤖 AI Stock Price Forecast")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption(
    "Prophet trend model + XGBoost direction classifier trained on 90+ technical features. "
    "Backtest accuracy shown is walk-forward out-of-sample — not in-sample. "
    "For educational and research purposes only."
)

# ── Pre-populated aligned signals scan (DB-backed, cook-once) ────────────────
from backend.storage.ai_scan_db import load_latest_scan, store_scan, scan_age_days
from backend.storage.ai_forecast_db import load_all_latest, cache_age_days
from app.utils.auth import is_admin

# Build deduplicated stock list from all dashboard stocks
_seen: set = set()
_scan_stock_list: list[tuple[str, str]] = []
for _sec, _syms in sorted(SECTOR_STOCKS.items()):
    for _sym in _syms:
        _s = _sym.replace(".NS", "")
        if _s not in _seen:
            _seen.add(_s)
            _scan_stock_list.append((_s, _sec))
_n_stocks = len(_scan_stock_list)

def _signal_color(v):
    if "Strong Buy"  in str(v): return "color:#00C853;font-weight:700"
    if "Buy"         in str(v): return "color:#69F0AE;font-weight:600"
    if "Strong Sell" in str(v): return "color:#D50000;font-weight:700"
    if "Sell"        in str(v): return "color:#FF6D00;font-weight:600"
    return ""

def _prob_color(v):
    if not isinstance(v, (int, float)): return ""
    if v >= 65: return "color:#00C853;font-weight:700"
    if v >= 55: return "color:#69F0AE"
    if v <= 35: return "color:#D50000;font-weight:700"
    if v <= 45: return "color:#FF6D00"
    return ""

with st.expander("📋 Aligned Signals — All Dashboard Stocks (Both Models Agree)", expanded=True):

    # ── Header row: last scan info + refresh button ───────────────────────────
    age = cache_age_days()
    h1, h2 = st.columns([5, 2])
    with h1:
        if age is None:
            st.caption(f"🕐 No forecast data yet — auto-scan runs daily at **9 PM IST** via scheduler. Click **Force Scan** to run now (~15 min).")
        elif age == 0:
            st.caption(f"✅ Forecast computed **today** across {_n_stocks} stocks · Auto-refreshes nightly at 9 PM IST · For research only.")
        elif age <= 2:
            st.caption(f"✅ Last computed **{age} day(s) ago** · Auto-refreshes nightly · {_n_stocks} stocks · For research only.")
        else:
            st.caption(f"⚠️ Last computed **{age} day(s) ago** — scheduler may be offline. Click **Force Scan** to refresh manually.")
    with h2:
        if is_admin():
            run_scan_btn = st.button("⚡ Force Scan", type="secondary", width='stretch',
                                     help=f"Admin only. Runs Prophet + XGBoost for all {_n_stocks} stocks and caches results (~15 min).")
        else:
            run_scan_btn = False
            st.caption("🔒 Admin only")

    # ── Run pipeline if button clicked ────────────────────────────────────────
    if run_scan_btn:
        from backend.data_ingestion.ai_scan_pipeline import run_ai_scan_pipeline
        with st.spinner(f"Running Prophet + XGBoost for {_n_stocks} stocks — please wait (~15 min)…"):
            summary = run_ai_scan_pipeline(triggered_by="manual")
        st.success(
            f"✅ Done — {summary['cached']} stocks cached "
            f"({summary['bullish']} bullish · {summary['bearish']} bearish aligned · {summary['failed']} failed)"
        )
        st.cache_data.clear()
        st.rerun()

    # ── Load from ai_forecast_cache and display aligned signals ───────────────
    all_cached = load_all_latest()

    if all_cached:
        full_df = pd.DataFrame(all_cached)

        # 3-way alignment: XGB + Prophet must agree; ARIMA counts as third vote when available
        def _bullish_aligned(row):
            xgb_up  = row.get("Direction") == "UP"
            proph   = row.get("Prophet Trend") == "Bullish"
            arima   = row.get("ARIMA Trend") in ("Bullish", None)
            return xgb_up and proph and arima

        def _bearish_aligned(row):
            xgb_dn  = row.get("Direction") == "DOWN"
            proph   = row.get("Prophet Trend") == "Bearish"
            arima   = row.get("ARIMA Trend") in ("Bearish", None)
            return xgb_dn and proph and arima

        bullish_df = full_df[full_df.apply(_bullish_aligned, axis=1)].reset_index(drop=True)
        bearish_df = full_df[full_df.apply(_bearish_aligned, axis=1)].reset_index(drop=True)
        show_cols  = ["Symbol", "Sector", "Price (₹)", "XGB Prob", "Signal", "Accuracy %", "Prophet Trend", "ARIMA Trend"]

        col_b, col_s = st.columns(2)
        with col_b:
            st.markdown(f"#### 🟢 All Models Bullish &nbsp;<span style='font-size:13px;color:#888'>({len(bullish_df)} stocks)</span>", unsafe_allow_html=True)
            if not bullish_df.empty:
                st.dataframe(
                    bullish_df[show_cols].style
                        .map(_signal_color, subset=["Signal"])
                        .map(_prob_color,   subset=["XGB Prob"])
                        .format({"XGB Prob": "{:.1f}%", "Price (₹)": "₹{:,.1f}", "Accuracy %": "{:.1f}%"}),
                    width='stretch', hide_index=True,
                )
            else:
                st.info("No bullish aligned signals in last scan.")

        with col_s:
            st.markdown(f"#### 🔴 All Models Bearish &nbsp;<span style='font-size:13px;color:#888'>({len(bearish_df)} stocks)</span>", unsafe_allow_html=True)
            if not bearish_df.empty:
                st.dataframe(
                    bearish_df[show_cols].style
                        .map(_signal_color, subset=["Signal"])
                        .map(_prob_color,   subset=["XGB Prob"])
                        .format({"XGB Prob": "{:.1f}%", "Price (₹)": "₹{:,.1f}", "Accuracy %": "{:.1f}%"}),
                    width='stretch', hide_index=True,
                )
            else:
                st.info("No bearish aligned signals in last scan.")
    else:
        st.info(f"No forecast data yet — scheduler runs automatically at 9 PM IST. Click **⚡ Force Scan** above to run now.")

st.markdown("---")

# ── Nifty 50 / dashboard-universe news sentiment (DB-backed, cook-once) ──────
_NIFTY50_SYMBOLS = {
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC", "INDUSINDBK",
    "INFY", "JSWSTEEL", "JIOFIN", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NTPC", "NESTLEIND", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN",
    "SUNPHARMA", "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
}

with st.expander("📰 News Sentiment — Nifty 50", expanded=False):
    try:
        from backend.storage.sentiment_db import load_all_latest as _load_sent_all, cache_age_days as _sent_age
        from app.utils.auth import is_admin as _is_admin_sent

        _sent_age_days = _sent_age()
        sh1, sh2 = st.columns([5, 2])
        with sh1:
            if _sent_age_days is None:
                st.caption("🕐 No sentiment data yet — auto-scan runs daily at **9:45 PM IST** via scheduler. Click **Force Scan** to run now.")
            elif _sent_age_days == 0:
                st.caption("✅ Sentiment computed **today** · Auto-refreshes nightly at 9:45 PM IST · VADER + finance-lexicon scoring on Google News RSS headlines. For research only, not investment advice.")
            elif _sent_age_days <= 2:
                st.caption(f"✅ Last computed **{_sent_age_days} day(s) ago** · Auto-refreshes nightly.")
            else:
                st.caption(f"⚠️ Last computed **{_sent_age_days} day(s) ago** — scheduler may be offline. Click **Force Scan** to refresh.")
        with sh2:
            if _is_admin_sent():
                _run_sent_scan = st.button("⚡ Force Scan", type="secondary", width='stretch',
                                           key="sent_force_scan",
                                           help="Admin only. Fetches + scores news for every dashboard stock.")
            else:
                _run_sent_scan = False
                st.caption("🔒 Admin only")

        if _run_sent_scan:
            from backend.data_ingestion.sentiment_pipeline import run_sentiment_scan_pipeline
            with st.spinner("Fetching + scoring news headlines for all dashboard stocks…"):
                _sent_summary = run_sentiment_scan_pipeline(triggered_by="manual")
            st.success(
                f"✅ Done — {_sent_summary['bullish']} bullish · {_sent_summary['bearish']} bearish · "
                f"{_sent_summary['neutral']} neutral · {_sent_summary['failed']} failed"
            )
            st.cache_data.clear()
            st.rerun()

        # ── Market Sentiment Overview — aggregate gauge + top movers ────────
        try:
            from backend.storage.sentiment_db import market_sentiment_summary as _mkt_summary
            _mkt = _mkt_summary()
        except Exception:
            _mkt = {}

        if _mkt:
            st.markdown("#### 🌡️ Market Sentiment Overview")
            _card = ("background:#1a2236;border-radius:10px;padding:18px 16px;text-align:center;"
                    "min-height:110px;display:flex;flex-direction:column;justify-content:center")
            _mkt_color = {"Bullish": "#00C853", "Bearish": "#D50000"}.get(_mkt["label"], "#FFD600")

            ov1, ov2, ov3, ov4 = st.columns(4)
            ov1.markdown(f"""<div style='{_card};border-left:4px solid {_mkt_color}'>
              <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Overall Market Sentiment</div>
              <div style='color:{_mkt_color};font-size:26px;font-weight:700'>{_mkt['label']}</div>
              <div style='color:#ccc;font-size:13px;margin-top:4px'>Avg score {_mkt['avg_score']:+.3f}</div>
            </div>""", unsafe_allow_html=True)

            if _mkt["score_change"] is not None:
                _chg = _mkt["score_change"]
                _chg_color = "#00C853" if _chg > 0 else ("#D50000" if _chg < 0 else "#8899bb")
                _chg_arrow = "▲" if _chg > 0 else ("▼" if _chg < 0 else "—")
                ov2.markdown(f"""<div style='{_card};border-left:4px solid {_chg_color}'>
                  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>vs. Previous Scan</div>
                  <div style='color:{_chg_color};font-size:26px;font-weight:700'>{_chg_arrow} {_chg:+.3f}</div>
                  <div style='color:#ccc;font-size:13px;margin-top:4px'>Prior avg {_mkt['prev_avg_score']:+.3f}</div>
                </div>""", unsafe_allow_html=True)
            else:
                ov2.markdown(f"""<div style='{_card};border-left:4px solid #8899bb'>
                  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>vs. Previous Scan</div>
                  <div style='color:#8899bb;font-size:20px;font-weight:700'>Not enough history yet</div>
                  <div style='color:#ccc;font-size:13px;margin-top:4px'>Available after tomorrow's scan</div>
                </div>""", unsafe_allow_html=True)

            ov3.markdown(f"""<div style='{_card};border-left:4px solid #00C853'>
              <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Bullish</div>
              <div style='color:#00C853;font-size:26px;font-weight:700'>{_mkt['bullish']} <span style='font-size:15px'>({_mkt['bullish_pct']:.0f}%)</span></div>
              <div style='color:#ccc;font-size:13px;margin-top:4px'>of {_mkt['total']} stocks</div>
            </div>""", unsafe_allow_html=True)

            ov4.markdown(f"""<div style='{_card};border-left:4px solid #D50000'>
              <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Bearish</div>
              <div style='color:#D50000;font-size:26px;font-weight:700'>{_mkt['bearish']} <span style='font-size:15px'>({_mkt['bearish_pct']:.0f}%)</span></div>
              <div style='color:#ccc;font-size:13px;margin-top:4px'>of {_mkt['total']} stocks</div>
            </div>""", unsafe_allow_html=True)

            st.caption(f"As of {_mkt['scan_date']} · {_mkt['neutral']} neutral ({_mkt['neutral_pct']:.0f}%)")
            st.markdown("---")

        _sent_rows = _load_sent_all()
        if _sent_rows:
            _sent_df_all = pd.DataFrame(_sent_rows)

            if len(_sent_df_all) >= 2:
                _mv_col1, _mv_col2 = st.columns(2)
                with _mv_col1:
                    st.markdown("**🟢 Top 5 Bullish Movers**")
                    _top_bull = _sent_df_all.nlargest(5, "Score")[["Symbol", "Sector", "Score", "Sentiment"]]
                    st.dataframe(_top_bull.style.format({"Score": "{:+.3f}"}), width='stretch', hide_index=True)
                with _mv_col2:
                    st.markdown("**🔴 Top 5 Bearish Movers**")
                    _top_bear = _sent_df_all.nsmallest(5, "Score")[["Symbol", "Sector", "Score", "Sentiment"]]
                    st.dataframe(_top_bear.style.format({"Score": "{:+.3f}"}), width='stretch', hide_index=True)
                st.markdown("---")

            fc0, fc1, fc2 = st.columns([2, 3, 2])
            with fc0:
                _sent_universe = st.radio("Universe", ["Nifty 50", "All Dashboard Stocks"],
                                          horizontal=True, key="sent_universe")
            with fc1:
                _sent_search = st.text_input("🔍 Search symbol", key="sent_search", placeholder="e.g. RELIANCE")
            with fc2:
                _sent_filter = st.multiselect(
                    "Filter", ["Bullish", "Bearish", "Neutral"],
                    default=["Bullish", "Bearish", "Neutral"], key="sent_filter",
                )

            _sent_df = (
                _sent_df_all[_sent_df_all["Symbol"].isin(_NIFTY50_SYMBOLS)]
                if _sent_universe == "Nifty 50" else _sent_df_all
            )
            _filtered = _sent_df[_sent_df["Sentiment"].isin(_sent_filter)]
            if _sent_search:
                _filtered = _filtered[_filtered["Symbol"].str.contains(_sent_search.upper(), na=False)]
            _filtered = _filtered.sort_values("Score", ascending=False)

            def _sent_color(v):
                if v == "Bullish": return "color:#00C853;font-weight:700"
                if v == "Bearish": return "color:#D50000;font-weight:700"
                return "color:#FFD600"

            st.caption(f"{len(_filtered)} of {len(_sent_df)} stocks shown ({_sent_universe})")
            st.dataframe(
                _filtered[["Symbol", "Sector", "Score", "Sentiment", "Headlines", "Positive", "Negative", "Neutral"]]
                    .style.map(_sent_color, subset=["Sentiment"])
                    .format({"Score": "{:+.3f}"}),
                width='stretch', hide_index=True, height=380,
            )
        else:
            st.info("No sentiment data yet — scheduler runs automatically at 9:45 PM IST. Click **⚡ Force Scan** above to run now.")
    except Exception as _sent_err:
        st.info("📰 News sentiment temporarily unavailable.")

st.markdown("---")

# ── Build stock list (all stocks, grouped by sector) ─────────────────────────
_all_stocks: list[tuple[str, str]] = []
for sec, stocks in sorted(SECTOR_STOCKS.items()):
    for sym in stocks:
        _all_stocks.append((sym.replace(".NS", ""), sec))
_all_stocks.sort(key=lambda x: x[0])

stock_labels   = [f"{s} ({sec})" for s, sec in _all_stocks]
symbol_map     = {f"{s} ({sec})": sym for (s, sec), sym in zip(_all_stocks, [s + ".NS" for s, _ in _all_stocks])}
symbol_clean   = {f"{s} ({sec})": s   for s, sec in _all_stocks}

# ── Controls row ──────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns([4, 2, 2])
with c1:
    selected_label = st.selectbox("Select Stock", stock_labels, index=0, key="ai_stock")
with c2:
    horizon = st.selectbox("Forecast Horizon", ["5 days", "15 days", "30 days"], index=2, key="ai_horizon")
with c3:
    forward_days_map = {"5 days": 5, "15 days": 15, "30 days": 30}
    horizon_days  = forward_days_map[horizon]
    xgb_fwd_days  = 5   # XGBoost always predicts 5-day direction; horizon only affects Prophet
    st.markdown("<br>", unsafe_allow_html=True)
    run_btn = st.button("▶ Run Forecast", type="primary", width='stretch')

ticker_ns   = symbol_map[selected_label]
ticker_name = symbol_clean[selected_label]

# ── DB cache helpers ──────────────────────────────────────────────────────────
from backend.storage.ai_forecast_db import load_forecast, store_forecast as _store_fc

@st.cache_data(ttl=300, show_spinner=False)
def _load_cached(ticker_clean: str):
    return load_forecast(ticker_clean)

def _to_series(date_list: list, value_list: list) -> pd.Series:
    """Reconstruct pd.Series with date index from cached lists."""
    dates = [datetime.date.fromisoformat(d) if isinstance(d, str) else d for d in date_list]
    return pd.Series(value_list, index=dates)

# ── Live fetch + model (fallback when not cached) ─────────────────────────────
@st.cache_data(ttl=21600, show_spinner=False)
def _batch_prefetch_all():
    """Fetch all NSE stocks in one batch call — shared across all ticker selections."""
    import yfinance as yf
    from config import SECTOR_STOCKS
    seen: set = set()
    tickers: list[str] = []
    for syms in SECTOR_STOCKS.values():
        for sym in syms:
            s = sym.replace(".NS", "") + ".NS"
            if s not in seen:
                seen.add(s)
                tickers.append(s)
    return yf.download(tickers, period="3y", interval="1d",
                       group_by="ticker", threads=False,
                       progress=False, auto_adjust=True)

@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_and_model(ticker_ns: str, xgb_fwd: int):
    from backend.calculations.ai_forecast import run_prophet_forecast, run_xgb_direction, run_arima_forecast
    from backend.data_ingestion.yfinance_fetcher import _get_close
    from backend.data_ingestion.ai_scan_pipeline import _slice_ticker

    batch = _batch_prefetch_all()
    raw = _slice_ticker(batch, ticker_ns)

    # Fallback: individual fetch if ticker missing from batch
    if raw is None or raw.empty:
        import yfinance as yf
        raw = yf.download(ticker_ns, period="3y", interval="1d",
                          progress=False, auto_adjust=True)

    if raw is None or raw.empty or len(raw) < 300:
        return None, None, None, None

    raw.index = pd.to_datetime(raw.index).date
    close     = _get_close(raw)
    if close is None:
        return None, None, None, None

    prophet_res = run_prophet_forecast(close, horizon_days=30)
    xgb_res     = run_xgb_direction(raw, forward_days=xgb_fwd)
    arima_res   = run_arima_forecast(close, horizon_days=30)
    return raw, prophet_res, xgb_res, arima_res


# ── Load data: DB cache first, live fallback ──────────────────────────────────
cached_result, cache_date = _load_cached(ticker_name)

# Decide what to do
use_cache = bool(cached_result and not run_btn)

if not use_cache and not run_btn and "ai_last_ticker" not in st.session_state:
    st.info("Select a stock and click **▶ Run Forecast** to generate predictions, or wait for nightly cache.")
    st.stop()

if use_cache:
    # ── Instant render from DB cache ──────────────────────────────────────────
    prophet_res = cached_result["prophet_res"]
    xgb_res     = cached_result["xgb_res"]
    arima_res   = cached_result.get("arima_res")

    c6m = cached_result.get("close_6m", {})
    ema = cached_result.get("ema", {})

    actual_6m = _to_series(c6m.get("dates", []), c6m.get("prices", []))
    # OHLC for candlestick view (present in caches written after this feature)
    if c6m.get("open") and c6m.get("high") and c6m.get("low"):
        open_6m = _to_series(c6m["dates"], c6m["open"])
        high_6m = _to_series(c6m["dates"], c6m["high"])
        low_6m  = _to_series(c6m["dates"], c6m["low"])
    else:
        open_6m = high_6m = low_6m = None
    ema20_6m  = _to_series(ema.get("ema20",  {}).get("dates", []), ema.get("ema20",  {}).get("values", []))
    ema50_6m  = _to_series(ema.get("ema50",  {}).get("dates", []), ema.get("ema50",  {}).get("values", []))
    ema200_6m = _to_series(ema.get("ema200", {}).get("dates", []), ema.get("ema200", {}).get("values", []))

    cache_notice = f"📦 Showing cached forecast from **{cache_date}** · No live data needed · Recomputed nightly at 9 PM IST"
    st.caption(cache_notice)

else:
    # ── Live compute: fetch from Yahoo Finance + train models ─────────────────
    if run_btn or st.session_state.get("ai_last_ticker") != ticker_ns:
        st.session_state["ai_last_ticker"] = ticker_ns

    with st.spinner(f"Fetching market data for all stocks then training models for {ticker_name} — first load ~60 seconds…"):
        if run_btn:
            _fetch_and_model.clear()
            _batch_prefetch_all.clear()
        raw, prophet_res, xgb_res, arima_res = _fetch_and_model(ticker_ns, xgb_fwd_days)

    if raw is None:
        st.error(f"Could not fetch enough data for {ticker_name}. Need at least 3 years of history.")
        st.stop()

    from backend.data_ingestion.yfinance_fetcher import _get_close
    close = _get_close(raw)
    actual_6m = close.tail(126)
    ema20_6m  = close.ewm(span=20,  adjust=False).mean().tail(126)
    ema50_6m  = close.rolling(50, min_periods=1).mean().tail(126)
    ema200_6m = close.ewm(span=200, adjust=False).mean().tail(126)

    def _ohlc_col(name: str):
        try:
            col = raw[name]
            if hasattr(col, "columns"):  # yfinance multi-index
                col = col.iloc[:, 0]
            return col.reindex(actual_6m.index).astype(float)
        except Exception:
            return None

    open_6m, high_6m, low_6m = _ohlc_col("Open"), _ohlc_col("High"), _ohlc_col("Low")

    # Store to cache so next visit is instant
    if prophet_res and not prophet_res.get("error") and xgb_res and not xgb_res.get("error"):
        try:
            from backend.calculations.ai_forecast import run_full_stock_forecast as _rfs
            # Determine sector for this stock
            _sector = next((sec for sec, syms in SECTOR_STOCKS.items()
                            if ticker_ns in syms or ticker_ns.replace(".NS","") in [s.replace(".NS","") for s in syms]),
                           "Unknown")
            _fc_res = {
                "price":          float(close.iloc[-1]),
                "xgb_prob":       xgb_res["prob_up"],
                "xgb_direction":  xgb_res["direction"],
                "xgb_signal":     xgb_res["signal_label"],
                "xgb_accuracy":   xgb_res["backtest_accuracy"],
                "n_train_bars":   xgb_res["n_train_bars"],
                "n_features":     xgb_res["n_features"],
                "backtest_monthly":   xgb_res["backtest_monthly"],
                "feature_importance": xgb_res["feature_importance"],
                "prophet_trend":     prophet_res["trend_direction"],
                "prophet_trend_pct": prophet_res["trend_pct"],
                "prophet_forecast": {
                    "history_dates":  [str(d) for d in prophet_res["history_dates"]],
                    "history_prices": prophet_res["history_prices"],
                    "forecast_dates": [str(d) for d in prophet_res["forecast_dates"]],
                    "yhat":           prophet_res["yhat"],
                    "yhat_lower":     prophet_res["yhat_lower"],
                    "yhat_upper":     prophet_res["yhat_upper"],
                    "backtest_dates": [str(d) for d in prophet_res.get("backtest_dates", [])],
                    "backtest_yhat":  prophet_res.get("backtest_yhat", []),
                },
                "close_6m": {
                    "dates":  [str(d) for d in actual_6m.index],
                    "prices": [float(v) for v in actual_6m.values],
                    "open":   [float(v) for v in open_6m.values] if open_6m is not None else [],
                    "high":   [float(v) for v in high_6m.values] if high_6m is not None else [],
                    "low":    [float(v) for v in low_6m.values]  if low_6m  is not None else [],
                },
                "ema": {
                    "ema20":  {"dates": [str(d) for d in ema20_6m.index],  "values": [float(v) for v in ema20_6m.values]},
                    "ema50":  {"dates": [str(d) for d in ema50_6m.index],  "values": [float(v) for v in ema50_6m.values]},
                    "ema200": {"dates": [str(d) for d in ema200_6m.index], "values": [float(v) for v in ema200_6m.values]},
                },
                "computed_at": datetime.datetime.utcnow().isoformat(),
            }
            # Add ARIMA if available
            _arima_ok = arima_res and not arima_res.get("error")
            if _arima_ok:
                _fc_res["arima_direction"] = arima_res["direction"]
                _fc_res["arima_trend_pct"] = arima_res["trend_pct"]
                _fc_res["arima_forecast"]  = {
                    "forecast_dates": arima_res["forecast_dates"],
                    "yhat":           arima_res["yhat"],
                    "yhat_lower":     arima_res["yhat_lower"],
                    "yhat_upper":     arima_res["yhat_upper"],
                }
            _store_fc(ticker_name, _sector, _fc_res)
        except Exception:
            pass  # cache store failure is non-fatal


# ── Error handling ────────────────────────────────────────────────────────────
prophet_ok = prophet_res and not prophet_res.get("error")
xgb_ok     = xgb_res    and not xgb_res.get("error")
arima_ok   = arima_res  and not (arima_res or {}).get("error")

if not prophet_ok and not xgb_ok and not arima_ok:
    st.error(f"Model error: {(prophet_res or {}).get('error') or (xgb_res or {}).get('error')}")
    st.stop()

# ── Summary metric cards ──────────────────────────────────────────────────────
st.markdown("---")
m1, m2, m3, m4, m5 = st.columns(5)

if xgb_ok:
    prob_up   = xgb_res["prob_up"]
    prob_pct  = round(prob_up * 100, 1)
    direction = xgb_res["direction"]
    sig_label = xgb_res["signal_label"]
    bt_acc    = xgb_res["backtest_accuracy"]
    dir_color = "#00C853" if direction == "UP" else "#D50000"
    dir_icon  = "▲" if direction == "UP" else "▼"
else:
    prob_pct = bt_acc = 0
    sig_label = direction = "—"
    dir_color = "#888"
    dir_icon  = "—"

if prophet_ok:
    t_dir   = prophet_res["trend_direction"]
    t_pct   = float(prophet_res["trend_pct"] or 0)
    t_color = "#00C853" if t_dir == "Bullish" else ("#D50000" if t_dir == "Bearish" else "#FFD600")
else:
    t_dir = "—"; t_pct = 0.0; t_color = "#888"

if arima_ok:
    a_dir   = arima_res["direction"]
    a_pct   = float(arima_res["trend_pct"] or 0)
    a_color = "#00C853" if a_dir == "Bullish" else ("#D50000" if a_dir == "Bearish" else "#FFD600")
else:
    a_dir = "—"; a_pct = 0.0; a_color = "#888"

_card = "background:#1a2236;border-radius:10px;padding:18px 16px;text-align:center;min-height:110px;display:flex;flex-direction:column;justify-content:center"

m1.markdown(f"""
<div style='{_card};border-left:4px solid {dir_color}'>
  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>XGB Direction ({xgb_fwd_days}d)</div>
  <div style='color:{dir_color};font-size:30px;font-weight:700'>{dir_icon} {direction}</div>
  <div style='color:#ccc;font-size:13px;margin-top:4px'>{sig_label.split(" ",1)[-1] if xgb_ok else "—"}</div>
</div>""", unsafe_allow_html=True)

m2.markdown(f"""
<div style='{_card};border-left:4px solid #1E88E5'>
  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Upward Probability</div>
  <div style='color:#1E88E5;font-size:30px;font-weight:700'>{prob_pct:.1f}%</div>
  <div style='color:#ccc;font-size:13px;margin-top:4px'>XGBoost classifier</div>
</div>""", unsafe_allow_html=True)

m3.markdown(f"""
<div style='{_card};border-left:4px solid #FFD600'>
  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Backtest Accuracy</div>
  <div style='color:#FFD600;font-size:30px;font-weight:700'>{bt_acc:.1f}%</div>
  <div style='color:#ccc;font-size:13px;margin-top:4px'>Out-of-sample</div>
</div>""", unsafe_allow_html=True)

m4.markdown(f"""
<div style='{_card};border-left:4px solid {t_color}'>
  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Prophet Trend (30d)</div>
  <div style='color:{t_color};font-size:30px;font-weight:700'>{t_dir}</div>
  <div style='color:#ccc;font-size:13px;margin-top:4px'>{(t_pct or 0):+.2f}% projected</div>
</div>""", unsafe_allow_html=True)

m5.markdown(f"""
<div style='{_card};border-left:4px solid {a_color}'>
  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>ARIMA Trend (30d)</div>
  <div style='color:{a_color};font-size:30px;font-weight:700'>{a_dir}</div>
  <div style='color:#ccc;font-size:13px;margin-top:4px'>{(a_pct or 0):+.2f}% projected</div>
</div>""", unsafe_allow_html=True)

# ── Prophet chart ─────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader(f"📈 {ticker_name} — Price Trend Forecast ({horizon_days} days)")

if prophet_ok:
    # Truncate forecast to selected horizon
    fcast_dates  = prophet_res["forecast_dates"][:horizon_days]
    fcast_yhat   = prophet_res["yhat"][:horizon_days]
    fcast_lower  = prophet_res["yhat_lower"][:horizon_days]
    fcast_upper  = prophet_res["yhat_upper"][:horizon_days]

    _has_ohlc = open_6m is not None and high_6m is not None and low_6m is not None and len(actual_6m) > 0
    chart_style = st.radio("Chart style", ["📈 Line", "🕯️ Candlestick"],
                           horizontal=True, key="ai_chart_style")
    use_candles = chart_style.endswith("Candlestick")
    if use_candles and not _has_ohlc:
        st.info("Candlestick needs OHLC data — not in this cached forecast yet. "
                "Click **▶ Run Forecast** once (or wait for tonight's cache refresh). Showing line chart.")
        use_candles = False

    fig = go.Figure()

    # Confidence band (shaded)
    fig.add_trace(go.Scatter(
        x=fcast_dates + fcast_dates[::-1],
        y=fcast_upper + fcast_lower[::-1],
        fill="toself",
        fillcolor="rgba(255,145,0,0.12)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
        name="80% Confidence Band",
    ))

    # Actual price — line or candles
    if use_candles:
        fig.add_trace(go.Candlestick(
            x=list(actual_6m.index),
            open=list(open_6m.values), high=list(high_6m.values),
            low=list(low_6m.values), close=list(actual_6m.values),
            name="Actual Price",
            increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        ))
    else:
        fig.add_trace(go.Scatter(
            x=list(actual_6m.index),
            y=list(actual_6m.values),
            name="Actual Price",
            line=dict(color="#90CAF9", width=1.8),
            hovertemplate="₹%{y:,.1f}<extra>%{fullData.name}</extra>",
        ))

    # Actual price lookup for forecast-vs-actual hover difference
    _actual_by_date = {str(d): float(v) for d, v in zip(actual_6m.index, actual_6m.values)}

    def _diff_customdata(dates, values):
        """[(forecast-actual ₹, forecast-actual %), ...] pre-rounded, aligned to dates."""
        out = []
        for d, v in zip(dates, values):
            a = _actual_by_date.get(str(d))
            if a and a != 0:
                diff = v - a
                out.append([f"{diff:+,.1f}", f"{diff / a * 100:+.1f}"])
            else:
                out.append(["—", "—"])
        return out

    _diff_hover = "₹%{y:,.1f} · Δ vs Actual: %{customdata[0]} (%{customdata[1]}%)<extra>%{fullData.name}</extra>"

    # Prophet fitted line on history
    fig.add_trace(go.Scatter(
        x=prophet_res["history_dates"],
        y=prophet_res["history_prices"],
        name="Prophet Trend",
        line=dict(color="#E040FB", width=1.5, dash="dot"),
        opacity=0.7,
        customdata=_diff_customdata(prophet_res["history_dates"], prophet_res["history_prices"]),
        hovertemplate=_diff_hover,
    ))

    # Forecast line — amber dash-dot, same style as Past Forecast so the
    # model's line reads as one consistent color before and after Today
    fig.add_trace(go.Scatter(
        x=fcast_dates,
        y=fcast_yhat,
        name=f"Forecast ({horizon_days}d)",
        line=dict(color="#FF9100", width=2.2, dash="dashdot"),
        hovertemplate="₹%{y:,.1f}<extra>%{fullData.name}</extra>",
    ))

    # Past forecast (walk-forward backtest): what the model predicted for the
    # last 30 days WITHOUT seeing them — compare directly against Actual Price
    bt_dates = prophet_res.get("backtest_dates") or []
    bt_yhat  = prophet_res.get("backtest_yhat") or []
    if bt_dates and bt_yhat:
        fig.add_trace(go.Scatter(
            x=[str(d) for d in bt_dates],
            y=bt_yhat,
            name="Past Forecast (backtest)",
            line=dict(color="#FF9100", width=2.2, dash="dashdot"),
            customdata=_diff_customdata(bt_dates, bt_yhat),
            hovertemplate=_diff_hover,
        ))

    # EMA overlays
    _ma_hover = "₹%{y:,.1f}<extra>%{fullData.name}</extra>"
    fig.add_trace(go.Scatter(
        x=list(ema20_6m.index), y=list(ema20_6m.values),
        name="20 EMA", line=dict(color="#FFD600", width=1.5),
        hovertemplate=_ma_hover,
    ))
    fig.add_trace(go.Scatter(
        x=list(ema50_6m.index), y=list(ema50_6m.values),
        name="50 SMA", line=dict(color="#FF7043", width=1.5, dash="dash"),
        hovertemplate=_ma_hover,
    ))
    fig.add_trace(go.Scatter(
        x=list(ema200_6m.index), y=list(ema200_6m.values),
        name="200 EMA", line=dict(color="#EF5350", width=1.5, dash="dot"),
        hovertemplate=_ma_hover,
    ))

    # Vertical "today" line
    today_date = list(actual_6m.index)[-1] if not actual_6m.empty else datetime.date.today()
    fig.add_vline(x=str(today_date), line_dash="dash", line_color="#555",
                  annotation_text="Today", annotation_position="top")

    # Forecast end target annotation
    if fcast_yhat:
        end_y = fcast_yhat[-1]
        end_x = str(fcast_dates[-1])
        fig.add_annotation(
            x=end_x, y=end_y,
            text=f"  ₹{end_y:,.0f}",
            showarrow=False, font=dict(color="#FF9100", size=13),
        )

    fig.update_layout(
        template="plotly_dark",
        height=420,
        title=f"{ticker_name} — Actual + Prophet {horizon_days}-Day Forecast · 80% Confidence Band",
        yaxis=dict(tickprefix="₹"),
        legend=dict(orientation="h", y=1.06),
        margin=dict(t=55, b=30),
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
    )
    st.plotly_chart(fig, width='stretch')
else:
    _p_err = (prophet_res or {}).get("error")
    if _p_err:
        st.warning(f"Prophet model error: {_p_err}")
    else:
        st.info("📊 Prophet trend not yet available — will appear after tonight's nightly scan.")

# ── ARIMA chart ───────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader(f"📉 {ticker_name} — ARIMA Statistical Forecast ({horizon_days} days)")

if arima_ok:
    af_dates = arima_res["forecast_dates"][:horizon_days]
    af_yhat  = arima_res["yhat"][:horizon_days]
    af_lower = arima_res["yhat_lower"][:horizon_days]
    af_upper = arima_res["yhat_upper"][:horizon_days]

    fig_a = go.Figure()

    # Confidence band
    fig_a.add_trace(go.Scatter(
        x=af_dates + af_dates[::-1],
        y=af_upper + af_lower[::-1],
        fill="toself",
        fillcolor="rgba(255,152,0,0.12)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))

    # Actual price
    fig_a.add_trace(go.Scatter(
        x=list(actual_6m.index),
        y=list(actual_6m.values),
        name="Actual Price",
        line=dict(color="#90CAF9", width=1.8),
    ))

    # ARIMA forecast line
    fig_a.add_trace(go.Scatter(
        x=af_dates,
        y=af_yhat,
        name=f"ARIMA Forecast ({horizon_days}d)",
        line=dict(color="#FF9800", width=2.5),
    ))

    # Today marker
    today_date = list(actual_6m.index)[-1] if not actual_6m.empty else datetime.date.today()
    fig_a.add_vline(x=str(today_date), line_dash="dash", line_color="#555",
                    annotation_text="Today", annotation_position="top")

    if af_yhat:
        fig_a.add_annotation(
            x=str(af_dates[-1]), y=af_yhat[-1],
            text=f"  ₹{af_yhat[-1]:,.0f}",
            showarrow=False, font=dict(color="#FF9800", size=13),
        )

    fig_a.update_layout(
        template="plotly_dark",
        height=360,
        title=f"{ticker_name} — ARIMA Log-Return Forecast · {a_dir} ({a_pct:+.2f}%)",
        yaxis=dict(tickprefix="₹"),
        legend=dict(orientation="h", y=1.06),
        margin=dict(t=55, b=30),
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
    )
    st.plotly_chart(fig_a, width='stretch')
    st.caption("ARIMA fits on daily log-returns using auto-selected order (p,d,q). Confidence bands are 95% prediction intervals converted back to price levels.")
else:
    st.info("ARIMA model not available for this stock.")

# ── XGBoost section ───────────────────────────────────────────────────────────
st.markdown("---")
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader(f"🎯 XGBoost Direction Signal")

    if xgb_ok:
        # Probability gauge
        gauge_color = "#00C853" if prob_up >= 0.58 else ("#D50000" if prob_up <= 0.42 else "#FFD600")
        fig_g = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=prob_pct,
            delta={"reference": 50, "valueformat": ".1f", "suffix": "%"},
            title={"text": f"P(UP in {xgb_fwd_days} days)", "font": {"size": 15}},
            number={"suffix": "%", "font": {"size": 36}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#555"},
                "bar": {"color": gauge_color, "thickness": 0.3},
                "bgcolor": "#1a2236",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 35],  "color": "#2d1515"},
                    {"range": [35, 45], "color": "#2d2215"},
                    {"range": [45, 55], "color": "#1e2236"},
                    {"range": [55, 65], "color": "#152d1a"},
                    {"range": [65, 100],"color": "#0d2515"},
                ],
                "threshold": {
                    "line": {"color": "#fff", "width": 3},
                    "thickness": 0.75,
                    "value": 50,
                },
            },
        ))
        fig_g.update_layout(
            template="plotly_dark", height=260,
            margin=dict(t=30, b=10, l=20, r=20),
            paper_bgcolor="#0d1117",
            font=dict(color="#ccc"),
        )
        st.plotly_chart(fig_g, width='stretch')

        # Signal label
        sig_bg = {"🟢": "#0d2515", "🟡": "#2d2a10", "🔴": "#2d1010",
                  "🟠": "#2d1a0d", "⚪": "#1a2236"}
        bg_col = sig_bg.get(xgb_res["signal_label"][0], "#1a2236")
        st.markdown(
            f"<div style='background:{bg_col};border-radius:8px;padding:12px 16px;"
            f"text-align:center;font-size:16px;font-weight:600'>"
            f"{xgb_res['signal_label']}</div>",
            unsafe_allow_html=True,
        )
        n_bars  = xgb_res.get("n_train_bars", "—")
        n_feats = xgb_res.get("n_features", "—")
        st.caption(f"Model trained on {n_bars} bars · {n_feats} features")

        # Feature importance chart
        fi = xgb_res.get("feature_importance", [])
        if fi:
            st.markdown("**Top 10 Predictive Features**")
            fi_df = pd.DataFrame(fi[:10])
            fig_fi = go.Figure(go.Bar(
                x=fi_df["importance"],
                y=fi_df["feature"],
                orientation="h",
                marker=dict(color=fi_df["importance"],
                            colorscale="Blues", showscale=False),
                text=[f"{v:.1f}%" for v in fi_df["importance"]],
                textposition="outside",
            ))
            fig_fi.update_layout(
                template="plotly_dark", height=320,
                margin=dict(t=10, b=10, l=10, r=60),
                yaxis=dict(autorange="reversed"),
                xaxis=dict(title="Importance (%)"),
            )
            st.plotly_chart(fig_fi, width='stretch')
    else:
        _x_err = (xgb_res or {}).get("error")
        if _x_err:
            st.warning(f"XGBoost error: {_x_err}")
        else:
            st.info("📊 XGBoost signal not yet available — will appear after tonight's nightly scan.")

with col_right:
    st.subheader("📊 Walk-Forward Backtest Results")

    bt_monthly = xgb_res.get("backtest_monthly", []) if xgb_ok else []
    if xgb_ok and bt_monthly:
        bt_df = pd.DataFrame(bt_monthly)

        # Overall accuracy banner
        acc_color = "#00C853" if bt_acc >= 60 else ("#FFD600" if bt_acc >= 53 else "#FF6D00")
        st.markdown(
            f"<div style='background:#1a2236;border-radius:8px;padding:14px 18px;"
            f"border-left:4px solid {acc_color};margin-bottom:12px'>"
            f"<span style='color:#8899bb;font-size:13px'>Overall Out-of-Sample Accuracy</span><br>"
            f"<span style='color:{acc_color};font-size:28px;font-weight:700'>{bt_acc:.1f}%</span>"
            f"<span style='color:#8899bb;font-size:13px'> · Random baseline = 50%"
            f" · Edge = <b style=color:{acc_color}>{bt_acc-50:+.1f}%</b></span></div>",
            unsafe_allow_html=True,
        )

        # Monthly breakdown chart
        bt_df["color"] = bt_df["accuracy"].apply(
            lambda v: "#00C853" if v >= 60 else ("#FFD600" if v >= 50 else "#EF5350")
        )
        fig_bt = go.Figure(go.Bar(
            x=bt_df["month"],
            y=bt_df["accuracy"],
            marker_color=bt_df["color"],
            text=[f"{v:.0f}%" for v in bt_df["accuracy"]],
            textposition="outside",
        ))
        fig_bt.add_hline(y=50, line_dash="dash", line_color="#555",
                         annotation_text="50% random", annotation_position="bottom right")
        fig_bt.update_layout(
            template="plotly_dark", height=260,
            title="Monthly Directional Accuracy (out-of-sample)",
            yaxis=dict(range=[0, 105], title="Accuracy %"),
            margin=dict(t=40, b=40),
            xaxis_tickangle=-30,
        )
        st.plotly_chart(fig_bt, width='stretch')

        # Monthly table — latest month first
        display_bt = bt_df[["month", "accuracy", "correct", "n_bars"]].iloc[::-1].reset_index(drop=True).copy()
        display_bt.columns = ["Month", "Accuracy %", "Correct", "Total Bars"]

        def _acc_color(v):
            if not isinstance(v, (int, float)): return ""
            if v >= 60: return "color:#00C853;font-weight:600"
            if v >= 50: return "color:#FFD600"
            return "color:#EF5350"

        st.dataframe(
            display_bt.style.map(_acc_color, subset=["Accuracy %"])
                            .format({"Accuracy %": "{:.1f}"}),
            width='stretch', hide_index=True,
        )

        st.caption(
            "Walk-forward method: train on rolling 252 bars, test on next 21 bars, "
            f"slide 21 bars. Predicts {xgb_fwd_days}-day direction."
        )
    else:
        if xgb_ok:
            st.info("Not enough data for monthly backtest breakdown.")
        else:
            st.warning("Backtest unavailable.")

# ── News Sentiment (per-stock) ────────────────────────────────────────────────
st.markdown("---")
st.subheader(f"📰 {ticker_name} — News Sentiment")

try:
    from backend.storage.sentiment_db import load_sentiment as _load_stock_sentiment

    _sent_result, _sent_date = _load_stock_sentiment(ticker_name)

    sc1, sc2 = st.columns([1, 5])
    with sc1:
        _live_sent_btn = st.button("🔄 Refresh now", key="sent_refresh_stock",
                                   help="Live fetch — bypasses the nightly cache")
    with sc2:
        if _sent_result and not _live_sent_btn:
            st.caption(f"📦 Cached from **{_sent_date}** · Recomputed nightly at 9:45 PM IST")

    if _live_sent_btn:
        from backend.calculations.news_sentiment import analyze_stock_news
        with st.spinner(f"Fetching live news for {ticker_name}…"):
            _live_res = analyze_stock_news(ticker_name)
        _summary = _live_res["summary"]
        _headlines_df = _live_res["headlines"]
    elif _sent_result:
        _summary = _sent_result["summary"]
        _headlines_df = pd.DataFrame(_sent_result["headlines"])
    else:
        _summary = None
        _headlines_df = pd.DataFrame()

    if _summary and _summary.get("n", 0) > 0:
        _label = _summary["label"]
        _score = _summary["score"]
        _lcolor = {"Bullish": "#00C853", "Bearish": "#D50000"}.get(_label, "#FFD600")

        sm1, sm2, sm3, sm4 = st.columns(4)
        sm1.markdown(f"""<div style='{_card};border-left:4px solid {_lcolor}'>
          <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Overall Sentiment</div>
          <div style='color:{_lcolor};font-size:26px;font-weight:700'>{_label}</div>
          <div style='color:#ccc;font-size:13px;margin-top:4px'>Score {_score:+.3f}</div>
        </div>""", unsafe_allow_html=True)
        sm2.markdown(f"""<div style='{_card};border-left:4px solid #00C853'>
          <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Positive</div>
          <div style='color:#00C853;font-size:26px;font-weight:700'>{_summary.get('pos', 0)}</div>
        </div>""", unsafe_allow_html=True)
        sm3.markdown(f"""<div style='{_card};border-left:4px solid #D50000'>
          <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Negative</div>
          <div style='color:#D50000;font-size:26px;font-weight:700'>{_summary.get('neg', 0)}</div>
        </div>""", unsafe_allow_html=True)
        sm4.markdown(f"""<div style='{_card};border-left:4px solid #8899bb'>
          <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Headlines Analyzed</div>
          <div style='color:#ccc;font-size:26px;font-weight:700'>{_summary.get('n', 0)}</div>
        </div>""", unsafe_allow_html=True)

        if not _headlines_df.empty and "headline" in _headlines_df.columns:
            _cols = ["published", "headline", "source", "sentiment", "score"]
            if "link" in _headlines_df.columns:
                _cols.append("link")
            _disp = _headlines_df[[c for c in _cols if c in _headlines_df.columns]].copy() \
                if "sentiment" in _headlines_df.columns else _headlines_df
            _disp.columns = [c.title() for c in _disp.columns]
            st.dataframe(
                _disp, width='stretch', hide_index=True, height=280,
                column_config={
                    "Link": st.column_config.LinkColumn(
                        "Article", display_text="Open ↗", help="Opens the original article in a new tab",
                        width="small",
                    ),
                    "Score": st.column_config.NumberColumn("Score", width="small"),
                    "Sentiment": st.column_config.TextColumn("Sentiment", width="small"),
                } if "Link" in _disp.columns else None,
            )
    else:
        st.info("No recent news found for this stock, or sentiment isn't cached yet — click **🔄 Refresh now** for a live check.")
except Exception:
    st.info("📰 News sentiment temporarily unavailable for this stock.")

# ── Methodology note ──────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("📖 Model Methodology"):
    st.markdown(f"""<div style='font-size:12px;line-height:1.6;color:#b0bec5'>

**Prophet (Trend Forecast)**
- Facebook/Meta time-series model with weekly + yearly seasonality and Indian market holidays
- Outputs 30-day price path with 80% confidence band
- Best interpreted as a trend direction indicator, not a precise price target
- **Past Forecast (backtest) line**: the model is re-trained on data ending 30 days ago and
  predicts the held-out window — an honest view of what it *would* have forecast vs what
  actually happened. Hover shows Δ vs Actual in ₹ and %.
- Chart supports **Line / Candlestick** toggle (candles need OHLC — available after a live
  run or the next nightly cache refresh)

**ARIMA (Statistical Forecast)**
- Auto-selected order (p,d,q) fitted on daily log-returns, converted back to price levels
- 95% prediction intervals; Neutral (0%) on stable large-caps is normal — their returns
  are near random-walk

**XGBoost Direction Classifier**
- Gradient-boosted trees trained on 60+ features per trading day
- Features: lag returns (1–21d), RSI slope, EMA distances, MACD histogram, ADX, ATR,
  Bollinger Band position, volume spike, candlestick patterns, calendar seasonality, 52w position
- Target: did close price go UP in the next **{xgb_fwd_days} trading days**?
- Probability > 58% = bullish lean; < 42% = bearish lean

**Walk-Forward Backtesting**
- Training window: rolling 252 bars · Test window: next 21 bars · Slide: 21 bars (no look-ahead bias)
- ~12 independent test folds → overall directional accuracy shown

**News Sentiment (VADER)**
- Headlines sourced from Google News RSS (India edition) — up to 25 recent items per stock,
  last 10 days, searched as `"{{symbol}}" NSE stock` with a broader `{{symbol}} share price`
  fallback query if the first search returns nothing
- Scored with **VADER** (lexicon + rule-based sentiment analyzer), boosted with a small
  finance-specific keyword list (e.g. "beats estimates", "order win", "target raised" as
  positive; "downgrade", "probe", "target cut" as negative) so generic-language sentiment
  models don't miss finance-specific phrasing — each match on the boost list is worth ±0.3,
  clamped to the [-1, +1] range
- Per-headline label: **🟢 Positive** (score > +0.15) · **🔴 Negative** (score < -0.15) ·
  **⚪ Neutral** (between)
- Stock-level aggregate: a **recency-weighted average** of all headline scores — the newest
  headline weighs roughly 3× the oldest in a 25-headline window (weight ∝ position^0.7,
  newest first) — so a wave of fresh news moves the aggregate faster than a single old story
  lingering in the list. Aggregate label: **Bullish** (> +0.15) · **Bearish** (< -0.15) ·
  **Neutral** (between)
- Nifty 50 / all-dashboard-stock table is **cook-once**: a nightly scheduler job (9:45 PM IST)
  fetches + scores every stock and caches the result, so the page loads instantly with zero
  live network calls. Use **🔄 Refresh now** on a single stock, or **⚡ Force Scan** (admin)
  for the full table, to bypass the cache for a live check
- **Why VADER, not a transformer model**: an earlier version used FinBERT (a finance-tuned
  transformer), but Streamlit Cloud's Python 3.14 runtime has no prebuilt wheels for
  torch/transformers — pip falls back to a source build that segfaults the process at import
  time. VADER and the RSS parser are pure Python with no compiled dependencies, so this can't
  happen; that's a deliberate trade of some per-headline nuance for a scoring engine that
  can never crash the server
- For research and screening only — headline-level sentiment is a noisy, short-horizon signal
  and is not a substitute for reading the actual news or fundamental analysis

**How to Use Both Signals Together**

<table style='width:100%;border-collapse:collapse;font-size:12px;margin:6px 0'>
<tr style='background:#1e2a3a;color:#90caf9'>
  <th style='padding:7px 10px;text-align:left;border:1px solid #2e3f55'>XGBoost</th>
  <th style='padding:7px 10px;text-align:left;border:1px solid #2e3f55'>Prophet</th>
  <th style='padding:7px 10px;text-align:left;border:1px solid #2e3f55'>Interpretation</th>
</tr>
<tr style='background:#0d1a10'>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>▲ UP</td>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>Bullish</td>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>✅ Strong alignment — high confidence setup</td>
</tr>
<tr style='background:#1a0d0d'>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>▼ DOWN</td>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>Bearish</td>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>✅ Strong alignment — avoid or wait</td>
</tr>
<tr style='background:#1a1a0d'>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>▼ DOWN</td>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>Bullish</td>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>⚠️ Short-term dip within a longer uptrend — may recover after weakness passes</td>
</tr>
<tr style='background:#1a1a0d'>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>▲ UP</td>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>Bearish</td>
  <td style='padding:6px 10px;border:1px solid #2e3f55'>⚠️ Short-term bounce in a downtrend — bounce may not sustain</td>
</tr>
</table>

Best setups: XGB and Prophet **agree** AND backtest accuracy **> 60%**.

**Realistic Expectations**
- Typical accuracy range on liquid NSE stocks: **55–67%**
- Accuracy > 50% = model has edge over coin flip
- Higher accuracy on trending stocks (ADX > 20); lower on sideways markets
- Past backtest accuracy does not guarantee future results

</div>""", unsafe_allow_html=True)

from app.utils.disclaimer import show_footer
show_footer()
