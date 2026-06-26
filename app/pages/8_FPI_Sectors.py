"""
FPI Sectors — Inspired by fpidata.in
Sector-wise FPI equity investment with trend, cumulative flow, and heatmap.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date, timedelta

st.set_page_config(page_title="FPI Sectors", layout="wide")

@st.cache_data(ttl=3600, show_spinner=False)
def load_data():
    from backend.data_ingestion.nsdl_fetcher import fetch_nsdl_fii_sectors
    return fetch_nsdl_fii_sectors()

with st.spinner("Loading FPI sector data..."):
    all_periods = load_data()

if not all_periods:
    st.error("No data. Go to Home and click Refresh.")
    st.stop()

sorted_dates = sorted(all_periods.keys(), reverse=True)  # newest first
latest_date  = sorted_dates[0]
latest_df    = all_periods[latest_date]

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🌏 FPI Sector Investment Tracker")
st.caption(f"Foreign Portfolio Investment · Equity only · ₹ Crore · Updated fortnightly · Latest: {latest_date.strftime('%d %b %Y')}")

# ── Top KPIs ─────────────────────────────────────────────────────────────────
total_net   = latest_df["net_curr_eq"].sum()
buyers      = int((latest_df["net_curr_eq"] > 0).sum())
sellers     = int((latest_df["net_curr_eq"] < 0).sum())
top_buy     = latest_df.loc[latest_df["net_curr_eq"].idxmax()]
top_sell    = latest_df.loc[latest_df["net_curr_eq"].idxmin()]
total_auc   = latest_df["auc_curr_eq"].sum()

k1,k2,k3,k4,k5 = st.columns(5)
k1.metric("Total Net Flow", f"₹{total_net:+,.0f} Cr",
           "Inflow" if total_net > 0 else "Outflow",
           delta_color="normal" if total_net > 0 else "inverse")
k2.metric("Buying Sectors",  f"{buyers}",  f"out of {buyers+sellers}")
k3.metric("Selling Sectors", f"{sellers}", "")
k4.metric("Top Buyer",  top_buy["nsdl_sector"][:18],  f"₹{top_buy['net_curr_eq']:+,.0f} Cr")
k5.metric("Top Seller", top_sell["nsdl_sector"][:18], f"₹{top_sell['net_curr_eq']:+,.0f} Cr")

st.markdown("---")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Sector Explorer",
    "📈 Trend Charts",
    "🔢 Cumulative Flow Tracker",
    "🟥 Heat Map",
])

PALETTE = ["#00C853","#64DD17","#FFD600","#FF6D00","#D50000",
           "#2979FF","#00BCD4","#AB47BC","#F06292","#8D6E63"]

# ════════════════════════════════════════════════════════════════════
# TAB 1 — Sector Explorer
# ════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Sector Explorer")

    # Period selector
    period_opts = {"Latest fortnight": 1, "3 months (6 fortnights)": 6,
                   "6 months": 12, "1 Year": 24, "2 Years": 48, "All time": len(sorted_dates)}
    period_sel  = st.radio("View period:", list(period_opts.keys()), index=0, horizontal=True)
    n_periods   = min(period_opts[period_sel], len(sorted_dates))
    sel_dates   = sorted_dates[:n_periods]

    if n_periods == 1:
        # Single fortnight: show buying vs selling bars
        df_show = latest_df.sort_values("net_curr_eq", ascending=True)
        colors  = ["#00C853" if v >= 0 else "#D50000" for v in df_show["net_curr_eq"]]
        fig = go.Figure(go.Bar(
            x=df_show["net_curr_eq"],
            y=df_show["nsdl_sector"],
            orientation="h",
            marker_color=colors,
            text=[f"₹{v:+,.0f}" for v in df_show["net_curr_eq"]],
            textposition="outside",
        ))
        fig.update_layout(
            template="plotly_dark", height=580,
            title=f"FPI Net Investment by Sector — {latest_date.strftime('%d %b %Y')} (₹ Crore)",
            xaxis_title="₹ Crore", margin=dict(l=230, r=130, t=50, b=20),
            xaxis_zeroline=True, xaxis_zerolinecolor="rgba(255,255,255,0.3)",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        # Multi-period: cumulative bar for the period
        cum_data = {}
        for d in sel_dates:
            df_p = all_periods[d]
            for _, row in df_p.iterrows():
                sec = row["nsdl_sector"]
                cum_data[sec] = cum_data.get(sec, 0) + (row["net_curr_eq"] or 0)

        cum_df = pd.DataFrame(list(cum_data.items()), columns=["Sector","Cumulative ₹ Cr"])
        cum_df = cum_df.sort_values("Cumulative ₹ Cr", ascending=True)
        colors = ["#00C853" if v >= 0 else "#D50000" for v in cum_df["Cumulative ₹ Cr"]]

        fig = go.Figure(go.Bar(
            x=cum_df["Cumulative ₹ Cr"],
            y=cum_df["Sector"],
            orientation="h",
            marker_color=colors,
            text=[f"₹{v:+,.0f}" for v in cum_df["Cumulative ₹ Cr"]],
            textposition="outside",
        ))
        lbl = f"{sel_dates[-1].strftime('%d %b %y')} → {sel_dates[0].strftime('%d %b %y')}"
        fig.update_layout(
            template="plotly_dark", height=580,
            title=f"Cumulative FPI Net Investment — {lbl} (₹ Crore)",
            xaxis_title="₹ Crore", margin=dict(l=230, r=130, t=50, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Sector table
    st.subheader(f"Sector Detail — {latest_date.strftime('%d %b %Y')}")
    prev_date = sorted_dates[1] if len(sorted_dates) > 1 else None
    prev_df   = all_periods[prev_date] if prev_date else None

    rows = []
    for _, r in latest_df.sort_values("net_curr_eq", ascending=False).iterrows():
        prev_net = None
        if prev_df is not None:
            m = prev_df[prev_df["nsdl_sector"] == r["nsdl_sector"]]
            if not m.empty:
                prev_net = m.iloc[0]["net_curr_eq"]
        chg = r["net_curr_eq"] - prev_net if prev_net is not None else None
        pct = (chg / abs(prev_net) * 100) if chg is not None and prev_net and prev_net != 0 else None
        rows.append({
            "Sector":             r["nsdl_sector"],
            "Net This Fortnight": r["net_curr_eq"],
            "Net Prev Fortnight": prev_net,
            "Change (₹ Cr)":      chg,
            "Change %":           pct,
            "AUC (₹ Cr)":         r["auc_curr_eq"],
            "AUC Chg %":          r["auc_pct_change"],
            "Signal":             r["signal"].replace("_"," ").title() if r["signal"] else "–",
        })
    tbl = pd.DataFrame(rows)

    def _cn(v):
        if not isinstance(v,(int,float)) or pd.isna(v): return ""
        return "color:#00C853;font-weight:600" if v > 0 else "color:#D50000;font-weight:600"

    st.dataframe(
        tbl.style
        .map(_cn, subset=["Net This Fortnight","Net Prev Fortnight","Change (₹ Cr)","Change %","AUC Chg %"])
        .format({
            "Net This Fortnight": lambda x: f"₹{x:+,.0f}" if isinstance(x,(int,float)) else "–",
            "Net Prev Fortnight": lambda x: f"₹{x:+,.0f}" if isinstance(x,(int,float)) else "–",
            "Change (₹ Cr)":      lambda x: f"₹{x:+,.0f}" if isinstance(x,(int,float)) else "–",
            "Change %":           lambda x: f"{x:+.1f}%"  if isinstance(x,(int,float)) else "–",
            "AUC (₹ Cr)":         lambda x: f"₹{x:,.0f}"  if isinstance(x,(int,float)) else "–",
            "AUC Chg %":          lambda x: f"{x:+.2f}%"  if isinstance(x,(int,float)) else "–",
        }),
        use_container_width=True, hide_index=True, height=500,
    )


# ════════════════════════════════════════════════════════════════════
# TAB 2 — Trend Charts per sector
# ════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Sector Trend — Fortnight by Fortnight")

    all_sector_names = sorted({s for df in all_periods.values() for s in df["nsdl_sector"]})

    col_l, col_r = st.columns([2, 1])
    sel_sectors = col_l.multiselect(
        "Select sectors (up to 6):", all_sector_names,
        default=all_sector_names[:4], max_selections=6,
    )
    range_opts = {"6 Months": 12, "1 Year": 24, "1.5 Years": 36, "2 Years": 48, "All": len(sorted_dates)}
    range_sel  = col_r.radio("Time range:", list(range_opts.keys()), index=1, horizontal=False)
    n_dates    = min(range_opts[range_sel], len(sorted_dates))
    chart_dates = sorted(sorted_dates[:n_dates])   # ascending for x-axis

    metric_sel = st.radio("Metric:", ["₹ Crore (net)", "% Change vs Prior Fortnight", "Cumulative ₹ Crore"], horizontal=True)

    if sel_sectors:
        fig = go.Figure()
        colors_p = ["#2979FF","#00C853","#FF6D00","#FFD600","#AB47BC","#00BCD4"]

        for i, sec in enumerate(sel_sectors):
            vals = []
            cum  = 0.0
            for j, d in enumerate(chart_dates):
                m = all_periods[d][all_periods[d]["nsdl_sector"] == sec]
                net = m.iloc[0]["net_curr_eq"] if not m.empty else None

                if metric_sel == "₹ Crore (net)":
                    vals.append(net)
                elif metric_sel == "Cumulative ₹ Crore":
                    cum += (net or 0)
                    vals.append(cum)
                else:
                    if j > 0:
                        pd_ = chart_dates[j-1]
                        pm  = all_periods[pd_][all_periods[pd_]["nsdl_sector"] == sec]
                        pn  = pm.iloc[0]["net_curr_eq"] if not pm.empty else None
                        if net is not None and pn and pn != 0:
                            vals.append((net - pn) / abs(pn) * 100)
                        else:
                            vals.append(None)
                    else:
                        vals.append(None)

            x_labels = [d.strftime("%d %b %y") for d in chart_dates]
            if metric_sel.startswith("%"):
                x_labels = x_labels[1:]
                vals     = vals[1:]

            fig.add_trace(go.Scatter(
                x=x_labels, y=vals, name=sec[:25],
                mode="lines+markers",
                line=dict(color=colors_p[i % len(colors_p)], width=2.5),
                marker=dict(size=7),
                connectgaps=False,
            ))

        fig.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)", line_width=1)
        ytitle = {"₹ Crore (net)": "₹ Crore", "% Change vs Prior Fortnight": "% Change", "Cumulative ₹ Crore": "Cumulative ₹ Cr"}
        fig.update_layout(
            template="plotly_dark", height=460,
            yaxis_title=ytitle[metric_sel],
            margin=dict(t=30, b=80, l=10, r=10),
            legend=dict(orientation="h", y=-0.3),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Select at least one sector above.")


# ════════════════════════════════════════════════════════════════════
# TAB 3 — Cumulative Flow Tracker (range selector)
# ════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Cumulative Flow Tracker")
    st.caption("Select a date range to see total FII flow per sector. Identifies consistent buyers/sellers.")

    date_labels_all = [d.strftime("%d %b %Y") for d in sorted_dates]
    c1, c2 = st.columns(2)
    to_sel3   = c1.selectbox("To (latest):",   date_labels_all, index=0,                               key="cum_to")
    from_sel3 = c2.selectbox("From (older):",  date_labels_all, index=min(11, len(date_labels_all)-1), key="cum_from")

    fd = sorted_dates[date_labels_all.index(from_sel3)]
    td = sorted_dates[date_labels_all.index(to_sel3)]
    if fd > td:
        fd, td = td, fd
    rng_dates = [d for d in sorted_dates if fd <= d <= td]

    if rng_dates:
        # Cumulative per sector
        cum = {}
        periods_with_data = {}
        for d in rng_dates:
            for _, row in all_periods[d].iterrows():
                s = row["nsdl_sector"]
                cum[s] = cum.get(s, 0) + (row["net_curr_eq"] or 0)
                periods_with_data[s] = periods_with_data.get(s, 0) + 1

        cum_df3 = pd.DataFrame({
            "Sector":        list(cum.keys()),
            "Cumulative ₹ Cr": list(cum.values()),
            "Periods":       [periods_with_data[s] for s in cum.keys()],
        }).sort_values("Cumulative ₹ Cr", ascending=False).reset_index(drop=True)
        cum_df3["Rank"] = range(1, len(cum_df3)+1)

        # Bar chart
        colors_c = ["#00C853" if v >= 0 else "#D50000" for v in cum_df3["Cumulative ₹ Cr"]]
        fig3 = go.Figure(go.Bar(
            x=cum_df3["Sector"],
            y=cum_df3["Cumulative ₹ Cr"],
            marker_color=colors_c,
            text=[f"₹{v:+,.0f}" for v in cum_df3["Cumulative ₹ Cr"]],
            textposition="outside",
        ))
        fig3.update_layout(
            template="plotly_dark", height=420,
            title=f"Cumulative FPI Flow: {fd.strftime('%d %b %y')} → {td.strftime('%d %b %y')} ({len(rng_dates)} fortnights)",
            yaxis_title="₹ Crore", margin=dict(t=50, b=140, l=10, r=10),
            xaxis_tickangle=-45,
        )
        fig3.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)")
        st.plotly_chart(fig3, use_container_width=True)

        # Table
        def _cn2(v):
            if not isinstance(v,(int,float)) or pd.isna(v): return ""
            return "color:#00C853;font-weight:600" if v > 0 else "color:#D50000;font-weight:600"

        st.dataframe(
            cum_df3.style
            .map(_cn2, subset=["Cumulative ₹ Cr"])
            .format({"Cumulative ₹ Cr": lambda x: f"₹{x:+,.0f}"}),
            use_container_width=True, hide_index=True,
        )


# ════════════════════════════════════════════════════════════════════
# TAB 4 — Heat Map
# ════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("FPI Flow Heat Map — Sectors × Fortnights")
    st.caption("Green = FII buying, Red = selling. Darker = larger flow.")

    range_hm = st.radio("Show:", ["6 Months", "1 Year", "2 Years", "All"], index=1, horizontal=True)
    n_hm = {"6 Months": 12, "1 Year": 24, "2 Years": 48, "All": len(sorted_dates)}[range_hm]
    hm_dates = sorted_dates[:n_hm]   # newest first

    all_secs = sorted({s for df in all_periods.values() for s in df["nsdl_sector"]})
    z_vals, x_labels, y_labels = [], [d.strftime("%d %b %y") for d in hm_dates], all_secs

    for sec in all_secs:
        row_vals = []
        for d in hm_dates:
            m = all_periods[d][all_periods[d]["nsdl_sector"] == sec]
            row_vals.append(m.iloc[0]["net_curr_eq"] if not m.empty else 0)
        z_vals.append(row_vals)

    fig4 = go.Figure(go.Heatmap(
        z=z_vals,
        x=x_labels,
        y=y_labels,
        colorscale=[[0,"#B71C1C"],[0.4,"#D50000"],[0.48,"#1a1d24"],[0.52,"#1a1d24"],[0.6,"#00C853"],[1,"#00600F"]],
        zmid=0,
        text=[[f"₹{v:+,.0f}" for v in row] for row in z_vals],
        texttemplate="%{text}",
        textfont={"size": 9},
        hoverongaps=False,
        colorbar=dict(title="₹ Cr"),
    ))
    fig4.update_layout(
        template="plotly_dark",
        height=max(480, len(all_secs) * 22 + 80),
        margin=dict(t=30, b=80, l=200, r=20),
        xaxis_side="top",
    )
    st.plotly_chart(fig4, use_container_width=True)
