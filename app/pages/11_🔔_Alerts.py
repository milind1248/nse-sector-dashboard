"""Alerts & Scanners — Breakout alerts, 20 EMA Pullback scanner, H-M scanner."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from config import SECTOR_STOCKS
from backend.data_ingestion.yfinance_fetcher import _get_close
from backend.calculations.indicators import ema_signal
from backend.calculations.ma_respect import analyze_stock, compute_mas
from backend.calculations.hm_indicators import atr as compute_atr


def _batch_download(symbols: list, period: str = "3mo", interval: str = "1d") -> dict:
    """
    Fetch OHLCV for many symbols in one/few yf.download calls instead of one call
    per symbol — cuts HTTP + memory overhead dramatically on constrained hosts.
    Chunked to keep any single request reasonably sized. Returns {symbol: df}.
    """
    import yfinance as yf
    out = {}
    uniq = list(dict.fromkeys(symbols))
    chunk_size = 75
    for i in range(0, len(uniq), chunk_size):
        chunk = uniq[i:i + chunk_size]
        try:
            batch = yf.download(chunk, period=period, interval=interval,
                                group_by="ticker", threads=False,
                                progress=False, auto_adjust=True)
        except Exception:
            batch = None
        if batch is None or batch.empty:
            continue
        multi = isinstance(batch.columns, pd.MultiIndex)
        for sym in chunk:
            try:
                if multi:
                    if sym not in batch.columns.get_level_values(0):
                        continue
                    df = batch[sym].dropna(how="all")
                else:
                    df = batch
                if df is not None and not df.empty:
                    out[sym] = df
            except Exception:
                continue
    return out

st.set_page_config(page_title="Alerts & Scanners | NSE Swing Trading | Market Sector Analysis", layout="wide")
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()
from app.utils.seo import inject_seo
inject_seo("Alerts")
from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("Alerts")

st.title("🚨 Alerts & Scanners")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption("Technical scanners and alerts across all NSE sectors. For informational and educational purposes only.")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_breakout, tab_ema, tab_hm, tab_frvp, tab_frvp_hm, tab_best_ma, tab_monte_carlo = st.tabs([
    "📡 Breakout Alerts",
    "📈 20 EMA Pullback Scanner",
    "🎯 H-M Scanner",
    "📊 FRVP Signal",
    "🔍 FRVP H-M Scanner",
    "📏 Best MA",
    "🎲 Monte Carlo Test",
])

# Pre-render loading skeletons into tabs 2 and 3 BEFORE any scanner starts.
# Without this, clicking those tabs during the ~30s breakout scan shows a blank.
_LOADING_CSS = """
<style>
@keyframes _pulse{0%{opacity:1}50%{opacity:.4}100%{opacity:1}}
._scan-loading{border-radius:8px;padding:28px 24px;margin:12px 0;
  background:#1e2130;animation:_pulse 1.6s ease-in-out infinite;
  color:#8899bb;font-size:15px;text-align:center;letter-spacing:.5px;}
._scan-bar{height:12px;border-radius:6px;background:#2e3350;margin:10px auto;
  animation:_pulse 1.6s ease-in-out infinite;}
</style>"""

with tab_ema:
    _ema_ph = st.empty()
    _ema_ph.markdown(_LOADING_CSS + """
<div class="_scan-loading">⏳ <strong>20 EMA Pullback Scanner</strong> is queued —
Breakout scan running first…<br>
<small>Loads automatically once ready (~60 s on first visit)</small></div>
<div class="_scan-bar" style="width:70%"></div>
<div class="_scan-bar" style="width:50%"></div>
<div class="_scan-bar" style="width:85%"></div>""", unsafe_allow_html=True)

with tab_hm:
    _hm_ph = st.empty()
    _hm_ph.markdown(_LOADING_CSS + """
<div class="_scan-loading">⏳ <strong>H-M Scanner</strong> is queued —
other scans loading first…<br>
<small>Loads automatically once ready (~90 s on first visit)</small></div>
<div class="_scan-bar" style="width:60%"></div>
<div class="_scan-bar" style="width:80%"></div>
<div class="_scan-bar" style="width:45%"></div>""", unsafe_allow_html=True)

with tab_frvp:
    _frvp_ph = st.empty()
    _frvp_ph.markdown(_LOADING_CSS + """
<div class="_scan-loading">⏳ <strong>FRVP Signal</strong> — select a stock to compute the volume profile…</div>
<div class="_scan-bar" style="width:65%"></div>
<div class="_scan-bar" style="width:80%"></div>
<div class="_scan-bar" style="width:50%"></div>""", unsafe_allow_html=True)

with tab_frvp_hm:
    _frvp_hm_ph = st.empty()
    _frvp_hm_ph.markdown(_LOADING_CSS + """
<div class="_scan-loading">⏳ <strong>FRVP H-M Scanner</strong> — click Run Scan to compute LOC levels…</div>
<div class="_scan-bar" style="width:70%"></div>
<div class="_scan-bar" style="width:55%"></div>
<div class="_scan-bar" style="width:80%"></div>""", unsafe_allow_html=True)

with tab_best_ma:
    _best_ma_ph = st.empty()
    _best_ma_ph.markdown(_LOADING_CSS + """
<div class="_scan-loading">⏳ <strong>Best MA Analyzer</strong> — select a stock to analyze…</div>
<div class="_scan-bar" style="width:70%"></div>
<div class="_scan-bar" style="width:50%"></div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — BREAKOUT ALERTS (existing, unchanged)
# ══════════════════════════════════════════════════════════════════════════════
with tab_breakout:
    st.subheader("Technical Alerts — Breakout & Reversal Patterns")
    st.caption("Stocks crossing key technical levels across all sectors.")

    @st.cache_data(ttl=3600, show_spinner=False)
    def scan_all_breakouts():
        alerts = []
        all_syms = [sym for stocks in SECTOR_STOCKS.values() for sym in stocks]
        batch = _batch_download(all_syms, period="3mo", interval="1d")
        for sector, stocks in SECTOR_STOCKS.items():
            for sym in stocks:
                try:
                    raw = batch.get(sym)
                    if raw is None or raw.empty:
                        continue
                    raw.index = pd.to_datetime(raw.index).date
                    close_s = _get_close(raw)
                    if close_s is None or len(close_s) < 20:
                        continue
                    price      = float(close_s.iloc[-1])
                    ema20_s    = close_s.ewm(span=20, adjust=False).mean()
                    ema20      = float(ema20_s.iloc[-1])
                    prev_close = float(close_s.iloc[-2])
                    prev_ema20 = float(ema20_s.iloc[-2])

                    delta = close_s.diff()
                    gain  = delta.clip(lower=0).rolling(14).mean()
                    loss  = (-delta.clip(upper=0)).rolling(14).mean()
                    rsi_s = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
                    rsi_clean = rsi_s.dropna()
                    rsi_now   = float(rsi_clean.iloc[-1]) if not rsi_clean.empty else None
                    rsi_prev  = float(rsi_clean.iloc[-2]) if len(rsi_clean) >= 2 else rsi_now

                    vol_series = None
                    for col in ["Volume", "volume"]:
                        if col in raw.columns:
                            v = raw[col]
                            if isinstance(v, pd.DataFrame): v = v.iloc[:, 0]
                            vol_series = v.dropna()
                            break

                    if prev_close < prev_ema20 and price > ema20:
                        alerts.append({"Symbol": sym.replace(".NS", ""), "Sector": sector,
                                       "Alert": "EMA20 Bullish Cross", "Price": price,
                                       "RSI": rsi_now, "Severity": "High"})
                    if rsi_prev and rsi_now and rsi_prev < 30 and rsi_now >= 30:
                        alerts.append({"Symbol": sym.replace(".NS", ""), "Sector": sector,
                                       "Alert": "RSI exits Oversold (>30)", "Price": price,
                                       "RSI": rsi_now, "Severity": "High"})
                    if rsi_prev and rsi_now and rsi_prev < 70 and rsi_now >= 70:
                        alerts.append({"Symbol": sym.replace(".NS", ""), "Sector": sector,
                                       "Alert": "RSI Overbought >70 — Monitor for potential reversal",
                                       "Price": price, "RSI": rsi_now, "Severity": "Medium"})
                    high52 = float(close_s.rolling(252, min_periods=50).max().iloc[-1])
                    if price >= high52 * 0.99:
                        alerts.append({"Symbol": sym.replace(".NS", ""), "Sector": sector,
                                       "Alert": "Near/At 52-Week High Breakout", "Price": price,
                                       "RSI": rsi_now, "Severity": "High"})
                    if vol_series is not None and len(vol_series) >= 20:
                        avg_vol   = float(vol_series.iloc[-20:].mean())
                        today_vol = float(vol_series.iloc[-1])
                        if avg_vol > 0 and today_vol > 2.5 * avg_vol:
                            alerts.append({"Symbol": sym.replace(".NS", ""), "Sector": sector,
                                           "Alert": f"Volume Spike {today_vol/avg_vol:.1f}x average",
                                           "Price": price, "RSI": rsi_now, "Severity": "Medium"})
                except Exception:
                    continue
        return pd.DataFrame(alerts) if alerts else pd.DataFrame()

    with st.spinner("Scanning all sectors for breakouts — ~30 seconds..."):
        df_alerts = scan_all_breakouts()

    if df_alerts.empty:
        st.info("No major signals today. Market may be in consolidation.")
    else:
        high_df = df_alerts[df_alerts["Severity"] == "High"]
        med_df  = df_alerts[df_alerts["Severity"] == "Medium"]

        m1, m2, m3 = st.columns(3)
        m1.metric("Total Alerts",    len(df_alerts))
        m2.metric("High Priority",   len(high_df))
        m3.metric("Medium Priority", len(med_df))

        st.markdown("---")
        st.subheader("High Priority Alerts")

        def _color_alert(val):
            if "Cross" in str(val) or "52-Week" in str(val): return "color:#00C853;font-weight:600"
            if "Oversold" in str(val): return "color:#64DD17"
            return "color:#FF6D00"

        if not high_df.empty:
            st.dataframe(
                high_df.style.map(_color_alert, subset=["Alert"]).format(
                    {"Price": "₹{:,.2f}", "RSI": lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "–"}),
                width='stretch', hide_index=True
            )
        else:
            st.info("No high-priority alerts today.")

        st.subheader("Medium Priority Alerts")
        if not med_df.empty:
            st.dataframe(
                med_df.style.map(_color_alert, subset=["Alert"]).format(
                    {"Price": "₹{:,.2f}", "RSI": lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "–"}),
                width='stretch', hide_index=True
            )

        st.markdown("---")
        st.subheader("Alerts by Sector")
        sector_counts = (df_alerts.groupby("Sector").size()
                         .reset_index(name="Count")
                         .sort_values("Count", ascending=False))
        fig = px.bar(sector_counts, x="Sector", y="Count", color="Count",
                     color_continuous_scale="YlOrRd", template="plotly_dark")
        fig.update_layout(height=300, margin=dict(t=20, b=60), xaxis_tickangle=-30)
        st.plotly_chart(fig, width='stretch')

        alert_sectors = df_alerts["Sector"].unique().tolist()
        if "al_jump_sector" in st.session_state and st.session_state["al_jump_sector"] not in alert_sectors:
            del st.session_state["al_jump_sector"]
        sel = st.selectbox("Jump to sector analysis:", alert_sectors, key="al_jump_sector")
        if st.button(f"Analyse {sel} →", type="primary"):
            st.session_state["selected_sector"] = sel
            st.switch_page("pages/2_📈_Sector_Analysis.py")

    st.markdown("---")
    if st.button("← FII Sector Watch"):
        st.switch_page("Home.py")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — 20 EMA PULLBACK SCANNER
# ══════════════════════════════════════════════════════════════════════════════
with tab_ema:
    _ema_ph.empty()
    st.subheader("📈 NSE Swing Trading — 20 EMA Pullback Scanner")
    st.caption(
        "Identifies stocks in a confirmed uptrend pulling back toward the rising 20 EMA — "
        "a low-risk entry before the next upward move. Ranked by Overall Pullback Score (0–100)."
    )

    # ── Sector filter & controls ───────────────────────────────────────────────
    fc1, fc2, fc3 = st.columns([3, 2, 2])
    with fc1:
        sector_options = ["All Sectors"] + sorted(SECTOR_STOCKS.keys())
        selected_sector = st.selectbox("Filter by Sector", sector_options, key="ema_sector")
    with fc2:
        min_score = st.slider("Min Pullback Score", 0, 100, 40, 5, key="ema_minscore")
    with fc3:
        max_ema_dist = st.slider("Max Distance from 20 EMA (%)", 0.0, 5.0, 2.0, 0.5, key="ema_maxdist")

    # ── Scanner logic ──────────────────────────────────────────────────────────
    @st.cache_data(ttl=3600, show_spinner=False)
    def run_ema_pullback_scanner() -> pd.DataFrame:
        import yfinance as yf

        # Fetch Nifty for relative strength
        try:
            nifty_raw = yf.download("^NSEI", period="6mo", interval="1d",
                                    progress=False, auto_adjust=True)
            nifty_close = _get_close(nifty_raw).dropna() if nifty_raw is not None and not nifty_raw.empty else None
        except Exception:
            nifty_close = None

        results = []

        all_syms = [sym for stocks in SECTOR_STOCKS.values() for sym in stocks]
        batch = _batch_download(all_syms, period="12mo", interval="1d")

        for sector, stocks in SECTOR_STOCKS.items():
            for sym in stocks:
                try:
                    raw = batch.get(sym)
                    if raw is None or raw.empty or len(raw) < 60:
                        continue

                    raw.index = pd.to_datetime(raw.index).date
                    close = _get_close(raw)
                    if close is None or len(close) < 60:
                        continue

                    # ── Volume series ──────────────────────────────────────────
                    vol = None
                    for col in ["Volume", "volume"]:
                        if col in raw.columns:
                            v = raw[col]
                            if isinstance(v, pd.DataFrame): v = v.iloc[:, 0]
                            vol = v.dropna()
                            break

                    # ── Moving averages ────────────────────────────────────────
                    ema20  = close.ewm(span=20,  adjust=False).mean()
                    sma50  = close.rolling(50).mean()
                    sma200 = close.rolling(200, min_periods=100).mean()

                    price    = float(close.iloc[-1])
                    e20      = float(ema20.iloc[-1])
                    s50      = float(sma50.iloc[-1])
                    s200_val = sma200.dropna()
                    s200     = float(s200_val.iloc[-1]) if not s200_val.empty else None

                    if np.isnan(e20) or np.isnan(s50):
                        continue

                    # ── Trend confirmation ─────────────────────────────────────
                    # 1. Price > 20 EMA
                    if price <= e20:
                        continue
                    # 2. 20 EMA > 50 SMA
                    if e20 <= s50:
                        continue
                    # 3. 50 SMA > 200 SMA (if available)
                    if s200 and s50 <= s200:
                        continue

                    # 4. 50 SMA rising over last 20 days
                    sma50_20d_ago = float(sma50.iloc[-21]) if len(sma50.dropna()) > 21 else None
                    sma50_rising  = (s50 > sma50_20d_ago) if sma50_20d_ago else False
                    if not sma50_rising:
                        continue

                    # 5. 20 EMA slope over last 10 days (must be positive overall)
                    ema20_10d_ago  = float(ema20.iloc[-11]) if len(ema20) > 11 else None
                    ema20_slope_10 = ((e20 - ema20_10d_ago) / ema20_10d_ago * 100) if ema20_10d_ago else None
                    if ema20_slope_10 is None or ema20_slope_10 <= 0:
                        continue

                    # 6. 200 SMA flat or rising
                    if s200 and len(s200_val) > 20:
                        s200_20d = float(s200_val.iloc[-21]) if len(s200_val) > 21 else None
                        s200_slope = ((s200 - s200_20d) / s200_20d * 100) if s200_20d else 0
                        if s200_slope < -1.0:   # allow slight flat/down but reject steep decline
                            continue
                    else:
                        s200_slope = 0.0

                    # ── Pullback detection ─────────────────────────────────────
                    ema_dist_pct = (price - e20) / e20 * 100
                    if ema_dist_pct < 0 or ema_dist_pct > 5:
                        continue

                    # Not closed below EMA20 more than 2 consecutive sessions
                    recent = close.iloc[-5:]
                    ema_recent = ema20.iloc[-5:]
                    below_ema_streak = int((recent < ema_recent).astype(int)
                                          .groupby((recent >= ema_recent).astype(int).cumsum())
                                          .cumsum().iloc[-1])
                    if below_ema_streak > 2:
                        continue

                    # Pullback remains above 50 SMA
                    recent_low = float(close.iloc[-5:].min())
                    if recent_low < s50:
                        continue

                    # Decreasing volume on pullback
                    vol_ratio = None
                    vol_decreasing = False
                    if vol is not None and len(vol) >= 20:
                        avg_vol   = float(vol.iloc[-20:].mean())
                        today_vol = float(vol.iloc[-1])
                        vol_ratio = today_vol / avg_vol if avg_vol > 0 else None
                        vol_decreasing = vol_ratio is not None and vol_ratio < 1.0

                    # ── Momentum indicators ────────────────────────────────────
                    # RSI(14)
                    delta = close.diff()
                    gain  = delta.clip(lower=0).rolling(14).mean()
                    loss  = (-delta.clip(upper=0)).rolling(14).mean()
                    rsi_s = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
                    rsi   = float(rsi_s.dropna().iloc[-1]) if not rsi_s.dropna().empty else None

                    # ADX(14)
                    try:
                        high_s = raw["High"] if "High" in raw.columns else raw.iloc[:, 1]
                        low_s  = raw["Low"]  if "Low"  in raw.columns else raw.iloc[:, 2]
                        if isinstance(high_s, pd.DataFrame): high_s = high_s.iloc[:, 0]
                        if isinstance(low_s,  pd.DataFrame): low_s  = low_s.iloc[:, 0]
                        tr    = pd.concat([high_s - low_s,
                                           (high_s - close.shift()).abs(),
                                           (low_s  - close.shift()).abs()], axis=1).max(axis=1)
                        dm_p  = (high_s.diff()).clip(lower=0)
                        dm_m  = (-low_s.diff()).clip(lower=0)
                        atr14 = tr.ewm(span=14, adjust=False).mean()
                        di_p  = 100 * dm_p.ewm(span=14, adjust=False).mean() / atr14.replace(0, float("nan"))
                        di_m  = 100 * dm_m.ewm(span=14, adjust=False).mean() / atr14.replace(0, float("nan"))
                        dx    = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, float("nan"))
                        adx   = float(dx.ewm(span=14, adjust=False).mean().dropna().iloc[-1])
                    except Exception:
                        adx = None

                    # MACD (12,26,9)
                    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
                    macd_sig  = macd_line.ewm(span=9, adjust=False).mean()
                    macd_val  = float(macd_line.iloc[-1])
                    macd_hist = float((macd_line - macd_sig).iloc[-1])
                    macd_positive = macd_val > 0 or macd_hist > 0

                    # OBV rising (last 5 days)
                    obv_rising = False
                    if vol is not None and len(vol) >= 10:
                        obv = (np.sign(close.diff()) * vol).fillna(0).cumsum()
                        obv_rising = float(obv.iloc[-1]) > float(obv.iloc[-6])

                    # ── Relative Strength vs Nifty ─────────────────────────────
                    rs_vs_nifty = None
                    if nifty_close is not None and len(close) >= 63 and len(nifty_close) >= 63:
                        try:
                            stock_ret = float(close.iloc[-1]) / float(close.iloc[-63]) - 1
                            nifty_ret = float(nifty_close.iloc[-1]) / float(nifty_close.iloc[-63]) - 1
                            rs_vs_nifty = (stock_ret - nifty_ret) * 100
                        except Exception:
                            pass

                    # ── Higher High / Higher Low check (last 60 days) ──────────
                    hh_hl = False
                    try:
                        seg = close.iloc[-60:]
                        mid = len(seg) // 2
                        first_half, second_half = seg.iloc[:mid], seg.iloc[mid:]
                        hh = float(second_half.max()) > float(first_half.max())
                        hl = float(second_half.min()) > float(first_half.min())
                        hh_hl = hh and hl
                    except Exception:
                        pass

                    # ── Bounce confirmation ────────────────────────────────────
                    bounce = False
                    try:
                        o_col = next((c for c in raw.columns if c.lower() == "open"), None)
                        if o_col:
                            open_s = raw[o_col]
                            if isinstance(open_s, pd.DataFrame): open_s = open_s.iloc[:, 0]
                            c0, c1 = float(close.iloc[-1]), float(close.iloc[-2])
                            o0, o1 = float(open_s.iloc[-1]), float(open_s.iloc[-2])
                            # Bullish engulfing
                            if c1 < o1 and c0 > o1 and o0 < c1:
                                bounce = True
                            # Hammer: lower wick >= 2× body
                            body = abs(c0 - o0)
                            h_col = next((c for c in raw.columns if c.lower() == "high"), None)
                            l_col = next((c for c in raw.columns if c.lower() == "low"),  None)
                            if h_col and l_col:
                                h0 = float(raw[h_col].iloc[-1] if not isinstance(raw[h_col], pd.DataFrame) else raw[h_col].iloc[-1, 0])
                                l0 = float(raw[l_col].iloc[-1] if not isinstance(raw[l_col], pd.DataFrame) else raw[l_col].iloc[-1, 0])
                                lower_wick = min(o0, c0) - l0
                                if lower_wick >= 2 * body and body > 0:
                                    bounce = True
                            # Close above prev day high
                            prev_h = float(raw[h_col].iloc[-2] if not isinstance(raw[h_col], pd.DataFrame) else raw[h_col].iloc[-2, 0]) if h_col else None
                            if prev_h and c0 > prev_h:
                                bounce = True
                            # Volume above 20-day avg
                            if vol_ratio and vol_ratio > 1.0:
                                bounce = True
                    except Exception:
                        pass

                    # ── Scoring (100 points) ───────────────────────────────────
                    score = 0

                    # Trend Quality (35)
                    score += 7   # price > EMA20 > SMA50 already enforced
                    score += 7   # EMA20 > SMA50 already enforced
                    score += 5 if ema20_slope_10 and ema20_slope_10 > 0 else 0
                    sma50_slope_pct = ((s50 - sma50_20d_ago) / sma50_20d_ago * 100) if sma50_20d_ago else 0
                    score += 5 if sma50_slope_pct > 0 else 0
                    score += 6 if hh_hl else 0
                    score += 5 if s200 and s50 > s200 else 0

                    # Entry Quality (30)
                    # Closer to EMA = better entry; 0% → 10 pts, 2% → 5 pts
                    entry_pts = max(0, int(10 - ema_dist_pct * 2.5))
                    score += entry_pts
                    score += 5 if vol_decreasing else 0
                    score += 5 if recent_low > s50 else 0
                    score += 10 if bounce else 0

                    # Momentum (20)
                    if rsi and 50 <= rsi <= 65:
                        score += 7
                    elif rsi and 45 <= rsi < 50:
                        score += 3
                    score += 5 if adx and adx > 20 else 0
                    score += 4 if macd_positive else 0
                    score += 4 if obv_rising else 0

                    # Relative Strength (15)
                    if rs_vs_nifty is not None:
                        if rs_vs_nifty > 5:
                            score += 15
                        elif rs_vs_nifty > 0:
                            score += 8
                        elif rs_vs_nifty > -3:
                            score += 3

                    # ── Slope labels ───────────────────────────────────────────
                    def _slope_label(pct):
                        if pct is None: return "—"
                        if pct > 0.5:  return f"↑ {pct:.2f}%"
                        if pct < -0.5: return f"↓ {pct:.2f}%"
                        return f"→ {pct:.2f}%"

                    results.append({
                        "Symbol":           sym.replace(".NS", ""),
                        "Sector":           sector,
                        "Price (₹)":        round(price, 2),
                        "20 EMA":           round(e20, 2),
                        "EMA Dist %":       round(ema_dist_pct, 2),
                        "EMA Slope (10d)":  _slope_label(ema20_slope_10),
                        "SMA50 Slope (20d)":_slope_label(sma50_slope_pct),
                        "RSI":              round(rsi, 1) if rsi else None,
                        "ADX":              round(adx, 1) if adx else None,
                        "Vol Ratio":        round(vol_ratio, 2) if vol_ratio else None,
                        "RS vs Nifty %":    round(rs_vs_nifty, 2) if rs_vs_nifty is not None else None,
                        "HH/HL":            "✅" if hh_hl else "—",
                        "Bounce":           "✅" if bounce else "—",
                        "Pullback Score":   score,
                        # hidden helpers
                        "_ema_dist":        ema_dist_pct,
                        "_sector":          sector,
                    })

                except Exception:
                    continue

        if not results:
            return pd.DataFrame()
        df = pd.DataFrame(results).sort_values("Pullback Score", ascending=False)
        return df

    # ── Run scanner ────────────────────────────────────────────────────────────
    with st.spinner("Running 20 EMA Pullback Scanner across all NSE sectors — ~60 seconds..."):
        df_ema = run_ema_pullback_scanner()

    if df_ema.empty:
        st.info("No stocks met the uptrend + pullback criteria today. Market may be extended or weak.")
    else:
        # Apply filters
        filtered = df_ema.copy()
        if selected_sector != "All Sectors":
            filtered = filtered[filtered["Sector"] == selected_sector]
        filtered = filtered[filtered["Pullback Score"] >= min_score]
        filtered = filtered[filtered["_ema_dist"] <= max_ema_dist]

        # Drop hidden helper cols
        display_cols = [c for c in filtered.columns if not c.startswith("_")]
        display = filtered[display_cols].reset_index(drop=True)

        # ── Summary metrics ────────────────────────────────────────────────────
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Stocks Scanned", len(df_ema))
        s2.metric("Passed Filters", len(display))
        s3.metric("With Bounce Signal", int((filtered["Bounce"] == "✅").sum()))
        s4.metric("Avg Pullback Score", f"{display['Pullback Score'].mean():.0f}" if not display.empty else "—")

        st.markdown("---")

        if display.empty:
            st.info("No stocks match the current filter settings. Try lowering the minimum score or increasing EMA distance.")
        else:
            # ── Score color styling ────────────────────────────────────────────
            def _score_color(val):
                if isinstance(val, (int, float)):
                    if val >= 70: return "color:#00C853;font-weight:700"
                    if val >= 50: return "color:#FFD600;font-weight:600"
                    return "color:#FF6D00"
                return ""

            def _rs_color(val):
                if isinstance(val, (int, float)):
                    return "color:#00C853" if val > 0 else "color:#EF5350"
                return ""

            def _ema_dist_color(val):
                if isinstance(val, (int, float)):
                    if val <= 1.0: return "color:#00C853;font-weight:600"
                    if val <= 2.0: return "color:#FFD600"
                    return "color:#FF6D00"
                return ""

            styled = (
                display.style
                .map(_score_color,    subset=["Pullback Score"])
                .map(_rs_color,       subset=["RS vs Nifty %"])
                .map(_ema_dist_color, subset=["EMA Dist %"])
                .format({
                    "Price (₹)":    "₹{:,.2f}",
                    "20 EMA":       "₹{:,.2f}",
                    "EMA Dist %":   "{:.2f}%",
                    "RSI":          lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
                    "ADX":          lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
                    "Vol Ratio":    lambda v: f"{v:.2f}x" if isinstance(v, (int, float)) else "—",
                    "RS vs Nifty %":lambda v: f"{v:+.2f}%" if isinstance(v, (int, float)) else "—",
                }, na_rep="—")
            )

            st.dataframe(styled, width='stretch', hide_index=True, height=520)

            # ── Score distribution chart ───────────────────────────────────────
            st.markdown("---")
            cc1, cc2 = st.columns(2)

            with cc1:
                st.markdown("**Score Distribution**")
                fig_hist = px.histogram(
                    display, x="Pullback Score", nbins=10,
                    color_discrete_sequence=["#1E88E5"],
                    template="plotly_dark",
                )
                fig_hist.update_layout(height=250, margin=dict(t=10, b=30))
                st.plotly_chart(fig_hist, width='stretch')

            with cc2:
                st.markdown("**Top Setups by Sector**")
                sector_best = (display.groupby("Sector")["Pullback Score"]
                               .max().reset_index()
                               .sort_values("Pullback Score", ascending=False).head(10))
                fig_bar = px.bar(sector_best, x="Sector", y="Pullback Score",
                                 color="Pullback Score", color_continuous_scale="Blues",
                                 template="plotly_dark")
                fig_bar.update_layout(height=250, margin=dict(t=10, b=60),
                                      xaxis_tickangle=-30)
                st.plotly_chart(fig_bar, width='stretch')

            # ── Stock drilldown ────────────────────────────────────────────────
            st.markdown("---")
            st.markdown("**Stock Drilldown**")
            _dd1, _dd2 = st.columns([4, 1])
            drill_sym = _dd1.selectbox(
                "Select a stock to view price vs 20 EMA:",
                display["Symbol"].tolist(),
                key="ema_drill"
            )
            ema_chart_type = _dd2.radio(
                "Chart", ["Line", "Candle"], horizontal=True, key="ema_chart_type"
            )
            if drill_sym:
                import yfinance as yf
                try:
                    dr_raw = yf.download(drill_sym + ".NS", period="6mo", interval="1d",
                                         progress=False, auto_adjust=True)
                    dr_close = _get_close(dr_raw)
                    if dr_close is not None and not dr_close.empty:
                        dr_ema20 = dr_close.ewm(span=20, adjust=False).mean()
                        dr_sma50 = dr_close.rolling(50, min_periods=1).mean()

                        # ── Detect buy signal bars (bounce off 20 EMA) ────────
                        sig_x, sig_y = [], []
                        for i in range(2, len(dr_close)):
                            p   = float(dr_close.iloc[i])
                            e   = float(dr_ema20.iloc[i])
                            p_1 = float(dr_close.iloc[i-1])
                            e_1 = float(dr_ema20.iloc[i-1])
                            dist = (p - e) / e * 100 if e else 999
                            # Price near EMA (0–3%) and prev bar was closer / touched
                            if 0 <= dist <= 3 and p > e and p_1 <= e_1 * 1.015:
                                sig_x.append(dr_close.index[i])
                                sig_y.append(p * 0.995)  # place circle just below bar

                        fig_d = go.Figure()
                        if ema_chart_type == "Candle":
                            try:
                                fig_d.add_trace(go.Candlestick(
                                    x=list(dr_close.index),
                                    open=dr_raw["Open"].squeeze(),
                                    high=dr_raw["High"].squeeze(),
                                    low=dr_raw["Low"].squeeze(),
                                    close=dr_raw["Close"].squeeze(),
                                    name="OHLC",
                                    increasing_line_color="#00C853",
                                    decreasing_line_color="#D50000",
                                ))
                            except Exception:
                                fig_d.add_trace(go.Scatter(x=dr_close.index, y=dr_close,
                                                           name="Close", line=dict(color="#90CAF9", width=1.5)))
                        else:
                            fig_d.add_trace(go.Scatter(x=dr_close.index, y=dr_close,
                                                       name="Close", line=dict(color="#90CAF9", width=1.5)))
                        fig_d.add_trace(go.Scatter(x=dr_ema20.index, y=dr_ema20,
                                                   name="20 EMA", line=dict(color="#FFD600", width=2)))
                        fig_d.add_trace(go.Scatter(x=dr_sma50.index, y=dr_sma50,
                                                   name="50 SMA", line=dict(color="#FF7043", width=1.5, dash="dash")))
                        if sig_x:
                            fig_d.add_trace(go.Scatter(
                                x=sig_x, y=sig_y, mode="markers", name="Buy Signal",
                                marker=dict(color="lime", size=12, symbol="circle",
                                            line=dict(color="white", width=1.5)),
                            ))
                        fig_d.update_layout(
                            template="plotly_dark", height=380,
                            title=f"{drill_sym} — Price vs 20 EMA & 50 SMA · 🟢 Buy Signals (6 months)",
                            yaxis=dict(tickprefix="₹"),
                            legend=dict(orientation="h", y=1.05),
                            margin=dict(t=50, b=30),
                            hovermode="x unified",
                            xaxis_rangeslider_visible=False,
                        )
                        st.plotly_chart(fig_d, width='stretch')
                        if sig_x:
                            st.caption(f"🟢 {len(sig_x)} buy signal(s) detected — price bounced from 20 EMA zone.")
                        else:
                            st.caption("No EMA bounce signals detected in the last 6 months.")
                except Exception as e:
                    st.warning(f"Could not load chart for {drill_sym}: {e}")

    st.markdown("---")
    st.caption(
        "**Methodology:** Trend confirmed when Price > 20 EMA > 50 SMA > 200 SMA, "
        "with rising EMA slope and HH/HL structure. Pullback entry when price is 0–2% above 20 EMA "
        "on declining volume. Bounce signals: Bullish Engulfing, Hammer, Close > Prev High, Volume Surge. "
        "Score weights: Trend Quality 35 · Entry Quality 30 · Momentum 20 · Relative Strength 15. "
        "For educational purposes only — not SEBI-registered investment advice."
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — H-M SCANNER
# Strategy: RSI(9) < 50 momentum reversal — stocks pulling back within an
# uptrend where RSI(9) has dipped below 50 and is now showing reversal signals
# via Stochastic crossover, MACD histogram turn, and bullish price action.
# ══════════════════════════════════════════════════════════════════════════════
with tab_hm:
    _hm_ph.empty()
    st.subheader("🎯 H-M Scanner — RSI(9) Momentum Reversal")
    st.caption(
        "Scans for stocks in an uptrend where RSI(9) has pulled below 50 and is "
        "showing early reversal signals (Stochastic crossover + MACD histogram turn + "
        "bullish candle). RSI(9) < 50 is mandatory. Ranked by H-M Score (0–100)."
    )

    # ── Filters ───────────────────────────────────────────────────────────────
    hf1, hf2, hf3, hf4 = st.columns([3, 2, 2, 2])
    with hf1:
        hm_sector = st.selectbox("Filter by Sector", ["All Sectors"] + sorted(SECTOR_STOCKS.keys()), key="hm_sector")
    with hf2:
        hm_min_score = st.slider("Min H-M Score", 0, 100, 40, 5, key="hm_minscore")
    with hf3:
        hm_rsi_max = st.slider("RSI(9) max", 20, 50, 50, 1, key="hm_rsimax",
                               help="Mandatory upper bound — RSI(9) must be below this value")
    with hf4:
        hm_weekly_filter = st.checkbox("Weekly RSI(9) > 50 confirm", value=True, key="hm_weekly",
                                       help="Only show stocks where Weekly RSI(9) is also above 50 (higher TF trend)")

    # ── Scanner ───────────────────────────────────────────────────────────────
    @st.cache_data(ttl=3600, show_spinner=False)
    def run_hm_scanner() -> pd.DataFrame:
        import yfinance as yf

        def _calc_rsi9(s):
            d = s.diff()
            g = d.clip(lower=0).rolling(9).mean()
            l = (-d.clip(upper=0)).rolling(9).mean()
            return (100 - (100 / (1 + g / l.replace(0, float("nan"))))).dropna()

        def _calc_wma21(rsi_s):
            w = np.arange(1, 22, dtype=float)
            return rsi_s.rolling(21).apply(lambda x: float(np.dot(x, w) / w.sum()), raw=True)

        # Nifty for relative strength
        try:
            nf_raw   = yf.download("^NSEI", period="6mo", interval="1d", progress=False, auto_adjust=True)
            nf_close = _get_close(nf_raw).dropna() if nf_raw is not None and not nf_raw.empty else None
        except Exception:
            nf_close = None

        results = []

        all_syms = [sym for stocks in SECTOR_STOCKS.values() for sym in stocks]
        daily_batch  = _batch_download(all_syms, period="12mo", interval="1d")
        weekly_batch = _batch_download(all_syms, period="2y",  interval="1wk")

        for sector, stocks in SECTOR_STOCKS.items():
            for sym in stocks:
                try:
                    raw = daily_batch.get(sym)
                    if raw is None or raw.empty or len(raw) < 60:
                        continue
                    raw.index = pd.to_datetime(raw.index).date
                    close = _get_close(raw)
                    if close is None or len(close) < 60:
                        continue

                    # ── OHLC/Vol helpers ──────────────────────────────────────
                    vol = None
                    for col in ["Volume", "volume"]:
                        if col in raw.columns:
                            v = raw[col]
                            vol = (v.iloc[:, 0] if isinstance(v, pd.DataFrame) else v).dropna()
                            break

                    def _col(names):
                        for n in names:
                            if n in raw.columns:
                                c = raw[n]
                                return (c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c)
                        return None

                    high_s = _col(["High", "high"])
                    low_s  = _col(["Low",  "low"])
                    open_s = _col(["Open", "open"])

                    # ── Price moving averages ─────────────────────────────────
                    ema20  = close.ewm(span=20,  adjust=False).mean()
                    sma50  = close.rolling(50).mean()
                    sma200 = close.rolling(200, min_periods=100).mean()

                    price  = float(close.iloc[-1])
                    e20    = float(ema20.iloc[-1])
                    s50    = float(sma50.iloc[-1])
                    s200_s = sma200.dropna()
                    s200   = float(s200_s.iloc[-1]) if not s200_s.empty else None

                    if np.isnan(e20) or np.isnan(s50):
                        continue

                    # ── Gate 1: price above 50 SMA (uptrend context) ──────────
                    if price < s50:
                        continue

                    # ── NK Rule: RSI(9), EMA(3) of RSI, WMA(21) of RSI ───────
                    rsi9_s  = _calc_rsi9(close)
                    if rsi9_s.empty or len(rsi9_s) < 25:
                        continue

                    ema3_s  = rsi9_s.ewm(span=3, adjust=False).mean()
                    wma21_s = _calc_wma21(rsi9_s).dropna()

                    rsi9    = float(rsi9_s.iloc[-1])
                    ema3    = float(ema3_s.iloc[-1])
                    wma21   = float(wma21_s.iloc[-1]) if not wma21_s.empty else None

                    # ── Gate 2: RSI(9) < 50 MANDATORY (NK sir rule) ──────────
                    if rsi9 >= 50:
                        continue

                    # ── NK Rule A: EMA(3) and WMA(21) crossed BELOW RSI(9) ───
                    # Both lines must now be below RSI(9) — Price Strength &
                    # Volume Strength both beneath RSI = buy setup per NK sir.
                    ema3_below_rsi  = ema3 < rsi9
                    wma21_below_rsi = wma21 is not None and wma21 < rsi9

                    # Detect the crossover happened recently (within 5 bars):
                    # Previously EMA(3) was >= RSI(9), now it's below
                    ema3_crossover  = False
                    wma21_crossover = False
                    lookback = min(5, len(rsi9_s) - 1)
                    for j in range(1, lookback + 1):
                        r_prev = float(rsi9_s.iloc[-(j+1)])
                        e_prev = float(ema3_s.iloc[-(j+1)])
                        if e_prev >= r_prev and ema3_below_rsi:
                            ema3_crossover = True
                        if wma21_s is not None and not wma21_s.empty and len(wma21_s) > j:
                            w_prev = float(wma21_s.iloc[-(j+1)])
                            if w_prev >= r_prev and wma21_below_rsi:
                                wma21_crossover = True

                    # ── NK Rule B: RSI(9) approaching 50 from below ───────────
                    # Best entry = RSI rising toward 50 after the crossover.
                    # "Approaching" = RSI in 35-50 range and rising.
                    rsi9_low5     = float(rsi9_s.iloc[-6:-1].min()) if len(rsi9_s) >= 6 else rsi9
                    rsi9_rising   = rsi9 > rsi9_low5
                    approaching50 = rsi9 >= 35 and rsi9 < 50 and rsi9_rising

                    # RSI recently crossed above 50 (within 3 bars) = confirmed entry
                    rsi_crossed50 = False
                    for j in range(1, 4):
                        if len(rsi9_s) > j and float(rsi9_s.iloc[-(j+1)]) < 50 <= rsi9:
                            rsi_crossed50 = True

                    # ── NK Rule C: Weekly RSI(9) > 50 (higher TF trend) ───────
                    weekly_rsi_ok = None
                    try:
                        wk_raw   = weekly_batch.get(sym)
                        wk_close = _get_close(wk_raw) if wk_raw is not None else None
                        if wk_close is not None and len(wk_close) >= 12:
                            wk_rsi9  = _calc_rsi9(wk_close)
                            if not wk_rsi9.empty:
                                weekly_rsi_ok = float(wk_rsi9.iloc[-1]) > 50
                    except Exception:
                        weekly_rsi_ok = None

                    # ── Stochastic(14,3) for additional confirmation ──────────
                    stoch_signal = False
                    stoch_k = stoch_d = None
                    if high_s is not None and low_s is not None and len(close) >= 17:
                        try:
                            lowest14  = low_s.rolling(14).min()
                            highest14 = high_s.rolling(14).max()
                            k_raw = 100 * (close - lowest14) / (highest14 - lowest14).replace(0, float("nan"))
                            k_s   = k_raw.rolling(3).mean()
                            d_s   = k_s.rolling(3).mean()
                            stoch_k = float(k_s.dropna().iloc[-1])
                            stoch_d = float(d_s.dropna().iloc[-1])
                            stoch_k_prev = float(k_s.dropna().iloc[-2]) if len(k_s.dropna()) >= 2 else stoch_k
                            stoch_d_prev = float(d_s.dropna().iloc[-2]) if len(d_s.dropna()) >= 2 else stoch_d
                            stoch_signal = (stoch_k > stoch_d and stoch_k_prev <= stoch_d_prev and stoch_k < 50)
                        except Exception:
                            pass

                    # ── MACD histogram ────────────────────────────────────────
                    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
                    macd_sig  = macd_line.ewm(span=9, adjust=False).mean()
                    hist      = macd_line - macd_sig
                    hist_now  = float(hist.iloc[-1])
                    hist_prev = float(hist.iloc[-2]) if len(hist) >= 2 else hist_now
                    macd_turn = hist_now > hist_prev
                    macd_positive = hist_now > 0

                    # ── Bullish candle ────────────────────────────────────────
                    bullish_candle = engulfing = hammer = False
                    if open_s is not None and len(close) >= 2:
                        try:
                            c0, o0 = float(close.iloc[-1]), float(open_s.iloc[-1])
                            c1, o1 = float(close.iloc[-2]), float(open_s.iloc[-2])
                            bullish_candle = c0 > o0
                            engulfing = c0 > o1 and o0 < c1 and c1 < o1
                            if high_s is not None and low_s is not None:
                                h0 = float(high_s.iloc[-1]); l0 = float(low_s.iloc[-1])
                                body = abs(c0 - o0)
                                lower_wick = min(c0, o0) - l0
                                upper_wick = h0 - max(c0, o0)
                                hammer = (lower_wick >= 2 * body and upper_wick <= body
                                          and body > 0 and c0 > o0)
                        except Exception:
                            pass

                    # ── Volume ────────────────────────────────────────────────
                    vol_ratio = None
                    vol_surge = False
                    if vol is not None and len(vol) >= 20:
                        avg_vol   = float(vol.iloc[-20:].mean())
                        today_vol = float(vol.iloc[-1])
                        vol_ratio = round(today_vol / avg_vol, 2) if avg_vol > 0 else None
                        vol_surge = vol_ratio is not None and vol_ratio > 1.2

                    # ── Relative Strength vs Nifty ────────────────────────────
                    rs_vs_nifty = None
                    if nf_close is not None and len(close) >= 63 and len(nf_close) >= 63:
                        try:
                            rs_vs_nifty = round(
                                (float(close.iloc[-1]) / float(close.iloc[-63]) -
                                 float(nf_close.iloc[-1]) / float(nf_close.iloc[-63])) * 100, 2
                            )
                        except Exception:
                            pass

                    dist_sma50 = round((price - s50) / s50 * 100, 2) if s50 else None

                    # ── NK sir H-M Signal definition ─────────────────────────
                    # Core: both EMA(3) and WMA(21) below RSI(9) + RSI rising toward 50
                    nk_core = ema3_below_rsi and wma21_below_rsi and rsi9_rising
                    # Strong: exact crossover detected recently
                    nk_crossover = ema3_crossover or wma21_crossover
                    # Confirmed entry: RSI just crossed above 50
                    nk_entry = rsi_crossed50
                    hm_signal = nk_core  # minimum requirement per NK sir

                    # ── H-M Scoring (100 pts) — NK sir priority ───────────────
                    score = 0

                    # NK Core Signal (40 pts — most important)
                    if nk_core:
                        score += 20
                    if nk_crossover:
                        score += 15   # exact crossover = stronger signal
                    if nk_entry:
                        score += 15   # RSI crossed 50 = confirmed entry

                    # RSI(9) zone (20 pts)
                    if rsi9 < 30:       score += 20
                    elif rsi9 < 40:     score += 15
                    elif rsi9 < 50:     score += 10

                    # Weekly trend (15 pts)
                    if weekly_rsi_ok is True:  score += 15
                    elif weekly_rsi_ok is None: score += 5   # unknown = neutral

                    # Approaching 50 zone (10 pts)
                    if approaching50:   score += 10

                    # Supporting signals (15 pts)
                    if stoch_signal:    score += 5
                    if macd_turn:       score += 5
                    if engulfing:       score += 3
                    elif hammer:        score += 2
                    elif bullish_candle: score += 1
                    if vol_surge:       score += 2
                    if rs_vs_nifty and rs_vs_nifty > 0: score += 3

                    # Signal type label
                    sig_parts = []
                    if nk_entry:            sig_parts.append("🟢RSI>50")
                    elif approaching50:     sig_parts.append("RSI→50")
                    if nk_crossover:        sig_parts.append("EMA/WMA✗")
                    elif nk_core:           sig_parts.append("Setup✓")
                    if weekly_rsi_ok is True: sig_parts.append("Wkly✓")
                    if stoch_signal:        sig_parts.append("Stoch✗")
                    if macd_turn:           sig_parts.append("MACD↑")
                    if vol_surge:           sig_parts.append("Vol↑")
                    signal_label = " · ".join(sig_parts) if sig_parts else "—"

                    results.append({
                        "Symbol":           sym.replace(".NS", ""),
                        "Sector":           sector,
                        "Price (₹)":        round(price, 2),
                        "RSI(9)":           round(rsi9, 1),
                        "EMA(3) of RSI":    round(ema3, 1),
                        "WMA(21) of RSI":   round(wma21, 1) if wma21 else None,
                        "RSI Dir":          "↑ Rising" if rsi9_rising else "↓ Fall",
                        "Wkly RSI(9)>50":   "✅" if weekly_rsi_ok else ("—" if weekly_rsi_ok is None else "❌"),
                        "NK Crossover":     "✅" if nk_crossover else "—",
                        "RSI>50 Entry":     "🟢" if nk_entry else "—",
                        "Stoch %K":         round(stoch_k, 1) if stoch_k else None,
                        "MACD Turn":        "✅" if macd_turn else "—",
                        "Candle":           ("Engulfing" if engulfing else "Hammer" if hammer
                                             else "Bullish" if bullish_candle else "—"),
                        "Vol Ratio":        vol_ratio,
                        "Dist SMA50 %":     dist_sma50,
                        "RS vs Nifty %":    rs_vs_nifty,
                        "Signal":           signal_label,
                        "H-M Signal":       "🟢 YES" if hm_signal else "—",
                        "H-M Score":        score,
                        "_sym_ns":          sym,
                        "_weekly_rsi_ok":   weekly_rsi_ok,
                    })

                except Exception:
                    continue

        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).sort_values("H-M Score", ascending=False)

    # ── Run ───────────────────────────────────────────────────────────────────
    with st.spinner("Running H-M Scanner across all NSE sectors — ~60 seconds..."):
        df_hm = run_hm_scanner()

    if df_hm.empty:
        st.info("No stocks met the RSI(9) < 50 criteria today.")
    else:
        # Apply filters
        fhm = df_hm.copy()
        if hm_sector != "All Sectors":
            fhm = fhm[fhm["Sector"] == hm_sector]
        fhm = fhm[fhm["RSI(9)"] < hm_rsi_max]
        fhm = fhm[fhm["H-M Score"] >= hm_min_score]
        if hm_weekly_filter:
            fhm = fhm[fhm["_weekly_rsi_ok"] != False]  # keep True and None, drop False
        display_hm = fhm[[c for c in fhm.columns if not c.startswith("_")]].reset_index(drop=True)

        # ── Summary metrics ────────────────────────────────────────────────────
        hm1, hm2, hm3, hm4 = st.columns(4)
        hm1.metric("Stocks Scanned",    len(df_hm))
        hm2.metric("RSI(9) < 50",       len(df_hm[df_hm["RSI(9)"] < 50]))
        hm3.metric("H-M Signal Active", int((fhm["H-M Signal"] == "🟢 YES").sum()))
        hm4.metric("Avg H-M Score",     f"{display_hm['H-M Score'].mean():.0f}" if not display_hm.empty else "—")

        st.markdown("---")

        if display_hm.empty:
            st.info("No stocks match the current filter settings.")
        else:
            # ── Styling ───────────────────────────────────────────────────────
            def _hm_score_color(val):
                if not isinstance(val, (int, float)): return ""
                if val >= 70: return "color:#00C853;font-weight:700"
                if val >= 50: return "color:#FFD600;font-weight:600"
                return "color:#FF6D00"

            def _rsi9_color(val):
                if not isinstance(val, (int, float)): return ""
                if val < 30: return "color:#00C853;font-weight:700"
                if val < 40: return "color:#64DD17"
                return "color:#FFD600"

            def _rs_color(val):
                if not isinstance(val, (int, float)): return ""
                return "color:#00C853" if val > 0 else "color:#EF5350"

            styled_hm = (
                display_hm.style
                .map(_hm_score_color, subset=["H-M Score"])
                .map(_rsi9_color,     subset=["RSI(9)"])
                .map(_rs_color,       subset=["RS vs Nifty %"])
                .format({
                    "Price (₹)":      "₹{:,.2f}",
                    "RSI(9)":         "{:.1f}",
                    "EMA(3) of RSI":  lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
                    "WMA(21) of RSI": lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
                    "RSI(14)":        lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
                    "Stoch %K":       lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
                    "Stoch %D":       lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else "—",
                    "MACD Hist":      lambda v: f"{v:+.3f}" if isinstance(v, (int, float)) else "—",
                    "Vol Ratio":      lambda v: f"{v:.2f}x" if isinstance(v, (int, float)) else "—",
                    "Dist SMA50 %":   lambda v: f"{v:+.2f}%" if isinstance(v, (int, float)) else "—",
                    "RS vs Nifty %":  lambda v: f"{v:+.2f}%" if isinstance(v, (int, float)) else "—",
                }, na_rep="—")
            )
            _row_px = 35
            _header_px = 38
            _tbl_height = min(_header_px + len(display_hm) * _row_px, 600)
            st.dataframe(styled_hm, width='stretch', hide_index=True, height=_tbl_height)

            # ── Charts row ────────────────────────────────────────────────────
            st.markdown("---")
            ch1, ch2 = st.columns(2)

            with ch1:
                st.markdown("**RSI(9) Distribution**")
                fig_rsi = px.histogram(display_hm, x="RSI(9)", nbins=10,
                                       color_discrete_sequence=["#43A047"],
                                       template="plotly_dark")
                fig_rsi.add_vline(x=50, line_dash="dash", line_color="#EF5350",
                                  annotation_text="50 line", annotation_position="top right")
                fig_rsi.add_vline(x=30, line_dash="dash", line_color="#FFD600",
                                  annotation_text="Oversold 30")
                fig_rsi.update_layout(height=250, margin=dict(t=10, b=30))
                st.plotly_chart(fig_rsi, width='stretch')

            with ch2:
                st.markdown("**H-M Score by Sector**")
                sec_hm = (display_hm.groupby("Sector")["H-M Score"]
                          .max().reset_index()
                          .sort_values("H-M Score", ascending=False).head(10))
                fig_sec = px.bar(sec_hm, x="Sector", y="H-M Score",
                                 color="H-M Score", color_continuous_scale="Greens",
                                 template="plotly_dark")
                fig_sec.update_layout(height=250, margin=dict(t=10, b=60),
                                      xaxis_tickangle=-30)
                st.plotly_chart(fig_sec, width='stretch')

            # ── Drilldown chart with green buy-signal circles ─────────────────
            st.markdown("---")
            st.markdown("**Stock Drilldown — RSI(9) + Buy Signals**")
            _dc1, _dc2 = st.columns([4, 1])
            hm_drill = _dc1.selectbox(
                "Select a stock:", display_hm["Symbol"].tolist(), key="hm_drill"
            )
            hm_chart_type = _dc2.radio(
                "Chart", ["Line", "Candle"], horizontal=True, key="hm_chart_type"
            )
            if hm_drill:
                import yfinance as yf
                try:
                    hd_raw   = yf.download(hm_drill + ".NS", period="6mo", interval="1d",
                                           progress=False, auto_adjust=True)
                    hd_close = _get_close(hd_raw)
                    if hd_close is not None and not hd_close.empty:
                        hd_ema20  = hd_close.ewm(span=20,  adjust=False).mean()
                        hd_sma50  = hd_close.rolling(50, min_periods=1).mean()

                        # RSI(9) series for subplot
                        hd_d9   = hd_close.diff()
                        hd_g9   = hd_d9.clip(lower=0).rolling(9).mean()
                        hd_l9   = (-hd_d9.clip(upper=0)).rolling(9).mean()
                        hd_rsi9 = (100 - (100 / (1 + hd_g9 / hd_l9.replace(0, float("nan"))))).dropna()

                        # ── NK sir buy signals on drilldown chart ────────────
                        # Signal A: EMA(3) or WMA(21) crossed below RSI(9)
                        #           while RSI(9) < 50
                        # Signal B: RSI(9) crosses above 50 (confirmed entry)
                        rsi9_ema3_d  = hd_rsi9.ewm(span=3, adjust=False).mean()
                        _w21d = np.arange(1, 22, dtype=float)
                        rsi9_wma21_d = hd_rsi9.rolling(21).apply(
                            lambda x: float(np.dot(x, _w21d) / _w21d.sum()), raw=True
                        )
                        sig_x, sig_y   = [], []   # green: crossover setup
                        sig_x2, sig_y2 = [], []   # bright green: RSI crossed 50

                        rsi9_arr  = hd_rsi9.values
                        ema3_arr  = rsi9_ema3_d.values
                        wma21_arr = rsi9_wma21_d.values

                        for i in range(22, len(hd_rsi9)):
                            r  = rsi9_arr[i]
                            e  = ema3_arr[i]
                            w  = wma21_arr[i]
                            r_prev = rsi9_arr[i-1]
                            e_prev = ema3_arr[i-1]
                            w_prev = wma21_arr[i-1] if not np.isnan(wma21_arr[i-1]) else w

                            if np.isnan(r) or np.isnan(e) or np.isnan(w):
                                continue

                            # Signal B: RSI(9) just crossed above 50
                            if r >= 50 and r_prev < 50:
                                sig_x2.append(hd_rsi9.index[i])
                                sig_y2.append(float(hd_close.iloc[i]) * 0.993)
                                continue

                            # Signal A: RSI < 50 and EMA(3) or WMA(21) just crossed below RSI
                            if r < 50:
                                ema_cross  = (e < r) and (e_prev >= r_prev)
                                wma_cross  = (w < r) and (w_prev >= r_prev)
                                both_below = (e < r) and (w < r)
                                if (ema_cross or wma_cross) and both_below:
                                    sig_x.append(hd_rsi9.index[i])
                                    sig_y.append(float(hd_close.iloc[i]) * 0.994)

                        from plotly.subplots import make_subplots
                        fig_hm = make_subplots(
                            rows=2, cols=1, shared_xaxes=True,
                            row_heights=[0.68, 0.32],
                            vertical_spacing=0.04,
                        )
                        # Price + MAs
                        if hm_chart_type == "Candle":
                            try:
                                fig_hm.add_trace(go.Candlestick(
                                    x=list(hd_close.index),
                                    open=hd_raw["Open"].squeeze(),
                                    high=hd_raw["High"].squeeze(),
                                    low=hd_raw["Low"].squeeze(),
                                    close=hd_raw["Close"].squeeze(),
                                    name="OHLC",
                                    increasing_line_color="#00C853",
                                    decreasing_line_color="#D50000",
                                ), row=1, col=1)
                            except Exception:
                                fig_hm.add_trace(go.Scatter(x=hd_close.index, y=hd_close,
                                                            name="Close", line=dict(color="#90CAF9", width=1.5)), row=1, col=1)
                        else:
                            fig_hm.add_trace(go.Scatter(x=hd_close.index, y=hd_close,
                                                        name="Close", line=dict(color="#90CAF9", width=1.5)), row=1, col=1)
                        fig_hm.add_trace(go.Scatter(x=hd_ema20.index, y=hd_ema20,
                                                    name="20 EMA", line=dict(color="#FFD600", width=2)), row=1, col=1)
                        fig_hm.add_trace(go.Scatter(x=hd_sma50.index, y=hd_sma50,
                                                    name="50 SMA", line=dict(color="#FF7043", width=1.5, dash="dash")), row=1, col=1)
                        # Only confirmed entry: RSI(9) crosses above 50 (catches the bottom)
                        if sig_x2:
                            fig_hm.add_trace(go.Scatter(
                                x=sig_x2, y=sig_y2, mode="markers", name="H-M Entry (RSI>50✓)",
                                marker=dict(color="lime", size=14, symbol="circle",
                                            line=dict(color="white", width=2)),
                            ), row=1, col=1)
                        # Use already-computed RSI smoothed series
                        rsi9_ema3  = rsi9_ema3_d
                        rsi9_wma21 = rsi9_wma21_d

                        # ── RSI(9) panel — fill above/below 50 (Zerodha style) ─
                        _idx  = hd_rsi9.index
                        _ema3 = rsi9_ema3.reindex(_idx)
                        _rsi9 = hd_rsi9.reindex(_idx)
                        _mid  = pd.Series(50.0, index=_idx)   # 50 baseline

                        # Green fill: RSI above 50
                        _rsi_above = _rsi9.where(_rsi9 >= 50, 50.0)
                        fig_hm.add_trace(go.Scatter(
                            x=_idx, y=_mid,
                            line=dict(width=0), mode="lines",
                            showlegend=False, hoverinfo="skip",
                        ), row=2, col=1)
                        fig_hm.add_trace(go.Scatter(
                            x=_idx, y=_rsi_above,
                            fill="tonexty", fillcolor="rgba(38,166,154,0.35)",
                            line=dict(width=0), mode="lines",
                            showlegend=False, hoverinfo="skip",
                        ), row=2, col=1)

                        # Red fill: RSI below 50
                        _rsi_below = _rsi9.where(_rsi9 <= 50, 50.0)
                        fig_hm.add_trace(go.Scatter(
                            x=_idx, y=_mid,
                            line=dict(width=0), mode="lines",
                            showlegend=False, hoverinfo="skip",
                        ), row=2, col=1)
                        fig_hm.add_trace(go.Scatter(
                            x=_idx, y=_rsi_below,
                            fill="tonexty", fillcolor="rgba(239,83,80,0.35)",
                            line=dict(width=0), mode="lines",
                            showlegend=False, hoverinfo="skip",
                        ), row=2, col=1)

                        # RSI(9) — black line
                        fig_hm.add_trace(go.Scatter(
                            x=_idx, y=_rsi9,
                            name="RSI(9)",
                            line=dict(color="#90CAF9", width=1.5),
                        ), row=2, col=1)
                        # EMA(3) of RSI(9) — green line
                        fig_hm.add_trace(go.Scatter(
                            x=_idx, y=_ema3,
                            name="EMA(3) of RSI(9)",
                            line=dict(color="#4CAF50", width=1.5),
                        ), row=2, col=1)
                        # WMA(21) of RSI(9) — red line
                        fig_hm.add_trace(go.Scatter(
                            x=rsi9_wma21.reindex(_idx).index,
                            y=rsi9_wma21.reindex(_idx),
                            name="WMA(21) of RSI(9)",
                            line=dict(color="#EF5350", width=1.5),
                        ), row=2, col=1)
                        # Only confirmed entry on RSI panel
                        if sig_x2:
                            _rsi_at_entry = [
                                float(hd_rsi9.loc[x]) if x in hd_rsi9.index else None
                                for x in sig_x2
                            ]
                            _ex = [x for x, v in zip(sig_x2, _rsi_at_entry) if v is not None]
                            _ey = [v for v in _rsi_at_entry if v is not None]
                            fig_hm.add_trace(go.Scatter(
                                x=_ex, y=_ey, mode="markers",
                                name="Entry signal (RSI panel)",
                                showlegend=False,
                                marker=dict(color="lime", size=6, symbol="circle",
                                            line=dict(color="white", width=1)),
                            ), row=2, col=1)

                        fig_hm.add_hline(y=50, line_dash="dash", line_color="#888888",
                                         annotation_text="50", row=2, col=1)
                        fig_hm.add_hline(y=30, line_dash="dot", line_color="#FFD600",
                                         annotation_text="30", row=2, col=1)
                        fig_hm.update_layout(
                            template="plotly_dark", height=500,
                            title=f"{hm_drill} — Price · RSI(9) · 🟢 H-M Buy Signals (6 months)",
                            yaxis=dict(tickprefix="₹"),
                            yaxis2=dict(title="RSI(9)", range=[0, 100]),
                            legend=dict(orientation="h", y=1.04),
                            margin=dict(t=55, b=30),
                            hovermode="x unified",
                            xaxis_rangeslider_visible=False,
                            xaxis2_rangeslider_visible=False,
                        )
                        st.plotly_chart(fig_hm, width='stretch')
                        if sig_x2:
                            st.caption(f"🟢 {len(sig_x2)} H-M entry signal(s) — RSI(9) crossed above 50 from below (bottom catch).")
                        else:
                            st.caption("No H-M entry signals detected in the last 6 months.")
                except Exception as e:
                    st.warning(f"Could not load chart for {hm_drill}: {e}")

    st.markdown("---")
    st.caption(
        "**H-M Methodology (NK Sir):** RSI(9) < 50 mandatory (pullback zone). "
        "**Setup signal 🟡** — EMA(3) of RSI (Price Strength) AND WMA(21) of RSI (Volume Strength) "
        "both cross below RSI(9): stock is in a pullback within an uptrend. "
        "**Entry signal 🟢** — RSI(9) then crosses back above 50: momentum has resumed, enter next day open. "
        "**Weekly RSI(9) > 50** confirms higher timeframe uptrend (use checkbox to filter). "
        "Exit when EMA(3) or WMA(21) cross back above RSI(9), or RSI falls below 50 again. "
        "Score weights: NK Core Signal 40 · RSI(9) zone 20 · Weekly trend 15 · Approaching 50 10 · "
        "Supporting signals (Stoch/MACD/Candle/Vol) 15. "
        "For educational purposes only — not SEBI-registered investment advice."
    )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — FRVP SIGNAL
# ══════════════════════════════════════════════════════════════════════════════
with tab_frvp:
    _frvp_ph.empty()

    import yfinance as yf
    from plotly.subplots import make_subplots

    @st.cache_data(ttl=3600, show_spinner=False)
    def _frvp_fetch(sym_ns: str):
        try:
            raw_w = yf.download(sym_ns, period="6mo", interval="1wk",
                                auto_adjust=True, progress=False)
            raw_d = yf.download(sym_ns, period="6mo", interval="1d",
                                auto_adjust=True, progress=False)
            if isinstance(raw_w.columns, pd.MultiIndex):
                raw_w = raw_w.droplevel(1, axis=1)
            if isinstance(raw_d.columns, pd.MultiIndex):
                raw_d = raw_d.droplevel(1, axis=1)
            raw_w = raw_w.dropna(subset=["Close"])
            raw_d = raw_d.dropna(subset=["Close"])
            return raw_w, raw_d
        except Exception:
            return None, None

    def _find_swing_pivot(df_w):
        # Use last 26 weeks (6 months); exclude the most recent 1 week (incomplete candle)
        search = df_w.iloc[max(0, len(df_w) - 26): max(1, len(df_w) - 1)]
        if len(search) < 4:
            return max(0, len(df_w) - 13), "Low"
        # Structural pivot = the single most extreme high OR low in the 3-6 month range
        max_pos = int(search["High"].values.argmax())
        min_pos = int(search["Low"].values.argmin())
        max_val = float(search["High"].iloc[max_pos])
        min_val = float(search["Low"].iloc[min_pos])
        # Use current price position to decide: if price is closer to the high,
        # the meaningful structural anchor is the swing LOW (base of the move), and vice-versa
        current = float(df_w["Close"].iloc[-1])
        mid = (max_val + min_val) / 2
        offset = len(df_w) - len(search)
        if current >= mid:
            # Price in upper half → anchor from the swing LOW
            return offset + min_pos, "Low"
        else:
            # Price in lower half → anchor from the swing HIGH
            return offset + max_pos, "High"

    def _compute_frvp(df_slice, n_bins=30, va_pct=0.70):
        if df_slice.empty or len(df_slice) < 2:
            return None
        price_min = float(df_slice["Low"].min())
        price_max = float(df_slice["High"].max())
        if price_max <= price_min:
            return None
        bin_size = (price_max - price_min) / n_bins
        vol_per_bin = np.zeros(n_bins)
        for _, row in df_slice.iterrows():
            lo, hi, vol = float(row["Low"]), float(row["High"]), float(row.get("Volume", 0) or 0)
            span = hi - lo
            if span <= 0:
                continue
            for i in range(n_bins):
                b_lo = price_min + i * bin_size
                b_hi = b_lo + bin_size
                overlap = max(0.0, min(hi, b_hi) - max(lo, b_lo))
                vol_per_bin[i] += vol * (overlap / span)
        poc_bin = int(vol_per_bin.argmax())
        poc = price_min + (poc_bin + 0.5) * bin_size
        total_vol = vol_per_bin.sum()
        target = total_vol * va_pct
        lo_idx = hi_idx = poc_bin
        va_vol = vol_per_bin[poc_bin]
        # Market Profile standard: expand symmetrically — keep equal distance above/below POC.
        # When one side is exhausted, continue on the other.
        while va_vol < target and (lo_idx > 0 or hi_idx < n_bins - 1):
            above_dist = hi_idx - poc_bin
            below_dist = poc_bin - lo_idx
            can_up   = hi_idx < n_bins - 1
            can_down = lo_idx > 0
            if can_up and (above_dist <= below_dist or not can_down):
                hi_idx += 1
                va_vol += vol_per_bin[hi_idx]
            elif can_down:
                lo_idx -= 1
                va_vol += vol_per_bin[lo_idx]
            else:
                break
        vah = price_min + (hi_idx + 1) * bin_size
        val = price_min + lo_idx * bin_size
        bins_df = pd.DataFrame({
            "price": price_min + (np.arange(n_bins) + 0.5) * bin_size,
            "volume": vol_per_bin,
        })
        return {"poc": poc, "vah": vah, "val": val, "bins": bins_df}

    # ── Tab identity banner ───────────────────────────────────────────────────
    st.markdown(
        "<div style='background:#1e293b;border-left:4px solid #6366f1;"
        "padding:10px 16px;border-radius:6px;margin-bottom:12px;font-size:13px'>"
        "📅 <b>Anchor:</b> Weekly swing pivot &nbsp;|&nbsp; "
        "⏱️ <b>Trade timeframe:</b> Daily bars &nbsp;|&nbsp; "
        "🎯 <b>Use case:</b> Swing / positional trades (days to weeks)"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Controls ──────────────────────────────────────────────────────────────
    all_stocks = sorted({s.replace(".NS", "") for sec in SECTOR_STOCKS.values() for s in sec})
    sel = st.selectbox("Select Stock", all_stocks, key="frvp_stock")
    sym_ns = sel + ".NS"

    with st.spinner(f"Computing FRVP for {sel}…"):
        df_w, df_d = _frvp_fetch(sym_ns)

    if df_w is None or df_w.empty or df_d is None or df_d.empty:
        st.warning(f"No data available for {sel}. Try another stock.")
    else:
        pivot_idx, _ = _find_swing_pivot(df_w)
        swing_pivot_date = df_w.index[pivot_idx]  # raw yfinance date for slice

        # Step 2: compute poc1 from DAILY FRVP over the full Step-1 range.
        # Daily data gives the same precise POC that TradingView's developing POC
        # settles to (e.g. 1,147.94 for INFY). Weekly FRVP gives a different,
        # higher POC because weekly bars smooth out intra-week volume distribution.
        df_d_full = df_d[df_d.index >= swing_pivot_date]
        frvp1 = (_compute_frvp(df_d_full) if len(df_d_full) >= 2
                 else _compute_frvp(df_w.iloc[pivot_idx:]))
        if frvp1 is None:
            st.warning("Insufficient data to compute volume profile.")
        else:
            poc1 = frvp1["poc"]
            # Scan WEEKLY bars backwards: find the latest candle that STRADDLED the
            # developing POC (Low <= poc1 <= High). Straddle = price crossed through
            # the POC level during that candle — the true "candle cut" condition.
            # High >= poc1 alone is too loose; Low <= poc1 <= High ensures the candle
            # actually traded on BOTH sides of the POC level.
            touch_idx = pivot_idx  # fallback: swing pivot itself
            for i in range(len(df_w) - 1, pivot_idx - 1, -1):
                if float(df_w["Low"].iloc[i]) <= poc1 <= float(df_w["High"].iloc[i]):
                    touch_idx = i
                    break

            start_date = df_w.index[touch_idx]
            # Step 3: FRVP start shifts to the Step-2 candle-cut date (Jun 8 for INFY),
            # end = last daily candle. Compute final POC on this daily slice.
            df_d_slice = df_d[df_d.index >= start_date]
            frvp = _compute_frvp(df_d_slice) if len(df_d_slice) >= 2 else frvp1

            poc  = frvp["poc"]
            vah  = frvp["vah"]
            val  = frvp["val"]
            bins_df = frvp["bins"]

            current_price = float(df_d["Close"].iloc[-1])
            signal    = "BUY" if current_price > poc else "SELL"
            sig_color = "#4ade80" if signal == "BUY" else "#f87171"
            bias_word = "ABOVE" if signal == "BUY" else "BELOW"

            # ── Signal card ───────────────────────────────────────────────────
            st.markdown(
                f"<div style='background:#111827;border-left:5px solid {sig_color};"
                f"padding:14px 20px;border-radius:8px;margin-bottom:14px'>"
                f"<span style='font-size:24px;font-weight:700;color:{sig_color}'>{signal}</span>"
                f"&nbsp;&nbsp;"
                f"<span style='color:#ccc;font-size:15px'>FRVP POC: "
                f"<b style='color:#fff'>₹{poc:,.2f}</b>"
                f" — price is <b style='color:{sig_color}'>{bias_word}</b> the POC</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            # ── Plotly chart ─────────────────────────────────────────────────
            # yfinance weekly bars use the LAST trading day of the week as the bar date,
            # but TradingView labels the same bar as the Monday (week start).
            # Normalize both dates to Monday so they match TradingView display.
            def _to_week_monday(d):
                ts = pd.Timestamp(d)
                return ts - pd.Timedelta(days=ts.weekday())

            swing_date_tv = _to_week_monday(swing_pivot_date)
            start_date_tv = _to_week_monday(start_date)   # weekly bar → normalize to Monday

            df_plot = df_d[df_d.index >= start_date].copy()
            if df_plot.empty:
                df_plot = df_d.copy()

            # ── H-M RSI(9) computations on FULL daily close (needs history) ──
            _close_full = df_d["Close"]
            _d9f        = _close_full.diff()
            _g9f        = _d9f.clip(lower=0).rolling(9).mean()
            _l9f        = (-_d9f.clip(upper=0)).rolling(9).mean()
            _rsi9_full  = (100 - (100 / (1 + _g9f / _l9f.replace(0, float("nan"))))).dropna()
            _ema3_full  = _rsi9_full.ewm(span=3, adjust=False).mean()
            _w21        = np.arange(1, 22, dtype=float)
            _wma21_full = _rsi9_full.rolling(21).apply(
                lambda x: float(np.dot(x, _w21) / _w21.sum()), raw=True
            )
            # Slice to FRVP display range (same dates as df_plot)
            _rsi9  = _rsi9_full[_rsi9_full.index >= df_plot.index[0]]
            _ema3  = _ema3_full.reindex(_rsi9.index)
            _wma21 = _wma21_full.reindex(_rsi9.index)
            # Entry signals: RSI(9) crosses above 50 from below
            _rsi9_arr = _rsi9_full.values
            _sig_x2, _sig_y2_rsi = [], []
            for _i in range(1, len(_rsi9_full)):
                if (_rsi9_full.index[_i] >= df_plot.index[0]
                        and _rsi9_arr[_i] >= 50 and _rsi9_arr[_i - 1] < 50):
                    _sig_x2.append(_rsi9_full.index[_i])
                    _sig_y2_rsi.append(float(_rsi9_arr[_i]))

            fig = make_subplots(
                rows=2, cols=2,
                row_heights=[0.65, 0.35],
                column_widths=[0.80, 0.20],
                specs=[
                    [{}, {}],
                    [{}, None],
                ],
                shared_yaxes=True,
                shared_xaxes=True,
                vertical_spacing=0.06,
                horizontal_spacing=0.005,
            )

            fig.add_trace(go.Candlestick(
                x=df_plot.index,
                open=df_plot["Open"], high=df_plot["High"],
                low=df_plot["Low"],   close=df_plot["Close"],
                increasing_line_color="#4ade80",
                decreasing_line_color="#f87171",
                name=sel,
            ), row=1, col=1)

            # EMA(20) — computed on full daily history for accuracy, plotted on df_plot range
            _ema20_full = df_d["Close"].ewm(span=20, adjust=False).mean()
            _ema20_plot = _ema20_full[_ema20_full.index >= df_plot.index[0]]
            fig.add_trace(go.Scatter(
                x=_ema20_plot.index, y=_ema20_plot,
                name="EMA(20)", line=dict(color="#FFD600", width=1.5),
            ), row=1, col=1)

            for price_level, label, color, dash in [
                (vah,           f"VAH {vah:,.2f}",   "cyan",      "dot"),
                (poc,           f"POC {poc:,.2f}",   "white",     "solid"),
                (val,           f"VAL {val:,.2f}",   "cyan",      "dot"),
                (current_price, f"CMP {current_price:,.2f}", sig_color, "dash"),
            ]:
                fig.add_shape(type="line", x0=df_plot.index[0], x1=df_plot.index[-1],
                              y0=price_level, y1=price_level,
                              line=dict(color=color, width=2 if label.startswith("POC") else 1,
                                        dash=dash),
                              row=1, col=1)
                fig.add_annotation(
                    x=df_plot.index[-1], y=price_level, text=label,
                    showarrow=False, xanchor="left", font=dict(color=color, size=11),
                    xref="x", yref="y",
                )

            bar_colors = ["#4ade80" if p >= poc else "#f87171" for p in bins_df["price"]]
            fig.add_trace(go.Bar(
                x=bins_df["volume"], y=bins_df["price"],
                orientation="h",
                marker_color=bar_colors,
                marker_opacity=0.7,
                showlegend=False,
                name="Volume Profile",
            ), row=1, col=2)

            # ── RSI(9) H-M panel (row 2, spanning both cols) ─────────────
            _idx  = _rsi9.index
            _mid  = pd.Series(50.0, index=_idx)
            _rsi_above = _rsi9.where(_rsi9 >= 50, 50.0)
            _rsi_below = _rsi9.where(_rsi9 <= 50, 50.0)

            # Green fill above 50
            fig.add_trace(go.Scatter(
                x=_idx, y=_mid, line=dict(width=0), mode="lines",
                showlegend=False, hoverinfo="skip",
            ), row=2, col=1)
            fig.add_trace(go.Scatter(
                x=_idx, y=_rsi_above,
                fill="tonexty", fillcolor="rgba(38,166,154,0.35)",
                line=dict(width=0), mode="lines",
                showlegend=False, hoverinfo="skip",
            ), row=2, col=1)

            # Red fill below 50
            fig.add_trace(go.Scatter(
                x=_idx, y=_mid, line=dict(width=0), mode="lines",
                showlegend=False, hoverinfo="skip",
            ), row=2, col=1)
            fig.add_trace(go.Scatter(
                x=_idx, y=_rsi_below,
                fill="tonexty", fillcolor="rgba(239,83,80,0.35)",
                line=dict(width=0), mode="lines",
                showlegend=False, hoverinfo="skip",
            ), row=2, col=1)

            # RSI(9), EMA(3), WMA(21) lines
            fig.add_trace(go.Scatter(
                x=_idx, y=_rsi9, name="RSI(9)",
                line=dict(color="#90CAF9", width=1.5),
            ), row=2, col=1)
            fig.add_trace(go.Scatter(
                x=_idx, y=_ema3, name="EMA(3)",
                line=dict(color="#4CAF50", width=1.5),
            ), row=2, col=1)
            fig.add_trace(go.Scatter(
                x=_wma21.reindex(_idx).index, y=_wma21.reindex(_idx),
                name="WMA(21)", line=dict(color="#EF5350", width=1.5),
            ), row=2, col=1)

            # Entry signal dots on RSI panel
            if _sig_x2:
                fig.add_trace(go.Scatter(
                    x=_sig_x2, y=_sig_y2_rsi, mode="markers",
                    name="H-M Entry", showlegend=False,
                    marker=dict(color="lime", size=7, symbol="circle",
                                line=dict(color="white", width=1)),
                ), row=2, col=1)

            fig.add_hline(y=50, line_dash="dash", line_color="#888888",
                          annotation_text="50", row=2, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="#FFD600",
                          annotation_text="30", row=2, col=1)

            fig.update_layout(
                height=720,
                template="plotly_dark",
                paper_bgcolor="#0e1117",
                plot_bgcolor="#0e1117",
                xaxis_rangeslider_visible=False,
                title=dict(
                    text=(f"{sel} — FRVP Signal  |  "
                          f"Step 1 Swing Start: {swing_date_tv.strftime('%d %b %Y')}  →  "
                          f"Step 2 Candle Cut: {start_date_tv.strftime('%d %b %Y')}"),
                    font=dict(size=14),
                ),
                margin=dict(l=10, r=10, t=45, b=10),
                showlegend=True,
                legend=dict(orientation="h", y=1.04, x=0),
                yaxis3=dict(title="RSI(9)", range=[0, 100]),
            )
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(showgrid=True, gridcolor="#1e2130", tickformat=",.0f")
            fig.update_xaxes(showgrid=False, col=2)

            st.plotly_chart(fig, width='stretch')

            # ── Key levels table ──────────────────────────────────────────────
            st.markdown("**Key Price Levels**")
            kl = pd.DataFrame({
                "Level": ["Value Area High (VAH)", "FRVP POC ← BUY / SELL gate",
                          "Value Area Low (VAL)", "Current Market Price"],
                "Price (₹)": [f"{vah:,.2f}", f"{poc:,.2f}", f"{val:,.2f}", f"{current_price:,.2f}"],
                "Bias": ["Resistance", "BUY / SELL gate", "Support",
                         f"{'↑ Above POC' if signal=='BUY' else '↓ Below POC'}"],
            })
            st.dataframe(kl, width='stretch', hide_index=True)

            st.caption(
                f"FRVP logic: Step 1 — anchor from the structural swing high/low of the last 3–6 months "
                f"(most extreme price level; direction chosen by current price position). "
                f"Step 2 — compute initial POC from weekly data; shift start to the last daily candle "
                f"that traded through (Low ≤ POC ≤ High) the initial POC. "
                f"Step 3 — recompute final POC on daily data from the shifted start date. "
                f"Value Area (VAH/VAL) expands symmetrically from POC covering 70% of total volume. "
                f"Signal: price > POC = BUY bias, price < POC = SELL bias. Educational use only."
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — FRVP H-M SCANNER
# Validated confluence: H-M buy regime + Close > VAH (rolling FRVP) + EMA-20
# pullback. Backed by a 20-year / Nifty-500 ablation study (see
# backend/calculations/frvp_confluence.py docstring) — the "complete" variant
# was the best risk-adjusted performer of 7 tested (60.4% win rate / std 9.50
# at 20-day hold vs. 54.6% / std 14.38 for H-M alone).
# ══════════════════════════════════════════════════════════════════════════════
with tab_frvp_hm:
    _frvp_hm_ph.empty()

    from backend.calculations.frvp_confluence import scan_current_state, backtest_symbol
    from concurrent.futures import ThreadPoolExecutor, as_completed

    st.subheader("🔍 FRVP H-M Scanner")
    st.markdown(
        "<div style='background:#1e293b;border-left:4px solid #f59e0b;"
        "padding:10px 16px;border-radius:6px;margin-bottom:12px;font-size:13px'>"
        "🎯 <b>Confluence:</b> H-M buy regime + Close &gt; VAH + EMA-20 pullback "
        "&nbsp;|&nbsp; ⏱️ <b>Use case:</b> Swing trades (5–20 day hold) "
        "&nbsp;|&nbsp; 📊 <b>Validated:</b> 20-year Nifty 500 ablation study"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "All three conditions must fire together on the same bar: H-M's RSI-above-WMA "
        "bullish regime, price closing above the Fixed-Range Volume Profile's Value Area "
        "High (rolling 60-day window), and price pulling back to within 1% of a rising, "
        "bullish-confirmed 20 EMA. Signals are deduplicated (fresh occurrence + 10-bar "
        "cooldown) so a persisting regime isn't counted as a new signal every day. "
        "For informational and educational purposes only — not investment advice."
    )

    all_syms_ns = sorted({s for stocks in SECTOR_STOCKS.values() for s in stocks})
    all_syms_display = [s.replace(".NS", "") for s in all_syms_ns]

    c1, c2 = st.columns([3, 1])
    with c1:
        selected_display = st.multiselect(
            "Stocks to scan",
            options=all_syms_display,
            default=all_syms_display,
            key="frvp_hm_stocks",
            help="Leave all selected to scan every stock in the dashboard universe.",
        )
    with c2:
        st.markdown("<br>", unsafe_allow_html=True)
        run_btn = st.button("▶ Run FRVP H-M Scan", type="primary", key="frvp_hm_run")

    selected_syms = [s + ".NS" for s in selected_display]

    @st.cache_data(ttl=900, show_spinner=False)
    def _frvp_hm_scan(symbols: tuple) -> pd.DataFrame:
        rows = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = {pool.submit(scan_current_state, s): s for s in symbols}
            for fut in as_completed(futs):
                try:
                    r = fut.result()
                    if r is not None:
                        rows.append(r)
                except Exception:
                    continue
        if not rows:
            return pd.DataFrame()
        df_out = pd.DataFrame(rows)
        order = df_out["Days Since Signal"].fillna(10_000)
        return df_out.assign(_o=order).sort_values("_o").drop(columns="_o").reset_index(drop=True)

    if run_btn:
        if not selected_syms:
            st.warning("Select at least one stock.")
        else:
            with st.spinner(f"Scanning {len(selected_syms)} stocks for confluence signals…"):
                df_res = _frvp_hm_scan(tuple(selected_syms))
            st.session_state["frvp_hm_df"] = df_res
            import pytz as _pytz
            st.session_state["frvp_hm_fetch_time"] = pd.Timestamp.now(tz=_pytz.timezone("Asia/Kolkata"))
            st.rerun()

    df_show = st.session_state.get("frvp_hm_df", pd.DataFrame())

    if df_show.empty and not run_btn:
        st.info("Click **▶ Run FRVP H-M Scan** to check every stock for the confluence condition.")
    elif df_show.empty:
        st.warning("No data returned — try again or select fewer stocks.")
    else:
        n_fresh = int(df_show["Fresh Today"].sum())
        n_regime = int(df_show["HM Regime"].sum())
        n_vah = int(df_show["Above VAH"].sum())
        n_pullback = int(df_show["EMA Pullback"].sum())
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🟢 Fresh Signal Today", n_fresh)
        m2.metric("H-M Buy Regime", n_regime)
        m3.metric("Above VAH", n_vah)
        m4.metric("EMA Pullback OK", n_pullback)

        fetch_ts = st.session_state.get("frvp_hm_fetch_time")
        if fetch_ts is not None:
            import pytz as _pytz
            now_ist = pd.Timestamp.now(tz=_pytz.timezone("Asia/Kolkata"))
            age_mins = int((now_ist - fetch_ts).total_seconds() // 60)
            age_str = f"{age_mins} min ago" if age_mins > 0 else "just now"
            st.caption(
                f"📡 Data fetched at **{fetch_ts.strftime('%d-%b-%Y %H:%M:%S')} IST** · "
                f"{age_str} · Cache refreshes every 15 min on next Run"
            )

        only_fresh = st.checkbox("Show only stocks with a fresh signal today", key="frvp_hm_only_fresh")
        view = df_show[df_show["Fresh Today"]] if only_fresh else df_show

        # StopLoss is computed off TODAY's bar (Low - 0.5*ATR), not off the historical
        # "Last Signal Date" shown in the same row — showing it for a stale signal reads
        # as if it belongs to that old trade, when it's just today's live ATR reference
        # with no active setup behind it. Blank it out unless the signal is fresh today.
        # Pre-formatted to its final display string here (not left as None/NaN for the
        # Styler to handle) — st.dataframe() doesn't reliably run .format() callables on
        # None/NaN cells in an object-dtype column, it just stringifies them as "None".
        def _stop_display(row):
            if row["Fresh Today"] and pd.notna(row["StopLoss"]):
                return f"₹{row['StopLoss']:,.2f}"
            return "—"
        view = view.assign(StopLoss=view.apply(_stop_display, axis=1))

        def _row_colour(row):
            if row["Fresh Today"]:
                c = "background-color:#0d3b0d; color:#ccffcc"
            elif row["HM Regime"] and row["Above VAH"]:
                c = "background-color:#1a2a1a; color:#ddffdd"
            else:
                c = ""
            return [c] * len(row)

        _bool_icon = lambda v: "✅" if v else "—"
        styled = (
            view.style
            .apply(_row_colour, axis=1)
            .format({
                "CMP": lambda v: f"₹{v:,.2f}" if v is not None else "—",
                "VAH": lambda v: f"₹{v:,.2f}" if v is not None else "—",
                "EMA20": lambda v: f"₹{v:,.2f}" if v is not None else "—",
                "HM Regime": _bool_icon, "Above VAH": _bool_icon,
                "EMA Pullback": _bool_icon, "Fresh Today": _bool_icon,
                "Last Signal Date": lambda v: v if v else "—",
                "Days Since Signal": lambda v: f"{int(v)}" if v is not None and v == v else "—",
            })
        )
        st.dataframe(styled, width='stretch', hide_index=True, height=420)

        st.download_button(
            "⬇ Export CSV",
            view.to_csv(index=False).encode(),
            file_name="frvp_hm_scanner.csv",
            mime="text/csv",
            key="frvp_hm_export",
        )

        # ── Backtest ──────────────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("📈 Backtest Results")
        st.caption(
            "Validated on this exact confluence condition across 20 years / Nifty 500 "
            "(see the ablation study). Below re-runs the same logic on your selected "
            "stocks and lookback period."
        )

        bt_c1, bt_c2 = st.columns(2)
        with bt_c1:
            bt_period = st.selectbox("Backtest lookback", ["3y", "5y", "10y", "20y"], index=0,
                                     key="frvp_hm_bt_period")
        with bt_c2:
            bt_hold = st.selectbox("Hold period", [5, 10, 20], index=2, key="frvp_hm_bt_hold")

        run_bt = st.button("▶ Run Backtest", key="frvp_hm_bt_run")

        if run_bt:
            bt_syms = tuple(row["Symbol"] + ".NS" for _, row in df_show.iterrows())

            @st.cache_data(ttl=1800, show_spinner=False)
            def _run_bt(syms: tuple, period: str) -> pd.DataFrame:
                frames = []
                with ThreadPoolExecutor(max_workers=6) as pool:
                    futs = {pool.submit(backtest_symbol, s, period): s for s in syms}
                    for fut in as_completed(futs):
                        try:
                            r = fut.result()
                            if not r.empty:
                                frames.append(r)
                        except Exception:
                            continue
                return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

            with st.spinner(f"Backtesting {len(bt_syms)} stocks over {bt_period}…"):
                df_trades = _run_bt(bt_syms, bt_period)
            st.session_state["frvp_hm_trades"] = df_trades
            st.rerun()

        df_trades = st.session_state.get("frvp_hm_trades", pd.DataFrame())

        if df_trades.empty:
            st.info("Click **▶ Run Backtest** to compute historical performance for the scanned stocks.")
        else:
            ret_col = f"Ret{bt_hold}d%"
            valid = df_trades.dropna(subset=[ret_col]) if ret_col in df_trades.columns else pd.DataFrame()

            if valid.empty:
                st.warning("No completed trades for this hold period yet — try a shorter hold or longer lookback.")
            else:
                win_rate = (valid[ret_col] > 0).mean() * 100
                avg_ret = valid[ret_col].mean()
                med_ret = valid[ret_col].median()
                std_ret = valid[ret_col].std()

                bm1, bm2, bm3, bm4, bm5 = st.columns(5)
                bm1.metric("Total Signals", len(df_trades))
                bm2.metric("Stocks with Signals", df_trades["Symbol"].nunique())
                bm3.metric("Win Rate", f"{win_rate:.1f}%")
                bm4.metric("Avg Return", f"{avg_ret:+.2f}%")
                bm5.metric("Std Dev", f"{std_ret:.2f}%")

                st.caption(
                    f"Reference (20y / Nifty 500 full ablation study, {bt_hold}d hold): "
                    f"{'60.4% win / +2.67% avg / 9.50 std' if bt_hold == 20 else '57.3% win / +1.14% avg / 6.11 std' if bt_hold == 10 else '54.9% win / +0.62% avg / 4.14 std'} "
                    f"— your numbers above are scoped to the stocks/period selected, not the full study."
                )

                # ── Trade Log ─────────────────────────────────────────────────
                st.markdown("---")
                st.subheader("📋 Trade Log")

                syms_in_bt = sorted(df_trades["Symbol"].unique())
                tl_sym = st.selectbox("View trades for", ["All"] + syms_in_bt, key="frvp_hm_tl_sym")
                tl_view = df_trades if tl_sym == "All" else df_trades[df_trades["Symbol"] == tl_sym]
                tl_view = tl_view.sort_values("SignalDate", ascending=False).reset_index(drop=True)

                def _ret_color(val):
                    if not isinstance(val, (int, float)) or val != val:
                        return ""
                    return "color:#4ade80;font-weight:700" if val > 0 else (
                        "color:#f87171;font-weight:700" if val < 0 else "")

                ret_cols_present = [c for c in tl_view.columns if c.startswith("Ret")]
                _fmt = {"EntryPrice": "₹{:.2f}",
                       "StopLoss": lambda v: f"₹{v:,.2f}" if v == v else "—"}
                _fmt.update({c: lambda v: f"{v:+.2f}%" if v == v else "—" for c in ret_cols_present})

                styled_tl = (
                    tl_view.style
                    .map(_ret_color, subset=ret_cols_present)
                    .format(_fmt, na_rep="—")
                )
                st.dataframe(styled_tl, width='stretch', hide_index=True, height=380)

                st.download_button(
                    "⬇ Export Trade Log CSV",
                    tl_view.to_csv(index=False).encode(),
                    file_name=f"frvp_hm_trade_log_{tl_sym.lower()}.csv",
                    mime="text/csv",
                    key="frvp_hm_tl_export",
                )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — BEST MA ANALYZER
# ══════════════════════════════════════════════════════════════════════════════
with tab_best_ma:
    _best_ma_ph.empty()
    st.subheader("📏 Best Moving Average — MA Respect Analyzer")
    st.caption(
        "Identifies which moving average a stock respects most consistently using "
        "ATR-normalized touch detection, Wilson-adjusted scoring, and out-of-time consistency validation. "
        "For educational and historical analysis only."
    )

    # ── Input controls ─────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        sector_options = sorted(SECTOR_STOCKS.keys())
        selected_sector = st.selectbox("Sector", sector_options, key="best_ma_sector")
    with col2:
        stocks = SECTOR_STOCKS.get(selected_sector, [])
        stock_names = [s.replace(".NS", "") for s in stocks]
        selected_stock = st.selectbox("Stock", stock_names, key="best_ma_stock")
    with col3:
        period_options = {"3 Years": "3y", "5 Years": "5y", "10 Years": "10y"}
        selected_period = st.selectbox("History", list(period_options.keys()), index=1, key="best_ma_period")
        period_str = period_options[selected_period]

    # ── Advanced parameters ────────────────────────────────────────────────────
    with st.expander("⚙ Advanced Settings"):
        col_a1, col_a2, col_a3, col_a4 = st.columns(4)
        with col_a1:
            direction_type = st.radio("Direction", ["Support", "Resistance"], horizontal=True, key="best_ma_direction")
        with col_a2:
            tol_atr = st.slider("Touch Tolerance (ATR units)", 0.05, 1.0, 0.25, 0.05, key="best_ma_tol")
        with col_a3:
            fail_atr = st.slider("Failure Threshold (ATR units)", 0.2, 2.0, 0.5, 0.1, key="best_ma_fail")
        with col_a4:
            rebound_atr = st.slider("Rebound Target (ATR units)", 0.5, 3.0, 1.0, 0.1, key="best_ma_rebound")

    # ── Analyze button ─────────────────────────────────────────────────────────
    if st.button("▶ Analyze", type="primary", width='content'):
        ticker = f"{selected_stock}.NS"
        direction_lower = direction_type.lower()

        @st.cache_data(ttl=3600, show_spinner=False)
        def fetch_ohlcv(_ticker, _period):
            import yfinance as yf
            raw = yf.download(_ticker, period=_period, interval="1d", progress=False, auto_adjust=True)
            if raw is None or raw.empty or len(raw) < 60:
                return None

            # Normalize OHLCV (handle multi-index columns from auto_adjust)
            cols = {}
            for src, dst in [("Open", "open"), ("High", "high"), ("Low", "low"),
                              ("Close", "close"), ("Volume", "volume")]:
                if src in raw.columns:
                    series = raw[src]
                    if isinstance(series, pd.DataFrame):
                        series = series.iloc[:, 0]
                    cols[dst] = series

            if not all(k in cols for k in ["open", "high", "low", "close"]):
                return None

            df = pd.DataFrame(cols)
            df["date"] = pd.to_datetime(raw.index)
            return df.reset_index(drop=True)

        with st.spinner("Fetching data & analyzing…"):
            df = fetch_ohlcv(ticker, period_str)

            if df is None or len(df) < 60:
                result = None
            else:
                try:
                    result = analyze_stock(
                        df,
                        ma_types=("EMA", "SMA", "RMA", "WMA"),
                        ma_periods=(5, 8, 9, 10, 13, 20, 21, 34, 50, 55, 100, 150, 200),
                        direction=direction_lower,
                        tol_atr=tol_atr,
                        fail_atr=fail_atr,
                        rebound_atr=rebound_atr,
                        look_forward=10,
                        min_touches=8,
                        recent_bars=252,
                    )
                except Exception as e:
                    st.error(f"Analysis failed: {e}")
                    result = None

        if df is None or len(df) < 60:
            st.error("Insufficient historical data (need ≥60 bars). Try a longer history period.")
        elif result is None:
            pass  # error already shown above
        elif result["primary"] is None:
            st.warning(
                "No MA candidates found with a stable, statistically sufficient preference. "
                "Try a longer history, switch direction, or relax the tolerance settings."
            )
        else:
            primary = result["primary"]
            secondary = result["secondary"]
            long_term = result["long_term"]
            candidates = result["candidates"]  # dict[(type, period)] -> RespectMetrics
            touches = result["touches"]        # list[TouchEvent]

            ma_label = f"{primary.ma_type} {primary.ma_period}"

            # ── Summary cards ──────────────────────────────────────────────────
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("🎯 Primary MA", ma_label, f"Score: {primary.final_score:.0f}")
            m2.metric("📊 Current Status", primary.current_status, primary.confidence)
            m3.metric("✅ Hold Rate (Wilson)", f"{primary.wilson_hold_rate * 100:.1f}%",
                       f"raw {primary.raw_hold_rate * 100:.1f}%")
            m4.metric("📍 Touches", str(primary.total_touches),
                       f"{primary.successful_touches}W / {primary.failed_touches}L")

            st.markdown("---")

            # ── Candlestick chart with MAs ───────────────────────────────────────
            mas = compute_mas(
                df,
                types=("EMA", "SMA", "RMA", "WMA"),
                periods=(5, 8, 9, 10, 13, 20, 21, 34, 50, 55, 100, 150, 200),
            )
            atr_s = compute_atr(
                df.rename(columns={"high": "High", "low": "Low", "close": "Close"}),
                length=14,
            )

            df_chart = df.tail(504).copy()  # ~2y view
            chart_start_idx = df_chart.index[0]

            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df_chart["date"], open=df_chart["open"], high=df_chart["high"],
                low=df_chart["low"], close=df_chart["close"], name="Price"
            ))

            primary_ma_s = mas.get((primary.ma_type, primary.ma_period))
            if primary_ma_s is not None:
                ma_chart = primary_ma_s.loc[chart_start_idx:]
                fig.add_trace(go.Scatter(
                    x=df_chart["date"], y=ma_chart.values,
                    mode="lines", name=ma_label, line=dict(color="orange", width=2)
                ))
                atr_chart = atr_s.loc[chart_start_idx:]
                upper_band = ma_chart + 2 * atr_chart
                lower_band = ma_chart - 2 * atr_chart
                fig.add_trace(go.Scatter(x=df_chart["date"], y=upper_band.values, mode="lines",
                                          line=dict(color="rgba(255,165,0,0.15)"), showlegend=False))
                fig.add_trace(go.Scatter(x=df_chart["date"], y=lower_band.values, mode="lines",
                                          line=dict(color="rgba(255,165,0,0.15)"), fill="tonexty",
                                          name="±2 ATR Band"))

            if secondary is not None:
                sec_ma_s = mas.get((secondary.ma_type, secondary.ma_period))
                if sec_ma_s is not None:
                    fig.add_trace(go.Scatter(
                        x=df_chart["date"], y=sec_ma_s.loc[chart_start_idx:].values,
                        mode="lines", name=f"{secondary.ma_type} {secondary.ma_period} (secondary)",
                        line=dict(color="cyan", width=1.5, dash="dot")
                    ))

            if long_term is not None:
                lt_ma_s = mas.get((long_term.ma_type, long_term.ma_period))
                if lt_ma_s is not None:
                    fig.add_trace(go.Scatter(
                        x=df_chart["date"], y=lt_ma_s.loc[chart_start_idx:].values,
                        mode="lines", name=f"{long_term.ma_type} {long_term.ma_period} (long-term)",
                        line=dict(color="violet", width=1.5, dash="dash")
                    ))

            # Touch/outcome markers for primary MA, restricted to the visible window
            prim_touches = [t for t in touches
                             if t.ma_type == primary.ma_type and t.ma_period == primary.ma_period
                             and t.date >= df_chart["date"].iloc[0]]
            marker_map = {
                "success": ("triangle-up", "#00C853", "Rebound"),
                "failure": ("x", "#FF1744", "Failure"),
                "neutral": ("diamond", "#FFD600", "Neutral"),
            }
            for outcome, (symbol, color, label) in marker_map.items():
                pts = [t for t in prim_touches if t.outcome == outcome]
                if pts:
                    fig.add_trace(go.Scatter(
                        x=[t.date for t in pts], y=[t.low if direction_lower == "support" else t.high for t in pts],
                        mode="markers", name=label,
                        marker=dict(symbol=symbol, size=9, color=color, line=dict(width=1, color="white")),
                        hovertext=[f"{outcome.title()} · {t.date} · bars: {t.bars_to_outcome}" for t in pts],
                        hoverinfo="text"
                    ))

            fig.update_xaxes(
                rangeslider=dict(visible=False),
                rangeselector=dict(buttons=[
                    dict(count=3, label="3m", step="month"),
                    dict(count=6, label="6m", step="month"),
                    dict(count=1, label="1y", step="year"),
                    dict(count=2, label="2y", step="year"),
                    dict(step="all", label="All"),
                ])
            )
            fig.update_layout(title=f"{selected_stock} — Price & Best-Respected MA", height=480,
                               template="plotly_dark", legend=dict(orientation="h", y=1.08))
            st.plotly_chart(fig, width='stretch')

            st.markdown("---")

            # ── Ranked candidates table ────────────────────────────────────────
            st.subheader("📊 Ranked MA Candidates")
            candidates_data = []
            for m in candidates.values():
                candidates_data.append({
                    "MA": f"{m.ma_type} {m.ma_period}",
                    "Touches": m.total_touches,
                    "Win/Loss/Neutral": f"{m.successful_touches}/{m.failed_touches}/{m.neutral_touches}",
                    "Hold Rate (%)": round(m.raw_hold_rate * 100, 1),
                    "Wilson Hold (%)": round(m.wilson_hold_rate * 100, 1),
                    "Consistency": round(m.consistency_score, 2),
                    "Neighbor Stab.": round(m.neighbor_stability_score, 2),
                    "Score": m.final_score,
                    "Confidence": m.confidence,
                    "Status": m.current_status,
                })
            df_cand = (pd.DataFrame(candidates_data)
                       .sort_values("Score", ascending=False)
                       .reset_index(drop=True))
            st.dataframe(
                df_cand.style.format({"Score": "{:.1f}"}),
                width='stretch',
                hide_index=True
            )

            st.markdown("---")

            # ── Why selected explanation ───────────────────────────────────────
            st.subheader("💡 Why Selected")
            st.info(
                f"**{ma_label}** was selected as the primary MA with a score of "
                f"**{primary.final_score:.0f}/100** ({primary.confidence} confidence) based on "
                f"{primary.total_touches} qualifying touches — a Wilson-adjusted hold rate of "
                f"{primary.wilson_hold_rate * 100:.1f}%, out-of-time consistency of "
                f"{primary.consistency_score:.2f}, and neighbor-period stability of "
                f"{primary.neighbor_stability_score:.2f}. Currently the stock is **{primary.current_status}** "
                f"this MA."
            )
            if secondary is not None:
                st.caption(f"Secondary candidate: {secondary.ma_type} {secondary.ma_period} "
                           f"(score {secondary.final_score:.0f}, {secondary.total_touches} touches)")
            if long_term is not None:
                st.caption(f"Long-term candidate: {long_term.ma_type} {long_term.ma_period} "
                           f"(score {long_term.final_score:.0f}, {long_term.total_touches} touches)")

            # ── Touch events table ───────────────────────────────────────────────
            if touches:
                with st.expander("📍 Touch Events Detail (primary MA)"):
                    touches_data = [{
                        "Date": str(t.date),
                        "MA": f"{t.ma_type} {t.ma_period}",
                        "Low": round(t.low, 2),
                        "MA Value": round(t.ma_value, 2),
                        "Outcome": t.outcome or "—",
                        "Bars to Outcome": t.bars_to_outcome if t.bars_to_outcome is not None else "—",
                    } for t in prim_touches[-100:]]
                    if touches_data:
                        st.dataframe(pd.DataFrame(touches_data), width='stretch', hide_index=True)

            st.markdown("---")

            # ── Downloads ─────────────────────────────────────────────────────
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                csv_cand = df_cand.to_csv(index=False)
                st.download_button(
                    "⬇ Candidates CSV", csv_cand.encode(),
                    file_name=f"ma_candidates_{selected_stock.lower()}.csv",
                    mime="text/csv", key="best_ma_candidates_csv"
                )
            with col_d2:
                csv_touches = pd.DataFrame([{
                    "Date": str(t.date), "MA Type": t.ma_type, "MA Period": t.ma_period,
                    "Low": round(t.low, 2), "MA Value": round(t.ma_value, 2),
                    "Outcome": t.outcome or "", "Bars to Outcome": t.bars_to_outcome,
                } for t in touches]).to_csv(index=False)
                st.download_button(
                    "⬇ All Touch Events CSV", csv_touches.encode(),
                    file_name=f"ma_touches_{selected_stock.lower()}.csv",
                    mime="text/csv", key="best_ma_touches_csv"
                )

            st.markdown("---")

            for w in result.get("warnings", []):
                st.warning(w)

            st.caption(
                "⚠️ **Disclaimer:** This analysis identifies historically most-respected moving averages based "
                "on statistical patterns. It does not predict future price action or guarantee the stock will "
                "continue to respect any MA. Past performance is not indicative of future results. "
                "For educational purposes only."
            )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — MONTE CARLO TEST
# Upload any trade-log CSV with a return-per-trade column and stress-test it
# with bootstrap resampling + trade-order shuffle. Works with any strategy's
# results, not just this page's own scanners — purely a statistics tool, no
# trading signal of its own.
# ══════════════════════════════════════════════════════════════════════════════
with tab_monte_carlo:
    st.subheader("🎲 Monte Carlo Strategy Test")
    st.caption(
        "Upload a trade log (CSV) with one row per trade and a return-per-trade % column. "
        "Runs bootstrap resampling and trade-order shuffle to show the realistic range of "
        "outcomes and drawdown risk behind your results — not just the one sequence that "
        "happened to occur. For informational and educational purposes only."
    )

    from backend.calculations.monte_carlo_generic import (
        detect_return_column, clean_returns, bootstrap_simulation, shuffle_simulation,
        summarize_simulation, basic_trade_stats,
    )

    uploaded = st.file_uploader("Upload trade log CSV", type=["csv"], key="mc_upload")

    if uploaded is None:
        st.info("Upload a CSV to get started. Any column with a name like "
               "'Return%', 'PnL%', 'Ret', or similar is auto-detected — values can be "
               "plain numbers (2.5) or percent strings (2.5%).")
    else:
        try:
            mc_df = pd.read_csv(uploaded)
        except Exception as e:
            st.error(f"Could not read this file as CSV: {e}")
            mc_df = None

        if mc_df is not None and not mc_df.empty:
            st.markdown("**Preview**")
            st.dataframe(mc_df.head(10), width='stretch', hide_index=True)

            detected_col = detect_return_column(mc_df)
            numeric_cols = [c for c in mc_df.columns]
            default_idx = numeric_cols.index(detected_col) if detected_col in numeric_cols else 0

            mc_c1, mc_c2, mc_c3 = st.columns(3)
            with mc_c1:
                return_col = st.selectbox(
                    "Return % column", numeric_cols, index=default_idx, key="mc_return_col",
                    help="Auto-detected where possible — change if it picked the wrong column."
                )
            with mc_c2:
                mc_sims = st.number_input("Simulations", min_value=200, max_value=20000,
                                          value=2000, step=200, key="mc_sims")
            with mc_c3:
                mc_capital = st.number_input("Starting capital (₹)", min_value=1_000,
                                             value=100_000, step=10_000, key="mc_capital")

            returns = clean_returns(mc_df[return_col])
            n_dropped = len(mc_df) - len(returns)
            if n_dropped > 0:
                st.warning(f"{n_dropped} row(s) couldn't be read as a number in this column and were skipped.")

            if returns.empty:
                st.error("No valid numeric returns found in the selected column. Pick a different column.")
            else:
                stats = basic_trade_stats(returns)
                st.markdown("---")
                st.markdown("**Trade Log Summary**")
                s1, s2, s3, s4, s5 = st.columns(5)
                s1.metric("Trades", stats["n_trades"])
                s2.metric("Win Rate", f"{stats['win_rate_pct']:.1f}%")
                s3.metric("Avg Return", f"{stats['avg_return_pct']:+.2f}%")
                s4.metric("Best Trade", f"{stats['best_trade_pct']:+.2f}%")
                s5.metric("Worst Trade", f"{stats['worst_trade_pct']:+.2f}%")

                run_mc = st.button("▶ Run Monte Carlo", type="primary", key="mc_run")

                if run_mc:
                    with st.spinner(f"Running {mc_sims:,} bootstrap + {mc_sims:,} shuffle simulations…"):
                        boot = bootstrap_simulation(returns, n_sims=mc_sims, initial_capital=mc_capital)
                        shuf = shuffle_simulation(returns, n_sims=mc_sims, initial_capital=mc_capital)
                    st.session_state["mc_boot"] = boot
                    st.session_state["mc_shuf"] = shuf
                    st.rerun()

                boot = st.session_state.get("mc_boot", pd.DataFrame())
                shuf = st.session_state.get("mc_shuf", pd.DataFrame())

                if not boot.empty and not shuf.empty:
                    boot_summary = summarize_simulation(boot)
                    shuf_summary = summarize_simulation(shuf)

                    st.markdown("---")
                    st.subheader("📊 Bootstrap Simulation — Plausible Outcome Range")
                    st.caption("Resamples your trades WITH replacement — the range of outcomes this "
                              "trade population could plausibly produce, not just the one path you saw.")
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Prob. of Profit", f"{boot_summary['prob_profit_pct']:.1f}%")
                    m2.metric("Median Return", f"{boot_summary['total_return_p50']:+.1f}%")
                    m3.metric("5th–95th Pctile",
                             f"{boot_summary['total_return_p5']:+.0f}% to {boot_summary['total_return_p95']:+.0f}%")
                    m4.metric("Median Max DD", f"-{boot_summary['max_dd_p50']:.1f}%")
                    m5.metric("Worst-Case Max DD (95th)", f"-{boot_summary['max_dd_p95']:.1f}%")

                    fig_hist = go.Figure()
                    fig_hist.add_trace(go.Histogram(x=boot["total_return_pct"], nbinsx=60,
                                                    marker_color="#42A5F5", name="Total Return"))
                    fig_hist.add_vline(x=0, line_dash="dash", line_color="#EF5350")
                    fig_hist.add_vline(x=boot_summary["total_return_p50"], line_dash="dot",
                                       line_color="#FFD600", annotation_text="Median")
                    fig_hist.update_layout(template="plotly_dark", height=340,
                                           title=f"Distribution of Total Return across {mc_sims:,} Bootstrap Simulations",
                                           xaxis_title="Total Return (%)", yaxis_title="Simulations")
                    st.plotly_chart(fig_hist, width='stretch')

                    st.markdown("---")
                    st.subheader("🔀 Trade-Order Shuffle — Sequence-of-Returns Risk")
                    st.caption("Same exact trades every time (identical total return by construction) — "
                              "only the order is randomized. Shows how much worse your drawdown could "
                              "plausibly have been just from bad luck in trade sequencing.")
                    sh1, sh2, sh3 = st.columns(3)
                    sh1.metric("Actual Total Return", f"{shuf_summary['total_return_p50']:+.1f}%")
                    sh2.metric("Median Max Drawdown", f"-{shuf_summary['max_dd_p50']:.1f}%")
                    sh3.metric("Worst-Seen Max Drawdown", f"-{shuf_summary['worst_max_dd']:.1f}%")

                    fig_dd = go.Figure()
                    fig_dd.add_trace(go.Histogram(x=shuf["max_drawdown_pct"], nbinsx=50,
                                                  marker_color="#EF5350", name="Max Drawdown"))
                    fig_dd.update_layout(template="plotly_dark", height=320,
                                         title="Distribution of Max Drawdown across Trade-Order Shuffles",
                                         xaxis_title="Max Drawdown (%)", yaxis_title="Simulations")
                    st.plotly_chart(fig_dd, width='stretch')

                    st.download_button(
                        "⬇ Export Bootstrap Simulations CSV",
                        boot.to_csv(index=False).encode(),
                        file_name="monte_carlo_bootstrap.csv", mime="text/csv", key="mc_export_boot",
                    )

                    with st.expander("📖 How to read this"):
                        st.markdown("""
- **Bootstrap simulation** shows the *range* of results your trade population could plausibly
  produce — your single actual result is one draw from this distribution, not the guaranteed outcome.
- **Trade-order shuffle** isolates *sequence* risk — even a genuinely profitable trade log can
  show a much deeper drawdown than what you actually experienced, purely from unlucky ordering
  of losing trades. Size your risk around this number, not the drawdown you happened to see.
- Equity compounds directly off each trade's return % — no position sizing or leverage is
  assumed, so this reflects exactly the numbers in your uploaded file.
                        """)
                else:
                    st.info("Click **▶ Run Monte Carlo** to simulate.")

    st.caption(
        "⚠️ **Disclaimer:** This tool analyzes a trade log you provide — it does not generate, "
        "validate, or endorse any trading strategy. Simulation results describe statistical "
        "properties of your uploaded data only. For educational purposes only."
    )

from app.utils.disclaimer import show_footer
show_footer()
