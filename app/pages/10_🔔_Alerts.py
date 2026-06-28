"""Breakout and signal alerts across all sectors."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
from config import SECTOR_STOCKS
from backend.data_ingestion.yfinance_fetcher import _get_close
from backend.calculations.indicators import ema_signal

st.set_page_config(page_title="Sector Alerts | FII Breakouts & Reversals | Market Sector Analysis", layout="wide")
from app.utils.seo import inject_seo
inject_seo("Alerts")

from app.utils.logo import show_logo
show_logo()

st.title("\U0001f6a8 Technical Alerts — Breakout & Reversal Patterns")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption("Stocks crossing key technical levels across all sectors. For informational purposes only.")

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

                # Volume spike
                vol_series = None
                for col in ["Volume","volume"]:
                    if col in raw.columns:
                        v = raw[col]
                        if isinstance(v, pd.DataFrame): v = v.iloc[:,0]
                        vol_series = v.dropna()
                        break

                if prev_close < prev_ema20 and price > ema20:
                    alerts.append({"Symbol": sym.replace(".NS",""), "Sector": sector,
                                   "Alert": "EMA20 Bullish Cross", "Price": price,
                                   "RSI": rsi_now, "Severity": "High"})
                if rsi_prev and rsi_now and rsi_prev < 30 and rsi_now >= 30:
                    alerts.append({"Symbol": sym.replace(".NS",""), "Sector": sector,
                                   "Alert": "RSI exits Oversold (>30)", "Price": price,
                                   "RSI": rsi_now, "Severity": "High"})
                if rsi_prev and rsi_now and rsi_prev < 70 and rsi_now >= 70:
                    alerts.append({"Symbol": sym.replace(".NS",""), "Sector": sector,
                                   "Alert": "RSI Overbought >70 — Monitor for potential reversal", "Price": price,
                                   "RSI": rsi_now, "Severity": "Medium"})
                high52 = float(close_s.rolling(252, min_periods=50).max().iloc[-1])
                if price >= high52 * 0.99:
                    alerts.append({"Symbol": sym.replace(".NS",""), "Sector": sector,
                                   "Alert": "Near/At 52-Week High Breakout", "Price": price,
                                   "RSI": rsi_now, "Severity": "High"})
                if vol_series is not None and len(vol_series) >= 20:
                    avg_vol   = float(vol_series.iloc[-20:].mean())
                    today_vol = float(vol_series.iloc[-1])
                    if avg_vol > 0 and today_vol > 2.5 * avg_vol:
                        alerts.append({"Symbol": sym.replace(".NS",""), "Sector": sector,
                                       "Alert": f"Volume Spike {today_vol/avg_vol:.1f}x average",
                                       "Price": price, "RSI": rsi_now, "Severity": "Medium"})
            except Exception:
                continue
    return pd.DataFrame(alerts) if alerts else pd.DataFrame()

with st.spinner("Scanning all sectors for breakouts — ~30 seconds..."):
    df_alerts = scan_all_breakouts()

if df_alerts.empty:
    st.info("No major signals today. Market may be in consolidation.")
    st.stop()

high_df = df_alerts[df_alerts["Severity"] == "High"]
med_df  = df_alerts[df_alerts["Severity"] == "Medium"]

m1,m2,m3 = st.columns(3)
m1.metric("Total Alerts",    len(df_alerts))
m2.metric("High Priority",   len(high_df))
m3.metric("Medium Priority", len(med_df))

st.markdown("---")
st.subheader("High Priority Alerts")
if not high_df.empty:
    def color_alert(val):
        if "Cross" in str(val) or "52-Week" in str(val): return "color:#00C853;font-weight:600"
        if "Oversold" in str(val): return "color:#64DD17"
        return "color:#FF6D00"
    st.dataframe(
        high_df.style.map(color_alert, subset=["Alert"]).format(
            {"Price": "₹{:,.2f}", "RSI": lambda v: f"{v:.1f}" if isinstance(v,(int,float)) else "–"}),
        use_container_width=True, hide_index=True
    )
else:
    st.info("No high-priority alerts today.")

st.subheader("Medium Priority Alerts")
if not med_df.empty:
    st.dataframe(
        med_df.style.map(color_alert, subset=["Alert"]).format(
            {"Price": "₹{:,.2f}", "RSI": lambda v: f"{v:.1f}" if isinstance(v,(int,float)) else "–"}),
        use_container_width=True, hide_index=True
    )

st.markdown("---")
st.subheader("Alerts by Sector")
sector_counts = df_alerts.groupby("Sector").size().reset_index(name="Count").sort_values("Count", ascending=False)
fig = px.bar(sector_counts, x="Sector", y="Count", color="Count",
              color_continuous_scale="YlOrRd", template="plotly_dark")
fig.update_layout(height=300, margin=dict(t=20,b=60), xaxis_tickangle=-30)
st.plotly_chart(fig, use_container_width=True)

alert_sectors = df_alerts["Sector"].unique().tolist()
sel = st.selectbox("Jump to sector analysis:", alert_sectors)
if st.button(f"Analyse {sel} →", type="primary"):
    st.session_state["selected_sector"] = sel
    st.switch_page("pages/2_📈_Sector_Analysis.py")

st.markdown("---")
if st.button("← FII Sector Watch"):
    st.switch_page("Home.py")
from app.utils.disclaimer import show_footer
show_footer()
