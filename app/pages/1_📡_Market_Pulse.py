"""Market breadth, sector heatmap, and RRG in one pulse view."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from datetime import date, timedelta

from config import SECTOR_STOCKS, NIFTY_SYMBOL
from backend.data_ingestion.yfinance_fetcher import (
    fetch_all_sector_prices, compute_pct_returns, fetch_market_summary, _get_close,
)
from backend.calculations.relative_strength import compute_rrg_coordinates

st.set_page_config(page_title="Market Pulse | Nifty Breadth & Relative Rotation | Market Sector Analysis", layout="wide")
from app.utils.seo import inject_seo
inject_seo("Market_Pulse")

from app.utils.logo import show_logo
show_logo()

# Define cache functions first so Refresh button can clear them
@st.cache_data(ttl=300, show_spinner=False)
def get_market_summary():
    return fetch_market_summary()

@st.cache_data(ttl=300, show_spinner=False)
def get_breadth():
    """Download NSE Bhavcopy and compute advance/decline directly."""
    import requests, zipfile, io as _io
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for offset in range(6):
        dt = date.today() - timedelta(days=offset)
        url = (f"https://nsearchives.nseindia.com/content/cm/"
               f"BhavCopy_NSE_CM_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip")
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            z = zipfile.ZipFile(_io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            eq = df[~df['SctySrs'].isin({'GS', 'GB', 'TB', 'IV'})].copy()
            eq['ClsPric']      = pd.to_numeric(eq['ClsPric'],      errors='coerce')
            eq['PrvsClsgPric'] = pd.to_numeric(eq['PrvsClsgPric'], errors='coerce')
            eq = eq.dropna(subset=['ClsPric', 'PrvsClsgPric'])
            eq = eq[eq['PrvsClsgPric'] > 0]
            adv = int((eq['ClsPric'] > eq['PrvsClsgPric']).sum())
            dec = int((eq['ClsPric'] < eq['PrvsClsgPric']).sum())
            unc = int((eq['ClsPric'] == eq['PrvsClsgPric']).sum())
            if adv + dec > 0:
                return {"advance": adv, "decline": dec, "unchanged": unc}
        except Exception:
            continue
    return {"advance": 0, "decline": 0, "unchanged": 0}

col_h, col_ref = st.columns([6, 1])
col_h.title("📡 Market Pulse")
if col_ref.button("🔄 Refresh", use_container_width=True):
    get_market_summary.clear()
    get_breadth.clear()
    st.rerun()
st.caption("Overall market breadth, sector heatmap, and RRG rotation at a glance.")

with st.spinner("Loading market data..."):
    summary = get_market_summary()

breadth = get_breadth()

st.subheader("Market Indices")
idx_cols = st.columns(len(summary))
for col, (name, data) in zip(idx_cols, summary.items()):
    if not data:
        col.metric(name, "N/A"); continue
    col.metric(name, f"₹{data['close']:,.0f}",
               f"{data['change']:+.0f} ({data['pct']:+.2f}%)",
               delta_color="normal")

adv = int(breadth.get("advance", 0) or 0)
dec = int(breadth.get("decline", 0) or 0)
unc = int(breadth.get("unchanged", 0) or 0)
ad_ratio = adv / dec if dec > 0 else None
b1,b2,b3,b4 = st.columns(4)
b1.metric("Advancing", adv)
b2.metric("Declining",  dec)
b3.metric("A/D Ratio",  f"{ad_ratio:.2f}" if ad_ratio is not None else "–",
           ("Bullish" if ad_ratio > 1.5 else "Bearish") if ad_ratio is not None else "No data")
b4.metric("Unchanged",  unc)

st.markdown("---")

# ── Sector heatmap ────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def get_heatmap():
    sector_prices = fetch_all_sector_prices()
    rows = []
    for sector, df in sector_prices.items():
        if df is None or df.empty: continue
        rets = compute_pct_returns(df)
        rows.append({"Sector": sector, "1W": rets.get("pct_1w"), "2W": rets.get("pct_2w"),
                     "1M": rets.get("pct_1m"), "3M": rets.get("pct_3m"),
                     "6M": rets.get("pct_6m"), "1Y": rets.get("pct_1y")})
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("Sector")
    return df.sort_values("1M", ascending=False)

st.subheader("Sector Heatmap — % Returns")
with st.spinner("Computing sector returns..."):
    hm = get_heatmap()

if not hm.empty:
    fig = px.imshow(hm, color_continuous_scale="RdYlGn", zmin=-10, zmax=10,
                    text_auto=".1f", aspect="auto")
    fig.update_layout(template="plotly_dark",
                       height=max(380, len(hm)*24),
                       margin=dict(t=20,b=20,l=140,r=20),
                       coloraxis_colorbar=dict(title="%"))
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# ── RRG ───────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def get_rrg():
    sector_prices = fetch_all_sector_prices()
    nifty_raw = yf.download(NIFTY_SYMBOL, period="1y", interval="1d",
                             progress=False, auto_adjust=True)
    nifty_raw.index = pd.to_datetime(nifty_raw.index).date
    return compute_rrg_coordinates(sector_prices, nifty_raw)

st.subheader("Relative Rotation Graph (RRG)")
st.caption("Leading = strong + rising | Improving = weak but turning up | Weakening = strong but fading | Lagging = weak + falling")

with st.spinner("Computing RRG..."):
    rrg_data = get_rrg()

if rrg_data:
    colors = {"Leading":"#00C853","Improving":"#00BCD4","Lagging":"#D50000","Weakening":"#FF6D00"}
    fig2 = go.Figure()
    for item in rrg_data:
        trail = item.get("trail", [])
        if len(trail) > 1:
            fig2.add_trace(go.Scatter(
                x=[t["rs_ratio"] for t in trail[:-1]],
                y=[t["rs_momentum"] for t in trail[:-1]],
                mode="lines", line=dict(color=colors.get(item["quadrant"],"#888"), width=1),
                showlegend=False, opacity=0.35,
            ))
        fig2.add_trace(go.Scatter(
            x=[item["rs_ratio"]], y=[item["rs_momentum"]], mode="markers+text",
            marker=dict(size=14, color=colors.get(item["quadrant"],"#888"),
                        line=dict(width=1,color="white")),
            text=[item["sector"]], textposition="top center", textfont=dict(size=9),
            name=item["quadrant"], showlegend=False,
        ))
    fig2.add_vline(x=100, line_dash="dot", line_color="white", opacity=0.25)
    fig2.add_hline(y=100, line_dash="dot", line_color="white", opacity=0.25)
    for lbl, x, y in [("Leading",102,102),("Improving",98,102),("Lagging",98,98),("Weakening",102,98)]:
        fig2.add_annotation(x=x, y=y, text=lbl, showarrow=False,
                             font=dict(size=10,color=colors[lbl]), opacity=0.5)
    fig2.update_layout(template="plotly_dark", height=500,
                        xaxis_title="RS-Ratio (relative strength)",
                        yaxis_title="RS-Momentum (trend of RS)",
                        margin=dict(t=30,b=30,l=50,r=20))
    st.plotly_chart(fig2, use_container_width=True)

    # Quadrant tables
    quad_cols = st.columns(4)
    for col, quad in zip(quad_cols, ["Leading","Improving","Weakening","Lagging"]):
        sectors = [d["sector"] for d in rrg_data if d["quadrant"] == quad]
        col.markdown(f"**{quad}**")
        if sectors:
            for s in sectors:
                btn_label = s[:18]
                if col.button(btn_label, key=f"rrg_{quad}_{s}", use_container_width=True):
                    st.session_state["selected_sector"] = s
                    st.switch_page("pages/2_📈_Sector_Analysis.py")
        else:
            col.caption("None")
else:
    st.info("Insufficient data for RRG. Run 'Refresh All Data' in sidebar.")

st.markdown("---")
if st.button("← FII Sector Watch", use_container_width=False):
    st.switch_page("Home.py")
from app.utils.disclaimer import show_footer
show_footer()
