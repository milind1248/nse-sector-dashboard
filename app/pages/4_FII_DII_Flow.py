"""Detailed FII/DII daily + fortnightly flow charts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from backend.data_ingestion.nse_fetcher import fetch_fii_dii
from backend.data_ingestion.nsdl_fetcher import get_latest_nsdl

st.set_page_config(page_title="FII / DII Flow", layout="wide")
st.title("\U0001f3e6 FII / DII Flow Dashboard")
st.caption("Daily institutional flow + fortnightly sector breakdown from NSDL.")

tabs = st.tabs(["Daily Flow", "Fortnightly Sector Breakdown"])

with tabs[0]:
    period_map = {"Weekly":7,"Fortnightly":14,"Monthly":30,"Quarterly":90}
    period = st.radio("View period", list(period_map.keys()), horizontal=True, index=1)
    days   = period_map[period]

    @st.cache_data(ttl=3600, show_spinner=False)
    def load_daily_fii(days):
        return fetch_fii_dii(days=max(days+10, 90))

    with st.spinner("Loading FII/DII data..."):
        df = load_daily_fii(days)

    if df is None or df.empty:
        st.error("FII/DII data unavailable.")
    else:
        df = df.sort_values("date")
        curr = df.tail(days)
        fii_net_sum = curr["fii_net"].sum() if "fii_net" in curr.columns else 0
        dii_net_sum = curr["dii_net"].sum() if "dii_net" in curr.columns else 0

        m1,m2,m3,m4 = st.columns(4)
        m1.metric(f"FII Net ({period})", f"₹{fii_net_sum:+,.0f} Cr",
                   delta_color="normal" if fii_net_sum >= 0 else "inverse")
        m2.metric(f"DII Net ({period})", f"₹{dii_net_sum:+,.0f} Cr",
                   delta_color="normal" if dii_net_sum >= 0 else "inverse")
        m3.metric("FII Buy Days", str((curr["fii_net"]>0).sum()) if "fii_net" in curr.columns else "–")
        m4.metric("DII Buy Days", str((curr["dii_net"]>0).sum()) if "dii_net" in curr.columns else "–")

        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            colors = ["#00C853" if v >= 0 else "#D50000" for v in df.tail(days*3)["fii_net"]]
            fig = go.Figure(go.Bar(x=df.tail(days*3)["date"].astype(str),
                                    y=df.tail(days*3)["fii_net"],
                                    marker_color=colors, name="FII Net"))
            fig.update_layout(template="plotly_dark", title=f"FII Net Flow (₹ Cr) — Last {min(days*3,len(df))} days",
                               height=300, margin=dict(t=40,b=20))
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            colors2 = ["#00BCD4" if v >= 0 else "#FF6D00" for v in df.tail(days*3)["dii_net"]]
            fig2 = go.Figure(go.Bar(x=df.tail(days*3)["date"].astype(str),
                                     y=df.tail(days*3)["dii_net"],
                                     marker_color=colors2, name="DII Net"))
            fig2.update_layout(template="plotly_dark", title=f"DII Net Flow (₹ Cr) — Last {min(days*3,len(df))} days",
                                height=300, margin=dict(t=40,b=20))
            st.plotly_chart(fig2, use_container_width=True)

        df2 = df.copy()
        df2["fii_cum"] = df2["fii_net"].cumsum()
        df2["dii_cum"] = df2["dii_net"].cumsum()
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=df2["date"].astype(str), y=df2["fii_cum"],
                                   name="FII Cumulative", line=dict(color="#2979FF", width=2)))
        fig3.add_trace(go.Scatter(x=df2["date"].astype(str), y=df2["dii_cum"],
                                   name="DII Cumulative", line=dict(color="#FF6D00", width=2)))
        fig3.update_layout(template="plotly_dark", height=280,
                            title="Cumulative FII + DII Net Flow (₹ Cr)", margin=dict(t=40,b=20))
        st.plotly_chart(fig3, use_container_width=True)

        with st.expander("Raw daily data"):
            st.dataframe(curr.sort_values("date", ascending=False), use_container_width=True, hide_index=True)

with tabs[1]:
    @st.cache_data(ttl=3600, show_spinner=False)
    def load_nsdl():
        return get_latest_nsdl(periods=4)

    with st.spinner("Loading NSDL fortnightly data..."):
        curr_df, prev_df, curr_date, prev_date = load_nsdl()

    if curr_df is None:
        st.error("NSDL data unavailable.")
    else:
        st.markdown(f"**Period:** {curr_date} | **Previous:** {prev_date}")

        sorted_df = curr_df.sort_values("net_curr_eq", ascending=True)
        colors4 = ["#00C853" if v > 0 else "#D50000" for v in sorted_df["net_curr_eq"]]
        fig4 = go.Figure(go.Bar(x=sorted_df["net_curr_eq"], y=sorted_df["nsdl_sector"],
                                 orientation="h", marker_color=colors4,
                                 text=[f"₹{v:+,.0f}" for v in sorted_df["net_curr_eq"]],
                                 textposition="outside"))
        fig4.update_layout(template="plotly_dark", height=580,
                            title=f"FII Equity Net by Sector — {curr_date} (₹ Cr)",
                            margin=dict(t=50,b=20,l=220,r=120), xaxis_title="₹ Crore")
        st.plotly_chart(fig4, use_container_width=True)

        if prev_df is not None:
            merged = curr_df[["nsdl_sector","net_curr_eq"]].merge(
                prev_df[["nsdl_sector","net_curr_eq"]].rename(columns={"net_curr_eq":"net_prev"}),
                on="nsdl_sector", how="left"
            ).sort_values("net_curr_eq", ascending=False)
            fig5 = go.Figure()
            fig5.add_trace(go.Bar(name=f"Current ({curr_date})",
                                   x=merged["nsdl_sector"], y=merged["net_curr_eq"],
                                   marker_color="#2979FF"))
            fig5.add_trace(go.Bar(name=f"Previous ({prev_date})",
                                   x=merged["nsdl_sector"], y=merged["net_prev"],
                                   marker_color="#FF6D00", opacity=0.6))
            fig5.update_layout(barmode="group", template="plotly_dark", height=420,
                                title="Current vs Previous Fortnight FII Equity Flow",
                                margin=dict(t=50,b=100,l=20,r=20), xaxis_tickangle=-45)
            st.plotly_chart(fig5, use_container_width=True)

        st.subheader("FII Total Holdings (AUC) by Sector")
        auc_df = curr_df[["nsdl_sector","auc_prev_eq","auc_curr_eq","auc_change","auc_pct_change"]].copy()
        auc_df.columns = ["Sector","AUC Prev (Cr)","AUC Curr (Cr)","Change (Cr)","Change %"]
        auc_df = auc_df.sort_values("AUC Curr (Cr)", ascending=False)

        def c_chg(v):
            if not isinstance(v,(int,float)): return ""
            return "color:#00C853" if v > 0 else "color:#D50000" if v < 0 else ""

        st.dataframe(
            auc_df.style.map(c_chg, subset=["Change (Cr)","Change %"])
                        .format({"AUC Prev (Cr)": "₹{:,.0f}", "AUC Curr (Cr)": "₹{:,.0f}",
                                 "Change (Cr)": "₹{:+,.0f}", "Change %": "{:+.2f}%"}),
            use_container_width=True, hide_index=True
        )
