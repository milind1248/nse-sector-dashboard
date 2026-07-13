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
import json
from datetime import date

st.set_page_config(
    page_title="Market Sector Analysis | FII Fortnightly Sector Flow Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Scheduler — local/VPS only, never on the shared Cloud web process ─────────
# ai_scan_daily trains Prophet+XGBoost+ARIMA for 185 stocks in 4 threads inside
# whatever process calls get_scheduler(). On Streamlit Cloud's free tier that
# process also serves every visitor's HTTP request; the job's memory footprint
# has twice now crashed the whole site with a SIGSEGV (job_run_log shows
# ai_scan_daily stuck in "running" with no finish — the process died mid-job).
# Cook-once architecture only requires the scheduler to run *somewhere* writing
# to the shared DB — that's `python run.py schedule` on a local machine/VPS.
# Cloud should only ever read.
_host = st.context.headers.get("host", "").lower().split(":")[0]
if _host not in ("marketsector.streamlit.app",):
    try:
        from backend.data_ingestion.scheduler import get_scheduler
        get_scheduler()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Scheduler failed to start: {e}")

from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.seo import inject_seo
inject_seo("Home")

from app.utils.logo import show_logo
from app.utils.visitor import get_visitor_count, render_visitor_counter
show_logo()
get_visitor_count()   # increment DB counter once per session

from app.utils.user_session import handle_oauth_callback
handle_oauth_callback()   # consumes ?code=... if this is a Google OAuth redirect landing


# ── FII Ticker — own lightweight cache, renders before main data load ─────────
@st.cache_data(ttl=3600, show_spinner=False)
def _get_ticker_data():
    from backend.storage.db import get_conn
    try:
        con = get_conn()
        rows = con.execute("""
            SELECT nsdl_sector, net_curr_eq, report_date
            FROM nsdl_fii_sector
            WHERE report_date = (SELECT MAX(report_date) FROM nsdl_fii_sector)
            ORDER BY
              CASE WHEN net_curr_eq >= 0 THEN 0 ELSE 1 END,
              CASE WHEN net_curr_eq >= 0 THEN -net_curr_eq ELSE net_curr_eq END
        """).fetchall()
        con.close()
        raw_date = rows[0][2] if rows else None
        try:
            date_lbl = raw_date.strftime("%d %b %Y") if raw_date else ""
        except Exception:
            date_lbl = str(raw_date or "")
        return [(r[0], r[1]) for r in rows], date_lbl
    except Exception:
        return [], ""

def _render_ticker(rows: list, period_label: str):
    items = []
    for sec, val in rows:
        color = "#00C853" if val >= 0 else "#FF5252"
        arrow = "▲" if val >= 0 else "▼"
        sign  = "+" if val >= 0 else ""
        items.append(
            f'<span style="margin:0 28px;white-space:nowrap">'
            f'<span style="color:#aaa;font-size:12px">{sec}</span>&nbsp;'
            f'<span style="color:{color};font-weight:600;font-size:13px">'
            f'{arrow} ₹{sign}{val:,.0f} Cr</span>'
            f'</span>'
        )
    content = "".join(items) * 2
    st.markdown(f"""
<div style="background:#0e1117;border:1px solid #2a2a3a;border-radius:6px;
            overflow:hidden;height:34px;display:flex;align-items:center;margin-bottom:4px">
  <div style="flex-shrink:0;background:#1a1f2e;padding:0 14px;height:100%;
              display:flex;align-items:center;border-right:1px solid #2a2a3a;
              font-size:11px;font-weight:700;color:#4a9eff;white-space:nowrap">
    FII&nbsp;{period_label}
  </div>
  <div style="overflow:hidden;flex:1;height:100%">
    <div style="display:flex;align-items:center;height:100%;white-space:nowrap;
                animation:fii-scroll 22s linear infinite">
      {content}
    </div>
  </div>
</div>
<style>
@keyframes fii-scroll{{0%{{transform:translateX(0)}}100%{{transform:translateX(-50%)}}}}
div[style*="fii-scroll"]:hover{{animation-play-state:paused}}
</style>
""", unsafe_allow_html=True)

_ticker_rows, _ticker_lbl = _get_ticker_data()

# ── Home page announcement (configured in Admin) ──────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _get_announcement() -> dict:
    _ann_path = Path(__file__).parent.parent / "data" / "announcement.json"
    try:
        return json.loads(_ann_path.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False, "text": ""}

_ann = _get_announcement()
if _ann.get("enabled") and _ann.get("text", "").strip():
    st.markdown(
        f"<div style='background:#0d2818;border-left:4px solid #4ade80;"
        f"padding:10px 16px;border-radius:4px;margin-bottom:8px;"
        f"font-weight:700;color:#4ade80;font-size:15px;'>📢 {_ann['text']}</div>",
        unsafe_allow_html=True,
    )

if _ticker_rows:
    _render_ticker(_ticker_rows, _ticker_lbl)

# ── Cold-start DB sync (runs in background thread so Home page renders instantly)
@st.cache_resource(show_spinner=False)
def _cold_start_sync():
    """Spawns a daemon thread so the page is never blocked by NSDL HTTP calls."""
    import threading
    def _do_sync():
        try:
            from backend.data_ingestion.nsdl_fetcher import (
                _dates_in_db, sync_nsdl_to_db, should_sync_today
            )
            n = len(_dates_in_db())
            if n < 5:
                sync_nsdl_to_db(force_refresh_latest=False)
            elif should_sync_today():
                sync_nsdl_to_db(force_refresh_latest=True)
        except Exception:
            pass
    t = threading.Thread(target=_do_sync, daemon=True)
    t.start()

_cold_start_sync()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("<p style='font-size:15px;font-weight:700;margin:0 0 6px 0;white-space:nowrap'>📊 Market Sector Analysis</p>", unsafe_allow_html=True)
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()
    with st.expander("📋 INVESTOR DECISION FLOW", expanded=False):
        st.markdown("""
<div style="font-size:11px; color:#888; line-height:1.8;">
<span style="color:#3a5a8a;">①</span> 🏠 <b>Home</b> <span style="color:#555;">→ FII buying this fortnight?</span><br>
<span style="color:#3a5a8a;">②</span> 📡 <b>Market Pulse</b> <span style="color:#555;">→ Broad market health check</span><br>
<span style="color:#3a5a8a;">③</span> 📈 <b>Sector Analysis</b> <span style="color:#555;">→ Which sectors are moving?</span><br>
<span style="color:#3a5a8a;">④</span> 🏛️ <b>Index Stocks</b> <span style="color:#555;">→ Stocks inside those indices</span><br>
<span style="color:#3a5a8a;">⑤</span> 🏦 <b>FII DII Flow</b> <span style="color:#555;">→ Daily institutional activity</span><br>
<span style="color:#3a5a8a;">⑥</span> 🌐 <b>FII Sectors</b> <span style="color:#555;">→ 5yr fortnightly history</span><br>
<span style="color:#3a5a8a;">⑦</span> 🌏 <b>FPI Sectors</b> <span style="color:#555;">→ Foreign portfolio by sector</span><br>
<span style="color:#3a5a8a;">⑧</span> 🎯 <b>Stock Screener</b> <span style="color:#555;">→ Stocks in selected sector</span><br>
<span style="color:#3a5a8a;">⑨</span> 💰 <b>Smart Money</b> <span style="color:#555;">→ Delivery % + Action + FO OI signals</span><br>
<span style="color:#3a5a8a;">⑩</span> 📊 <b>FII Accumulation</b> <span style="color:#555;">→ Quarterly FII shareholding changes</span><br>
<span style="color:#3a5a8a;">⑪</span> 🔔 <b>Alerts</b> <span style="color:#555;">→ Breakouts & reversals</span><br>
<span style="color:#3a5a8a;">⑫</span> 🤖 <b>AI Forecast</b> <span style="color:#555;">→ Prophet + XGBoost price prediction</span><br>
<span style="color:#3a5a8a;">⑬</span> 🔢 <b>Gann Analysis</b> <span style="color:#555;">→ ATR · Degree levels · Date projection · Price-Time square</span><br>
<span style="color:#3a5a8a;">⑭</span> 📤 <b>Export</b> <span style="color:#555;">→ Download for offline use</span><br>
<span style="color:#3a5a8a;">⑮</span> 🔐 <b>Admin</b> <span style="color:#555;">→ Job monitor & pipeline triggers</span>
</div>
""", unsafe_allow_html=True)
    st.markdown("---")
    from app.utils.auth import is_admin
    if is_admin():
        _do_refresh = st.button("🔄 Refresh Data", width='stretch',
                                help="Fetches today's latest NSDL + price data only. Old historical data stays.")
    else:
        st.caption("🔒 Data refresh is admin-only.")
        _do_refresh = False
    if _do_refresh:
        from backend.data_ingestion.job_logger import log_start, log_finish as _lf
        _home_rid = log_start("sector_snapshot", "Sector Snapshot (FII/DII + Breadth + Prices)", "admin")
        _home_err = None
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
            _home_err = str(e)

        bar.progress(55, text="Fetching latest FII/DII daily flow...")
        try:
            from backend.data_ingestion.nse_fetcher import fetch_fii_dii, fetch_market_breadth
            fetch_fii_dii(days=30)
            fetch_market_breadth()
        except Exception as e:
            st.warning(f"FII/DII: {e}")
            _home_err = str(e)

        bar.progress(80, text="Fetching sector index prices...")
        try:
            from backend.data_ingestion.yfinance_fetcher import fetch_all_sector_prices
            fetch_all_sector_prices()
        except Exception as e:
            st.warning(f"Sector prices: {e}")
            _home_err = str(e)

        bar.progress(100, text="Done!")
        _lf(_home_rid, "failed" if _home_err else "success", error_msg=_home_err)
        st.success("Latest data loaded! Reloading page...")
        st.rerun()

    st.markdown("---")
    st.caption(f"Data as of: {date.today().strftime('%d %b %Y')}")
    st.caption("NSDL updates every fortnight (1st & 15th of month).")
    render_visitor_counter()

# ── Inline splash placeholder — replaces blank area while data loads ──────────
_SPLASH_HTML = """
<style>
@keyframes candleRise {
  0%   { transform:scaleY(0); opacity:0; }
  60%  { transform:scaleY(1.08); opacity:1; }
  100% { transform:scaleY(1); opacity:1; }
}
@keyframes lineDrawFull {
  0%   { stroke-dashoffset:500; opacity:0; }
  20%  { opacity:1; }
  100% { stroke-dashoffset:0; opacity:1; }
}
@keyframes tickerScroll {
  0%   { transform:translateX(0); }
  100% { transform:translateX(-50%); }
}
@keyframes pulseDot {
  0%,100% { opacity:1; transform:scale(1); }
  50%      { opacity:.3; transform:scale(.5); }
}
@keyframes fadeInUp {
  from { opacity:0; transform:translateY(12px); }
  to   { opacity:1; transform:translateY(0); }
}
.pl-wrap {
  background:#0e1117; border-radius:12px;
  border:1px solid #1e2130;
  display:flex; flex-direction:column; align-items:center;
  justify-content:center; gap:22px;
  padding:40px 20px 36px; margin:8px 0;
  min-height:420px;
}
.pl-brand  { font-size:12px; letter-spacing:3px; color:#444; text-transform:uppercase; animation:fadeInUp .5s ease both; }
.pl-title  { font-size:32px; font-weight:800; color:#fff; animation:fadeInUp .5s ease .1s both; }
.pl-title span { color:#2979ff; }
.pl-sub    { font-size:12px; color:#555; letter-spacing:1px; animation:fadeInUp .5s ease .2s both; }
.pl-candle { animation:fadeInUp .5s ease .05s both; }
.pl-cbody  { transform-origin:bottom; animation:candleRise .65s cubic-bezier(.22,1,.36,1) both; }
.pl-tpath  { stroke-dasharray:500; stroke-dashoffset:500; animation:lineDrawFull 1.4s ease .35s both; }
.pl-ticker { width:100%; max-width:700px; overflow:hidden; border-top:1px solid #1a1d2e; border-bottom:1px solid #1a1d2e; padding:7px 0; animation:fadeInUp .5s ease .4s both; }
.pl-tinner { display:inline-block; white-space:nowrap; font-size:12px; color:#3a3d4a; animation:tickerScroll 16s linear infinite; }
.pl-tinner span.u { color:#00c853; } .pl-tinner span.d { color:#d50000; }
.pl-dots   { display:flex; gap:7px; animation:fadeInUp .5s ease .5s both; }
.pl-dots i { display:inline-block; width:8px; height:8px; border-radius:50%; background:#2979ff; animation:pulseDot 1.2s ease infinite; }
.pl-dots i:nth-child(2){ animation-delay:.2s; }
.pl-dots i:nth-child(3){ animation-delay:.4s; }
</style>
<div class="pl-wrap" id="nse-inline-splash">
  <div class="pl-brand">FII Fortnightly Intelligence</div>
  <svg class="pl-candle" width="380" height="130" viewBox="0 0 380 130">
    <line x1="35"  y1="10" x2="35"  y2="100" stroke="#2a2d3a" stroke-width="2"/>
    <line x1="90"  y1="18" x2="90"  y2="96"  stroke="#2a2d3a" stroke-width="2"/>
    <line x1="145" y1="12" x2="145" y2="105" stroke="#2a2d3a" stroke-width="2"/>
    <line x1="200" y1="6"  x2="200" y2="90"  stroke="#2a2d3a" stroke-width="2"/>
    <line x1="255" y1="20" x2="255" y2="98"  stroke="#2a2d3a" stroke-width="2"/>
    <line x1="310" y1="8"  x2="310" y2="82"  stroke="#2a2d3a" stroke-width="2"/>
    <line x1="365" y1="4"  x2="365" y2="75"  stroke="#2a2d3a" stroke-width="2"/>
    <g class="pl-cbody" style="animation-delay:.06s"><rect x="22"  y="45" width="26" height="55" rx="3" fill="#D50000"/></g>
    <g class="pl-cbody" style="animation-delay:.16s"><rect x="77"  y="28" width="26" height="50" rx="3" fill="#00C853"/></g>
    <g class="pl-cbody" style="animation-delay:.26s"><rect x="132" y="52" width="26" height="53" rx="3" fill="#D50000"/></g>
    <g class="pl-cbody" style="animation-delay:.36s"><rect x="187" y="18" width="26" height="52" rx="3" fill="#00C853"/></g>
    <g class="pl-cbody" style="animation-delay:.46s"><rect x="242" y="32" width="26" height="50" rx="3" fill="#00C853"/></g>
    <g class="pl-cbody" style="animation-delay:.56s"><rect x="297" y="16" width="26" height="48" rx="3" fill="#00C853"/></g>
    <g class="pl-cbody" style="animation-delay:.66s"><rect x="352" y="10" width="26" height="42" rx="3" fill="#00C853"/></g>
    <polyline class="pl-tpath" points="35,72 90,52 145,78 200,44 255,58 310,36 365,28"
      fill="none" stroke="#FFD600" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="365" cy="28" r="6" fill="#FFD600"/>
  </svg>
  <div class="pl-title">FII <span>Sector</span> Analysis</div>
  <div class="pl-sub">Preparing FII fortnightly sector intelligence…</div>
  <div class="pl-ticker">
    <div class="pl-tinner">
      &nbsp;&nbsp;NIFTY 50 <span class="u">▲ 24,502 &nbsp;+0.62%</span> &nbsp;|&nbsp;
      NIFTY BANK <span class="u">▲ 52,340 &nbsp;+0.44%</span> &nbsp;|&nbsp;
      NIFTY IT <span class="d">▼ 38,120 &nbsp;-0.31%</span> &nbsp;|&nbsp;
      NIFTY AUTO <span class="u">▲ 22,870 &nbsp;+1.12%</span> &nbsp;|&nbsp;
      FII NET <span class="u">▲ ₹4,210 Cr</span> &nbsp;|&nbsp;
      NIFTY PHARMA <span class="u">▲ 21,430 &nbsp;+0.88%</span> &nbsp;|&nbsp;
      NIFTY FMCG <span class="d">▼ 56,210 &nbsp;-0.19%</span> &nbsp;|&nbsp;
      NIFTY METAL <span class="u">▲ 9,320 &nbsp;+2.04%</span>&nbsp;&nbsp;
      NIFTY 50 <span class="u">▲ 24,502 &nbsp;+0.62%</span> &nbsp;|&nbsp;
      NIFTY BANK <span class="u">▲ 52,340 &nbsp;+0.44%</span> &nbsp;|&nbsp;
      NIFTY IT <span class="d">▼ 38,120 &nbsp;-0.31%</span> &nbsp;|&nbsp;
      NIFTY AUTO <span class="u">▲ 22,870 &nbsp;+1.12%</span>&nbsp;&nbsp;
    </div>
  </div>
  <div class="pl-dots"><i></i><i></i><i></i></div>
</div>
"""

# ── Load NSDL data (all available fortnights) ─────────────────────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def load_nsdl_history():
    from backend.data_ingestion.nsdl_fetcher import fetch_nsdl_fii_sectors
    return fetch_nsdl_fii_sectors()

with st.status("📂 Loading NSE market intelligence…", expanded=True) as _load_status:
    # Splash fills the expanded status area while data loads
    st.markdown(_SPLASH_HTML, unsafe_allow_html=True)
    all_periods = load_nsdl_history()
    if all_periods:
        n = len(all_periods)
        latest = max(all_periods.keys())
        _load_status.update(
            label=f"✅ {n} fortnightly reports loaded · Latest: {latest.strftime('%d %b %Y')}",
            state="complete", expanded=False,   # collapses → hides splash
        )
    else:
        _load_status.update(label="❌ No data found", state="error")

if not all_periods:
    st.error("No NSDL data found in database. Click **🔄 Refresh Latest Data** in the sidebar to fetch from NSDL.")
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
from app.utils.loading import data_freshness_bar
st.title("📊 FII Fortnightly Sector Watch")
st.markdown(
    "**Start here every morning.** "
    "See where FII money is flowing → explore sector price trends → screen stocks for further research."
)
data_freshness_bar(curr_date, record_count=len(all_periods), source="NSDL · fpi.nsdl.co.in")

# Summary metrics
total_curr    = curr_df["net_curr_eq"].sum()
buying_count  = int((curr_df["net_curr_eq"] > 0).sum())
selling_count = int((curr_df["net_curr_eq"] < 0).sum())
top_buyer     = curr_df.iloc[0]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total FII Equity Flow This Fortnight", f"₹{total_curr:+,.0f} Cr",
           "Net Inflow" if total_curr > 0 else "Net Outflow",
           delta_color="normal")
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
    _xmax = sorted_curr["net_curr_eq"].max()
    _xmin = sorted_curr["net_curr_eq"].min()
    fig_bar.update_layout(
        template="plotly_dark", height=600,
        title=f"FII Equity Net Investment — {curr_date.strftime('%d %b %Y')} (₹ Crore)",
        margin=dict(t=50, b=20, l=240, r=20),
        xaxis=dict(
            title="₹ Crore",
            zeroline=True,
            zerolinecolor="rgba(255,255,255,0.3)",
            zerolinewidth=1.5,
            range=[_xmin * 1.18, _xmax * 1.18],
        ),
    )
    st.plotly_chart(fig_bar, width='stretch')

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
        width='stretch', hide_index=True, height=520,
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
        st.dataframe(styled_hist, width='stretch', height=max(380, len(all_sector_names)*28+40))

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
                       hide_index=True, width='stretch')
        sc2.markdown("**Most Fortnights Selling**")
        sc2.dataframe(sell_counts.rename("Sell periods").reset_index().rename(columns={"index":"Sector"}),
                       hide_index=True, width='stretch')
        sc3.markdown("**Cumulative Flow in Range (₹ Cr)**")
        sc3.dataframe(
            total_flow.rename("Total ₹ Cr").reset_index().rename(columns={"index":"Sector"})
            .style.map(color_n, subset=["Total ₹ Cr"])
            .format({"Total ₹ Cr": lambda x: f"₹{x:+,.0f}" if isinstance(x,(int,float)) else "–"}),
            hide_index=True, width='stretch'
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
            template="plotly_dark", height=500,
            title=f"FII Equity Net Investment — {'% change' if view.startswith('%') else '₹ Crore'}",
            yaxis_title="% Change" if view.startswith("%") else "₹ Crore",
            margin=dict(t=50, b=110, l=10, r=10),
            xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
            legend=dict(
                orientation="h",
                y=-0.28,
                x=0,
                xanchor="left",
                font=dict(size=11),
                itemwidth=80,
            ),
            hovermode="x unified",
        )
        st.plotly_chart(fig_trend, width='stretch')

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
    if c1.button("📈 Analyse sector price trend", width='stretch', type="primary"):
        st.session_state["selected_sector"]          = internal
        st.session_state["selected_sector_nsdl"]     = selected
        st.session_state["selected_sector_net_curr"] = net_curr
        st.switch_page("pages/2_📈_Sector_Analysis.py")
    if c2.button("🔍 Analyse stocks in this sector", width='stretch'):
        st.session_state["selected_sector"]          = internal
        st.session_state["selected_sector_nsdl"]     = selected
        st.session_state["selected_sector_net_curr"] = net_curr
        st.switch_page("pages/7_🎯_Stock_Picker.py")

from app.utils.disclaimer import show_footer
show_footer()
