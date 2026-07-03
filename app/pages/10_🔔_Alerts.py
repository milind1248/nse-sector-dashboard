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

st.set_page_config(page_title="Alerts & Scanners | NSE Swing Trading | Market Sector Analysis", layout="wide")
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()
from app.utils.seo import inject_seo
inject_seo("Alerts")
from app.utils.logo import show_logo
show_logo()

st.title("🚨 Alerts & Scanners")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption("Technical scanners and alerts across all NSE sectors. For informational and educational purposes only.")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_breakout, tab_ema, tab_hm, tab_frvp = st.tabs([
    "📡 Breakout Alerts",
    "📈 20 EMA Pullback Scanner",
    "🎯 H-M Scanner",
    "📊 FRVP Signal",
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


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — BREAKOUT ALERTS (existing, unchanged)
# ══════════════════════════════════════════════════════════════════════════════
with tab_breakout:
    st.subheader("Technical Alerts — Breakout & Reversal Patterns")
    st.caption("Stocks crossing key technical levels across all sectors.")

    @st.cache_data(ttl=3600, show_spinner=False)
    def scan_all_breakouts():
        import yfinance as yf
        alerts = []
        for sector, stocks in SECTOR_STOCKS.items():
            for sym in stocks:
                try:
                    raw = yf.download(sym, period="3mo", interval="1d", progress=False, auto_adjust=True)
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
        sel = st.selectbox("Jump to sector analysis:", alert_sectors)
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

        for sector, stocks in SECTOR_STOCKS.items():
            for sym in stocks:
                try:
                    raw = yf.download(sym, period="12mo", interval="1d",
                                      progress=False, auto_adjust=True)
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

        for sector, stocks in SECTOR_STOCKS.items():
            for sym in stocks:
                try:
                    raw = yf.download(sym, period="12mo", interval="1d", progress=False, auto_adjust=True)
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
                        wk_raw   = yf.download(sym, period="2y", interval="1wk", progress=False, auto_adjust=True)
                        wk_close = _get_close(wk_raw)
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

        frvp1 = _compute_frvp(df_w.iloc[pivot_idx:])
        if frvp1 is None:
            st.warning("Insufficient data to compute volume profile.")
        else:
            poc1 = frvp1["poc"]
            touch_idx = pivot_idx
            for i in range(len(df_w) - 1, pivot_idx - 1, -1):
                # Candle must have TRADED THROUGH the POC (Low <= POC <= High)
                if float(df_w["Low"].iloc[i]) <= poc1 <= float(df_w["High"].iloc[i]):
                    touch_idx = i
                    break

            start_date = df_w.index[touch_idx]
            # Step 3: recompute final POC on DAILY data from shifted start date
            # (daily granularity gives a more precise POC than weekly)
            df_d_slice = df_d[df_d.index >= start_date]
            frvp = _compute_frvp(df_d_slice) if len(df_d_slice) >= 2 else None
            if frvp is None:
                frvp = _compute_frvp(df_w.iloc[touch_idx:]) or frvp1

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
            df_plot = df_d[df_d.index >= start_date].copy()
            if df_plot.empty:
                df_plot = df_d.copy()

            fig = make_subplots(
                rows=1, cols=2,
                column_widths=[0.80, 0.20],
                shared_yaxes=True,
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

            fig.update_layout(
                height=580,
                template="plotly_dark",
                paper_bgcolor="#0e1117",
                plot_bgcolor="#0e1117",
                xaxis_rangeslider_visible=False,
                title=dict(
                    text=f"{sel} — FRVP Signal  |  Start: {start_date.strftime('%d %b %Y')}",
                    font=dict(size=14),
                ),
                margin=dict(l=10, r=10, t=45, b=10),
                showlegend=False,
            )
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(showgrid=True, gridcolor="#1e2130", tickformat=",.0f")
            fig.update_xaxes(showgrid=False, col=2)

            st.plotly_chart(fig, use_container_width=True)

            # ── Key levels table ──────────────────────────────────────────────
            st.markdown("**Key Price Levels**")
            kl = pd.DataFrame({
                "Level": ["Value Area High (VAH)", "FRVP POC ← BUY / SELL gate",
                          "Value Area Low (VAL)", "Current Market Price"],
                "Price (₹)": [f"{vah:,.2f}", f"{poc:,.2f}", f"{val:,.2f}", f"{current_price:,.2f}"],
                "Bias": ["Resistance", "BUY / SELL gate", "Support",
                         f"{'↑ Above POC' if signal=='BUY' else '↓ Below POC'}"],
            })
            st.dataframe(kl, use_container_width=True, hide_index=True)

            st.caption(
                f"FRVP logic: Step 1 — anchor from the structural swing high/low of the last 3–6 months "
                f"(most extreme price level; direction chosen by current price position). "
                f"Step 2 — compute initial POC from weekly data; shift start to the last daily candle "
                f"that traded through (Low ≤ POC ≤ High) the initial POC. "
                f"Step 3 — recompute final POC on daily data from the shifted start date. "
                f"Value Area (VAH/VAL) expands symmetrically from POC covering 70% of total volume. "
                f"Signal: price > POC = BUY bias, price < POC = SELL bias. Educational use only."
            )

from app.utils.disclaimer import show_footer
show_footer()
