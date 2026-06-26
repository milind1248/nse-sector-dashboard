"""
FII Invest Sector — Full historical fortnightly matrix + FII-Price-Stock analysis.
Dates: 15th and last day of every month (matches NSDL publication schedule).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import timedelta

st.set_page_config(page_title="FII Historical Sector Investment | 5-Year Heatmap | NSE Sector Analysis", layout="wide")
from app.utils.seo import inject_seo
inject_seo("FII_Invest_Sector")

from app.utils.logo import show_logo
show_logo()

st.title("\U0001f4cb FII Invest Sector — Fortnightly History")
st.caption(
    "Sectors × Fortnightly dates × FII equity net investment (₹ Crore). "
    "NSDL publishes on the 15th and last day of every month."
)

# ── Load NSDL (all available fortnights) ─────────────────────────────────────
@st.cache_data(ttl=86400, show_spinner=False)  # NSDL never changes intraday
def load_all_periods():
    from backend.data_ingestion.nsdl_fetcher import fetch_nsdl_fii_sectors
    return fetch_nsdl_fii_sectors()

with st.status("📂 Loading FII sector history…", expanded=False) as _s7:
    st.write("Reading all fortnightly NSDL reports (May 2020 → today) from local database.")
    all_periods = load_all_periods()
    if all_periods:
        n_r7 = len(all_periods)
        ld7  = max(all_periods.keys())
        _s7.update(label=f"✅ {n_r7} fortnightly reports loaded · Latest: {ld7.strftime('%d %b %Y')}",
                   state="complete", expanded=False)
    else:
        _s7.update(label="❌ No data — go to Home and click Refresh", state="error")

if not all_periods:
    st.error("No NSDL data. Go to **Home** and click 🔄 **Refresh Latest Data**.")
    st.stop()

sorted_dates = sorted(all_periods.keys())          # oldest → newest (internal order)
date_labels  = [d.strftime("%d %b %Y") for d in sorted_dates]
# For UI display — newest first
sorted_dates_desc = sorted_dates[::-1]
date_labels_desc  = date_labels[::-1]
all_sectors  = sorted({s for df in all_periods.values() for s in df["nsdl_sector"]})

# ── Build master pivot (sectors × fortnights) ─────────────────────────────────
def build_pivot(periods_dict, dates, labels, sectors):
    rows = {}
    for sec in sectors:
        row = {}
        for d, lbl in zip(dates, labels):
            df_p  = periods_dict[d]
            match = df_p[df_p["nsdl_sector"] == sec]
            row[lbl] = float(match.iloc[0]["net_curr_eq"]) if not match.empty and match.iloc[0]["net_curr_eq"] is not None else None
        rows[sec] = row
    return pd.DataFrame(rows).T

pivot = build_pivot(all_periods, sorted_dates, date_labels, all_sectors)
pivot.index.name = "Sector"

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_matrix, tab_analysis = st.tabs([
    "📊 Sector × Fortnight Matrix",
    "🔬 FII→Price→Stock Analysis",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Full matrix
# ══════════════════════════════════════════════════════════════════════════════
with tab_matrix:
    # Sidebar-style filters inside expander
    with st.expander("⚙️ Filters", expanded=True):
        fc1, fc2, fc3 = st.columns(3)
        # Latest on left: "To" (newest) in left column, "From" (older) in right
        to_lbl   = fc1.selectbox("To fortnight (latest)",  date_labels_desc,
                                   index=0, key="m_to")
        from_lbl = fc2.selectbox("From fortnight (older)", date_labels_desc,
                                   index=min(7, len(date_labels_desc)-1), key="m_from")
        show_mode = fc3.radio("Values as", ["₹ Crore", "% change vs prior"], key="m_mode",
                               horizontal=True)
        fsec = st.multiselect("Filter sectors (blank = all)", all_sectors, key="m_fsec")

    from_idx = date_labels.index(from_lbl)
    to_idx   = date_labels.index(to_lbl)
    if from_idx > to_idx:
        from_idx, to_idx = to_idx, from_idx

    sel_labels = date_labels[from_idx : to_idx + 1]      # ascending (oldest→newest)
    sel_dates  = sorted_dates[from_idx : to_idx + 1]
    # Display order: newest first (latest on left)
    sel_labels_display = sel_labels[::-1]

    sub        = pivot[sel_labels].copy()
    sub_display = sub[sel_labels_display]                 # reversed for display
    if fsec:
        sub         = sub.loc[sub.index.isin(fsec)]
        sub_display = sub_display.loc[sub_display.index.isin(fsec)]

    # Summary row — based on latest (last in ascending = sel_labels[-1])
    latest_lbl = sel_labels[-1]
    latest = sub[latest_lbl].dropna()
    m1,m2,m3,m4 = st.columns(4)
    m1.metric(f"Total Flow ({latest_lbl})", f"₹{latest.sum():+,.0f} Cr")
    m2.metric("Buying sectors",  str(int((latest>0).sum())))
    m3.metric("Selling sectors", str(int((latest<0).sum())))
    m4.metric("Top buyer",       latest.idxmax()[:18] if not latest.empty else "–",
               f"₹{latest.max():+,.0f} Cr" if not latest.empty else "")

    st.markdown(f"**{len(sel_labels)} fortnights shown** ({to_lbl} → {from_lbl}) · {len(sub)} sectors  *(Latest on left)*")

    # Build display table (₹ Cr or % change) — using display order (newest-first cols)
    if show_mode.startswith("%") and len(sel_labels_display) > 1:
        def to_pct_row(row):
            out = {}
            for i, col in enumerate(sel_labels_display):
                # next item in display list is the OLDER fortnight (ascending order reversed)
                older_col = sel_labels_display[i+1] if i < len(sel_labels_display)-1 else None
                if older_col is None:
                    out[col] = None
                else:
                    curr_v, prev_v = row[col], row[older_col]
                    if curr_v is not None and prev_v is not None and prev_v != 0:
                        out[col] = ((curr_v - prev_v) / abs(prev_v)) * 100
                    else:
                        out[col] = None
            return pd.Series(out)
        disp = sub_display.apply(to_pct_row, axis=1)
        fmt_cell = lambda v: f"{v:+.1f}%" if isinstance(v,(int,float)) and not pd.isna(v) else "–"
        vmax = 200
    else:
        disp = sub_display.copy()
        fmt_cell = lambda v: f"₹{v:+,.0f}" if isinstance(v,(int,float)) and not pd.isna(v) else "–"
        flat = [v for r in disp.values.tolist() for v in r if v and not pd.isna(v)]
        vmax = max((abs(min(flat)), abs(max(flat))), default=1000) if flat else 1000

    # Heatmap — latest date on left (x-axis starts with newest)
    fig_hm = go.Figure(go.Heatmap(
        z=disp.values.tolist(),
        x=disp.columns.tolist(),
        y=disp.index.tolist(),
        colorscale=[
            [0.0,  "#7f0000"], [0.35, "#D50000"], [0.45, "#FF6D00"],
            [0.50, "#1a1a2e"],
            [0.55, "#64DD17"], [0.65, "#00C853"], [1.0,  "#003300"],
        ],
        zmin=-vmax, zmax=vmax,
        text=[[fmt_cell(v) for v in row] for row in disp.values.tolist()],
        texttemplate="%{text}",
        textfont=dict(size=9, color="white"),
        hovertemplate="<b>%{y}</b><br>%{x}<br>%{text}<extra></extra>",
        showscale=True,
        colorbar=dict(title=dict(text="₹Cr" if show_mode.startswith("₹") else "%", side="right")),
    ))
    fig_hm.update_layout(
        template="plotly_dark",
        height=max(420, len(disp) * 30 + 120),
        margin=dict(t=30, b=70, l=230, r=80),
        xaxis=dict(tickangle=-35, tickfont=dict(size=9), side="top"),
        yaxis=dict(tickfont=dict(size=9), autorange="reversed"),
    )
    st.plotly_chart(fig_hm, use_container_width=True)

    # Data table below heatmap — latest on left
    with st.expander("📋 View raw data table (latest on left)"):
        fmt_d = {c: fmt_cell for c in disp.columns}
        def cn(v):
            if not isinstance(v,(int,float)) or pd.isna(v): return ""
            return "color:#00C853;font-weight:600" if v>0 else "color:#D50000;font-weight:600"
        st.dataframe(disp.style.map(cn).format(fmt_d),
                     use_container_width=True,
                     height=min(600, len(disp)*32+60))

    # Cumulative summary — title shows latest → older
    st.markdown("---")
    st.subheader(f"Cumulative FII Flow in Range: {to_lbl} → {from_lbl}")
    cumul = sub.sum(axis=1).sort_values(ascending=False)
    colors_c = ["#00C853" if v >= 0 else "#D50000" for v in cumul.values]
    fig_c = go.Figure(go.Bar(
        x=cumul.values, y=cumul.index,
        orientation="h", marker_color=colors_c,
        text=[f"₹{v:+,.0f}" for v in cumul.values], textposition="outside",
    ))
    fig_c.update_layout(template="plotly_dark", height=max(350, len(cumul)*28+80),
                         margin=dict(t=20, b=20, l=230, r=120),
                         xaxis_title="₹ Crore (cumulative)")
    st.plotly_chart(fig_c, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — FII → Price → Stock Analysis
# "Did FII buying actually lead to sector price going up? Did stocks follow?"
# ══════════════════════════════════════════════════════════════════════════════
with tab_analysis:
    st.subheader("FII Buying → Sector Price → Stock Performance Analysis")
    st.markdown(
        "**Investor question:** When FII bought a sector in a fortnight, "
        "did the sector index actually go up? And did the stocks in that sector rise too? "
        "This table cross-references FII flow with price data."
    )

    @st.cache_data(ttl=86400, show_spinner=False)
    def load_sector_prices_analysis():
        from backend.data_ingestion.yfinance_fetcher import fetch_all_sector_prices, _get_close
        from config import SECTOR_STOCKS, SECTOR_INDICES
        import yfinance as yf
        return fetch_all_sector_prices(), SECTOR_STOCKS, SECTOR_INDICES

    # Lazy load — only fetch yfinance when user requests it (avoids 20+ API calls on every page open)
    if "price_analysis_loaded" not in st.session_state:
        st.info(
            "**📈 Price data not yet loaded.**\n\n"
            "This tab fetches 1-year price history for 20+ Nifty sector indices from Yahoo Finance. "
            "It takes **10–20 seconds** on first load, then is cached for 24 hours.\n\n"
            "Click below when you're ready."
        )
        if st.button("🚀 Load Price vs FII Analysis", type="primary"):
            st.session_state["price_analysis_loaded"] = True
            st.rerun()
        st.stop()

    with st.status("🌐 Fetching sector index prices from Yahoo Finance…", expanded=True) as _syf:
        st.write("Downloading 1-year OHLCV data for Nifty Bank, IT, Auto, Pharma and 17 more indices.")
        st.write("⏱️ First load: ~10–20 seconds. After that, served from cache for 24 hours.")
        sector_prices, SECTOR_STOCKS, SECTOR_INDICES = load_sector_prices_analysis()
        _syf.update(label="✅ Sector prices loaded · Source: Yahoo Finance",
                    state="complete", expanded=False)

    # Pick fortnight and look-back window
    ac1, ac2 = st.columns(2)
    sel_fn   = ac1.selectbox("Select fortnight to analyse:", date_labels[::-1], key="an_fn")
    fwd_days = ac2.select_slider(
        "Measure price change over:", [7, 15, 30, 45, 60],
        value=15, key="an_fwd",
        help="How many calendar days after the fortnight end to measure price change"
    )

    fn_idx  = date_labels.index(sel_fn)
    fn_date = sorted_dates[fn_idx]
    fn_df   = all_periods[fn_date]

    # Build analysis rows
    @st.cache_data(ttl=1800, show_spinner=False)
    def build_analysis(fn_date_str: str, fwd_days: int):
        from backend.data_ingestion.yfinance_fetcher import _get_close, fetch_sector_stocks
        from config import SECTOR_INDICES
        import yfinance as yf
        from datetime import date as date_cls

        fn_date_obj = date_cls.fromisoformat(fn_date_str)
        end_date    = fn_date_obj + timedelta(days=fwd_days)
        nsdl_df     = all_periods.get(fn_date_obj)
        if nsdl_df is None:
            return pd.DataFrame()

        rows = []
        for _, r in nsdl_df.iterrows():
            nsdl_sec  = r["nsdl_sector"]
            int_sec   = r["sector"]
            fii_net   = r["net_curr_eq"]
            fii_signal= r["signal"]

            # Sector index return over [fn_date → fn_date+fwd_days]
            sym = SECTOR_INDICES.get(int_sec)
            idx_ret = None
            if sym:
                try:
                    raw = yf.download(sym,
                                       start=str(fn_date_obj - timedelta(days=5)),
                                       end=str(end_date + timedelta(days=5)),
                                       progress=False, auto_adjust=True)
                    if not raw.empty:
                        cs = _get_close(raw)
                        if cs is not None and len(cs) >= 2:
                            # Find closest dates
                            idx_list = list(cs.index)
                            start_close = None
                            end_close   = None
                            for d in idx_list:
                                if d >= fn_date_obj and start_close is None:
                                    start_close = float(cs.loc[d])
                                if d >= end_date:
                                    end_close = float(cs.loc[d])
                                    break
                            if end_close is None:
                                end_close = float(cs.iloc[-1])
                            if start_close:
                                idx_ret = ((end_close - start_close) / start_close) * 100
                except Exception:
                    pass

            # Top 3 stocks return in same window
            top_stocks = []
            try:
                stock_prices = fetch_sector_stocks(int_sec)
                stock_rets = []
                for stk_sym, stk_df in stock_prices.items():
                    if stk_df is None or stk_df.empty:
                        continue
                    try:
                        raw2 = yf.download(stk_sym,
                                            start=str(fn_date_obj - timedelta(days=5)),
                                            end=str(end_date + timedelta(days=5)),
                                            progress=False, auto_adjust=True)
                        if raw2.empty:
                            continue
                        cs2 = _get_close(raw2)
                        if cs2 is None or len(cs2) < 2:
                            continue
                        idx2 = list(cs2.index)
                        sc2, ec2 = None, None
                        for d in idx2:
                            if d >= fn_date_obj and sc2 is None:
                                sc2 = float(cs2.loc[d])
                            if d >= end_date:
                                ec2 = float(cs2.loc[d])
                                break
                        if ec2 is None:
                            ec2 = float(cs2.iloc[-1])
                        if sc2 and sc2 > 0:
                            stock_rets.append((stk_sym.replace(".NS",""), ((ec2-sc2)/sc2)*100))
                    except Exception:
                        continue
                stock_rets.sort(key=lambda x: x[1], reverse=True)
                top_stocks = stock_rets[:3]
            except Exception:
                pass

            # Verdict
            if fii_net and fii_net > 0 and idx_ret and idx_ret > 0:
                verdict = "Confirmed"   # FII bought + index up
            elif fii_net and fii_net > 0 and idx_ret and idx_ret <= 0:
                verdict = "Diverged"    # FII bought but price fell
            elif fii_net and fii_net < 0 and idx_ret and idx_ret < 0:
                verdict = "Aligned-Sell"
            else:
                verdict = "Mixed"

            avg_stock_ret = sum(v for _, v in top_stocks)/len(top_stocks) if top_stocks else None

            rows.append({
                "Sector":             nsdl_sec,
                "FII Net (₹Cr)":      fii_net,
                "FII Signal":         fii_signal.replace("_"," ").title(),
                f"Index {fwd_days}d%": idx_ret,
                f"Avg Top3 Stk {fwd_days}d%": avg_stock_ret,
                "Top Stocks":         ", ".join(f"{s}({v:+.1f}%)" for s,v in top_stocks),
                "Verdict":            verdict,
            })

        return pd.DataFrame(rows).sort_values("FII Net (₹Cr)", ascending=False)

    with st.spinner(f"Analysing FII vs price for {sel_fn} (fetching {fwd_days}d price data)..."):
        an_df = build_analysis(fn_date.isoformat(), fwd_days)

    if an_df.empty:
        st.warning("No analysis data available for this fortnight.")
    else:
        # Summary verdicts
        confirmed   = (an_df["Verdict"] == "Confirmed").sum()
        diverged    = (an_df["Verdict"] == "Diverged").sum()
        aligned_sel = (an_df["Verdict"] == "Aligned-Sell").sum()
        mixed       = (an_df["Verdict"] == "Mixed").sum()

        v1,v2,v3,v4 = st.columns(4)
        v1.metric("FII Bought + Price Up", str(confirmed),
                   "Confirmed signal", delta_color="normal")
        v2.metric("FII Bought + Price Down", str(diverged),
                   "FII wrong / price lag", delta_color="inverse")
        v3.metric("FII Sold + Price Down", str(aligned_sel))
        v4.metric("Mixed / No data", str(mixed))

        # Verdict legend
        st.markdown("""
<small>
🟢 **Confirmed** = FII buying + index rose → strong signal to find stocks &nbsp;|&nbsp;
🔴 **Diverged** = FII bought but price fell → wait, could be accumulation or wrong call &nbsp;|&nbsp;
🟡 **Aligned-Sell** = FII sold + index fell → sector to avoid &nbsp;|&nbsp;
⚪ **Mixed** = insufficient price data
</small>
""", unsafe_allow_html=True)

        st.markdown("---")

        # Main analysis table
        idx_col  = f"Index {fwd_days}d%"
        stk_col  = f"Avg Top3 Stk {fwd_days}d%"

        def color_verdict(v):
            return {"Confirmed":"color:#00C853;font-weight:700",
                    "Diverged":"color:#FF6D00;font-weight:700",
                    "Aligned-Sell":"color:#D50000;font-weight:700",
                    "Mixed":"color:#888"}.get(v,"")
        def color_fii(v):
            if not isinstance(v,(int,float)): return ""
            return "color:#00C853;font-weight:600" if v>0 else "color:#D50000;font-weight:600"
        def color_ret(v):
            if not isinstance(v,(int,float)) or pd.isna(v): return ""
            return "color:#00C853" if v>0 else "color:#D50000"

        st.subheader(f"Sector Analysis — {sel_fn} · {fwd_days}-day price window")
        st.dataframe(
            an_df.style
                 .map(color_fii,     subset=["FII Net (₹Cr)"])
                 .map(color_ret,     subset=[idx_col, stk_col])
                 .map(color_verdict, subset=["Verdict"])
                 .format({
                     "FII Net (₹Cr)": lambda v: f"₹{v:+,.0f}" if isinstance(v,(int,float)) else "–",
                     idx_col:          lambda v: f"{v:+.2f}%" if isinstance(v,(int,float)) else "No data",
                     stk_col:          lambda v: f"{v:+.2f}%" if isinstance(v,(int,float)) else "–",
                 }),
            use_container_width=True, hide_index=True, height=540,
        )

        # Confirmed sectors — call to action
        st.markdown("---")
        confirmed_df = an_df[an_df["Verdict"] == "Confirmed"].sort_values("FII Net (₹Cr)", ascending=False)
        if not confirmed_df.empty:
            st.subheader("✅ Confirmed Sectors — FII Buying + Price Confirmed")
            st.caption("These are the highest-conviction sectors: FII bought AND index rose. Best candidates for stock picking.")
            for _, row in confirmed_df.iterrows():
                col1, col2, col3 = st.columns([2,1,1])
                sec_label = row["Sector"]
                col1.markdown(f"**{sec_label}**  \n{row['Top Stocks']}")
                col2.metric("FII Net", f"₹{row['FII Net (₹Cr)']:+,.0f} Cr")
                col3.metric(f"Index {fwd_days}d", f"{row[idx_col]:+.2f}%" if isinstance(row[idx_col],(int,float)) else "–")
                # Navigate button
                int_sec = fn_df[fn_df["nsdl_sector"]==sec_label]["sector"].values
                if len(int_sec):
                    if st.button(f"Find stocks in {sec_label[:20]} →", key=f"an_btn_{sec_label}"):
                        st.session_state["selected_sector"]          = int_sec[0]
                        st.session_state["selected_sector_nsdl"]     = sec_label
                        st.session_state["selected_sector_net_curr"] = row["FII Net (₹Cr)"]
                        st.switch_page("pages/2_🎯_Stock_Picker.py")
                st.markdown("---")
        else:
            st.info("No confirmed sectors in this fortnight / time window. Try a longer price window or a different fortnight.")

        # Scatter: FII flow vs index return
        st.subheader("Scatter: FII Net Flow vs Sector Index Return")
        plot_df = an_df.dropna(subset=[idx_col]).copy()
        if not plot_df.empty:
            fig_sc = go.Figure()
            colors_sc = ["#00C853" if v=="Confirmed" else "#FF6D00" if v=="Diverged"
                          else "#D50000" if v=="Aligned-Sell" else "#888"
                          for v in plot_df["Verdict"]]
            fig_sc.add_trace(go.Scatter(
                x=plot_df["FII Net (₹Cr)"],
                y=plot_df[idx_col],
                mode="markers+text",
                marker=dict(size=14, color=colors_sc, line=dict(width=1,color="white")),
                text=plot_df["Sector"].str[:14],
                textposition="top center",
                textfont=dict(size=8),
                hovertemplate="<b>%{text}</b><br>FII: ₹%{x:+,.0f} Cr<br>Index: %{y:+.2f}%<extra></extra>",
            ))
            fig_sc.add_vline(x=0, line_dash="dot", line_color="rgba(255,255,255,0.2)")
            fig_sc.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)")
            # Quadrant labels
            for lbl, ax, ay in [("FII Buy\nPrice Up",1,1),("FII Buy\nPrice Down",1,-1),
                                  ("FII Sell\nPrice Up",-1,1),("FII Sell\nPrice Down",-1,-1)]:
                xr = plot_df["FII Net (₹Cr)"].max()*0.85*ax if ax>0 else plot_df["FII Net (₹Cr)"].min()*0.85
                yr = plot_df[idx_col].max()*0.85 if ay>0 else plot_df[idx_col].min()*0.85
                fig_sc.add_annotation(x=xr, y=yr, text=lbl, showarrow=False,
                                       font=dict(size=9,color="rgba(255,255,255,0.35)"))
            fig_sc.update_layout(
                template="plotly_dark", height=420,
                title=f"FII Flow vs Sector Index Return ({fwd_days} days after {sel_fn})",
                xaxis_title="FII Net Equity (₹ Crore)",
                yaxis_title=f"Sector Index Return % ({fwd_days}d)",
                margin=dict(t=50,b=40,l=60,r=20),
            )
            st.plotly_chart(fig_sc, use_container_width=True)
            st.caption(
                "Top-right quadrant = FII bought + price rose (Confirmed) — best signals. "
                "Bottom-right = FII bought but price fell (Diverged) — possible lag or wrong call."
            )
