"""
NSE Sector Intelligence Engine
Sector → Index → Stocks → Weightage → Analytics
Data sourced from SectorMapping (static, refreshed manually).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import sqlite3

st.set_page_config(
    page_title="NSE Sector Intelligence | Index Constituents & Weightage",
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

INDEX_INFO = {
    "BANKNIFTY":        {"display": "Bank Nifty",              "ticker": "^NSEBANK"},
    "NIFTY_AUTO":       {"display": "Nifty Auto",              "ticker": "^CNXAUTO"},
    "NCONSDUR":         {"display": "Nifty Consumer Durables", "ticker": "^CNXCONSUM"},
    "NIFTY_FMCG":       {"display": "Nifty FMCG",             "ticker": "^CNXFMCG"},
    "NIFTY_IT":         {"display": "Nifty IT",                "ticker": "^CNXIT"},
    "NIFTY_MEDIA":      {"display": "Nifty Media",             "ticker": "^CNXMEDIA"},
    "NIFTY_METAL":      {"display": "Nifty Metal",             "ticker": "^CNXMETAL"},
    "NIFTY_OIL_AND_GAS":{"display": "Nifty Oil & Gas",        "ticker": "^CNXENERGY"},
    "NIFTY_PHARMA":     {"display": "Nifty Pharma",            "ticker": "^CNXPHARMA"},
    "NIFTY_BANK":       {"display": "Nifty PSU Bank",          "ticker": "^CNXPSUBANK"},
    "NIFTY_REALTY":     {"display": "Nifty Realty",            "ticker": "^CNXREALTY"},
    "NIFTY_HEALTHCARE": {"display": "Nifty Healthcare",        "ticker": "^CNXPHARMA"},
}

# ── Data loader ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def load_sector_data() -> pd.DataFrame:
    db = Path(__file__).resolve().parent.parent.parent / "data" / "nse_dashboard.db"
    con = sqlite3.connect(str(db))
    df = pd.read_sql("SELECT * FROM sector_intelligence ORDER BY sector, index_name, weightage_pct DESC", con)
    con.close()
    return df

def get_sectors(df):
    return sorted(df["sector"].dropna().unique())

def get_indices_for_sector(df, sector):
    sub = df[df["sector"] == sector]
    idxs = sub[["index_name","index_display"]].drop_duplicates()
    return idxs.to_dict("records")

def get_stocks_for_index(df, index_name):
    return df[df["index_name"] == index_name].sort_values("weightage_pct", ascending=False).reset_index(drop=True)

# ── Analytics helpers ─────────────────────────────────────────────────────────
def hhi(weights):
    """Herfindahl-Hirschman Index — market concentration (0-10000)."""
    return sum((w ** 2) for w in weights if pd.notna(w))

def concentration(stocks_df, top_n):
    top = stocks_df.head(top_n)["weightage_pct"].sum()
    return top

# ── Page ──────────────────────────────────────────────────────────────────────
st.title("🏛️ NSE Sector Intelligence")
st.caption("Sector → Index → Constituent Stocks → Weightage · Static NSE reference data")

with st.spinner("Loading sector data…"):
    df_all = load_sector_data()

sectors = get_sectors(df_all)

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — sector selector
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 🏛️ Sector Intelligence")
    st.markdown("---")

    sector_options = [f"{SECTOR_ICONS.get(s,'📌')} {s}" for s in sectors]
    sel_sector_label = st.selectbox("Select Sector", sector_options, key="si_sector")
    selected_sector  = sel_sector_label.split(" ", 1)[1]   # strip emoji

    indices = get_indices_for_sector(df_all, selected_sector)
    st.markdown(f"**{len(indices)} index** for this sector")
    st.markdown("---")

    # Quick search
    search_q = st.text_input("🔍 Search Stock Symbol", placeholder="e.g. HDFCBANK")

# ── If search query, show results first ───────────────────────────────────────
if search_q.strip():
    q = search_q.strip().upper()
    results = df_all[df_all["symbol"].str.upper().str.contains(q, na=False) |
                     df_all["company_name"].str.upper().str.contains(q, na=False)]
    st.subheader(f"🔍 Search results for '{search_q}'")
    if results.empty:
        st.info("No matching stocks found.")
    else:
        st.dataframe(
            results[["company_name","symbol","sector","index_display","industry","weightage_pct","market_cap_cr"]]
            .rename(columns={
                "company_name":"Company", "symbol":"Symbol", "sector":"Sector",
                "index_display":"Index", "industry":"Industry",
                "weightage_pct":"Weight %", "market_cap_cr":"Mkt Cap (₹Cr)",
            })
            .style.format({"Weight %": "{:.2f}%", "Mkt Cap (₹Cr)": "₹{:,.0f}"}),
            use_container_width=True, hide_index=True,
        )
    st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# SECTOR HEADER
# ══════════════════════════════════════════════════════════════════════════════
icon = SECTOR_ICONS.get(selected_sector, "📌")
sector_stocks = df_all[df_all["sector"] == selected_sector]
total_mktcap  = sector_stocks["market_cap_cr"].sum()

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{icon} Sector", selected_sector)
c2.metric("Indices", len(indices))
c3.metric("Total Stocks", len(sector_stocks))
c4.metric("Sector Mkt Cap", f"₹{total_mktcap/100:.1f}L Cr" if total_mktcap > 0 else "–")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# INDEX CHIPS — click to select
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("#### 📊 Indices in this Sector")

if "si_selected_index" not in st.session_state:
    st.session_state["si_selected_index"] = indices[0]["index_name"] if indices else None

# Show index buttons
idx_cols = st.columns(min(len(indices), 4))
for i, idx in enumerate(indices):
    with idx_cols[i % 4]:
        active = st.session_state["si_selected_index"] == idx["index_name"]
        label  = f"{'✅ ' if active else ''}{idx['index_display']}"
        if st.button(label, key=f"idx_btn_{idx['index_name']}", use_container_width=True,
                     type="primary" if active else "secondary"):
            st.session_state["si_selected_index"] = idx["index_name"]
            st.rerun()

selected_index = st.session_state["si_selected_index"]

# Reset if sector changed and index no longer valid
if selected_index not in [i["index_name"] for i in indices]:
    st.session_state["si_selected_index"] = indices[0]["index_name"] if indices else None
    selected_index = st.session_state["si_selected_index"]

if not selected_index:
    st.warning("No index data available for this sector.")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# INDEX DETAIL
# ══════════════════════════════════════════════════════════════════════════════
stocks_df   = get_stocks_for_index(df_all, selected_index)
idx_display = INDEX_INFO.get(selected_index, {}).get("display", selected_index)
total_wt    = stocks_df["weightage_pct"].sum()
n_stocks    = len(stocks_df)

st.markdown("---")
st.markdown(f"## {idx_display} · {n_stocks} Constituents")

# ── Summary metrics ───────────────────────────────────────────────────────────
wts = stocks_df["weightage_pct"].dropna().tolist()
hhi_val  = hhi(wts)
top5_wt  = concentration(stocks_df, 5)
top10_wt = concentration(stocks_df, 10)
idx_mcap = stocks_df["market_cap_cr"].sum()

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Constituents",    n_stocks)
m2.metric("Top 5 Weight",   f"{top5_wt:.1f}%")
m3.metric("Top 10 Weight",  f"{top10_wt:.1f}%")
m4.metric("HHI (Concentration)", f"{hhi_val:.0f}",
          help="Herfindahl Index: <1500=low, 1500-2500=moderate, >2500=high concentration")
m5.metric("Index Mkt Cap",  f"₹{idx_mcap/100:.1f}L Cr" if idx_mcap > 0 else "–")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# TWO COLUMN LAYOUT — Table + Charts
# ══════════════════════════════════════════════════════════════════════════════
col_table, col_charts = st.columns([5, 4], gap="large")

with col_table:
    st.subheader(f"📋 Constituent Stocks")

    # Rank column
    stocks_display = stocks_df.copy()
    stocks_display.insert(0, "Rank", range(1, len(stocks_display) + 1))
    stocks_display["weightage_pct"] = stocks_display["weightage_pct"].fillna(0)

    # Color style
    def color_wt(val):
        if not isinstance(val, (int, float)): return ""
        if val >= 15: return "background-color:#003300;color:#00C853;font-weight:700"
        if val >= 10: return "background-color:#002200;color:#00C853"
        if val >= 5:  return "color:#64DD17"
        return "color:#aaa"

    display_cols = {
        "Rank": "Rank", "company_name": "Company", "symbol": "Symbol",
        "industry": "Industry", "series": "Series",
        "weightage_pct": "Weight %", "market_cap_cr": "Mkt Cap (₹Cr)",
    }
    avail = [c for c in display_cols if c in stocks_display.columns]
    show  = stocks_display[avail].rename(columns=display_cols)

    st.dataframe(
        show.style
            .map(color_wt, subset=["Weight %"])
            .format({
                "Weight %":     lambda v: f"{v:.2f}%" if isinstance(v,(int,float)) else "–",
                "Mkt Cap (₹Cr)":lambda v: f"₹{v:,.0f}" if isinstance(v,(int,float)) and not pd.isna(v) else "–",
            }),
        use_container_width=True, hide_index=True,
        height=min(600, 40 + n_stocks * 35),
    )

with col_charts:
    tab_pie, tab_tree, tab_bar = st.tabs(["🥧 Pie", "🗺️ Treemap", "📊 Bar"])

    valid = stocks_df[stocks_df["weightage_pct"].notna() & (stocks_df["weightage_pct"] > 0)].copy()
    # Group others < 1%
    top_12 = valid.head(12).copy()
    others = valid.iloc[12:]["weightage_pct"].sum()
    if others > 0:
        others_row = pd.DataFrame([{"symbol": "Others", "company_name": "Others",
                                     "weightage_pct": others}])
        top_12 = pd.concat([top_12, others_row], ignore_index=True)

    with tab_pie:
        fig_pie = go.Figure(go.Pie(
            labels=top_12["symbol"],
            values=top_12["weightage_pct"],
            hole=0.42,
            textinfo="percent+label",
            textfont=dict(size=11),
            marker=dict(colors=px.colors.qualitative.Bold),
            hovertemplate="<b>%{label}</b><br>%{value:.2f}%<extra></extra>",
        ))
        fig_pie.update_layout(
            template="plotly_dark", height=400,
            showlegend=False, margin=dict(t=20, b=20, l=10, r=10),
            annotations=[dict(text=idx_display, x=0.5, y=0.5,
                              font=dict(size=11, color="white"), showarrow=False)],
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with tab_tree:
        fig_tree = px.treemap(
            valid.head(20),
            path=["symbol"],
            values="weightage_pct",
            color="weightage_pct",
            color_continuous_scale=[[0,"#D50000"],[0.4,"#FF6D00"],[1,"#00C853"]],
            hover_data={"company_name": True, "weightage_pct": ":.2f"},
        )
        fig_tree.update_traces(texttemplate="<b>%{label}</b><br>%{value:.1f}%", textfont_size=12)
        fig_tree.update_layout(
            template="plotly_dark", height=400,
            margin=dict(t=10, b=10, l=10, r=10),
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig_tree, use_container_width=True)

    with tab_bar:
        top_bar = valid.head(15).sort_values("weightage_pct")
        colors  = ["#2979FF" if i >= len(top_bar)-5 else "#1e3a5f"
                   for i in range(len(top_bar))]
        fig_bar = go.Figure(go.Bar(
            y=top_bar["symbol"],
            x=top_bar["weightage_pct"],
            orientation="h",
            marker_color=colors,
            text=[f"{v:.1f}%" for v in top_bar["weightage_pct"]],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Weight: %{x:.2f}%<extra></extra>",
        ))
        fig_bar.update_layout(
            template="plotly_dark", height=420,
            margin=dict(t=10, b=10, l=20, r=60),
            xaxis_title="Weightage (%)",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS SECTION
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("📐 Index Analytics")

a1, a2 = st.columns(2)

with a1:
    st.markdown("**Cumulative Weight Distribution**")
    cumulative = valid["weightage_pct"].cumsum().reset_index(drop=True)
    fig_cum = go.Figure()
    fig_cum.add_trace(go.Scatter(
        x=list(range(1, len(cumulative)+1)),
        y=cumulative,
        mode="lines+markers",
        line=dict(color="#2979FF", width=2),
        fill="tozeroy", fillcolor="rgba(41,121,255,0.1)",
        marker=dict(size=5),
        hovertemplate="Top %{x} stocks: %{y:.1f}%<extra></extra>",
    ))
    fig_cum.add_hline(y=50, line_dash="dot", line_color="#FFD600", annotation_text="50%")
    fig_cum.add_hline(y=80, line_dash="dot", line_color="#FF6D00", annotation_text="80%")
    fig_cum.update_layout(
        template="plotly_dark", height=260,
        xaxis_title="Number of Stocks", yaxis_title="Cumulative Weight (%)",
        margin=dict(t=10, b=40, l=40, r=20),
    )
    st.plotly_chart(fig_cum, use_container_width=True)

with a2:
    st.markdown("**Weight Tiers**")
    tiers = {
        "🔵 Heavyweight (>10%)":   int((valid["weightage_pct"] > 10).sum()),
        "🟢 Large (5–10%)":        int(((valid["weightage_pct"] >= 5) & (valid["weightage_pct"] <= 10)).sum()),
        "🟡 Mid (2–5%)":           int(((valid["weightage_pct"] >= 2) & (valid["weightage_pct"] < 5)).sum()),
        "⚪ Small (<2%)":          int((valid["weightage_pct"] < 2).sum()),
    }
    for tier, count in tiers.items():
        pct = count / n_stocks * 100 if n_stocks else 0
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;padding:6px 12px;"
            f"background:#12151f;border-radius:6px;margin-bottom:4px'>"
            f"<span>{tier}</span>"
            f"<span style='color:#2979ff;font-weight:700'>{count} stocks &nbsp;"
            f"<span style='color:#555;font-size:11px'>({pct:.0f}%)</span></span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("")
    # Equal weight vs actual
    eq_wt = 100 / n_stocks if n_stocks else 0
    st.markdown(
        f"<div style='background:#1a1d2e;border-radius:8px;padding:12px 16px;margin-top:8px'>"
        f"<div style='font-size:12px;color:#888'>Equal Weight vs Actual (Top Stock)</div>"
        f"<div style='font-size:22px;font-weight:700;color:#2979ff'>{eq_wt:.2f}%</div>"
        f"<div style='font-size:11px;color:#555'>equal weight per stock vs "
        f"<span style='color:#00C853'>{valid.iloc[0]['weightage_pct']:.2f}%</span> "
        f"({valid.iloc[0]['symbol']}) actual</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

# ── Industry breakdown within index ──────────────────────────────────────────
st.markdown("---")
st.subheader("🏭 Industry Breakdown")

ind_grp = (stocks_df.groupby("industry")["weightage_pct"]
           .sum().sort_values(ascending=False).reset_index())
ind_grp.columns = ["Industry", "Total Weight %"]

fig_ind = go.Figure(go.Bar(
    x=ind_grp["Industry"], y=ind_grp["Total Weight %"],
    marker_color="#2979FF",
    text=[f"{v:.1f}%" for v in ind_grp["Total Weight %"]],
    textposition="outside",
))
fig_ind.update_layout(
    template="plotly_dark", height=280,
    margin=dict(t=20, b=80, l=10, r=10),
    xaxis_tickangle=-35, yaxis_title="Total Weight (%)",
)
st.plotly_chart(fig_ind, use_container_width=True)

# ── All sectors overview ──────────────────────────────────────────────────────
st.markdown("---")
with st.expander("🌐 All Sectors Overview", expanded=False):
    overview_rows = []
    for sec in sectors:
        sec_df = df_all[df_all["sector"] == sec]
        idxs   = sec_df["index_display"].unique()
        total  = sec_df["market_cap_cr"].sum()
        overview_rows.append({
            "Icon":       SECTOR_ICONS.get(sec, "📌"),
            "Sector":     sec,
            "Indices":    ", ".join(idxs),
            "Stocks":     len(sec_df),
            "Mkt Cap (₹Cr)": total,
        })
    ov_df = pd.DataFrame(overview_rows)
    st.dataframe(
        ov_df.style.format({"Mkt Cap (₹Cr)": "₹{:,.0f}"}),
        use_container_width=True, hide_index=True,
    )

st.caption("📌 Data sourced from NSE index constituent files · Weightages are as per last update · Static reference data")
