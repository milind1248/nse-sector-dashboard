"""
NSE Sector Index Stock — Sector → Index → Stocks → Weightage
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import sqlite3

from backend.data_ingestion.sector_sync import sync_all, get_last_sync

st.set_page_config(
    page_title="Sector Index Stock | NSE Constituents & Weightage",
    page_icon="🏛️", layout="wide"
)

from app.utils.seo import inject_seo
inject_seo("Home")
from app.utils.logo import show_logo
show_logo()

# ── Constants ─────────────────────────────────────────────────────────────────
SECTOR_ICONS = {
    "Auto": "🚗", "Bank": "🏦", "Consumer Durables": "📺",
    "FMCG": "🛒", "Healthcare": "🏥", "IT": "💻",
    "Media": "📡", "Metal": "⚙️", "OIL & GAS": "⛽",
    "PHARMA": "💊", "PSU Bank": "🏛️", "REALTY": "🏗️",
}

INDEX_DISPLAY = {
    "BANKNIFTY":         "Bank Nifty",
    "NIFTY_AUTO":        "Nifty Auto",
    "NCONSDUR":          "Nifty Consumer Durables",
    "NIFTY_FMCG":        "Nifty FMCG",
    "NIFTY_IT":          "Nifty IT",
    "NIFTY_MEDIA":       "Nifty Media",
    "NIFTY_METAL":       "Nifty Metal",
    "NIFTY_OIL_AND_GAS": "Nifty Oil & Gas",
    "NIFTY_PHARMA":      "Nifty Pharma",
    "NIFTY_BANK":        "Nifty PSU Bank",
    "NIFTY_REALTY":      "Nifty Realty",
    "NIFTY_HEALTHCARE":  "Nifty Healthcare",
}

# ── Data ──────────────────────────────────────────────────────────────────────
_DB = Path(__file__).resolve().parent.parent.parent / "data" / "nse_dashboard.db"

@st.cache_data(ttl=3600, show_spinner=False)
def load_data() -> pd.DataFrame:
    con = sqlite3.connect(str(_DB))
    df = pd.read_sql(
        "SELECT * FROM sector_intelligence ORDER BY sector, index_name, weightage_pct DESC", con
    )
    con.close()
    df["index_display"] = df["index_name"].map(INDEX_DISPLAY).fillna(df["index_name"])
    return df

def hhi(weights):
    return sum(w ** 2 for w in weights if pd.notna(w))

# ── Load ──────────────────────────────────────────────────────────────────────
with st.spinner("Loading sector data…"):
    df_all = load_data()

sectors = sorted(df_all["sector"].dropna().unique())

# ══════════════════════════════════════════════════════════════════════════════
# PAGE HEADER + SECTOR DROPDOWN  (main area, top of page)
# ══════════════════════════════════════════════════════════════════════════════
st.title("🏛️ Sector Index Stock")
st.caption("Select a sector → choose an index → view constituent stocks with weightage")

# ══════════════════════════════════════════════════════════════════════════════
# DATA SYNC PANEL
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("🔄 Data Sync — NSE India + Yahoo Finance", expanded=False):
    last = get_last_sync(_DB)
    sc1, sc2, sc3 = st.columns([3, 3, 2])

    with sc1:
        st.markdown("**Data Sources**")
        st.markdown(
            "- 🏛️ **NSE India archives** — live constituent list per index  \n"
            "- 💹 **Yahoo Finance** — market cap & last price per stock  \n"
            "- 📐 **Calculated** — weightage % from market cap"
        )
    with sc2:
        st.markdown("**Last Sync**")
        if last:
            st.markdown(
                f"🕐 **{last['synced_at']}**  \n"
                f"📊 {last['indices_synced']} indices · {last['stocks_total']} stocks  \n"
                f"🔁 {last['changes']}  \n"
                f"📄 Factsheet date: **{last.get('factsheet_date','N/A')}**"
            )
        else:
            st.markdown("⚠️ Never synced — data is from Excel seed file")

    with sc3:
        st.markdown("**Actions**")
        do_sync = st.button("🔄 Sync Now", type="primary", use_container_width=True,
                            help="Fetch latest constituent list from NSE and market caps from Yahoo Finance")
        st.caption("Takes ~2–3 min · All 12 indices")

    if do_sync:
        prog_bar  = st.progress(0.0)
        prog_text = st.empty()
        result_box = st.empty()

        def _progress(msg: str, pct: float):
            prog_bar.progress(min(pct, 1.0))
            prog_text.markdown(f"⏳ {msg}")

        with st.spinner("Syncing data from NSE India + Yahoo Finance…"):
            try:
                result = sync_all(str(_DB), progress_cb=_progress)
                prog_bar.progress(1.0)
                prog_text.empty()

                ok   = result["indices_ok"]
                fail = result["indices_failed"]
                result_box.success(
                    f"✅ Sync complete!  \n"
                    f"**{ok}** indices synced · **{result['stocks_total']}** stocks  \n"
                    f"🆕 +{result['stocks_added']} added · "
                    f"✏️ ~{result['stocks_updated']} updated · "
                    f"🗑️ -{result['stocks_removed']} removed  \n"
                    f"📄 Factsheet date: **{result.get('factsheet_date','N/A')}**  \n"
                    f"📌 Weightages sourced from NiftyIndices official factsheets (PDF)"
                    + (f"  \n⚠️ Failed: {', '.join(fail)}" if fail else "")
                )
            except Exception as e:
                prog_text.empty()
                result_box.error(f"❌ Sync failed: {e}")

        # Clear cache so page reloads with fresh data
        load_data.clear()
        st.rerun()

# ── Sector selector — prominent, full-width ───────────────────────────────────
sector_labels = [f"{SECTOR_ICONS.get(s,'📌')}  {s}" for s in sectors]
label_to_sector = {f"{SECTOR_ICONS.get(s,'📌')}  {s}": s for s in sectors}

col_sel, col_info = st.columns([3, 5], gap="large")
with col_sel:
    chosen_label = st.selectbox(
        "📂 Select Sector",
        options=sector_labels,
        key="sis_sector",
        help="Choose a sector to see its NSE indices and constituent stocks",
    )
selected_sector = label_to_sector[chosen_label]

# Sector-level data
sector_df = df_all[df_all["sector"] == selected_sector]
indices_in_sector = (
    sector_df[["index_name", "index_display"]]
    .drop_duplicates()
    .sort_values("index_display")
    .to_dict("records")
)

with col_info:
    icon = SECTOR_ICONS.get(selected_sector, "📌")
    n_indices = len(indices_in_sector)
    n_stocks  = len(sector_df)
    total_mc  = sector_df["market_cap_cr"].sum()
    # Build index symbol + display name lines
    idx_lines = "".join(
        f"<div style='margin-top:4px'>"
        f"<span style='color:#82b1ff;font-size:11px;font-weight:700;letter-spacing:0.5px'>{i['index_name']}</span>"
        f"<br><span style='color:#aaa;font-size:10px'>{i['index_display']}</span>"
        f"</div>"
        for i in indices_in_sector
    )
    stock_symbols = " · ".join(sector_df["symbol"].dropna().unique()[:5]) + ("…" if n_stocks > 5 else "")
    st.markdown(
        f"<div style='background:#12151f;border-radius:10px;padding:14px 20px;margin-top:24px'>"
        f"<span style='font-size:28px'>{icon}</span>&nbsp;"
        f"<span style='font-size:20px;font-weight:700;color:#e0e0e0'>{selected_sector}</span>"
        f"<div style='display:flex;gap:32px;margin-top:8px;align-items:flex-start'>"
        f"<div><div style='color:#888;font-size:11px;letter-spacing:1px'>INDICES</div>"
        f"<div style='color:#2979ff;font-size:20px;font-weight:700'>{n_indices}</div>"
        f"{idx_lines}</div>"
        f"<div><div style='color:#888;font-size:11px;letter-spacing:1px'>STOCKS</div>"
        f"<div style='color:#2979ff;font-size:20px;font-weight:700'>{n_stocks}</div>"
        f"<div style='color:#aaa;font-size:10px;margin-top:4px'>{stock_symbols}</div></div>"
        f"<div><div style='color:#888;font-size:11px;letter-spacing:1px'>SECTOR MKT CAP</div>"
        f"<div style='color:#00C853;font-size:20px;font-weight:700'>"
        f"{'₹{:,.0f} Cr'.format(total_mc) if total_mc > 0 else '–'}</div>"
        f"<div style='color:#aaa;font-size:10px;margin-top:4px'>combined all indices</div></div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# INDEX SELECTION — tab per index (handles multiple indices per sector)
# ══════════════════════════════════════════════════════════════════════════════
if not indices_in_sector:
    st.warning("No index data found for this sector.")
    st.stop()

st.markdown("#### 📊 NSE Indices in this Sector")

if len(indices_in_sector) == 1:
    selected_index = indices_in_sector[0]["index_name"]
    st.markdown(
        f"<div style='display:inline-block;background:#1a237e;color:#82b1ff;"
        f"padding:6px 18px;border-radius:20px;font-weight:600;font-size:14px'>"
        f"✅ {indices_in_sector[0]['index_display']}</div>",
        unsafe_allow_html=True,
    )
    st.markdown("")
else:
    # Multiple indices — use tabs
    tab_labels = [i["index_display"] for i in indices_in_sector]
    tabs = st.tabs(tab_labels)

    # We render each tab's content below; first resolve selected index from session state
    if "sis_index" not in st.session_state or \
            st.session_state["sis_index"] not in [i["index_name"] for i in indices_in_sector]:
        st.session_state["sis_index"] = indices_in_sector[0]["index_name"]

    # Button row as fallback for clarity
    btn_cols = st.columns(len(indices_in_sector))
    for i, idx in enumerate(indices_in_sector):
        active = st.session_state.get("sis_index") == idx["index_name"]
        with btn_cols[i]:
            if st.button(
                f"{'✅ ' if active else ''}{idx['index_display']}",
                key=f"sis_idxbtn_{idx['index_name']}",
                use_container_width=True,
                type="primary" if active else "secondary",
            ):
                st.session_state["sis_index"] = idx["index_name"]
                st.rerun()

    selected_index = st.session_state.get("sis_index", indices_in_sector[0]["index_name"])

# ══════════════════════════════════════════════════════════════════════════════
# STOCKS TABLE + CHARTS for selected index
# ══════════════════════════════════════════════════════════════════════════════
stocks = df_all[df_all["index_name"] == selected_index].sort_values(
    "weightage_pct", ascending=False
).reset_index(drop=True)

idx_label = INDEX_DISPLAY.get(selected_index, selected_index)
n_stocks  = len(stocks)
wts       = stocks["weightage_pct"].dropna().tolist()
hhi_val   = hhi(wts)
top5_wt   = stocks.head(5)["weightage_pct"].sum()
top10_wt  = stocks.head(10)["weightage_pct"].sum()
idx_mc    = stocks["market_cap_cr"].sum()

st.markdown("---")
st.markdown(f"## {idx_label} &nbsp;<span style='font-size:14px;color:#555;font-weight:400'>{selected_index}</span>", unsafe_allow_html=True)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Constituents",   n_stocks,    help=f"Stocks in {selected_index}")
m2.metric("Top 5 Weight",  f"{top5_wt:.1f}%")
m3.metric("Top 10 Weight", f"{top10_wt:.1f}%")
m4.metric("HHI",           f"{hhi_val:.0f}",
          help="Herfindahl-Hirschman Index: <1500 low, 1500–2500 moderate, >2500 high concentration")
m5.metric("Index Mkt Cap", f"₹{idx_mc:,.0f} Cr" if idx_mc > 0 else "–", help=f"Sum of constituent mkt caps · {selected_index}")

st.markdown("---")

# ── Two-column: table left, charts right ──────────────────────────────────────
col_tbl, col_ch = st.columns([5, 4], gap="large")

with col_tbl:
    st.subheader("📋 Constituent Stocks")
    display = stocks.copy()
    display.insert(0, "Rank", range(1, len(display)+1))
    display["weightage_pct"] = display["weightage_pct"].fillna(0)

    def color_wt(val):
        if not isinstance(val, (int, float)): return ""
        if val >= 15: return "background-color:#003300;color:#00C853;font-weight:700"
        if val >= 10: return "background-color:#002200;color:#00C853"
        if val >= 5:  return "color:#64DD17"
        return "color:#aaa"

    # Column order: Rank, Company, Symbol, Weight%, Mkt Cap — Industry & Series at end
    col_order = ["Rank", "company_name", "symbol", "weightage_pct", "market_cap_cr", "industry", "series"]
    col_order = [c for c in col_order if c in display.columns]
    rename = {
        "Rank": "Rank", "company_name": "Company", "symbol": "Symbol",
        "weightage_pct": "Weight %", "market_cap_cr": "Mkt Cap (₹Cr)",
        "industry": "Industry", "series": "Series",
    }
    show = display[col_order].rename(columns=rename)

    # Inject small-font CSS for this dataframe
    st.markdown(
        "<style>"
        "[data-testid='stDataFrame'] td, [data-testid='stDataFrame'] th "
        "{ font-size: 11px !important; padding: 2px 6px !important; }"
        "</style>",
        unsafe_allow_html=True,
    )
    st.dataframe(
        show.style
            .map(color_wt, subset=["Weight %"])
            .format({
                "Weight %":      lambda v: f"{v:.2f}%" if isinstance(v, (int,float)) else "–",
                "Mkt Cap (₹Cr)": lambda v: f"₹{v:,.0f}" if isinstance(v,(int,float)) and not pd.isna(v) else "–",
            }),
        use_container_width=True, hide_index=True,
        height=min(560, 42 + n_stocks * 28),
        column_config={
            "Rank":          st.column_config.NumberColumn(width="small"),
            "Symbol":        st.column_config.TextColumn(width="small"),
            "Weight %":      st.column_config.TextColumn(width="small"),
            "Mkt Cap (₹Cr)": st.column_config.TextColumn(width="medium"),
            "Industry":      st.column_config.TextColumn(width="medium"),
            "Series":        st.column_config.TextColumn(width="small"),
        },
    )

with col_ch:
    valid = stocks[stocks["weightage_pct"].notna() & (stocks["weightage_pct"] > 0)].copy()
    top12 = valid.head(12).copy()
    others_sum = valid.iloc[12:]["weightage_pct"].sum()
    if others_sum > 0:
        top12 = pd.concat([top12, pd.DataFrame([{
            "symbol": "Others", "company_name": "Others", "weightage_pct": others_sum
        }])], ignore_index=True)

    tab_pie, tab_tree, tab_bar = st.tabs(["🥧 Pie", "🗺️ Treemap", "📊 Bar"])

    with tab_pie:
        fig = go.Figure(go.Pie(
            labels=top12["symbol"], values=top12["weightage_pct"],
            hole=0.42, textinfo="percent+label", textfont=dict(size=9),
            marker=dict(colors=px.colors.qualitative.Bold),
            hovertemplate="<b>%{label}</b><br>%{value:.2f}%<extra></extra>",
        ))
        fig.update_layout(
            template="plotly_dark", height=300, showlegend=False,
            margin=dict(t=10,b=10,l=5,r=5),
            annotations=[dict(text=selected_index, x=0.5, y=0.5,
                              font=dict(size=9,color="white"), showarrow=False)],
        )
        st.plotly_chart(fig, use_container_width=True)

    with tab_tree:
        fig = px.treemap(
            valid.head(20), path=["symbol"], values="weightage_pct",
            color="weightage_pct",
            color_continuous_scale=[[0,"#D50000"],[0.4,"#FF6D00"],[1,"#00C853"]],
            hover_data={"company_name": True, "weightage_pct": ":.2f"},
        )
        fig.update_traces(texttemplate="<b>%{label}</b><br>%{value:.1f}%", textfont_size=10)
        fig.update_layout(template="plotly_dark", height=300,
                          margin=dict(t=5,b=5,l=5,r=5), coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

    with tab_bar:
        top15 = valid.head(15).sort_values("weightage_pct")
        colors = ["#2979FF" if i >= len(top15)-5 else "#1e3a5f" for i in range(len(top15))]
        fig = go.Figure(go.Bar(
            y=top15["symbol"], x=top15["weightage_pct"], orientation="h",
            marker_color=colors,
            text=[f"{v:.1f}%" for v in top15["weightage_pct"]], textposition="outside",
            hovertemplate="<b>%{y}</b><br>%{x:.2f}%<extra></extra>",
        ))
        fig.update_layout(template="plotly_dark", height=300,
                          margin=dict(t=5,b=5,l=10,r=50), xaxis_title="Weightage (%)")
        st.plotly_chart(fig, use_container_width=True)

# ── Analytics ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📐 Analytics")

a1, a2 = st.columns(2)

with a1:
    st.markdown("**Cumulative Weight Distribution**")
    cum = valid["weightage_pct"].cumsum().reset_index(drop=True)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(1, len(cum)+1)), y=cum,
        mode="lines+markers", line=dict(color="#2979FF", width=2),
        fill="tozeroy", fillcolor="rgba(41,121,255,0.1)", marker=dict(size=5),
        hovertemplate="Top %{x} stocks: %{y:.1f}%<extra></extra>",
    ))
    fig.add_hline(y=50, line_dash="dot", line_color="#FFD600", annotation_text="50%")
    fig.add_hline(y=80, line_dash="dot", line_color="#FF6D00", annotation_text="80%")
    fig.update_layout(template="plotly_dark", height=250,
                      xaxis_title="No. of Stocks", yaxis_title="Cumulative Weight (%)",
                      margin=dict(t=10,b=40,l=40,r=20))
    st.plotly_chart(fig, use_container_width=True)

with a2:
    st.markdown("**Weight Tiers**")
    tiers = {
        "🔵 Heavyweight (>10%)": int((valid["weightage_pct"] > 10).sum()),
        "🟢 Large (5–10%)":      int(((valid["weightage_pct"] >= 5) & (valid["weightage_pct"] <= 10)).sum()),
        "🟡 Mid (2–5%)":         int(((valid["weightage_pct"] >= 2) & (valid["weightage_pct"] < 5)).sum()),
        "⚪ Small (<2%)":        int((valid["weightage_pct"] < 2).sum()),
    }
    for tier, count in tiers.items():
        pct = count / n_stocks * 100 if n_stocks else 0
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;padding:6px 12px;"
            f"background:#12151f;border-radius:6px;margin-bottom:4px'>"
            f"<span>{tier}</span>"
            f"<span style='color:#2979ff;font-weight:700'>{count}"
            f"<span style='color:#555;font-size:11px'> ({pct:.0f}%)</span></span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    eq = 100/n_stocks if n_stocks else 0
    top1 = valid.iloc[0] if not valid.empty else None
    st.markdown(
        f"<div style='background:#1a1d2e;border-radius:8px;padding:12px 16px;margin-top:10px'>"
        f"<div style='font-size:11px;color:#888'>Equal weight per stock</div>"
        f"<div style='font-size:20px;font-weight:700;color:#2979ff'>{eq:.2f}%</div>"
        f"<div style='font-size:11px;color:#555'>vs top holding "
        f"<span style='color:#00C853'>{top1['symbol'] if top1 is not None else '–'} "
        f"@ {top1['weightage_pct']:.2f}%</span></div>"
        f"</div>" if top1 is not None else "",
        unsafe_allow_html=True,
    )

# ── Industry breakdown ────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🏭 Industry Breakdown within Index")
ind = stocks.groupby("industry")["weightage_pct"].sum().sort_values(ascending=False).reset_index()
ind.columns = ["Industry","Total Weight %"]
fig = go.Figure(go.Bar(
    x=ind["Industry"], y=ind["Total Weight %"],
    marker_color="#2979FF",
    text=[f"{v:.1f}%" for v in ind["Total Weight %"]], textposition="outside",
))
fig.update_layout(template="plotly_dark", height=270,
                  margin=dict(t=20,b=80,l=10,r=10),
                  xaxis_tickangle=-35, yaxis_title="Total Weight (%)")
st.plotly_chart(fig, use_container_width=True)

# ── All sectors overview ──────────────────────────────────────────────────────
st.markdown("---")
with st.expander("🌐 All Sectors Overview", expanded=False):
    rows = []
    for sec in sectors:
        sd = df_all[df_all["sector"] == sec]
        rows.append({
            "": SECTOR_ICONS.get(sec,"📌"),
            "Sector": sec,
            "Indices": ", ".join(sd["index_display"].unique()),
            "Stocks": len(sd),
            "Mkt Cap (₹Cr)": sd["market_cap_cr"].sum(),
        })
    ov = pd.DataFrame(rows)
    st.dataframe(
        ov.style.format({"Mkt Cap (₹Cr)": "₹{:,.0f}"}),
        use_container_width=True, hide_index=True,
    )

# ── Index Price Chart (yfinance + Plotly) ─────────────────────────────────────
st.markdown("---")
st.subheader(f"📈 {idx_label} · Price Chart")

YF_SYMBOL = {
    "BANKNIFTY":         "^NSEBANK",
    "NIFTY_AUTO":        "^CNXAUTO",
    "NCONSDUR":          "^CNXCONSUM",
    "NIFTY_FMCG":        "^CNXFMCG",
    "NIFTY_IT":          "^CNXIT",
    "NIFTY_MEDIA":       "^CNXMEDIA",
    "NIFTY_METAL":       "^CNXMETAL",
    "NIFTY_OIL_AND_GAS": "^CNXENERGY",
    "NIFTY_PHARMA":      "^CNXPHARMA",
    "NIFTY_BANK":        "^CNXPSUBANK",
    "NIFTY_REALTY":      "^CNXREALTY",
    "NIFTY_HEALTHCARE":  "^CNXPHARMA",
}
yf_sym = YF_SYMBOL.get(selected_index, f"^{selected_index}")

period_opts = {"3 Months": "3mo", "6 Months": "6mo", "1 Year": "1y", "2 Years": "2y"}
pc1, pc2 = st.columns([2, 6])
with pc1:
    period_label = st.selectbox("Period", list(period_opts.keys()), index=2, key="sis_period")
period = period_opts[period_label]

@st.cache_data(ttl=900, show_spinner=False)
def fetch_index_ohlcv(symbol: str, period: str):
    try:
        import yfinance as yf
        df = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            return None
        df = df.reset_index()
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] if c[1] == "" else c[0] for c in df.columns]
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except Exception as e:
        return None

with st.spinner(f"Loading {idx_label} price data…"):
    ohlcv = fetch_index_ohlcv(yf_sym, period)

if ohlcv is None or ohlcv.empty:
    st.info(f"Price data not available for {idx_label} ({yf_sym}). This index may not be on Yahoo Finance.")
else:
    # Compute EMA 20 & EMA 50
    close_col = next((c for c in ohlcv.columns if c.lower() == "close"), None)
    date_col  = next((c for c in ohlcv.columns if c.lower() in ("date","datetime","index")), ohlcv.columns[0])

    if close_col:
        ohlcv["EMA20"] = ohlcv[close_col].ewm(span=20, adjust=False).mean()
        ohlcv["EMA50"] = ohlcv[close_col].ewm(span=50, adjust=False).mean()

    open_col  = next((c for c in ohlcv.columns if c.lower() == "open"),   None)
    high_col  = next((c for c in ohlcv.columns if c.lower() == "high"),   None)
    low_col   = next((c for c in ohlcv.columns if c.lower() == "low"),    None)
    vol_col   = next((c for c in ohlcv.columns if c.lower() == "volume"), None)

    from plotly.subplots import make_subplots
    rows = 3 if vol_col else 2
    row_heights = [0.55, 0.25, 0.20] if rows == 3 else [0.65, 0.35]
    fig_idx = make_subplots(
        rows=rows, cols=1, shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
        subplot_titles=[idx_label, "RSI (14)", "Volume"] if rows == 3 else [idx_label, "RSI (14)"],
    )

    # Candlestick
    if all([open_col, high_col, low_col, close_col]):
        fig_idx.add_trace(go.Candlestick(
            x=ohlcv[date_col], open=ohlcv[open_col], high=ohlcv[high_col],
            low=ohlcv[low_col], close=ohlcv[close_col],
            name=idx_label,
            increasing_line_color="#00C853", decreasing_line_color="#D50000",
            increasing_fillcolor="#00C853", decreasing_fillcolor="#D50000",
        ), row=1, col=1)
    else:
        fig_idx.add_trace(go.Scatter(
            x=ohlcv[date_col], y=ohlcv[close_col], name=idx_label,
            line=dict(color="#2979FF", width=1.5),
        ), row=1, col=1)

    # EMA lines
    if close_col:
        fig_idx.add_trace(go.Scatter(
            x=ohlcv[date_col], y=ohlcv["EMA20"], name="EMA 20",
            line=dict(color="#FFD600", width=1.2), opacity=0.85,
        ), row=1, col=1)
        fig_idx.add_trace(go.Scatter(
            x=ohlcv[date_col], y=ohlcv["EMA50"], name="EMA 50",
            line=dict(color="#FF6D00", width=1.2), opacity=0.85,
        ), row=1, col=1)

        # RSI
        delta = ohlcv[close_col].diff()
        gain  = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
        loss  = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
        rs    = gain / loss.replace(0, float("nan"))
        rsi   = 100 - 100 / (1 + rs)
        rsi_color = ["#00C853" if v >= 50 else "#D50000" for v in rsi.fillna(50)]
        fig_idx.add_trace(go.Scatter(
            x=ohlcv[date_col], y=rsi, name="RSI",
            line=dict(color="#CE93D8", width=1.2),
        ), row=2, col=1)
        fig_idx.add_hline(y=70, line_dash="dot", line_color="#D50000", line_width=0.8, row=2, col=1)
        fig_idx.add_hline(y=30, line_dash="dot", line_color="#00C853", line_width=0.8, row=2, col=1)
        fig_idx.add_hrect(y0=30, y1=70, fillcolor="rgba(100,100,100,0.05)", line_width=0, row=2, col=1)

    # Volume
    if vol_col and rows == 3:
        vol_colors = ["#00C853" if (close_col and i > 0 and ohlcv[close_col].iloc[i] >= ohlcv[close_col].iloc[i-1])
                      else "#D50000" for i in range(len(ohlcv))]
        fig_idx.add_trace(go.Bar(
            x=ohlcv[date_col], y=ohlcv[vol_col], name="Volume",
            marker_color=vol_colors, opacity=0.7,
        ), row=3, col=1)

    last_close = ohlcv[close_col].iloc[-1] if close_col else None
    prev_close = ohlcv[close_col].iloc[-2] if close_col and len(ohlcv) > 1 else None
    chg_pct    = ((last_close - prev_close) / prev_close * 100) if last_close and prev_close else None

    fig_idx.update_layout(
        template="plotly_dark", height=520,
        margin=dict(t=30, b=20, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
                    font=dict(size=10)),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )
    fig_idx.update_yaxes(tickfont=dict(size=10), gridcolor="#1e2130")
    fig_idx.update_xaxes(tickfont=dict(size=10), gridcolor="#1e2130")

    st.plotly_chart(fig_idx, use_container_width=True)
    if last_close and chg_pct is not None:
        color = "#00C853" if chg_pct >= 0 else "#D50000"
        arrow = "▲" if chg_pct >= 0 else "▼"
        st.caption(
            f"**{idx_label}** &nbsp;|&nbsp; Last close: "
            f"<span style='color:{color};font-weight:700'>{last_close:,.2f} "
            f"{arrow} {abs(chg_pct):.2f}%</span> &nbsp;|&nbsp; "
            f"Yahoo Finance symbol: `{yf_sym}` &nbsp;|&nbsp; "
            f"Data delayed · Not investment advice",
            unsafe_allow_html=True,
        )

st.caption("📌 Data sourced from NSE index constituent files · Weightages are reference data")
