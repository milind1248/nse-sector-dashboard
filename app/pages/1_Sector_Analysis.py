"""
Step 2 in investor flow: "Is price confirming FII buying?"
Shows sector index chart, technicals, and breadth.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from config import SECTOR_INDICES, SECTOR_STOCKS, NIFTY_SYMBOL
from backend.data_ingestion.yfinance_fetcher import fetch_index_ohlcv, _get_close, compute_pct_returns
from backend.calculations.indicators import compute_all_indicators, ema_signal
from backend.calculations.sector_score import compute_sector_score, score_label
from backend.calculations.relative_strength import compute_rs_ratio
from backend.calculations.advance_decline import compute_sector_advance_decline
from backend.data_ingestion.yfinance_fetcher import fetch_sector_stocks

st.set_page_config(page_title="Sector Analysis", layout="wide")

# ── Get sector from session ────────────────────────────────────────────────────
sector = st.session_state.get("selected_sector")
all_sectors = list(SECTOR_STOCKS.keys())
sector = st.selectbox("Sector", all_sectors,
                       index=all_sectors.index(sector) if sector and sector in all_sectors else 0,
                       key="sa_sector_sel")
st.session_state["selected_sector"] = sector

nsdl_name = st.session_state.get("selected_sector_nsdl", sector)
net_curr   = st.session_state.get("selected_sector_net_curr")

# ── Header banner ──────────────────────────────────────────────────────────────
if net_curr is not None:
    banner_color = "#00C853" if net_curr > 0 else "#D50000"
    direction    = "BUYING" if net_curr > 0 else "SELLING"
    st.markdown(
        f"<div style='background:{banner_color}22;border-left:4px solid {banner_color};"
        f"padding:12px 16px;border-radius:6px;margin-bottom:16px'>"
        f"<b>FII is {direction} ₹{net_curr:+,.0f} Cr</b> in <b>{nsdl_name}</b> this fortnight. "
        f"Check below whether price action confirms this flow.</div>",
        unsafe_allow_html=True,
    )

st.title(f"📈 {sector} — Sector Analysis")
st.caption("Does the price trend confirm FII buying? If yes → proceed to Stock Picker.")

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def load_sector_analysis(sector: str):
    sym = SECTOR_INDICES.get(sector)
    sector_df = fetch_index_ohlcv(sym, period="1y") if sym else None

    nifty_raw = yf.download(NIFTY_SYMBOL, period="1y", interval="1d",
                             progress=False, auto_adjust=True)
    nifty_raw.index = pd.to_datetime(nifty_raw.index).date

    stock_prices = fetch_sector_stocks(sector)
    ad = compute_sector_advance_decline(stock_prices, lookback_days=1)
    ad_week = compute_sector_advance_decline(stock_prices, lookback_days=5)

    if sector_df is not None and not sector_df.empty:
        indic = compute_all_indicators(sector_df)
        rets  = compute_pct_returns(sector_df)
        close_s = _get_close(sector_df)
        close   = float(close_s.iloc[-1]) if close_s is not None else None
        rs      = compute_rs_ratio(sector_df, nifty_raw)
        score   = compute_sector_score(
            rs_vs_nifty=rs, pct_1w=rets.get("pct_1w"), pct_1m=rets.get("pct_1m"),
            rsi_14=indic.get("rsi_14"), close=close, ema_200=indic.get("ema_200"),
        )
    else:
        indic, rets, close, rs, score = {}, {}, None, None, 50

    return sector_df, nifty_raw, indic, rets, close, rs, score, ad, ad_week

with st.spinner("Loading sector data..."):
    sector_df, nifty_raw, indic, rets, close, rs, score, ad, ad_week = load_sector_analysis(sector)

# ── Verdict banner ────────────────────────────────────────────────────────────
rsi = indic.get("rsi_14")
ema20, ema50, ema200 = indic.get("ema_20"), indic.get("ema_50"), indic.get("ema_200")
ema_sig = ema_signal(close or 0, ema20, ema50, ema200)
label, score_color = score_label(score)

verdict_color = "#00C853" if ema_sig == "Bullish" else "#D50000" if ema_sig == "Bearish" else "#FF6D00"
verdict_text  = (
    "Price is CONFIRMING FII buying — trend is Bullish. Good time to look for stock entry."
    if ema_sig == "Bullish" else
    "Price DIVERGING from FII buying — sector is still in downtrend. Wait for price to recover."
    if ema_sig == "Bearish" else
    "Price is MIXED — monitor for trend confirmation before entering."
)
st.markdown(
    f"<div style='background:{verdict_color}22;border-left:4px solid {verdict_color};"
    f"padding:12px 16px;border-radius:6px;margin-bottom:8px'>"
    f"<b>Price verdict: {ema_sig}</b> — {verdict_text}</div>",
    unsafe_allow_html=True,
)

# ── Key metric cards ───────────────────────────────────────────────────────────
c1,c2,c3,c4,c5,c6 = st.columns(6)
c1.metric("Score",    f"{score:.0f}",  label)
c2.metric("RSI(14)", f"{rsi:.1f}" if rsi else "–",
           "Overbought" if rsi and rsi > 70 else "Oversold" if rsi and rsi < 30 else "Neutral")
c3.metric("1W %",    f"{rets.get('pct_1w',0):+.1f}%")
c4.metric("1M %",    f"{rets.get('pct_1m',0):+.1f}%")
c5.metric("A/D Today", f"{ad['advance']}/{ad['decline']}",
           f"Ratio {ad['ad_ratio']:.1f}" if ad['ad_ratio'] != float('inf') else "")
c6.metric("A/D Week",  f"{ad_week['advance']}/{ad_week['decline']}",
           f"Ratio {ad_week['ad_ratio']:.1f}" if ad_week['ad_ratio'] != float('inf') else "")

st.markdown("---")

# ── Charts ─────────────────────────────────────────────────────────────────────
if sector_df is not None and not sector_df.empty:
    tab1, tab2, tab3 = st.tabs(["Price + EMAs", "RSI", "RS vs Nifty"])

    with tab1:
        fig = go.Figure()
        try:
            fig.add_trace(go.Candlestick(
                x=list(sector_df.index),
                open=sector_df["Open"].squeeze(),
                high=sector_df["High"].squeeze(),
                low=sector_df["Low"].squeeze(),
                close=sector_df["Close"].squeeze(),
                name="OHLC",
                increasing_line_color="#00C853",
                decreasing_line_color="#D50000",
            ))
        except Exception:
            close_s = _get_close(sector_df)
            fig.add_trace(go.Scatter(x=list(sector_df.index), y=close_s,
                                      name="Close", line=dict(color="#2979FF")))

        # EMA overlays
        close_s = _get_close(sector_df)
        for period, color, label2 in [(20,"#FFD600","EMA20"),(50,"#FF6D00","EMA50"),(200,"#2979FF","EMA200")]:
            ema = close_s.ewm(span=period, adjust=False).mean()
            fig.add_trace(go.Scatter(x=list(sector_df.index), y=ema,
                                      name=label2, line=dict(color=color, width=1.5)))

        # Shade FII buying period (last 15 days)
        if sector_df.index[-1]:
            fig.add_vrect(
                x0=str(sector_df.index[-15]), x1=str(sector_df.index[-1]),
                fillcolor="#00C853" if (net_curr or 0) > 0 else "#D50000",
                opacity=0.05, line_width=0,
                annotation_text="FII period", annotation_position="top left",
            )

        fig.update_layout(template="plotly_dark", height=450,
                           xaxis_rangeslider_visible=False,
                           title=f"{sector} Index — Last 1 Year",
                           margin=dict(t=50,b=20,l=10,r=10))
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        close_s = _get_close(sector_df)
        delta = close_s.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi_s = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
        fig2  = go.Figure()
        fig2.add_trace(go.Scatter(x=list(sector_df.index), y=rsi_s,
                                   name="RSI(14)", line=dict(color="#AB47BC", width=2)))
        fig2.add_hline(y=70, line_dash="dot", line_color="#D50000", opacity=0.6,
                        annotation_text="Overbought 70")
        fig2.add_hline(y=30, line_dash="dot", line_color="#00C853", opacity=0.6,
                        annotation_text="Oversold 30")
        fig2.add_hrect(y0=70, y1=100, fillcolor="#D50000", opacity=0.05, line_width=0)
        fig2.add_hrect(y0=0,  y1=30,  fillcolor="#00C853", opacity=0.05, line_width=0)
        fig2.update_layout(template="plotly_dark", height=300,
                            yaxis=dict(range=[0,100]),
                            margin=dict(t=20,b=20,l=10,r=10))
        st.plotly_chart(fig2, use_container_width=True)

    with tab3:
        # Relative strength vs Nifty
        close_s   = _get_close(sector_df)
        nifty_cls = _get_close(nifty_raw)
        common    = close_s.index.intersection(nifty_cls.index)
        if len(common) > 20:
            s_norm = (close_s.loc[common] / float(close_s.loc[common].iloc[0])) * 100
            n_norm = (nifty_cls.loc[common] / float(nifty_cls.loc[common].iloc[0])) * 100
            rs     = s_norm - n_norm
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(x=list(common), y=s_norm,
                                       name=f"{sector} (base 100)", line=dict(color="#2979FF")))
            fig3.add_trace(go.Scatter(x=list(common), y=n_norm,
                                       name="Nifty50 (base 100)", line=dict(color="#888",dash="dot")))
            fig3.add_hline(y=100, line_dash="dot", line_color="#555", opacity=0.5)
            fig3.update_layout(template="plotly_dark", height=350,
                                title="Relative Performance vs Nifty50 (rebased to 100)",
                                margin=dict(t=50,b=20))
            st.plotly_chart(fig3, use_container_width=True)

            rs_val = float(rs.iloc[-1])
            if rs_val > 0:
                st.success(f"Sector is outperforming Nifty by {rs_val:+.1f} points — RS is POSITIVE")
            else:
                st.warning(f"Sector is underperforming Nifty by {rs_val:.1f} points — RS is NEGATIVE")
else:
    st.warning(f"No price data available for {sector} index. Check config.py for the correct Yahoo Finance symbol.")

# ── EMA levels table ──────────────────────────────────────────────────────────
if close and any(v for v in [ema20, ema50, ema200]):
    st.markdown("---")
    st.subheader("Key Price Levels")
    lvl_df = pd.DataFrame([
        {"Level": "Current Price", "Value": f"₹{close:,.2f}", "Above/Below": ""},
        {"Level": "EMA 20",  "Value": f"₹{ema20:,.2f}"  if ema20  else "–",
         "Above/Below": "✅ Above" if close > (ema20 or 0)  else "⚠️ Below"},
        {"Level": "EMA 50",  "Value": f"₹{ema50:,.2f}"  if ema50  else "–",
         "Above/Below": "✅ Above" if close > (ema50 or 0)  else "⚠️ Below"},
        {"Level": "EMA 200", "Value": f"₹{ema200:,.2f}" if ema200 else "–",
         "Above/Below": "✅ Above" if close > (ema200 or 0) else "⚠️ Below"},
    ])
    st.dataframe(lvl_df, use_container_width=True, hide_index=True)

# ── CTA ───────────────────────────────────────────────────────────────────────
st.markdown("---")
c1, c2 = st.columns(2)
if c1.button("🔍 Find Best Stocks in This Sector →", use_container_width=True, type="primary"):
    st.switch_page("pages/2_Stock_Picker.py")
if c2.button("← Back to FII Sector Watch", use_container_width=True):
    st.switch_page("main.py")
