"""Market breadth, sector heatmap, and RRG in one pulse view.
Breadth / Heatmap / RRG are served from SQLite (cooked nightly at 8 PM IST).
Market Indices are fetched live from yfinance (near-real-time, 15-min delay).
"""
import sys
import sqlite3
import json
from pathlib import Path
from datetime import date, timedelta
from datetime import timezone, timedelta as td
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf

from config import NIFTY_SYMBOL
from backend.data_ingestion.yfinance_fetcher import fetch_market_summary

st.set_page_config(
    page_title="Market Pulse | Nifty Breadth & Relative Rotation | Market Sector Analysis",
    layout="wide",
)
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()
from app.utils.seo import inject_seo
inject_seo("Market_Pulse")
from app.utils.logo import show_logo
show_logo()

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nse_dashboard.db"
_IST = timezone(td(hours=5, minutes=30))


def _db():
    return sqlite3.connect(_DB_PATH)


# ── Staleness helper ──────────────────────────────────────────────────────────

def _staleness_banner(trade_date_str: str | None):
    """Show a contextual banner based on how old the stored data is."""
    if not trade_date_str:
        st.warning(
            "⚠️ No data found. The Market Pulse pipeline has not run yet. "
            "Ask admin to trigger **Market Pulse Snapshot** manually, or wait until 8 PM IST today."
        )
        return
    try:
        td_date  = date.fromisoformat(trade_date_str)
        today    = date.today()
        days_old = (today - td_date).days
        fmt_date = td_date.strftime("%A, %d %b %Y")

        if days_old == 0:
            st.success(f"✅ Data as of **today ({fmt_date})** — updated at 8 PM IST.")
        elif days_old == 1:
            st.info(f"📅 Data as of **yesterday ({fmt_date})**. Next update tonight at 8 PM IST.")
        elif days_old in (2, 3) and td_date.weekday() == 4:
            # Friday data shown on weekend
            st.info(
                f"📅 Data as of **{fmt_date}** (last trading day). "
                "Markets are closed on weekends — next update Monday 8 PM IST."
            )
        else:
            st.warning(
                f"⚠️ Data as of **{fmt_date}** ({days_old} days old). "
                "The scheduler may not have run — ask admin to trigger a manual refresh."
            )
    except Exception:
        pass


# ── SQLite readers ────────────────────────────────────────────────────────────

def _read_breadth():
    try:
        con = _db()
        row = con.execute(
            "SELECT trade_date, advance, decline, unchanged, ad_ratio "
            "FROM market_breadth ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        con.close()
        if row:
            return {"trade_date": row[0], "advance": row[1],
                    "decline": row[2], "unchanged": row[3], "ad_ratio": row[4]}
    except Exception:
        pass
    return {}


def _read_heatmap():
    try:
        con = _db()
        rows = con.execute(
            "SELECT sector, ret_1w, ret_2w, ret_1m, ret_3m, ret_6m, ret_1y, trade_date "
            "FROM sector_heatmap WHERE trade_date = ("
            "  SELECT MAX(trade_date) FROM sector_heatmap"
            ") ORDER BY ret_1m DESC"
        ).fetchall()
        trade_date = con.execute(
            "SELECT MAX(trade_date) FROM sector_heatmap"
        ).fetchone()[0]
        con.close()
        if not rows:
            return pd.DataFrame(), None
        df = pd.DataFrame(rows, columns=["Sector","1W","2W","1M","3M","6M","1Y","trade_date"])
        df = df.set_index("Sector").drop(columns=["trade_date"])
        return df, trade_date
    except Exception:
        return pd.DataFrame(), None


def _read_rrg():
    try:
        con = _db()
        rows = con.execute(
            "SELECT sector, rs_ratio, rs_momentum, quadrant, trail_json, trade_date "
            "FROM rrg_snapshot WHERE trade_date = ("
            "  SELECT MAX(trade_date) FROM rrg_snapshot"
            ")"
        ).fetchall()
        trade_date = con.execute(
            "SELECT MAX(trade_date) FROM rrg_snapshot"
        ).fetchone()[0]
        con.close()
        if not rows:
            return [], None
        result = []
        for r in rows:
            result.append({
                "sector":      r[0],
                "rs_ratio":    r[1],
                "rs_momentum": r[2],
                "quadrant":    r[3],
                "trail":       json.loads(r[4]) if r[4] else [],
            })
        return result, trade_date
    except Exception:
        return [], None


# ── Header + admin refresh ────────────────────────────────────────────────────

col_h, col_ref = st.columns([6, 1])
col_h.title("📡 Market Pulse")

from app.utils.auth import is_admin
if is_admin():
    if col_ref.button("🔄 Refresh Data", use_container_width=True):
        from backend.data_ingestion.job_logger import log_start, log_finish
        from backend.data_ingestion.market_pulse_pipeline import run_market_pulse_pipeline
        rid = log_start("market_pulse_snapshot",
                        "Market Pulse Snapshot (Breadth + Heatmap + RRG)", "admin")
        with st.spinner("Running Market Pulse pipeline — fetching Bhavcopy, sector returns, RRG…"):
            try:
                summary = run_market_pulse_pipeline(triggered_by="admin")
                log_finish(rid, "success",
                           records_done=summary.get("heatmap_sectors", 0))
                st.success(
                    f"✅ Market Pulse updated — "
                    f"Breadth: {summary.get('breadth_date','—')} · "
                    f"Sectors: {summary.get('heatmap_sectors', 0)} · "
                    f"RRG: {summary.get('rrg_sectors', 0)}"
                )
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                log_finish(rid, "failed", error_msg=str(e))
                st.error(f"Pipeline failed: {e}")
else:
    col_ref.caption("🔒 Admin only.")

st.caption("Market Indices are live (15-min delay). Breadth / Heatmap / RRG are as of last EOD update (8 PM IST).")

# ── Section 1: Market Indices — LIVE (unchanged) ──────────────────────────────
st.subheader("Market Indices")
st.caption("Live prices — 15-minute delay during market hours.")

@st.cache_data(ttl=300, show_spinner=False)
def get_market_summary():
    return fetch_market_summary()

with st.spinner("Loading live indices..."):
    summary = get_market_summary()

idx_cols = st.columns(len(summary))
for col, (name, data) in zip(idx_cols, summary.items()):
    if not data:
        col.metric(name, "N/A")
        continue
    col.metric(name, f"₹{data['close']:,.0f}",
               f"{data['change']:+.0f} ({data['pct']:+.2f}%)",
               delta_color="normal")

st.markdown("---")

# ── Section 2: Advance / Decline Breadth — from SQLite ───────────────────────
st.subheader("NSE Market Breadth")

breadth = _read_breadth()
_staleness_banner(breadth.get("trade_date"))

adv = int(breadth.get("advance", 0) or 0)
dec = int(breadth.get("decline", 0) or 0)
unc = int(breadth.get("unchanged", 0) or 0)
ad_ratio = breadth.get("ad_ratio")

b1, b2, b3, b4 = st.columns(4)
b1.metric("Advancing",  adv  or "—")
b2.metric("Declining",  dec  or "—")
b3.metric(
    "A/D Ratio",
    f"{ad_ratio:.2f}" if ad_ratio else "—",
    ("Bullish" if ad_ratio and ad_ratio > 1.5 else "Bearish") if ad_ratio else None,
)
b4.metric("Unchanged", unc or "—")

st.markdown("---")

# ── Section 3: Sector Heatmap — from SQLite ───────────────────────────────────
st.subheader("Sector Heatmap — % Returns")

hm, hm_date = _read_heatmap()
if hm_date:
    fmt = date.fromisoformat(hm_date).strftime("%d %b %Y")
    st.caption(f"Data as of **{fmt}**")

if not hm.empty:
    fig = px.imshow(
        hm, color_continuous_scale="RdYlGn", zmin=-10, zmax=10,
        text_auto=".1f", aspect="auto",
    )
    fig.update_layout(
        template="plotly_dark",
        height=max(380, len(hm) * 24),
        margin=dict(t=20, b=20, l=140, r=20),
        coloraxis_colorbar=dict(title="%"),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No heatmap data yet. Run the Market Pulse pipeline (Admin → Market Pulse Snapshot).")

st.markdown("---")

# ── Section 4: RRG — from SQLite ─────────────────────────────────────────────
st.subheader("Relative Rotation Graph (RRG)")
st.caption(
    "Leading = strong + rising | Improving = weak but turning up | "
    "Weakening = strong but fading | Lagging = weak + falling"
)

rrg_data, rrg_date = _read_rrg()
if rrg_date:
    fmt = date.fromisoformat(rrg_date).strftime("%d %b %Y")
    st.caption(f"Data as of **{fmt}**")

if rrg_data:
    colors = {
        "Leading": "#00C853", "Improving": "#00BCD4",
        "Lagging": "#D50000",  "Weakening": "#FF6D00",
    }
    fig2 = go.Figure()
    for item in rrg_data:
        trail = item.get("trail", [])
        if len(trail) > 1:
            fig2.add_trace(go.Scatter(
                x=[t["rs_ratio"]    for t in trail[:-1]],
                y=[t["rs_momentum"] for t in trail[:-1]],
                mode="lines",
                line=dict(color=colors.get(item["quadrant"], "#888"), width=1),
                showlegend=False, opacity=0.35,
            ))
        fig2.add_trace(go.Scatter(
            x=[item["rs_ratio"]], y=[item["rs_momentum"]],
            mode="markers+text",
            marker=dict(size=14, color=colors.get(item["quadrant"], "#888"),
                        line=dict(width=1, color="white")),
            text=[item["sector"]], textposition="top center",
            textfont=dict(size=9),
            name=item["quadrant"], showlegend=False,
        ))
    fig2.add_vline(x=100, line_dash="dot", line_color="white", opacity=0.25)
    fig2.add_hline(y=100, line_dash="dot", line_color="white", opacity=0.25)
    for lbl, x, y in [("Leading",102,102),("Improving",98,102),
                       ("Lagging",98,98),("Weakening",102,98)]:
        fig2.add_annotation(x=x, y=y, text=lbl, showarrow=False,
                             font=dict(size=10, color=colors[lbl]), opacity=0.5)
    fig2.update_layout(
        template="plotly_dark", height=500,
        xaxis_title="RS-Ratio (relative strength)",
        yaxis_title="RS-Momentum (trend of RS)",
        margin=dict(t=30, b=30, l=50, r=20),
    )
    st.plotly_chart(fig2, use_container_width=True)

    quad_cols = st.columns(4)
    for col, quad in zip(quad_cols, ["Leading", "Improving", "Weakening", "Lagging"]):
        sectors = [d["sector"] for d in rrg_data if d["quadrant"] == quad]
        col.markdown(f"**{quad}**")
        if sectors:
            for s in sectors:
                if col.button(s[:18], key=f"rrg_{quad}_{s}", use_container_width=True):
                    st.session_state["selected_sector"] = s
                    st.switch_page("pages/2_📈_Sector_Analysis.py")
        else:
            col.caption("None")
else:
    st.info(
        "No RRG data yet. Run the Market Pulse pipeline via "
        "Admin → Market Pulse Snapshot, or wait until 8 PM IST today."
    )

st.markdown("---")
if st.button("← FII Sector Watch", use_container_width=False):
    st.switch_page("Home.py")
from app.utils.disclaimer import show_footer
show_footer()
