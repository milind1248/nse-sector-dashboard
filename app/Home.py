"""
NSE Sector Intelligence Dashboard
Entry point: FII Fortnightly Sector Watch — investor decision flow starts here.
All data is live: NSDL for fortnightly FPI data, yfinance for prices.
No hardcoded data. Refresh fetches only latest; historical stays cached.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date

st.set_page_config(
    page_title="NSE Sector Analysis",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Cold-start DB sync (Streamlit Cloud resets filesystem on restart) ─────────
@st.cache_resource(show_spinner=False)
def _cold_start_sync():
    """
    Runs once per server process.
    • If DB is empty → full historical sync (first-ever deployment).
    • If today is a fortnightly publish date AND we don't have it yet → sync latest only.
    • Otherwise → no network call; just load from DB.
    """
    try:
        from backend.data_ingestion.nsdl_fetcher import (
            _dates_in_db, sync_nsdl_to_db, should_sync_today
        )
        n = len(_dates_in_db())
        if n < 5:
            sync_nsdl_to_db(force_refresh_latest=False)   # first-run full load
        elif should_sync_today():
            sync_nsdl_to_db(force_refresh_latest=True)    # auto-fetch new fortnight
    except Exception:
        pass

_cold_start_sync()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📊 NSE Sector Analysis")
    st.markdown("**Investor Decision Flow**")
    st.markdown("""
🏠 **Home**
&nbsp;&nbsp;&nbsp;↳ Where is FII buying this fortnight?

🌏 **FPI Sectors**
&nbsp;&nbsp;&nbsp;↳ Deep-dive: first/second half, top buyers

🌐 **FII Invest Sector**
&nbsp;&nbsp;&nbsp;↳ 5-year sector flow history & heatmap

📈 **Sector Analysis**
&nbsp;&nbsp;&nbsp;↳ Is index price confirming FII flow?

🎯 **Stock Picker**
&nbsp;&nbsp;&nbsp;↳ Find the best stock in the right sector

🏦 **FII DII Flow**
&nbsp;&nbsp;&nbsp;↳ Daily institutional buy/sell activity

📡 **Market Pulse**
&nbsp;&nbsp;&nbsp;↳ Breadth, RRG & overall market health

🔔 **Alerts**
&nbsp;&nbsp;&nbsp;↳ Sectors breaking out or reversing

📤 **Export**
&nbsp;&nbsp;&nbsp;↳ Download data for offline analysis
""")
    st.markdown("---")
    if st.button("🔄 Refresh Latest Data", use_container_width=True,
                  help="Fetches today's latest NSDL + price data only. Old historical data stays."):
        bar = st.progress(0, text="Clearing cache...")
        st.cache_data.clear()
        try:
            from backend.storage.cache import invalidate_all
            invalidate_all()
        except Exception:
            pass

        bar.progress(20, text="Syncing NSDL FII data (new reports only)...")
        try:
            import importlib
            import backend.data_ingestion.nsdl_fetcher as _nsdl_mod
            importlib.reload(_nsdl_mod)
            _nsdl_mod.sync_nsdl_to_db(force_refresh_latest=True)
        except Exception as e:
            st.warning(f"NSDL: {e}")

        bar.progress(55, text="Fetching latest FII/DII daily flow...")
        try:
            from backend.data_ingestion.nse_fetcher import fetch_fii_dii, fetch_market_breadth
            fetch_fii_dii(days=30)
            fetch_market_breadth()
        except Exception as e:
            st.warning(f"FII/DII: {e}")

        bar.progress(80, text="Fetching sector index prices...")
        try:
            from backend.data_ingestion.yfinance_fetcher import fetch_all_sector_prices
            fetch_all_sector_prices()
        except Exception as e:
            st.warning(f"Sector prices: {e}")

        bar.progress(100, text="Done!")
        st.success("Latest data loaded! Reloading page...")
        st.rerun()

    st.markdown("---")
    st.caption(f"Data as of: {date.today().strftime('%d %b %Y')}")
    st.caption("NSDL updates every fortnight (1st & 15th of month).")

# ── Load NSDL data (all available fortnights) ─────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def load_nsdl_history():
    from backend.data_ingestion.nsdl_fetcher import fetch_nsdl_fii_sectors
    return fetch_nsdl_fii_sectors()   # all stored data from DB

with st.spinner("Loading FII sector data from NSDL..."):
    all_periods = load_nsdl_history()

if not all_periods:
    st.error("Could not load NSDL FII data. Check your internet connection and try Refresh.")
    st.stop()

sorted_dates  = sorted(all_periods.keys(), reverse=True)
curr_date     = sorted_dates[0]
prev_date     = sorted_dates[1] if len(sorted_dates) > 1 else None
curr_df       = all_periods[curr_date]
prev_df       = all_periods[prev_date] if prev_date else None

# Build master trend matrix: rows = date, cols = sector
all_sector_names = sorted({s for df in all_periods.values() for s in df["nsdl_sector"]})
trend_rows = []
for d in sorted(all_periods.keys()):
    row = {"_date": d, "Period": d.strftime("%d %b %Y")}
    for sec in all_sector_names:
        match = all_periods[d][all_periods[d]["nsdl_sector"] == sec]
        row[sec] = match.iloc[0]["net_curr_eq"] if not match.empty else None
    trend_rows.append(row)
trend_df = pd.DataFrame(trend_rows).set_index("_date")

# ── Page header ───────────────────────────────────────────────────────────────
st.title("📊 FII Fortnightly Sector Watch")
st.markdown(
    "**Start here every morning.** "
    "See where FII money is flowing → click sector → confirm price → find stocks to buy."
)

# Summary metrics
total_curr    = curr_df["net_curr_eq"].sum()
buying_count  = int((curr_df["net_curr_eq"] > 0).sum())
selling_count = int((curr_df["net_curr_eq"] < 0).sum())
top_buyer     = curr_df.iloc[0]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total FII Equity Flow This Fortnight", f"₹{total_curr:+,.0f} Cr",
           "Net Inflow" if total_curr > 0 else "Net Outflow",
           delta_color="normal" if total_curr > 0 else "inverse")
m2.metric("Sectors Buying", str(buying_count))
m3.metric("Sectors Selling", str(selling_count))
m4.metric("Top Sector", top_buyer["nsdl_sector"][:22], f"₹{top_buyer['net_curr_eq']:+,.0f} Cr")

# ── Tab layout ────────────────────────────────────────────────────────────────
tab_curr, tab_hist, tab_trend = st.tabs([
    f"📅 Current: {curr_date.strftime('%d %b %Y')}",
    "📊 Historical % Change Table",
    "📈 Sector Flow Trend Chart",
])

SIGNAL_COLOR = {
    "buying":     ("#00C853", "Buying"),
    "light_buy":  ("#64DD17", "Light Buy"),
    "light_sell": ("#FF6D00", "Light Sell"),
    "selling":    ("#D50000", "Selling"),
    "neutral":    ("#888888", "–"),
}

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Current fortnight bar chart + table
# ══════════════════════════════════════════════════════════════════════════════
with tab_curr:
    sorted_curr = curr_df.sort_values("net_curr_eq", ascending=True)
    colors_bar  = ["#00C853" if v > 0 else "#D50000" for v in sorted_curr["net_curr_eq"]]
    fig_bar = go.Figure(go.Bar(
        x=sorted_curr["net_curr_eq"],
        y=sorted_curr["nsdl_sector"],
        orientation="h",
        marker_color=colors_bar,
        text=[f"₹{v:+,.0f}" for v in sorted_curr["net_curr_eq"]],
        textposition="outside",
    ))
    fig_bar.update_layout(
        template="plotly_dark", height=600,
        title=f"FII Equity Net Investment — {curr_date.strftime('%d %b %Y')} (₹ Crore)",
        margin=dict(t=50, b=20, l=240, r=130),
        xaxis_title="₹ Crore", xaxis_zeroline=True,
        xaxis_zerolinecolor="rgba(255,255,255,0.3)", xaxis_zerolinewidth=1.5,
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # Sector table
    rows = []
    for _, r in curr_df.iterrows():
        _, sig_label = SIGNAL_COLOR.get(r["signal"], ("#888", "–"))
        prev_net = None
        if prev_df is not None:
            match = prev_df[prev_df["nsdl_sector"] == r["nsdl_sector"]]
            if not match.empty:
                prev_net = match.iloc[0]["net_curr_eq"]
        pct_chg = None
        if prev_net and prev_net != 0:
            pct_chg = ((r["net_curr_eq"] - prev_net) / abs(prev_net)) * 100
        rows.append({
            "Sector":           r["nsdl_sector"],
            "Signal":           sig_label,
            "Net Curr (Cr)":    r["net_curr_eq"],
            "Net Prev (Cr)":    prev_net,
            "Chg vs Prev (Cr)": r["net_curr_eq"] - prev_net if prev_net is not None else None,
            "Chg vs Prev %":    pct_chg,
            "AUC Curr (Cr)":    r["auc_curr_eq"],
            "AUC Chg %":        r["auc_pct_change"],
            "_internal":        r["sector"],
        })

    display_df = pd.DataFrame(rows)

    def color_num(val):
        if not isinstance(val, (int, float)): return ""
        return "color:#00C853;font-weight:600" if val > 0 else "color:#D50000;font-weight:600"

    def color_sig(val):
        for k, (c, l) in SIGNAL_COLOR.items():
            if val == l: return f"color:{c};font-weight:600"
        return ""

    st.dataframe(
        display_df.drop(columns=["_internal"])
        .style
        .map(color_num, subset=["Net Curr (Cr)","Net Prev (Cr)","Chg vs Prev (Cr)","Chg vs Prev %","AUC Chg %"])
        .map(color_sig, subset=["Signal"])
        .format({
            "Net Curr (Cr)":    lambda x: f"₹{x:+,.0f}" if isinstance(x,(int,float)) else "–",
            "Net Prev (Cr)":    lambda x: f"₹{x:+,.0f}" if isinstance(x,(int,float)) else "–",
            "Chg vs Prev (Cr)": lambda x: f"₹{x:+,.0f}" if isinstance(x,(int,float)) else "–",
            "Chg vs Prev %":    lambda x: f"{x:+.1f}%"  if isinstance(x,(int,float)) else "–",
            "AUC Curr (Cr)":    lambda x: f"₹{x:,.0f}"  if isinstance(x,(int,float)) else "–",
            "AUC Chg %":        lambda x: f"{x:+.2f}%"  if isinstance(x,(int,float)) else "–",
        }),
        use_container_width=True, hide_index=True, height=520,
    )
    st.caption("AUC = Assets Under Custody (total FII holding). Chg vs Prev = change from previous fortnight.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Historical % change table with date range filter
# (like the Excel sheet: sectors as rows, fortnights as columns, % changes)
# ══════════════════════════════════════════════════════════════════════════════
with tab_hist:
    st.subheader("FII Net Flow History — All Fortnights")
    st.caption(
        "Shows FII equity net investment (₹ Cr) per sector per fortnight. "
        "**% column** = change from the previous fortnight. "
        "Green = FII increased buying / reduced selling. Red = opposite."
    )

    # Date range filter
    date_labels = [d.strftime("%d %b %Y") for d in sorted_dates]
    col_to, col_from = st.columns(2)
    to_sel   = col_to.selectbox("To fortnight (latest):", date_labels,
                                 index=0, key="hist_to")
    from_sel = col_from.selectbox("From fortnight (older):", date_labels,
                                   index=min(len(date_labels)-1, 11), key="hist_from")

    from_date = sorted_dates[date_labels.index(from_sel)]
    to_date   = sorted_dates[date_labels.index(to_sel)]
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    # newest first so latest date is leftmost column
    filtered_dates = sorted([d for d in sorted_dates if from_date <= d <= to_date], reverse=True)

    if len(filtered_dates) < 1:
        st.warning("No data in selected range.")
    else:
        # Build display table:
        # Rows = sectors
        # For each fortnight: Net (Cr) column + % change vs previous fortnight column
        cols_in_order = []   # (date, col_type) where col_type = "net" or "pct"
        for d in filtered_dates:
            cols_in_order.append(d)

        # Build wide table
        table_data = {"Sector": all_sector_names}
        for i, d in enumerate(filtered_dates):
            df_p = all_periods[d]
            lbl  = d.strftime("%d %b %y")
            net_vals = []
            pct_vals = []
            for sec in all_sector_names:
                match = df_p[df_p["nsdl_sector"] == sec]
                net   = match.iloc[0]["net_curr_eq"] if not match.empty else None
                net_vals.append(net)

                # previous chronological fortnight = next index in newest-first list
                prev_d = filtered_dates[i+1] if i < len(filtered_dates)-1 else None
                if prev_d is not None and net is not None:
                    df_prev    = all_periods[prev_d]
                    prev_match = df_prev[df_prev["nsdl_sector"] == sec]
                    prev_net   = prev_match.iloc[0]["net_curr_eq"] if not prev_match.empty else None
                    if prev_net is not None and prev_net != 0:
                        pct = ((net - prev_net) / abs(prev_net)) * 100
                    else:
                        pct = None
                else:
                    pct = None
                pct_vals.append(pct)

            table_data[f"₹ {lbl}"]  = net_vals
            table_data[f"% {lbl}"]  = pct_vals

        hist_table = pd.DataFrame(table_data).set_index("Sector")

        # Style: red/green for net & %
        net_cols = [c for c in hist_table.columns if c.startswith("₹")]
        pct_cols = [c for c in hist_table.columns if c.startswith("%")]

        def color_n(v):
            if not isinstance(v,(int,float)) or pd.isna(v): return ""
            return "color:#00C853;font-weight:600" if v > 0 else "color:#D50000;font-weight:600"

        fmt_dict = {}
        for c in net_cols:
            fmt_dict[c] = lambda x: f"₹{x:+,.0f}" if isinstance(x,(int,float)) and not pd.isna(x) else "–"
        for c in pct_cols:
            fmt_dict[c] = lambda x: f"{x:+.1f}%" if isinstance(x,(int,float)) and not pd.isna(x) else "–"

        styled_hist = hist_table.style.map(color_n, subset=net_cols + pct_cols).format(fmt_dict)
        st.dataframe(styled_hist, use_container_width=True, height=max(380, len(all_sector_names)*28+40))

        # Summary: which sectors consistently bought in range
        st.markdown("---")
        st.subheader("Consistent FII Buying / Selling in Selected Range")
        net_sub = hist_table[net_cols]
        buy_counts  = (net_sub > 0).sum(axis=1).sort_values(ascending=False)
        sell_counts = (net_sub < 0).sum(axis=1).sort_values(ascending=False)
        total_flow  = net_sub.sum(axis=1).sort_values(ascending=False)

        sc1, sc2, sc3 = st.columns(3)
        sc1.markdown("**Most Fortnights Buying**")
        sc1.dataframe(buy_counts.rename("Buy periods").reset_index().rename(columns={"index":"Sector"}),
                       hide_index=True, use_container_width=True)
        sc2.markdown("**Most Fortnights Selling**")
        sc2.dataframe(sell_counts.rename("Sell periods").reset_index().rename(columns={"index":"Sector"}),
                       hide_index=True, use_container_width=True)
        sc3.markdown("**Cumulative Flow in Range (₹ Cr)**")
        sc3.dataframe(
            total_flow.rename("Total ₹ Cr").reset_index().rename(columns={"index":"Sector"})
            .style.map(color_n, subset=["Total ₹ Cr"])
            .format({"Total ₹ Cr": lambda x: f"₹{x:+,.0f}" if isinstance(x,(int,float)) else "–"}),
            hide_index=True, use_container_width=True
        )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Sector trend line chart
# ══════════════════════════════════════════════════════════════════════════════
with tab_trend:
    st.subheader("Sector FII Flow Trend — Fortnight by Fortnight")

    selected_sectors = st.multiselect(
        "Select sectors to compare (up to 8):",
        all_sector_names,
        default=all_sector_names[:5],
        max_selections=8,
    )

    view = st.radio("Show:", ["₹ Crore (net investment)", "% Change vs Prior Fortnight"],
                     horizontal=True)

    if selected_sectors:
        date_labels_asc = [d.strftime("%d %b %y") for d in sorted(all_periods.keys())]
        dates_asc       = sorted(all_periods.keys())

        fig_trend = go.Figure()
        palette = ["#2979FF","#00C853","#FF6D00","#AB47BC","#FFD600","#00BCD4","#F44336","#64DD17"]

        for i, sec in enumerate(selected_sectors):
            y_vals = []
            for j, d in enumerate(dates_asc):
                df_p  = all_periods[d]
                match = df_p[df_p["nsdl_sector"] == sec]
                net   = match.iloc[0]["net_curr_eq"] if not match.empty else None

                if view.startswith("%") and j > 0:
                    prev_d = dates_asc[j-1]
                    pm     = all_periods[prev_d][all_periods[prev_d]["nsdl_sector"] == sec]
                    prev_n = pm.iloc[0]["net_curr_eq"] if not pm.empty else None
                    if net is not None and prev_n is not None and prev_n != 0:
                        y_vals.append(((net - prev_n) / abs(prev_n)) * 100)
                    else:
                        y_vals.append(None)
                else:
                    y_vals.append(net)

            xs = date_labels_asc if not view.startswith("%") else date_labels_asc[1:]
            ys = y_vals          if not view.startswith("%") else y_vals[1:]

            fig_trend.add_trace(go.Scatter(
                x=xs, y=ys,
                name=sec[:28], mode="lines+markers",
                line=dict(color=palette[i % len(palette)], width=2),
                marker=dict(size=7),
                connectgaps=False,
            ))

        fig_trend.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.25)", line_width=1)
        fig_trend.update_layout(
            template="plotly_dark", height=460,
            title=f"FII Equity Net Investment — {'% change' if view.startswith('%') else '₹ Crore'}",
            yaxis_title="% Change" if view.startswith("%") else "₹ Crore",
            margin=dict(t=50, b=70, l=10, r=10),
            legend=dict(orientation="h", y=-0.25),
            hovermode="x unified",
        )
        st.plotly_chart(fig_trend, use_container_width=True)

    st.caption(f"{len(all_periods)} fortnights loaded. Refresh to add the latest fortnight when NSDL publishes it.")

# ── Drill-down ────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("Drill Down into a Sector")

sector_options = curr_df["nsdl_sector"].tolist()  # already sorted by net_curr_eq desc
selected = st.selectbox(
    "Choose sector (pre-selected = top FII buying this fortnight):",
    sector_options, index=0,
)
if selected:
    matched   = curr_df[curr_df["nsdl_sector"] == selected].iloc[0]
    internal  = matched["sector"]
    net_curr  = matched["net_curr_eq"]
    sig_label = SIGNAL_COLOR.get(matched["signal"], ("#888","–"))[1]
    color     = SIGNAL_COLOR.get(matched["signal"], ("#888","–"))[0]

    st.markdown(
        f"<div style='background:{color}22;border-left:4px solid {color};"
        f"padding:10px 16px;border-radius:6px'>"
        f"<b>{selected}</b> — FII is <b>{sig_label}</b> ₹{net_curr:+,.0f} Cr this fortnight.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("")

    c1, c2 = st.columns(2)
    if c1.button("📈 Analyse sector price trend", use_container_width=True, type="primary"):
        st.session_state["selected_sector"]          = internal
        st.session_state["selected_sector_nsdl"]     = selected
        st.session_state["selected_sector_net_curr"] = net_curr
        st.switch_page("pages/1_📈_Sector_Analysis.py")
    if c2.button("🔍 Find stocks to buy in this sector", use_container_width=True):
        st.session_state["selected_sector"]          = internal
        st.session_state["selected_sector_nsdl"]     = selected
        st.session_state["selected_sector_net_curr"] = net_curr
        st.switch_page("pages/2_🎯_Stock_Picker.py")
