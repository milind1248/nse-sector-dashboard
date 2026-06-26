"""
FPI Sectors — Full analysis inspired by fpidata.in
Tabs: Overview | Sector Trend | Cumulative Flow Tracker | Heat Map | AUC Holdings
"""
import sys
import calendar
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date

st.set_page_config(page_title="FPI Sector Investment Tracker | First Half Second Half | NSE Sector Analysis", layout="wide")
from app.utils.seo import inject_seo
inject_seo("FPI_Sectors")


# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def load_data():
    from backend.data_ingestion.nsdl_fetcher import fetch_nsdl_fii_sectors
    return fetch_nsdl_fii_sectors()

all_periods = load_data()   # served from Streamlit cache; no spinner needed

if not all_periods:
    st.error("No data. Go to Home and click Refresh.")
    st.stop()

sorted_dates = sorted(all_periods.keys(), reverse=True)  # newest first
latest_date  = sorted_dates[0]
latest_df    = all_periods[latest_date]
all_sectors  = sorted({s for df in all_periods.values() for s in df["nsdl_sector"]})
date_labels  = [d.strftime("%d %b %Y") for d in sorted_dates]

# ── Helpers ───────────────────────────────────────────────────────────────────
def _cn(v):
    if not isinstance(v, (int, float)) or pd.isna(v): return ""
    return "color:#00C853;font-weight:600" if v > 0 else "color:#D50000;font-weight:600"

def _fmt_cr(v):
    return f"₹{v:+,.0f}" if isinstance(v, (int, float)) else "–"

def _is_first_half(d: date) -> bool:
    """15th of month = first half (1st–15th)."""
    return d.day == 15

def _is_second_half(d: date) -> bool:
    """Last day of month = second half (16th–EOM)."""
    return d.day == calendar.monthrange(d.year, d.month)[1]

def _filter_by_half(dates, half):
    if half == "First Half (1–15)":
        return [d for d in dates if _is_first_half(d)]
    if half == "Second Half (16–EOM)":
        return [d for d in dates if _is_second_half(d)]
    return dates  # Combined

def _cum_for_dates(dates):
    """Cumulative net_curr_eq per sector over a list of dates."""
    cum = {}
    for d in dates:
        if d not in all_periods: continue
        for _, row in all_periods[d].iterrows():
            s = row["nsdl_sector"]
            cum[s] = cum.get(s, 0) + (row["net_curr_eq"] or 0)
    return cum

def _top_n_table(cum_dict, n=5):
    df = pd.DataFrame(list(cum_dict.items()), columns=["Sector", "₹ Crore"])
    df = df.sort_values("₹ Crore", ascending=False).reset_index(drop=True)
    buyers  = df[df["₹ Crore"] > 0].head(n)
    sellers = df[df["₹ Crore"] < 0].sort_values("₹ Crore").head(n)
    return buyers, sellers

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🌏 FPI Sector Investment Tracker")
st.caption(
    f"Foreign Portfolio Investment · Equity only · ₹ Crore · "
    f"Updated fortnightly · Latest: **{latest_date.strftime('%d %b %Y')}** · "
    f"{len(sorted_dates)} reports loaded"
)

# ── Top KPIs (always latest fortnight) ───────────────────────────────────────
total_net  = latest_df["net_curr_eq"].sum()
buyers     = int((latest_df["net_curr_eq"] > 0).sum())
sellers    = int((latest_df["net_curr_eq"] < 0).sum())
top_buy    = latest_df.loc[latest_df["net_curr_eq"].idxmax()]
top_sell   = latest_df.loc[latest_df["net_curr_eq"].idxmin()]
total_auc  = latest_df["auc_curr_eq"].sum() if "auc_curr_eq" in latest_df.columns else 0

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Total Net Flow", f"₹{total_net:+,.0f} Cr",
          "Inflow" if total_net > 0 else "Outflow",
          delta_color="normal" if total_net > 0 else "inverse")
k2.metric("Buying Sectors",  f"{buyers}",  f"of {buyers+sellers}")
k3.metric("Selling Sectors", f"{sellers}", "")
k4.metric("Top Buyer",  top_buy["nsdl_sector"][:20],  f"₹{top_buy['net_curr_eq']:+,.0f} Cr")
k5.metric("Top Seller", top_sell["nsdl_sector"][:20], f"₹{top_sell['net_curr_eq']:+,.0f} Cr")
k6.metric("Total AUC",  f"₹{total_auc/100000:.1f}L Cr" if total_auc else "–", "Holdings")

st.markdown("---")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_ov, tab_net, tab_trend, tab_cum, tab_hm, tab_auc = st.tabs([
    "📊 Overview",
    "📉 Net Investment Trend",
    "📈 Sector Trend",
    "🔢 Cumulative Flow Tracker",
    "🟥 Heat Map",
    "🏦 AUC Holdings",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Overview (Sector Explorer — like fpidata.in)
# ══════════════════════════════════════════════════════════════════════════════
with tab_ov:
    st.subheader("Sector Explorer")

    # ── Step 1: pick half → this filters which dates appear in dropdowns ───────
    half_sel = st.radio(
        "Fortnight half:",
        ["Combined", "First Half (1–15)", "Second Half (16–EOM)"],
        index=0, horizontal=True, key="ov_half",
        help="First Half = 15th reports | Second Half = month-end reports | Combined = all",
    )

    # Build date pool based on half selection (all available dates, newest first)
    pool = _filter_by_half(sorted_dates, half_sel)  # newest first
    pool_labels = [d.strftime("%d %b %Y") for d in pool]

    if not pool:
        st.warning("No data for selected half. Try 'Combined'.")
    else:
        # ── Step 2: To / From date dropdowns (filtered by half) ────────────────
        dc1, dc2 = st.columns(2)
        to_lbl_ov   = dc1.selectbox("To date (latest):",  pool_labels, index=0,           key="ov_to")
        from_lbl_ov = dc2.selectbox("From date (older):", pool_labels,
                                     index=min(11, len(pool_labels) - 1), key="ov_from")

        to_date_ov   = pool[pool_labels.index(to_lbl_ov)]
        from_date_ov = pool[pool_labels.index(from_lbl_ov)]
        if from_date_ov > to_date_ov:
            from_date_ov, to_date_ov = to_date_ov, from_date_ov
            from_lbl_ov, to_lbl_ov   = to_lbl_ov, from_lbl_ov

        sel_dates = [d for d in pool if from_date_ov <= d <= to_date_ov]

        n_f = len(sel_dates)
        half_tag = {"Combined": "", "First Half (1–15)": " · First Half", "Second Half (16–EOM)": " · Second Half"}[half_sel]
        st.caption(f"**{n_f} fortnights** · {from_lbl_ov} → {to_lbl_ov}{half_tag}")

        if n_f == 1:
            # Single fortnight — show individual bar (not cumulative)
            df_show = all_periods[sel_dates[0]].sort_values("net_curr_eq", ascending=True)
            colors  = ["#00C853" if v >= 0 else "#D50000" for v in df_show["net_curr_eq"]]
            fig = go.Figure(go.Bar(
                x=df_show["net_curr_eq"], y=df_show["nsdl_sector"],
                orientation="h", marker_color=colors,
                text=[f"₹{v:+,.0f}" for v in df_show["net_curr_eq"]],
                textposition="outside",
            ))
            fig.update_layout(
                template="plotly_dark", height=600,
                title=f"FPI Net Investment — {sel_dates[0].strftime('%d %b %Y')} (₹ Crore)",
                xaxis_title="₹ Crore", margin=dict(l=240, r=140, t=50, b=20),
                xaxis_zeroline=True, xaxis_zerolinecolor="rgba(255,255,255,0.3)",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            # Multi-period cumulative
            cum = _cum_for_dates(sel_dates)
            cum_df = pd.DataFrame(list(cum.items()), columns=["Sector", "Cumulative ₹ Cr"])
            cum_df = cum_df.sort_values("Cumulative ₹ Cr", ascending=True)
            colors = ["#00C853" if v >= 0 else "#D50000" for v in cum_df["Cumulative ₹ Cr"]]
            fig = go.Figure(go.Bar(
                x=cum_df["Cumulative ₹ Cr"], y=cum_df["Sector"],
                orientation="h", marker_color=colors,
                text=[f"₹{v:+,.0f}" for v in cum_df["Cumulative ₹ Cr"]],
                textposition="outside",
            ))
            fig.update_layout(
                template="plotly_dark", height=600,
                title=f"Cumulative FPI Investment — {from_lbl_ov} to {to_lbl_ov}{half_tag} ({n_f} fortnights)",
                xaxis_title="₹ Crore", margin=dict(l=240, r=140, t=50, b=20),
            )
            st.plotly_chart(fig, use_container_width=True)

        # ── Top Buyers / Sellers cards ─────────────────────────────────────────
        st.markdown("---")
        cum_all = _cum_for_dates(sel_dates)
        buyers_df, sellers_df = _top_n_table(cum_all, n=5)

        bc1, bc2 = st.columns(2)
        with bc1:
            st.markdown("### 🟢 Top Buyers")
            for _, row in buyers_df.iterrows():
                st.markdown(
                    f"<div style='background:#00C85315;border-left:4px solid #00C853;"
                    f"padding:8px 14px;border-radius:5px;margin-bottom:6px'>"
                    f"<b>{row['Sector']}</b> &nbsp;"
                    f"<span style='color:#00C853;font-size:1.1em'>₹{row['₹ Crore']:+,.0f} Cr</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        with bc2:
            st.markdown("### 🔴 Top Sellers")
            for _, row in sellers_df.iterrows():
                st.markdown(
                    f"<div style='background:#D5000015;border-left:4px solid #D50000;"
                    f"padding:8px 14px;border-radius:5px;margin-bottom:6px'>"
                    f"<b>{row['Sector']}</b> &nbsp;"
                    f"<span style='color:#D50000;font-size:1.1em'>₹{row['₹ Crore']:+,.0f} Cr</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        # ── Sector detail table ────────────────────────────────────────────────
        st.markdown("---")
        st.subheader(f"All Sectors — Detail Table ({latest_date.strftime('%d %b %Y')})")
        prev_date_v = sorted_dates[1] if len(sorted_dates) > 1 else None
        prev_df_v   = all_periods[prev_date_v] if prev_date_v else None

        rows = []
        for _, r in latest_df.sort_values("net_curr_eq", ascending=False).iterrows():
            prev_net = None
            if prev_df_v is not None:
                m = prev_df_v[prev_df_v["nsdl_sector"] == r["nsdl_sector"]]
                if not m.empty:
                    prev_net = m.iloc[0]["net_curr_eq"]
            chg = r["net_curr_eq"] - prev_net if prev_net is not None else None
            pct = (chg / abs(prev_net) * 100) if chg is not None and prev_net and prev_net != 0 else None
            rows.append({
                "Sector":             r["nsdl_sector"],
                "Net This (₹ Cr)":    r["net_curr_eq"],
                "Net Prev (₹ Cr)":    prev_net,
                "Change (₹ Cr)":      chg,
                "Change %":           pct,
                "AUC (₹ Cr)":         r.get("auc_curr_eq"),
                "AUC Chg %":          r.get("auc_pct_change"),
                "Signal":             r["signal"].replace("_", " ").title() if r.get("signal") else "–",
            })
        tbl = pd.DataFrame(rows)
        st.dataframe(
            tbl.style
               .map(_cn, subset=["Net This (₹ Cr)", "Net Prev (₹ Cr)", "Change (₹ Cr)", "Change %", "AUC Chg %"])
               .format({
                   "Net This (₹ Cr)": _fmt_cr, "Net Prev (₹ Cr)": _fmt_cr,
                   "Change (₹ Cr)":   _fmt_cr,
                   "Change %":    lambda x: f"{x:+.1f}%" if isinstance(x, (int, float)) else "–",
                   "AUC (₹ Cr)":  lambda x: f"₹{x:,.0f}" if isinstance(x, (int, float)) else "–",
                   "AUC Chg %":   lambda x: f"{x:+.2f}%" if isinstance(x, (int, float)) else "–",
               }),
            use_container_width=True, hide_index=True, height=500,
        )


# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Fortnightly Net Investment Trend  (fpidata.in style)
# ══════════════════════════════════════════════════════════════════════════════
with tab_net:
    st.subheader("Fortnightly Net Investment Trend ( Equity Only )")
    st.caption("Bars = net FII equity investment per fortnight · Line = cumulative total")

    # ── Sector chip selector ──────────────────────────────────────────────────
    sector_list = sorted(all_sectors)
    if "net_sector" not in st.session_state:
        st.session_state["net_sector"] = sector_list[0]

    # Render chips as inline buttons
    chip_cols = st.columns(min(len(sector_list), 6))
    per_row   = 6
    rows_needed = (len(sector_list) + per_row - 1) // per_row
    for r in range(rows_needed):
        cols = st.columns(per_row)
        for c in range(per_row):
            idx = r * per_row + c
            if idx >= len(sector_list):
                break
            sec = sector_list[idx]
            active = sec == st.session_state["net_sector"]
            label  = sec[:28]
            if cols[c].button(
                label,
                key=f"chip_{idx}",
                type="primary" if active else "secondary",
                use_container_width=True,
            ):
                st.session_state["net_sector"] = sec
                st.rerun()

    selected_sec = st.session_state["net_sector"]

    # ── Time range selector ───────────────────────────────────────────────────
    range_map = {"6M": 12, "1Y": 24, "1.5Y": 36, "2Y": 48, "All": len(sorted_dates)}
    tr1, tr2, tr3, tr4, tr5, _ = st.columns([1, 1, 1, 1, 1, 6])
    if "net_range" not in st.session_state:
        st.session_state["net_range"] = "1Y"

    for lbl, col in zip(range_map, [tr1, tr2, tr3, tr4, tr5]):
        active_r = lbl == st.session_state["net_range"]
        if col.button(lbl, key=f"rng_{lbl}", type="primary" if active_r else "secondary"):
            st.session_state["net_range"] = lbl
            st.rerun()

    n_periods_net = min(range_map[st.session_state["net_range"]], len(sorted_dates))
    net_dates     = sorted(sorted_dates[:n_periods_net])   # ascending for chart

    # ── Build series ──────────────────────────────────────────────────────────
    bar_vals, cum_vals, x_labels = [], [], []
    cum = 0.0
    for d in net_dates:
        df_d = all_periods.get(d)
        if df_d is None:
            continue
        m = df_d[df_d["nsdl_sector"] == selected_sec]
        net = float(m.iloc[0]["net_curr_eq"]) if not m.empty else 0.0
        cum += net
        bar_vals.append(net)
        cum_vals.append(cum)
        x_labels.append(d.strftime("%d %b %Y"))

    if not bar_vals:
        st.warning(f"No data for '{selected_sec}'.")
    else:
        bar_colors = ["#00C853" if v >= 0 else "#D50000" for v in bar_vals]

        fig_net = go.Figure()

        # Bars — fortnightly net
        fig_net.add_trace(go.Bar(
            x=x_labels, y=bar_vals,
            name="Net Investment (₹ Cr)",
            marker_color=bar_colors,
            opacity=0.85,
            hovertemplate="<b>%{x}</b><br>Net: ₹ %{y:+,.0f} Cr<extra></extra>",
        ))

        # Line — cumulative
        fig_net.add_trace(go.Scatter(
            x=x_labels, y=cum_vals,
            name="Cumulative (₹ Cr)",
            mode="lines+markers",
            line=dict(color="#00E5FF", width=2.5),
            marker=dict(size=6, color="#00E5FF",
                        line=dict(color="#ffffff", width=1)),
            yaxis="y2",
            hovertemplate="<b>%{x}</b><br>Cumulative: ₹ %{y:+,.0f} Cr<extra></extra>",
        ))

        fig_net.add_hline(y=0, line_dash="dot",
                          line_color="rgba(255,255,255,0.15)", line_width=1)

        fig_net.update_layout(
            template="plotly_dark",
            height=480,
            title=dict(
                text=f"{selected_sec} &nbsp;·&nbsp; {len(x_labels)} fortnightly data points",
                font=dict(size=13), x=0,
            ),
            margin=dict(t=50, b=60, l=10, r=10),
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.18, x=0),
            yaxis=dict(
                title="Net ₹ Cr (bars)",
                gridcolor="rgba(255,255,255,0.06)",
                zeroline=True, zerolinecolor="rgba(255,255,255,0.2)",
            ),
            yaxis2=dict(
                title="Cumulative ₹ Cr (line)",
                overlaying="y", side="right",
                gridcolor="rgba(0,0,0,0)",
                zeroline=False,
            ),
            bargap=0.25,
        )
        st.plotly_chart(fig_net, use_container_width=True)

        # ── Quick stats below chart ───────────────────────────────────────────
        total_in  = sum(v for v in bar_vals if v > 0)
        total_out = sum(v for v in bar_vals if v < 0)
        buy_f     = sum(1 for v in bar_vals if v > 0)
        sell_f    = sum(1 for v in bar_vals if v < 0)
        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("Cumulative Net",   f"₹{cum_vals[-1]:+,.0f} Cr")
        s2.metric("Total Inflow",     f"₹{total_in:,.0f} Cr")
        s3.metric("Total Outflow",    f"₹{total_out:,.0f} Cr")
        s4.metric("Buy Fortnights",   f"{buy_f} / {len(bar_vals)}")
        s5.metric("Sell Fortnights",  f"{sell_f} / {len(bar_vals)}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Sector Trend
# ══════════════════════════════════════════════════════════════════════════════
with tab_trend:
    st.subheader("Sector Trend — Fortnight by Fortnight")

    col_l, col_m, col_r = st.columns([3, 1, 1])
    sel_sectors = col_l.multiselect(
        "Select sectors (up to 6):", all_sectors,
        default=all_sectors[:4], max_selections=6, key="tr_secs"
    )
    range_opts = {"6 Months": 12, "1 Year": 24, "1.5 Years": 36, "2 Years": 48, "All": len(sorted_dates)}
    range_sel  = col_m.radio("Time range:", list(range_opts.keys()), index=1, key="tr_range")
    half_tr    = col_r.radio("Half:", ["Combined", "First Half", "Second Half"], index=0, key="tr_half")

    n_dates     = min(range_opts[range_sel], len(sorted_dates))
    base_dates  = sorted_dates[:n_dates]
    if half_tr == "First Half":
        chart_dates = sorted([d for d in base_dates if _is_first_half(d)])
    elif half_tr == "Second Half":
        chart_dates = sorted([d for d in base_dates if _is_second_half(d)])
    else:
        chart_dates = sorted(base_dates)

    metric_sel = st.radio(
        "Metric:", ["₹ Crore (net)", "% Change vs Prior Fortnight", "Cumulative ₹ Crore"],
        horizontal=True, key="tr_metric"
    )

    if sel_sectors and chart_dates:
        fig = go.Figure()
        colors_p = ["#2979FF", "#00C853", "#FF6D00", "#FFD600", "#AB47BC", "#00BCD4"]

        for i, sec in enumerate(sel_sectors):
            vals = []
            cum  = 0.0
            for j, d in enumerate(chart_dates):
                m   = all_periods[d][all_periods[d]["nsdl_sector"] == sec]
                net = m.iloc[0]["net_curr_eq"] if not m.empty else None

                if metric_sel == "₹ Crore (net)":
                    vals.append(net)
                elif metric_sel == "Cumulative ₹ Crore":
                    cum += (net or 0)
                    vals.append(cum)
                else:
                    if j > 0:
                        pd_ = chart_dates[j - 1]
                        pm  = all_periods[pd_][all_periods[pd_]["nsdl_sector"] == sec]
                        pn  = pm.iloc[0]["net_curr_eq"] if not pm.empty else None
                        vals.append((net - pn) / abs(pn) * 100 if net and pn and pn != 0 else None)
                    else:
                        vals.append(None)

            x_labels = [d.strftime("%d %b %y") for d in chart_dates]
            if metric_sel.startswith("%"):
                x_labels, vals = x_labels[1:], vals[1:]

            fig.add_trace(go.Scatter(
                x=x_labels, y=vals, name=sec[:25],
                mode="lines+markers",
                line=dict(color=colors_p[i % len(colors_p)], width=2.5),
                marker=dict(size=7), connectgaps=False,
            ))

        fig.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)", line_width=1)
        ytitle = {"₹ Crore (net)": "₹ Crore", "% Change vs Prior Fortnight": "% Change", "Cumulative ₹ Crore": "Cumulative ₹ Cr"}
        fig.update_layout(
            template="plotly_dark", height=480,
            yaxis_title=ytitle[metric_sel],
            margin=dict(t=30, b=80, l=10, r=10),
            legend=dict(orientation="h", y=-0.3),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Select at least one sector to plot.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Cumulative Flow Tracker
# ══════════════════════════════════════════════════════════════════════════════
with tab_cum:
    st.subheader("Cumulative Flow Tracker")
    st.caption("Identify consistent FII buyers and sellers over any date range.")

    # Quick range buttons + custom date range
    cr1, cr2, cr3 = st.columns([2, 2, 1])
    quick_opts = {"3 months": 6, "6 months": 12, "1 Year": 24, "2 Years": 48, "All time": len(sorted_dates)}
    quick_sel  = cr1.radio("Quick range:", list(quick_opts.keys()), index=1, horizontal=True, key="cum_quick")
    half_cum   = cr2.radio("Fortnight half:", ["Combined", "First Half (1–15)", "Second Half (16–EOM)"],
                            index=0, horizontal=True, key="cum_half")

    # Custom date override
    with st.expander("📅 Custom date range (overrides quick range above)"):
        cc1, cc2 = st.columns(2)
        to_sel_c   = cc1.selectbox("To (latest):",  date_labels, index=0, key="cum_to_c")
        from_sel_c = cc2.selectbox("From (older):", date_labels,
                                    index=min(11, len(date_labels)-1), key="cum_from_c")
        use_custom = st.checkbox("Use this custom range instead of quick range", value=False, key="cum_use_custom")

    if use_custom:
        fd = sorted_dates[date_labels.index(from_sel_c)]
        td = sorted_dates[date_labels.index(to_sel_c)]
        if fd > td: fd, td = td, fd
        base_dates_c = [d for d in sorted_dates if fd <= d <= td]
        range_label  = f"{td.strftime('%d %b %Y')} → {fd.strftime('%d %b %Y')}"
    else:
        n_q = min(quick_opts[quick_sel], len(sorted_dates))
        base_dates_c = sorted_dates[:n_q]
        range_label  = f"{base_dates_c[-1].strftime('%d %b %Y')} → {base_dates_c[0].strftime('%d %b %Y')}"

    rng_dates = _filter_by_half(base_dates_c, half_cum)
    half_lbl  = f" · {half_cum}" if half_cum != "Combined" else ""

    if not rng_dates:
        st.warning("No data for this combination.")
    else:
        cum = _cum_for_dates(rng_dates)
        cum_df3 = pd.DataFrame(list(cum.items()), columns=["Sector", "Cumulative ₹ Cr"])
        cum_df3 = cum_df3.sort_values("Cumulative ₹ Cr", ascending=False).reset_index(drop=True)
        cum_df3["Rank"] = range(1, len(cum_df3) + 1)

        # ── Top Buyers / Sellers cards ────────────────────────────────────────
        buyers_c, sellers_c = _top_n_table(cum, n=5)
        cb1, cb2 = st.columns(2)
        with cb1:
            st.markdown("### 🟢 Top Buyers")
            for _, row in buyers_c.iterrows():
                st.markdown(
                    f"<div style='background:#00C85318;border-left:4px solid #00C853;"
                    f"padding:8px 14px;border-radius:5px;margin-bottom:5px'>"
                    f"<b>{row['Sector']}</b> — "
                    f"<span style='color:#00C853'>₹{row['₹ Crore']:+,.0f} Cr</span></div>",
                    unsafe_allow_html=True,
                )
        with cb2:
            st.markdown("### 🔴 Top Sellers")
            for _, row in sellers_c.iterrows():
                st.markdown(
                    f"<div style='background:#D5000018;border-left:4px solid #D50000;"
                    f"padding:8px 14px;border-radius:5px;margin-bottom:5px'>"
                    f"<b>{row['Sector']}</b> — "
                    f"<span style='color:#D50000'>₹{row['₹ Crore']:+,.0f} Cr</span></div>",
                    unsafe_allow_html=True,
                )

        st.markdown("---")

        # Bar chart
        colors_c = ["#00C853" if v >= 0 else "#D50000" for v in cum_df3["Cumulative ₹ Cr"]]
        fig3 = go.Figure(go.Bar(
            x=cum_df3["Sector"], y=cum_df3["Cumulative ₹ Cr"],
            marker_color=colors_c,
            text=[f"₹{v:+,.0f}" for v in cum_df3["Cumulative ₹ Cr"]],
            textposition="outside",
        ))
        fig3.update_layout(
            template="plotly_dark", height=430,
            title=f"Cumulative FPI Flow: {range_label}{half_lbl} ({len(rng_dates)} fortnights)",
            yaxis_title="₹ Crore",
            margin=dict(t=50, b=150, l=10, r=10),
            xaxis_tickangle=-45,
        )
        fig3.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)")
        st.plotly_chart(fig3, use_container_width=True)

        # Full ranking table
        st.dataframe(
            cum_df3.style
                   .map(_cn, subset=["Cumulative ₹ Cr"])
                   .format({"Cumulative ₹ Cr": _fmt_cr}),
            use_container_width=True, hide_index=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Heat Map
# ══════════════════════════════════════════════════════════════════════════════
with tab_hm:
    st.subheader("FPI Flow Heat Map — Sectors × Fortnights")
    st.caption("Green = FII buying, Red = selling. Latest fortnight on left.")

    hc1, hc2 = st.columns([3, 1])
    range_hm = hc1.radio("Time range:", ["6 Months", "1 Year", "2 Years", "All"],
                          index=1, horizontal=True, key="hm_range")
    half_hm  = hc2.radio("Half:", ["Combined", "First Half", "Second Half"],
                          index=0, key="hm_half")

    n_hm = {"6 Months": 12, "1 Year": 24, "2 Years": 48, "All": len(sorted_dates)}[range_hm]
    base_hm = sorted_dates[:n_hm]
    if half_hm == "First Half":
        hm_dates = [d for d in base_hm if _is_first_half(d)]
    elif half_hm == "Second Half":
        hm_dates = [d for d in base_hm if _is_second_half(d)]
    else:
        hm_dates = base_hm   # newest first

    if not hm_dates:
        st.warning("No data for this combination.")
    else:
        x_labels = [d.strftime("%d %b %y") for d in hm_dates]  # newest on left
        z_vals   = []
        for sec in all_sectors:
            row_v = []
            for d in hm_dates:
                if d not in all_periods:
                    row_v.append(0)
                    continue
                m = all_periods[d][all_periods[d]["nsdl_sector"] == sec]
                row_v.append(m.iloc[0]["net_curr_eq"] if not m.empty else 0)
            z_vals.append(row_v)

        # Suppress text labels when many columns (too dense)
        show_text = len(hm_dates) <= 16

        fig4 = go.Figure(go.Heatmap(
            z=z_vals,
            x=x_labels,
            y=all_sectors,
            colorscale=[
                [0.0, "#7f0000"], [0.3, "#D50000"], [0.46, "#1a1d24"],
                [0.54, "#1a1d24"],
                [0.7, "#00C853"], [1.0, "#003300"],
            ],
            zmid=0,
            text=[[f"₹{v:+,.0f}" for v in row] for row in z_vals] if show_text else None,
            texttemplate="%{text}" if show_text else None,
            textfont={"size": 8},
            hoverongaps=False,
            hovertemplate="<b>%{y}</b><br>%{x}<br>₹%{z:+,.0f} Cr<extra></extra>",
            colorbar=dict(title=dict(text="₹ Cr", side="right"), thickness=12),
        ))
        fig4.update_layout(
            template="plotly_dark",
            height=max(500, len(all_sectors) * 24 + 120),
            margin=dict(t=50, b=60, l=220, r=80),
            xaxis=dict(tickangle=-40, tickfont=dict(size=9), side="top", title="← Latest"),
            yaxis=dict(tickfont=dict(size=9), autorange="reversed"),
        )
        st.plotly_chart(fig4, use_container_width=True)
        if not show_text:
            st.caption("💡 Values hidden for readability — hover on cells to see ₹ Cr values. Select '6 Months' range to see labels.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — AUC Holdings
# ══════════════════════════════════════════════════════════════════════════════
with tab_auc:
    st.subheader("Assets Under Custody (AUC) — Total FII Holdings by Sector")
    st.caption("AUC = total value of FII equity holdings in each sector at the end of the fortnight.")

    auc_df = latest_df[["nsdl_sector", "auc_prev_eq", "auc_curr_eq", "auc_change", "auc_pct_change"]].copy()
    auc_df.columns = ["Sector", "AUC Prev (₹ Cr)", "AUC Curr (₹ Cr)", "Change (₹ Cr)", "Change %"]
    auc_df = auc_df.sort_values("AUC Curr (₹ Cr)", ascending=False).reset_index(drop=True)

    # AUC bar chart
    fig_auc = go.Figure(go.Bar(
        x=auc_df["Sector"], y=auc_df["AUC Curr (₹ Cr)"],
        marker_color="#2979FF",
        text=[f"₹{v:,.0f}" for v in auc_df["AUC Curr (₹ Cr)"]],
        textposition="outside",
        name="AUC Current",
    ))
    fig_auc.add_trace(go.Bar(
        x=auc_df["Sector"], y=auc_df["AUC Prev (₹ Cr)"],
        marker_color="#FF6D00", opacity=0.5, name="AUC Previous",
    ))
    fig_auc.update_layout(
        barmode="group", template="plotly_dark", height=420,
        title=f"AUC by Sector — {latest_date.strftime('%d %b %Y')} vs Previous (₹ Crore)",
        margin=dict(t=50, b=150, l=10, r=10), xaxis_tickangle=-45,
    )
    st.plotly_chart(fig_auc, use_container_width=True)

    # Table
    st.dataframe(
        auc_df.style
              .map(_cn, subset=["Change (₹ Cr)", "Change %"])
              .format({
                  "AUC Prev (₹ Cr)": lambda x: f"₹{x:,.0f}" if isinstance(x, (int, float)) else "–",
                  "AUC Curr (₹ Cr)": lambda x: f"₹{x:,.0f}" if isinstance(x, (int, float)) else "–",
                  "Change (₹ Cr)":   lambda x: f"₹{x:+,.0f}" if isinstance(x, (int, float)) else "–",
                  "Change %":        lambda x: f"{x:+.2f}%" if isinstance(x, (int, float)) else "–",
              }),
        use_container_width=True, hide_index=True,
    )
