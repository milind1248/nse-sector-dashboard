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
            run_scan_btn = st.button("⚡ Force Scan", type="secondary", use_container_width=True,
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
                    use_container_width=True, hide_index=True,
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
                    use_container_width=True, hide_index=True,
                )
            else:
                st.info("No bearish aligned signals in last scan.")
    else:
        st.info(f"No forecast data yet — scheduler runs automatically at 9 PM IST. Click **⚡ Force Scan** above to run now.")

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
    run_btn = st.button("▶ Run Forecast", type="primary", use_container_width=True)

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
def _fetch_and_model(ticker_ns: str, xgb_fwd: int):
    import yfinance as yf
    from backend.calculations.ai_forecast import run_prophet_forecast, run_xgb_direction
    from backend.data_ingestion.yfinance_fetcher import _get_close

    raw = yf.download(ticker_ns, period="3y", interval="1d",
                      progress=False, auto_adjust=True)
    if raw is None or raw.empty or len(raw) < 300:
        return None, None, None

    raw.index = pd.to_datetime(raw.index).date
    close     = _get_close(raw)
    if close is None:
        return None, None, None

    prophet_res = run_prophet_forecast(close, horizon_days=30)
    xgb_res     = run_xgb_direction(raw, forward_days=xgb_fwd)
    from backend.calculations.ai_forecast import run_arima_forecast
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
    ema20_6m  = _to_series(ema.get("ema20",  {}).get("dates", []), ema.get("ema20",  {}).get("values", []))
    ema50_6m  = _to_series(ema.get("ema50",  {}).get("dates", []), ema.get("ema50",  {}).get("values", []))
    ema200_6m = _to_series(ema.get("ema200", {}).get("dates", []), ema.get("ema200", {}).get("values", []))

    cache_notice = f"📦 Showing cached forecast from **{cache_date}** · No live data needed · Recomputed nightly at 9 PM IST"
    st.caption(cache_notice)

else:
    # ── Live compute: fetch from Yahoo Finance + train models ─────────────────
    if run_btn or st.session_state.get("ai_last_ticker") != ticker_ns:
        st.session_state["ai_last_ticker"] = ticker_ns

    with st.spinner(f"Fetching data and training models for {ticker_name} — first load ~15–20 seconds…"):
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
                },
                "close_6m": {
                    "dates":  [str(d) for d in actual_6m.index],
                    "prices": [float(v) for v in actual_6m.values],
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

m1.markdown(f"""
<div style='background:#1a2236;border-radius:10px;padding:18px 16px;text-align:center;border-left:4px solid {dir_color}'>
  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>XGB Direction ({xgb_fwd_days}d)</div>
  <div style='color:{dir_color};font-size:30px;font-weight:700'>{dir_icon} {direction}</div>
  <div style='color:#ccc;font-size:13px;margin-top:4px'>{sig_label.split(" ",1)[-1] if xgb_ok else "—"}</div>
</div>""", unsafe_allow_html=True)

m2.markdown(f"""
<div style='background:#1a2236;border-radius:10px;padding:18px 16px;text-align:center;border-left:4px solid #1E88E5'>
  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Upward Probability</div>
  <div style='color:#1E88E5;font-size:30px;font-weight:700'>{prob_pct:.1f}%</div>
  <div style='color:#ccc;font-size:13px;margin-top:4px'>XGBoost classifier</div>
</div>""", unsafe_allow_html=True)

m3.markdown(f"""
<div style='background:#1a2236;border-radius:10px;padding:18px 16px;text-align:center;border-left:4px solid #FFD600'>
  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Backtest Accuracy</div>
  <div style='color:#FFD600;font-size:30px;font-weight:700'>{bt_acc:.1f}%</div>
  <div style='color:#ccc;font-size:13px;margin-top:4px'>Walk-forward out-of-sample</div>
</div>""", unsafe_allow_html=True)

m4.markdown(f"""
<div style='background:#1a2236;border-radius:10px;padding:18px 16px;text-align:center;border-left:4px solid {t_color}'>
  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>Prophet Trend (30d)</div>
  <div style='color:{t_color};font-size:30px;font-weight:700'>{t_dir}</div>
  <div style='color:#ccc;font-size:13px;margin-top:4px'>{t_pct:+.2f}% projected</div>
</div>""", unsafe_allow_html=True)

m5.markdown(f"""
<div style='background:#1a2236;border-radius:10px;padding:18px 16px;text-align:center;border-left:4px solid {a_color}'>
  <div style='color:#8899bb;font-size:13px;margin-bottom:6px'>ARIMA Trend (30d)</div>
  <div style='color:{a_color};font-size:30px;font-weight:700'>{a_dir}</div>
  <div style='color:#ccc;font-size:13px;margin-top:4px'>{a_pct:+.2f}% projected</div>
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

    fig = go.Figure()

    # Confidence band (shaded)
    fig.add_trace(go.Scatter(
        x=fcast_dates + fcast_dates[::-1],
        y=fcast_upper + fcast_lower[::-1],
        fill="toself",
        fillcolor="rgba(30,136,229,0.15)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
        name="80% Confidence Band",
    ))

    # Actual price
    fig.add_trace(go.Scatter(
        x=list(actual_6m.index),
        y=list(actual_6m.values),
        name="Actual Price",
        line=dict(color="#90CAF9", width=1.8),
    ))

    # Prophet fitted line on history
    fig.add_trace(go.Scatter(
        x=prophet_res["history_dates"],
        y=prophet_res["history_prices"],
        name="Prophet Trend",
        line=dict(color="#E040FB", width=1.5, dash="dot"),
        opacity=0.7,
    ))

    # Forecast line
    fig.add_trace(go.Scatter(
        x=fcast_dates,
        y=fcast_yhat,
        name=f"Forecast ({horizon_days}d)",
        line=dict(color="#1E88E5", width=2.5),
    ))

    # EMA overlays
    fig.add_trace(go.Scatter(
        x=list(ema20_6m.index), y=list(ema20_6m.values),
        name="20 EMA", line=dict(color="#FFD600", width=1.5),
    ))
    fig.add_trace(go.Scatter(
        x=list(ema50_6m.index), y=list(ema50_6m.values),
        name="50 SMA", line=dict(color="#FF7043", width=1.5, dash="dash"),
    ))
    fig.add_trace(go.Scatter(
        x=list(ema200_6m.index), y=list(ema200_6m.values),
        name="200 EMA", line=dict(color="#EF5350", width=1.5, dash="dot"),
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
            showarrow=False, font=dict(color="#1E88E5", size=13),
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
    st.warning(f"Prophet model error: {(prophet_res or {}).get('error')}")

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
        st.warning(f"XGBoost error: {(xgb_res or {}).get('error')}")

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
            use_container_width=True, hide_index=True,
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

# ── Methodology note ──────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("📖 Model Methodology"):
    st.markdown(f"""<div style='font-size:12px;line-height:1.6;color:#b0bec5'>

**Prophet (Trend Forecast)**
- Facebook/Meta time-series model with weekly + yearly seasonality and Indian market holidays
- Outputs 30-day price path with 80% confidence band
- Best interpreted as a trend direction indicator, not a precise price target

**XGBoost Direction Classifier**
- Gradient-boosted trees trained on 60+ features per trading day
- Features: lag returns (1–21d), RSI slope, EMA distances, MACD histogram, ADX, ATR,
  Bollinger Band position, volume spike, candlestick patterns, calendar seasonality, 52w position
- Target: did close price go UP in the next **{xgb_fwd_days} trading days**?
- Probability > 58% = bullish lean; < 42% = bearish lean

**Walk-Forward Backtesting**
- Training window: rolling 252 bars · Test window: next 21 bars · Slide: 21 bars (no look-ahead bias)
- ~12 independent test folds → overall directional accuracy shown

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
