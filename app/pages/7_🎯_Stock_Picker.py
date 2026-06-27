"""
Step 3: Screen stocks in the selected sector by momentum indicators.
Sorted by momentum score. For research purposes only.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf

from config import SECTOR_STOCKS, NIFTY_SYMBOL
from backend.data_ingestion.yfinance_fetcher import (
    fetch_sector_stocks, compute_pct_returns, fetch_stock_info, _get_close,
)
from backend.calculations.indicators import compute_all_indicators, ema_signal
from backend.calculations.sector_score import compute_sector_score, score_label
from backend.calculations.relative_strength import compute_rs_ratio

st.set_page_config(page_title="Stock Screener | FII Sector Stock Analysis | Market Sector Analysis", layout="wide")
from app.utils.seo import inject_seo
inject_seo("Stock_Picker")

from app.utils.logo import show_logo
show_logo()


sector = st.session_state.get("selected_sector")
all_sectors = list(SECTOR_STOCKS.keys())
sector = st.selectbox("Sector", all_sectors,
                       index=all_sectors.index(sector) if sector and sector in all_sectors else 0,
                       key="sp_sector_sel")
st.session_state["selected_sector"] = sector

nsdl_name = st.session_state.get("selected_sector_nsdl", sector)
net_curr   = st.session_state.get("selected_sector_net_curr")

if net_curr is not None:
    color = "#00C853" if net_curr > 0 else "#D50000"
    st.markdown(
        f"<div style='background:{color}22;border-left:4px solid {color};"
        f"padding:10px 16px;border-radius:6px;margin-bottom:12px'>"
        f"FII {'buying' if net_curr > 0 else 'selling'} ₹{net_curr:+,.0f} Cr in "
        f"<b>{nsdl_name}</b> this fortnight.</div>",
        unsafe_allow_html=True,
    )

st.title(f"\U0001f50d Stock Screener — {sector}")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption("Stocks ranked by momentum score. EMA trend and RSI zone are indicators displayed for research reference only.")

@st.cache_data(ttl=1800, show_spinner=False)
def load_stocks(sector: str):
    stock_prices = fetch_sector_stocks(sector)
    nifty_raw = yf.download(NIFTY_SYMBOL, period="1y", interval="1d",
                             progress=False, auto_adjust=True)
    nifty_raw.index = pd.to_datetime(nifty_raw.index).date

    rows = []
    for sym, df in stock_prices.items():
        if df is None or df.empty:
            continue
        try:
            info    = fetch_stock_info(sym)
            indic   = compute_all_indicators(df)
            rets    = compute_pct_returns(df)
            close_s = _get_close(df)
            if close_s is None or close_s.empty:
                continue
            close   = float(close_s.iloc[-1])
            rs      = compute_rs_ratio(df, nifty_raw)
            ema20   = indic.get("ema_20")
            ema50   = indic.get("ema_50")
            ema200  = indic.get("ema_200")
            rsi_14  = indic.get("rsi_14")
            score   = compute_sector_score(
                rs_vs_nifty=rs, pct_1w=rets.get("pct_1w"), pct_1m=rets.get("pct_1m"),
                rsi_14=rsi_14, close=close, ema_200=ema200,
                volume_ratio=indic.get("volume_ratio"),
            )
            sl_label, _ = score_label(score)
            ema_sig = ema_signal(close, ema20, ema50, ema200)
            try:
                high52 = info.get("52w_high") or float(df["High"].squeeze().max())
                low52  = info.get("52w_low")  or float(df["Low"].squeeze().min())
            except Exception:
                high52, low52 = None, None
            mkt_cap = info.get("market_cap")

            rows.append({
                "Symbol":      sym.replace(".NS", ""),
                "Name":        info.get("name", sym)[:30],
                "Mkt Cap Cr":  round(mkt_cap / 1e7, 0) if mkt_cap else None,
                "Price":       round(close, 2),
                "Score":       score,
                "Score Label": sl_label,
                "EMA Signal":  ema_sig,
                "RSI":         round(rsi_14, 1) if rsi_14 else None,
                "1W %":        rets.get("pct_1w"),
                "1M %":        rets.get("pct_1m"),
                "3M %":        rets.get("pct_3m"),
                "52W H%":      round((high52 - close) / high52 * 100, 1) if high52 else None,
                "52W L%":      round((close - low52)  / low52 * 100, 1)  if low52  else None,
                "Vol Ratio":   indic.get("volume_ratio"),
                "RS vs Nifty": round(rs, 2) if rs else None,
                "_df":         df,
            })
        except Exception:
            continue

    rows.sort(key=lambda x: x["Score"], reverse=True)
    return rows

with st.spinner(f"Analysing all stocks in {sector}..."):
    stock_rows = load_stocks(sector)

if not stock_rows:
    st.warning("No stock data available for this sector.")
    st.stop()

# Top-5 cards
st.subheader("Top 5 by Momentum Score")
top5 = stock_rows[:5]
cols = st.columns(5)
for col, r in zip(cols, top5):
    sig_color = "#00C853" if r["EMA Signal"] == "Bullish" else "#D50000" if r["EMA Signal"] == "Bearish" else "#FF6D00"
    col.markdown(
        f"<div style='background:#161B22;border:1px solid {sig_color};"
        f"border-radius:8px;padding:10px;text-align:center'>"
        f"<div style='font-weight:600;font-size:15px'>{r['Symbol']}</div>"
        f"<div style='color:#888;font-size:11px'>{r['Name']}</div>"
        f"<div style='font-size:20px;font-weight:700;margin:4px 0'>₹{r['Price']:,.0f}</div>"
        f"<div style='color:{sig_color};font-size:12px'>{r['EMA Signal']}</div>"
        f"<div style='font-size:11px;margin-top:4px'>Score: <b>{r['Score']:.0f}</b> | RSI: {r['RSI'] or '–'}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# Full table
st.subheader("All Sector Stocks — Ranked by Momentum Score")

display_cols = ["Symbol","Name","Mkt Cap Cr","Price","Score","Score Label",
                "EMA Signal","RSI","1W %","1M %","3M %","52W H%","52W L%","Vol Ratio","RS vs Nifty"]
df_display = pd.DataFrame(stock_rows)[display_cols].copy()

def fmt_pct(v):
    return f"{v:+.1f}%" if isinstance(v, (int,float)) else "–"
def color_pct(v):
    if not isinstance(v, str) or "%" not in v: return ""
    try:
        n = float(v.replace("%","").replace("+",""))
        return "color:#00C853" if n>0 else "color:#D50000" if n<0 else ""
    except Exception:
        return ""
def color_ema(v):
    return "color:#00C853;font-weight:600" if v=="Bullish" else \
           "color:#D50000;font-weight:600" if v=="Bearish" else "color:#FF6D00"
def color_rsi(v):
    if not isinstance(v, (int,float)): return ""
    if v > 70: return "color:#D50000"
    if v < 30: return "color:#00C853"
    if 45 <= v <= 65: return "color:#64DD17;font-weight:600"
    return ""

for c in ["1W %","1M %","3M %"]:
    df_display[c] = df_display[c].apply(fmt_pct)
for c in ["52W H%","52W L%"]:
    df_display[c] = df_display[c].apply(lambda v: f"{v:.1f}%" if isinstance(v,(int,float)) else "–")
df_display["Mkt Cap Cr"] = df_display["Mkt Cap Cr"].apply(
    lambda v: f"₹{v:,.0f}" if isinstance(v,(int,float)) else "–")
df_display["Vol Ratio"] = df_display["Vol Ratio"].apply(
    lambda v: f"{v:.1f}x" if isinstance(v,(int,float)) else "–")

styled = (
    df_display.style
    .format({
        "Price":       lambda v: f"₹{v:,.1f}" if isinstance(v, (int, float)) else "–",
        "Score":       lambda v: f"{v:.1f}"   if isinstance(v, (int, float)) else "–",
        "RSI":         lambda v: f"{v:.1f}"   if isinstance(v, (int, float)) else "–",
        "RS vs Nifty": lambda v: f"{v:.1f}"   if isinstance(v, (int, float)) else "–",
    }, na_rep="–")
    .map(color_pct, subset=["1W %","1M %","3M %"])
    .map(color_ema, subset=["EMA Signal"])
    .map(color_rsi, subset=["RSI"])
)
st.dataframe(styled, use_container_width=True, hide_index=True, height=420)

st.caption(
    "**How to read:** RSI 45–65 = mid-range momentum. EMA Bullish = price above moving averages. "
    "Vol Ratio >1.5x = above-average volume. 52W H% = proximity to 52-week high. "
    "All indicators are for research reference only — not trading signals or investment recommendations."
)
st.markdown("---")

# Individual stock chart
st.subheader("Stock Chart — Deep Dive")
sym_options = [r["Symbol"] for r in stock_rows]
chosen = st.selectbox("Select stock for chart", sym_options, index=0)

if chosen:
    chosen_row = next((r for r in stock_rows if r["Symbol"] == chosen), None)
    if chosen_row:
        df = chosen_row["_df"]
        close_s = _get_close(df)

        ic = st.columns(6)
        _1m_raw = chosen_row.get("1M %")
        _rs_raw = chosen_row.get("RS vs Nifty")
        _1m_num = _1m_raw if isinstance(_1m_raw, (int, float)) else None
        _rs_num = _rs_raw if isinstance(_rs_raw, (int, float)) else None
        ic[0].metric("Price",      f"₹{chosen_row['Price']:,.2f}")
        ic[1].metric("Score",      f"{chosen_row['Score']:.0f}", chosen_row["Score Label"])
        ic[2].metric("EMA Signal", chosen_row["EMA Signal"])
        ic[3].metric("RSI",        f"{chosen_row['RSI'] or '–'}")
        ic[4].metric("1M Return",  f"{_1m_num:+.1f}%" if _1m_num is not None else "–",
                     f"{_1m_num:+.2f}%" if _1m_num is not None else None, delta_color="normal")
        ic[5].metric("RS vs Nifty",f"{_rs_num:+.2f}" if _rs_num is not None else "–",
                     f"{_rs_num:+.2f}" if _rs_num is not None else None, delta_color="normal")

        tab1, tab2 = st.tabs(["Price + EMAs", "RSI"])
        with tab1:
            import numpy as np
            from plotly.subplots import make_subplots

            # ── H-M indicator calc ────────────────────────────────────────
            delta9 = close_s.diff()
            gain9  = delta9.clip(lower=0).rolling(9).mean()
            loss9  = (-delta9.clip(upper=0)).rolling(9).mean()
            rsi9   = 100 - (100 / (1 + gain9 / loss9.replace(0, float("nan"))))
            ema3   = rsi9.ewm(span=3, adjust=False).mean()
            wma21  = rsi9.rolling(21).apply(
                lambda x: np.average(x, weights=range(1, 22)), raw=True
            )
            prev_e = ema3.shift(1); prev_w = wma21.shift(1)
            buy_cross  = (prev_e <  prev_w) & (ema3 >= wma21)
            sell_cross = (prev_e >  prev_w) & (ema3 <= wma21)
            dates = [str(d) for d in df.index]

            last_e = ema3.dropna().iloc[-1]; last_w = wma21.dropna().iloc[-1]
            sig_color = "#00C853" if last_e > last_w else "#D50000"
            sig_text  = "🟢 H-M: MILEGA (Bullish)" if last_e > last_w else "🔴 H-M: HILEGA (Bearish)"
            st.markdown(
                f"<div style='background:{sig_color}22;border-left:4px solid {sig_color};"
                f"padding:6px 12px;border-radius:4px;margin-bottom:6px;font-size:13px;"
                f"font-weight:700;color:{sig_color}'>{sig_text} — EMA3: {last_e:.1f} | WMA21: {last_w:.1f}</div>",
                unsafe_allow_html=True,
            )

            # ── Combined subplot: Price + H-M ─────────────────────────────
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=[0.65, 0.35],
                vertical_spacing=0.04,
            )

            # Row 1 — Candlestick + EMAs
            try:
                fig.add_trace(go.Candlestick(
                    x=list(df.index),
                    open=df["Open"].squeeze(), high=df["High"].squeeze(),
                    low=df["Low"].squeeze(),   close=df["Close"].squeeze(),
                    name="OHLC",
                    increasing_line_color="#00C853", decreasing_line_color="#D50000",
                ), row=1, col=1)
            except Exception:
                fig.add_trace(go.Scatter(x=list(df.index), y=close_s, name="Close"), row=1, col=1)
            for period, color, lbl in [(20,"#FFD600","EMA20"),(50,"#FF6D00","EMA50"),(200,"#2979FF","EMA200")]:
                ema_line = close_s.ewm(span=period, adjust=False).mean()
                fig.add_trace(go.Scatter(x=list(df.index), y=ema_line, name=lbl,
                                         line=dict(color=color, width=1.5)), row=1, col=1)

            # Row 2 — H-M (RSI9 + EMA3 + WMA21 with fills)
            # Green fill zone
            ema3_g  = ema3.where(ema3  >= wma21)
            wma21_g = wma21.where(ema3 >= wma21)
            fig.add_trace(go.Scatter(x=dates, y=wma21_g.tolist(),
                                     line=dict(width=0), showlegend=False, hoverinfo="skip"), row=2, col=1)
            fig.add_trace(go.Scatter(x=dates, y=ema3_g.tolist(),
                                     fill="tonexty", fillcolor="rgba(0,200,83,0.2)",
                                     line=dict(width=0), showlegend=False, hoverinfo="skip"), row=2, col=1)
            # Red fill zone
            ema3_r  = ema3.where(ema3  < wma21)
            wma21_r = wma21.where(ema3 < wma21)
            fig.add_trace(go.Scatter(x=dates, y=ema3_r.tolist(),
                                     line=dict(width=0), showlegend=False, hoverinfo="skip"), row=2, col=1)
            fig.add_trace(go.Scatter(x=dates, y=wma21_r.tolist(),
                                     fill="tonexty", fillcolor="rgba(213,0,0,0.2)",
                                     line=dict(width=0), showlegend=False, hoverinfo="skip"), row=2, col=1)

            fig.add_trace(go.Scatter(x=dates, y=rsi9.tolist(), name="RSI(9)",
                                     line=dict(color="#666", width=1), opacity=0.7), row=2, col=1)
            fig.add_trace(go.Scatter(x=dates, y=ema3.tolist(), name="EMA3",
                                     line=dict(color="#FFD600", width=1.5)), row=2, col=1)
            fig.add_trace(go.Scatter(x=dates, y=wma21.tolist(), name="WMA21",
                                     line=dict(color="#FF6D00", width=1.5)), row=2, col=1)

            # Buy/Sell crossover markers
            buy_x = [str(d) for d, v in zip(df.index, buy_cross) if v]
            buy_y = [ema3.loc[d] for d, v in zip(df.index, buy_cross) if v]
            if buy_x:
                fig.add_trace(go.Scatter(
                    x=buy_x, y=buy_y, mode="markers", name="Milega ▲",
                    marker=dict(symbol="triangle-up", color="#00C853", size=10,
                                line=dict(color="#fff", width=1)),
                    hovertemplate="<b>%{x}</b><br>Milega — EMA3: %{y:.1f}<extra></extra>",
                ), row=2, col=1)
            sell_x = [str(d) for d, v in zip(df.index, sell_cross) if v]
            sell_y = [ema3.loc[d] for d, v in zip(df.index, sell_cross) if v]
            if sell_x:
                fig.add_trace(go.Scatter(
                    x=sell_x, y=sell_y, mode="markers", name="Hilega ▼",
                    marker=dict(symbol="triangle-down", color="#D50000", size=10,
                                line=dict(color="#fff", width=1)),
                    hovertemplate="<b>%{x}</b><br>Hilega — EMA3: %{y:.1f}<extra></extra>",
                ), row=2, col=1)

            # Reference lines on H-M pane
            fig.add_hline(y=70, line_dash="dot",   line_color="#D50000", opacity=0.5, row=2, col=1)
            fig.add_hline(y=50, line_dash="solid",  line_color="#888888", opacity=0.9, line_width=1.5, row=2, col=1)
            fig.add_hline(y=30, line_dash="dot",   line_color="#00C853", opacity=0.5, row=2, col=1)

            fig.update_layout(
                template="plotly_dark", height=580,
                title=f"{chosen} — Price + EMAs  |  H-M",
                margin=dict(t=50, b=20, l=10, r=10),
                xaxis_rangeslider_visible=False,
                xaxis2_rangeslider_visible=False,
                legend=dict(orientation="h", y=1.04, x=0, font=dict(size=11)),
                hovermode="x unified",
            )
            fig.update_xaxes(
                showspikes=True, spikemode="across", spikesnap="cursor",
                spikethickness=1, spikedash="dot", spikecolor="#aaaaaa",
            )
            fig.update_yaxes(range=[0, 100], row=2, col=1)
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "**H-M:** EMA(3) of RSI(9) crosses above WMA(21) → 🟢 Milega. "
                "Crosses below → 🔴 Hilega. Shading = current bias. For informational purposes only."
            )

        with tab2:
            delta = close_s.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rsi_s = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=list(df.index), y=rsi_s, name="RSI(14)",
                                       line=dict(color="#AB47BC", width=2)))
            fig2.add_hline(y=70, line_dash="dot", line_color="#D50000", opacity=0.6)
            fig2.add_hline(y=30, line_dash="dot", line_color="#00C853", opacity=0.6)
            fig2.add_hrect(y0=45, y1=65, fillcolor="#00C853", opacity=0.06, line_width=0,
                            annotation_text="Ideal entry 45-65", annotation_position="top right")
            fig2.update_layout(template="plotly_dark", height=280, yaxis=dict(range=[0,100]),
                                margin=dict(t=30,b=20))
            st.plotly_chart(fig2, use_container_width=True)

st.markdown("---")
c1, c2, c3 = st.columns(3)
if c1.button("← Sector Analysis",  use_container_width=True):
    st.switch_page("pages/2_📈_Sector_Analysis.py")
if c2.button("← FII Sector Watch", use_container_width=True):
    st.switch_page("Home.py")
if c3.button("\U0001f4ca Market Pulse →", use_container_width=True):
    st.switch_page("pages/1_📡_Market_Pulse.py")
from app.utils.disclaimer import show_footer
show_footer()
