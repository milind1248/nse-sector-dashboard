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

st.set_page_config(page_title="NSE Sector Price Analysis | FII Flow vs Price | Market Sector Analysis", layout="wide")
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()
from app.utils.seo import inject_seo
inject_seo("Sector_Analysis")

from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("Sector Analysis")


# ── Get sector from session ────────────────────────────────────────────────────
sector = st.session_state.get("selected_sector")
all_sectors = sorted(SECTOR_STOCKS.keys())
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
st.caption("Compare the sector price trend with FII flow data for research purposes.")

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
    "Price trend and FII flow are aligned — conduct further research before making any decision."
    if ema_sig == "Bullish" else
    "Price trend and FII flow diverge — verify data from additional sources before drawing conclusions."
    if ema_sig == "Bearish" else
    "Price trend is mixed — monitor for additional data points before drawing conclusions."
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
_1w = rets.get('pct_1w', 0)
_1m = rets.get('pct_1m', 0)
c3.metric("1W %",    f"{_1w:+.1f}%", f"{_1w:+.2f}%", delta_color="normal")
c4.metric("1M %",    f"{_1m:+.1f}%", f"{_1m:+.2f}%", delta_color="normal")
c5.metric("A/D Today", f"{ad['advance']}/{ad['decline']}",
           f"Ratio {ad['ad_ratio']:.1f}" if ad['ad_ratio'] != float('inf') else "")
c6.metric("A/D Week",  f"{ad_week['advance']}/{ad_week['decline']}",
           f"Ratio {ad_week['ad_ratio']:.1f}" if ad_week['ad_ratio'] != float('inf') else "")

st.markdown("---")

# ── Charts ─────────────────────────────────────────────────────────────────────
if sector_df is not None and not sector_df.empty:
    tab1, tab2, tab3, tab4 = st.tabs(["Price + EMAs", "RSI", "RS vs Nifty", "📊 Stock RS"])

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
        st.plotly_chart(fig, width='stretch')

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
        st.plotly_chart(fig2, width='stretch')

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
            st.plotly_chart(fig3, width='stretch')

            rs_val = float(rs.iloc[-1])
            if rs_val > 0:
                st.success(f"Sector is outperforming Nifty by {rs_val:+.1f} points — RS is POSITIVE")
            else:
                st.warning(f"Sector is underperforming Nifty by {rs_val:.1f} points — RS is NEGATIVE")
    with tab4:
        st.caption("Stocks rebased to 100 at the start of the selected period. Lines above 100 = outperforming the base; compare against sector index and Nifty50.")

        period_map = {"1 Month": 21, "3 Months": 63, "6 Months": 126, "1 Year": 252}
        sel_period = st.radio("Period", list(period_map.keys()), index=1, horizontal=True, key="rs_period")
        lookback   = period_map[sel_period]

        stock_prices = fetch_sector_stocks(sector)  # timed_cache — no re-fetch

        # Build normalised series for each stock
        nifty_cls  = _get_close(nifty_raw)
        sector_cls = _get_close(sector_df)

        rs_rows   = []
        fig4      = go.Figure()

        # Collect all common dates across nifty + sector for trimming
        ref_dates = set(nifty_cls.index) & set(sector_cls.index)

        stock_series = {}
        for sym, df_s in stock_prices.items():
            if df_s is None or df_s.empty:
                continue
            cls = _get_close(df_s)
            if cls is None or len(cls) < 10:
                continue
            common = sorted(ref_dates & set(cls.index))
            if len(common) < 10:
                continue
            stock_series[sym] = cls.loc[common]

        if not stock_series:
            st.info("No stock price data available for this sector.")
        else:
            # Trim to lookback window using shared dates
            all_common = sorted(set.intersection(*[set(s.index) for s in stock_series.values()],
                                                  set(sector_cls.index), set(nifty_cls.index)))
            window = all_common[-lookback:] if len(all_common) >= lookback else all_common
            if not window:
                st.info("Insufficient data for selected period.")
            else:
                base = window[0]

                def _norm(series):
                    s = series.loc[window]
                    return (s / float(s.iloc[0])) * 100

                # Sector and Nifty reference lines
                sec_norm   = _norm(sector_cls)
                nifty_norm = _norm(nifty_cls)

                fig4.add_trace(go.Scatter(
                    x=list(window), y=nifty_norm,
                    name="Nifty50", line=dict(color="#888", width=2, dash="dot"),
                ))
                fig4.add_trace(go.Scatter(
                    x=list(window), y=sec_norm,
                    name=f"{sector} Index", line=dict(color="#FFD600", width=2.5),
                ))

                # Each stock — faint, colour by final RS vs sector
                for sym, cls in stock_series.items():
                    s_norm = _norm(cls)
                    last_vs_sector = round(float(s_norm.iloc[-1]) - float(sec_norm.iloc[-1]), 1)
                    last_vs_nifty  = round(float(s_norm.iloc[-1]) - float(nifty_norm.iloc[-1]), 1)
                    line_color = "#00C853" if last_vs_sector > 0 else "#FF5252"
                    short_sym  = sym.replace(".NS", "")

                    fig4.add_trace(go.Scatter(
                        x=list(window), y=s_norm,
                        name=short_sym,
                        line=dict(color=line_color, width=1),
                        opacity=0.55,
                        hovertemplate=f"<b>{short_sym}</b><br>%{{x}}<br>Rebased: %{{y:.1f}}<extra></extra>",
                    ))

                    rs_rows.append({
                        "Symbol":          short_sym,
                        "Last Price":      round(float(cls.iloc[-1]), 1),
                        f"RS vs Sector ({sel_period})":  last_vs_sector,
                        f"RS vs Nifty ({sel_period})":   last_vs_nifty,
                        "Signal":          "Outperforming" if last_vs_sector > 0 else "Underperforming",
                    })

                fig4.add_hline(y=100, line_dash="dot", line_color="#444", opacity=0.6)
                fig4.update_layout(
                    template="plotly_dark", height=460,
                    title=f"{sector} — Stock Relative Strength vs Sector & Nifty50 (base 100, {sel_period})",
                    margin=dict(t=50, b=20, l=10, r=10),
                    legend=dict(orientation="v", x=1.01, y=1, font=dict(size=10)),
                    hovermode="x unified",
                )
                st.plotly_chart(fig4, width='stretch')

                # RS summary table
                if rs_rows:
                    rs_df = pd.DataFrame(rs_rows).sort_values(
                        f"RS vs Sector ({sel_period})", ascending=False
                    ).reset_index(drop=True)

                    vs_sec_col = f"RS vs Sector ({sel_period})"
                    vs_nif_col = f"RS vs Nifty ({sel_period})"

                    def _rs_color(v):
                        if not isinstance(v, (int, float)): return ""
                        return "color:#00C853;font-weight:600" if v > 0 else "color:#FF5252;font-weight:600"

                    def _sig_color(v):
                        return "color:#00C853;font-weight:600" if v == "Outperforming" else "color:#FF5252"

                    st.dataframe(
                        rs_df.style
                            .map(_rs_color,  subset=[vs_sec_col, vs_nif_col])
                            .map(_sig_color, subset=["Signal"])
                            .format({
                                "Last Price":  lambda v: f"₹{v:,.1f}",
                                vs_sec_col:    lambda v: f"{v:+.1f}" if isinstance(v, (int, float)) else "–",
                                vs_nif_col:    lambda v: f"{v:+.1f}" if isinstance(v, (int, float)) else "–",
                            }, na_rep="–"),
                        width='stretch', hide_index=True,
                    )
                    st.caption(
                        "RS = rebased index points difference at end of period. "
                        "Positive = stock outperformed the benchmark over the period. "
                        "Not a buy/sell signal — for research reference only."
                    )

else:
    st.warning(f"No price data available for {sector} index. Check config.py for the correct market symbol.")

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
    st.dataframe(lvl_df, width='stretch', hide_index=True)

# ── CTA ───────────────────────────────────────────────────────────────────────
st.markdown("---")
c1, c2 = st.columns(2)
if c1.button("🔍 Screen Stocks in This Sector →", width='stretch', type="primary"):
    st.switch_page("pages/7_🎯_Stock_Picker.py")
if c2.button("← Back to FII Sector Watch", width='stretch'):
    st.switch_page("Home.py")
from app.utils.disclaimer import show_footer
show_footer()
