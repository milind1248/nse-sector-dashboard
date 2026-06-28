"""Admin Dashboard — job monitoring and manual pipeline triggers. Login required."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import sqlite3
import time
from datetime import datetime, date, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nse_dashboard.db"

def _to_ist(ts: str | None) -> str:
    """Convert a UTC ISO timestamp string to IST display string."""
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_ist = dt.astimezone(_IST)
        return dt_ist.strftime("%d %b %Y %H:%M IST")
    except Exception:
        return ts[:16] if ts else "—"

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Admin Dashboard | Market Sector Analysis",
    layout="wide",
)
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.logo import show_logo
show_logo()

from app.utils.auth import is_admin, require_admin, logout, session_remaining_minutes

# ── Auth gate ─────────────────────────────────────────────────────────────────
require_admin()

# ── DB ────────────────────────────────────────────────────────────────────────
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nse_dashboard.db"

def _db():
    return sqlite3.connect(_DB_PATH)

# ── Header ────────────────────────────────────────────────────────────────────
h1, h2 = st.columns([5, 1])
with h1:
    st.title("🔐 Admin Dashboard")
with h2:
    st.write("")
    if st.button("🚪 Logout", use_container_width=True):
        logout()
        st.rerun()

st.caption(
    f"Logged in · Session expires in **{session_remaining_minutes()} min** · "
    "All actions are logged. For internal use only."
)
st.markdown("---")

# ── Job Run Log ────────────────────────────────────────────────────────────────
st.subheader("Job Run History")

@st.cache_data(ttl=30, show_spinner=False)
def _load_job_log() -> pd.DataFrame:
    try:
        con = _db()
        df = pd.read_sql_query(
            "SELECT job_name, triggered_by, started_at, finished_at, status, records_done, error_msg "
            "FROM job_run_log ORDER BY started_at DESC LIMIT 100",
            con,
        )
        con.close()
        return df
    except Exception:
        return pd.DataFrame()

job_df = _load_job_log()

if job_df.empty:
    st.info("No job runs recorded yet. Runs will appear here after the scheduler fires or you trigger a manual run below.")
else:
    # Summary cards
    total     = len(job_df)
    successes = (job_df["status"] == "success").sum()
    failures  = (job_df["status"] == "failed").sum()
    running   = (job_df["status"] == "running").sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Runs", total)
    c2.metric("Successful", int(successes))
    c3.metric("Failed", int(failures))
    c4.metric("Running Now", int(running))

    # Format display — convert UTC timestamps to IST
    display = job_df.copy()
    display.columns = ["Job", "Triggered By", "started_raw", "finished_raw", "Status", "Records", "Error"]
    display["Started (IST)"]  = display["started_raw"].apply(_to_ist)
    display["Finished (IST)"] = display["finished_raw"].apply(_to_ist)
    display = display.drop(columns=["started_raw", "finished_raw"])
    display = display[["Job", "Triggered By", "Started (IST)", "Finished (IST)", "Status", "Records", "Error"]]

    def _status_color(val):
        if val == "success":  return "color: #43A047; font-weight:600"
        if val == "failed":   return "color: #E53935; font-weight:600"
        if val == "running":  return "color: #FB8C00; font-weight:600"
        return ""

    def _trigger_color(val):
        if val == "admin":    return "color: #64B5F6; font-weight:600"
        return "color: #aaa"

    styled = (
        display.style
        .map(_status_color,  subset=["Status"])
        .map(_trigger_color, subset=["Triggered By"])
        .format({"Records": lambda v: f"{int(v):,}" if v and not pd.isna(v) else "–",
                 "Started (IST)": lambda v: v or "—",
                 "Finished (IST)": lambda v: v or "—"}, na_rep="—")
    )
    st.dataframe(styled, use_container_width=True, height=320, hide_index=True)

st.markdown("---")

# ── Manual Triggers ────────────────────────────────────────────────────────────
st.subheader("Manual Pipeline Triggers")
st.caption(
    "These run the same pipelines as the scheduler, logged as 'admin'. "
    "Use sparingly — each run makes external data requests."
)

def _last_run_for(job_id: str) -> str:
    """Return last successful run timestamp for a job, or 'Never'."""
    try:
        con = _db()
        row = con.execute(
            "SELECT finished_at FROM job_run_log WHERE job_id=? AND status='success' "
            "ORDER BY finished_at DESC LIMIT 1",
            (job_id,)
        ).fetchone()
        con.close()
        if row and row[0]:
            return _to_ist(row[0])
        return "Never"
    except Exception:
        return "—"

# Table header
hc1, hc2, hc3, hc4, hc5 = st.columns([2, 3, 4, 3, 2])
hc1.markdown("**#**")
hc2.markdown("**Page**")
hc3.markdown("**Pipeline / What it refreshes**")
hc4.markdown("**Last Run (IST)**")
hc5.markdown("**Action**")
st.divider()

# ── Row 1: Market Pulse Snapshot ─────────────────────────────────────────────
r1c1, r1c2, r1c3, r1c4, r1c5 = st.columns([2, 3, 4, 3, 2])
r1c1.markdown("1")
r1c2.markdown("📡 Market Pulse")
r1c3.markdown("Market Pulse Snapshot — Bhavcopy breadth + sector heatmap + RRG → stored in DB (~3–5 min)")
r1c4.markdown(_last_run_for("market_pulse_snapshot"))
if r1c5.button("▶ Run", key="btn_mps", use_container_width=True):
    with st.spinner("Running Market Pulse pipeline…"):
        try:
            from backend.data_ingestion.market_pulse_pipeline import run_market_pulse_pipeline
            from backend.data_ingestion.job_logger import log_start, log_finish
            rid = log_start("market_pulse_snapshot",
                            "Market Pulse Snapshot (Breadth + Heatmap + RRG)", "admin")
            summary = run_market_pulse_pipeline(triggered_by="admin")
            log_finish(rid, "success", records_done=summary.get("heatmap_sectors", 0))
            st.cache_data.clear()
            st.success(
                f"✅ Market Pulse snapshot complete — "
                f"Breadth: {summary.get('breadth_date', '—')} · "
                f"Sectors: {summary.get('heatmap_sectors', 0)} · "
                f"RRG: {summary.get('rrg_sectors', 0)}"
            )
        except Exception as e:
            log_finish(rid, "failed", error_msg=str(e))
            st.error(f"Pipeline failed: {e}")
    st.rerun()

# ── Row 2: Sector Snapshot ────────────────────────────────────────────────────
r2c1, r2c2, r2c3, r2c4, r2c5 = st.columns([2, 3, 4, 3, 2])
r2c1.markdown("2")
r2c2.markdown("📈 Sector Analysis · 🏦 FII DII Flow · 🏢 FII Sectors · 🏠 Home")
r2c3.markdown("Sector Snapshot — FII/DII flows, sector prices, breadth data")
r2c4.markdown(_last_run_for("sector_snapshot"))
if r2c5.button("▶ Run", key="btn_sector", use_container_width=True):
    with st.spinner("Running sector snapshot…"):
        try:
            from backend.data_ingestion.pipeline import (
                run_fii_dii_pipeline, run_breadth_pipeline, run_sector_pipeline,
            )
            from backend.storage.cache import invalidate_all
            from backend.data_ingestion.job_logger import log_start, log_finish
            rid = log_start("sector_snapshot", "Sector Snapshot (FII/DII + Breadth + Prices)", "admin")
            invalidate_all()
            run_fii_dii_pipeline()
            run_breadth_pipeline()
            run_sector_pipeline()
            log_finish(rid, "success")
            st.cache_data.clear()
            st.success("✅ Sector snapshot completed.")
        except Exception as e:
            log_finish(rid, "failed", error_msg=str(e))
            st.error(f"Pipeline failed: {e}")
    st.rerun()

# ── Row 3: Index Stocks Sync ──────────────────────────────────────────────────
r3c1, r3c2, r3c3, r3c4, r3c5 = st.columns([2, 3, 4, 3, 2])
r3c1.markdown("3")
r3c2.markdown("🏛️ Index Stocks")
r3c3.markdown("NSE constituent list + market price feeds for market caps (~5–8 min)")
r3c4.markdown(_last_run_for("index_stocks_sync"))
if r3c5.button("▶ Run", key="btn_idx", use_container_width=True):
    with st.spinner("Syncing Index Stocks from NSE India + market price feeds…"):
        try:
            from pathlib import Path as _Path
            from backend.data_ingestion.sector_sync import sync_all
            from backend.data_ingestion.job_logger import log_start, log_finish
            _db_path = _Path(__file__).resolve().parent.parent.parent / "data" / "nse_dashboard.db"
            rid = log_start("index_stocks_sync", "Index Stocks Sync (NSE + Yahoo Finance)", "admin")
            result = sync_all(str(_db_path))
            log_finish(rid, "success", records_done=result.get("stocks_total", 0))
            st.cache_data.clear()
            st.success(
                f"✅ Sync complete — {result.get('indices_ok', 0)} indices · "
                f"{result.get('stocks_total', 0)} stocks  \n"
                f"+{result.get('stocks_added', 0)} added · "
                f"~{result.get('stocks_updated', 0)} updated · "
                f"-{result.get('stocks_removed', 0)} removed"
            )
        except Exception as e:
            log_finish(rid, "failed", error_msg=str(e))
            st.error(f"Sync failed: {e}")
    st.rerun()

# ── Row 4: Stock Snapshot ─────────────────────────────────────────────────────
r4c1, r4c2, r4c3, r4c4, r4c5 = st.columns([2, 3, 4, 3, 2])
r4c1.markdown("4")
r4c2.markdown("💰 Smart Money")
r4c3.markdown("Stock Snapshot — delivery %, OI, smart money signals for all FNO stocks")
r4c4.markdown(_last_run_for("stock_snapshot"))
if r4c5.button("▶ Run", key="btn_stock", use_container_width=True):
    with st.spinner("Running stock snapshot…"):
        try:
            from backend.data_ingestion.pipeline import run_stock_pipeline
            from backend.data_ingestion.job_logger import log_start, log_finish
            rid = log_start("stock_snapshot", "Stock Snapshot (Delivery + OI)", "admin")
            run_stock_pipeline()
            log_finish(rid, "success")
            st.cache_data.clear()
            st.success("✅ Stock snapshot completed.")
        except Exception as e:
            log_finish(rid, "failed", error_msg=str(e))
            st.error(f"Pipeline failed: {e}")
    st.rerun()

# ── Row 5: Shareholding Refresh ───────────────────────────────────────────────
r5c1, r5c2, r5c3, r5c4, r5c5 = st.columns([2, 3, 4, 3, 2])
r5c1.markdown("5")
r5c2.markdown("📊 FII Accumulation")
r5c3.markdown("Shareholding Refresh — FII/DII/Promoter quarterly data for all sector stocks (~3–5 min)")
r5c4.markdown(_last_run_for("shareholding_quarterly"))
if r5c5.button("▶ Run", key="btn_sh", use_container_width=True):
    with st.spinner("Running shareholding pipeline…"):
        try:
            from backend.data_ingestion.shareholding_pipeline import run_shareholding_pipeline
            from backend.data_ingestion.job_logger import log_start, log_finish
            rid = log_start("shareholding_quarterly",
                            "Quarterly Shareholding Refresh (All Sector Stocks)", "admin")
            run_shareholding_pipeline(triggered_by="admin")
            log_finish(rid, "success")
            st.cache_data.clear()
            st.success("✅ Shareholding pipeline completed.")
        except Exception as e:
            log_finish(rid, "failed", error_msg=str(e))
            st.error(f"Pipeline failed: {e}")
    st.rerun()

# ── Row 6: AI Scan ───────────────────────────────────────────────────────────
r6c1, r6c2, r6c3, r6c4, r6c5 = st.columns([2, 3, 4, 3, 2])
r6c1.markdown("6")
r6c2.markdown("🤖 AI Forecast")
r6c3.markdown("AI Scan — XGBoost direction signal for all dashboard stocks · stored to DB (~3–5 min)")
r6c4.markdown(_last_run_for("ai_scan_daily"))
if r6c5.button("▶ Run", key="btn_ai", use_container_width=True):
    with st.spinner("Running AI scan for all dashboard stocks (~3–5 min)…"):
        try:
            from backend.data_ingestion.ai_scan_pipeline import run_ai_scan_pipeline
            from backend.data_ingestion.job_logger import log_start, log_finish
            rid = log_start("ai_scan_daily",
                            "AI Scan — XGBoost Direction (All Dashboard Stocks)", "admin")
            summary = run_ai_scan_pipeline(triggered_by="admin")
            log_finish(rid, "success", records_done=summary.get("total", 0))
            st.cache_data.clear()
            st.success(
                f"✅ AI scan complete — {summary.get('total', 0)} signals stored "
                f"({summary.get('bullish', 0)} bullish · {summary.get('bearish', 0)} bearish)"
            )
        except Exception as e:
            log_finish(rid, "failed", error_msg=str(e))
            st.error(f"AI scan failed: {e}")
    st.rerun()

st.markdown("---")

# ── Data Inventory ────────────────────────────────────────────────────────────
st.subheader("Data Inventory")
st.caption("Rows and date range stored per table. Click ▶ Fix to refresh stale data.")

def _table_stats(tbl: str, date_col: str) -> dict:
    try:
        con = sqlite3.connect(_DB_PATH)
        row = con.execute(
            f"SELECT COUNT(DISTINCT {date_col}), MIN({date_col}), MAX({date_col}) FROM {tbl}"
        ).fetchone()
        total = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        con.close()
        days, mn, mx = row
        return {"days": days or 0, "rows": total, "oldest": mn or "—", "latest": mx or "—"}
    except Exception:
        return {"days": 0, "rows": 0, "oldest": "—", "latest": "—"}

def _fmt_date(d: str) -> str:
    try:
        return date.fromisoformat(d[:10]).strftime("%d %b %Y")
    except Exception:
        return d or "—"

def _days_color(val):
    if val in ("—", "N/A"):
        return "#888888"
    try:
        n = int(val)
        if n == 0:   return "#EF5350"
        if n < 5:    return "#FF6D00"
        return "#00C853"
    except Exception:
        return "#888888"

# (Page, Table, date_col, label, pipeline_key)
# pipeline_key maps to the corrective action to run
_inventory = [
    ("📡 Market Pulse",    "market_breadth",        "trade_date", "Breadth (advance/decline)", "market_pulse"),
    ("📡 Market Pulse",    "sector_heatmap",         "trade_date", "Sector Heatmap",            "market_pulse"),
    ("📡 Market Pulse",    "rrg_snapshot",           "trade_date", "RRG Snapshot",              "market_pulse"),
    ("📈 Sector Analysis", "daily_sector_snapshot",  "date",       "Sector Prices & Returns",   "sector"),
    ("🏦 FII DII Flow",    "fii_dii_daily",          "date",       "FII/DII Daily Flow",        "sector"),
    ("💰 Smart Money",     "daily_stock_snapshot",   "date",       "Stock Delivery & OI",       "stock"),
    ("💰 Smart Money",     "smart_money_history",    "trade_date", "Smart Money Signals",       "stock"),
    ("📊 FII Accumulation","shareholding_pattern",   None,         "Shareholding Pattern",      "shareholding"),
    ("🤖 AI Forecast",    "ai_scan_results",         "scan_date",  "AI Scan Signals (XGBoost)", "ai_scan"),
]

def _run_pipeline(key: str):
    from backend.data_ingestion.job_logger import log_start, log_finish
    if key == "market_pulse":
        from backend.data_ingestion.market_pulse_pipeline import run_market_pulse_pipeline
        rid = log_start("market_pulse_snapshot", "Market Pulse Snapshot (Breadth + Heatmap + RRG)", "admin")
        summary = run_market_pulse_pipeline(triggered_by="admin")
        log_finish(rid, "success", records_done=summary.get("heatmap_sectors", 0))
        return f"Market Pulse updated — {summary.get('breadth_date','—')} · {summary.get('heatmap_sectors',0)} sectors"
    elif key == "sector":
        from backend.data_ingestion.pipeline import run_fii_dii_pipeline, run_breadth_pipeline, run_sector_pipeline
        from backend.storage.cache import invalidate_all
        rid = log_start("sector_snapshot", "Sector Snapshot (FII/DII + Breadth + Prices)", "admin")
        invalidate_all(); run_fii_dii_pipeline(); run_breadth_pipeline(); run_sector_pipeline()
        log_finish(rid, "success")
        st.cache_data.clear()
        return "Sector snapshot completed."
    elif key == "stock":
        from backend.data_ingestion.pipeline import run_stock_pipeline
        rid = log_start("stock_snapshot", "Stock Snapshot (Delivery + OI)", "admin")
        run_stock_pipeline()
        log_finish(rid, "success")
        st.cache_data.clear()
        return "Stock snapshot completed."
    elif key == "shareholding":
        from backend.data_ingestion.shareholding_pipeline import run_shareholding_pipeline
        rid = log_start("shareholding_quarterly",
                        "Quarterly Shareholding Refresh (All Sector Stocks)", "admin")
        run_shareholding_pipeline(triggered_by="admin")
        log_finish(rid, "success")
        st.cache_data.clear()
        return "Shareholding refresh completed."
    elif key == "ai_scan":
        from backend.data_ingestion.ai_scan_pipeline import run_ai_scan_pipeline
        rid = log_start("ai_scan_daily", "AI Scan — XGBoost Direction (All Dashboard Stocks)", "admin")
        summary = run_ai_scan_pipeline(triggered_by="admin")
        log_finish(rid, "success", records_done=summary.get("total", 0))
        st.cache_data.clear()
        return f"AI scan complete — {summary.get('total', 0)} signals ({summary.get('bullish', 0)} bullish · {summary.get('bearish', 0)} bearish)"

# Header row
hc = st.columns([2, 3, 1.2, 1.2, 1.8, 1.8, 1.2])
for col, hdr in zip(hc, ["Page", "Table / Data", "Days stored", "Total rows", "Oldest", "Latest", "Action"]):
    col.markdown(f"**{hdr}**")
st.divider()

_seen_pipelines = set()   # track which pipeline button already shown per group
for i, (page, tbl, dcol, label, pipe_key) in enumerate(_inventory):
    if dcol:
        s = _table_stats(tbl, dcol)
        days_val = s["days"] if s["days"] else 0
        days_disp = str(days_val)
        rows_disp = f"{s['rows']:,}"
        oldest_disp = _fmt_date(s["oldest"])
        latest_disp = _fmt_date(s["latest"])
    else:
        try:
            con = sqlite3.connect(_DB_PATH)
            total = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            con.close()
        except Exception:
            total = 0
        days_val = "N/A"; days_disp = "N/A"
        rows_disp = f"{total:,}"
        oldest_disp = latest_disp = "—"

    rc = st.columns([2, 3, 1.2, 1.2, 1.8, 1.8, 1.2])
    rc[0].markdown(page)
    rc[1].markdown(label)
    rc[2].markdown(f":{('red' if days_val == 0 else 'orange' if isinstance(days_val, int) and days_val < 5 else 'green')}[**{days_disp}**]")
    rc[3].markdown(rows_disp)
    rc[4].markdown(oldest_disp)
    rc[5].markdown(latest_disp)

    # Show Fix button once per pipeline group (not once per table row)
    btn_key = f"inv_fix_{pipe_key}_{i}"
    if rc[6].button("▶ Fix", key=btn_key, use_container_width=True):
        with st.spinner(f"Running pipeline for {label}…"):
            try:
                msg = _run_pipeline(pipe_key)
                st.success(f"✅ {msg}")
            except Exception as e:
                st.error(f"Failed: {e}")
        st.rerun()

st.markdown("---")

# ── Upcoming scheduled runs ────────────────────────────────────────────────────
st.subheader("Scheduled Job Calendar")

def _next_weekday(hour_ist: int, minute_ist: int = 0) -> str:
    """Return the next Mon–Fri occurrence of a given IST time."""
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(IST)
    target_today = now_ist.replace(hour=hour_ist, minute=minute_ist, second=0, microsecond=0)
    # Start from today if time hasn't passed, else tomorrow
    candidate = now_ist if now_ist < target_today else now_ist + timedelta(days=1)
    # Skip to next weekday (Mon=0 … Fri=4)
    while candidate.weekday() > 4:
        candidate += timedelta(days=1)
    days_away = (candidate.date() - now_ist.date()).days
    label = "today" if days_away == 0 else ("tomorrow" if days_away == 1 else f"in {days_away} days")
    return f"{candidate.strftime('%d %b %Y')} {hour_ist:02d}:{minute_ist:02d} IST ({label})"

def _next_quarterly(month_str: str, day: int) -> str:
    """Calculate next occurrence of a quarterly schedule."""
    today = date.today()
    months = [int(m) for m in month_str.split(",")]
    candidates = []
    for yr in [today.year, today.year + 1]:
        for m in months:
            try:
                d = date(yr, m, day)
                if d >= today:
                    candidates.append(d)
            except ValueError:
                pass
    if not candidates:
        return "—"
    nxt = min(candidates)
    days_away = (nxt - today).days
    label = "today" if days_away == 0 else f"in {days_away} days"
    return f"{nxt.strftime('%d %b %Y')} 07:00 IST ({label})"

schedule_data = {
    "Job": [
        "Sector Snapshot (FII/DII + Breadth + Prices)",
        "Stock Snapshot (Delivery + OI)",
        "Market Pulse Snapshot (Breadth + Heatmap + RRG)",
        "AI Scan — XGBoost Direction (All Dashboard Stocks)",
        "Quarterly Shareholding Refresh",
    ],
    "Pages": [
        "Home · Sector Analysis · FII DII Flow · FII Sectors",
        "Smart Money",
        "Market Pulse",
        "AI Forecast",
        "FII Accumulation",
    ],
    "Frequency": [
        "Mon–Fri daily",
        "Mon–Fri daily",
        "Mon–Fri daily",
        "Mon–Fri daily",
        "4× per year",
    ],
    "Cron (IST)": [
        "18:00  (6:00 PM)",
        "18:30  (6:30 PM)",
        "20:00  (8:00 PM)",
        "21:00  (9:00 PM)",
        "27th Jan / Apr / Jul / Oct @ 07:00",
    ],
    "Next Run": [
        _next_weekday(18, 0),
        _next_weekday(18, 30),
        _next_weekday(20, 0),
        _next_weekday(21, 0),
        _next_quarterly("1,4,7,10", 27),
    ],
    "Last Run": [
        _last_run_for("sector_snapshot"),
        _last_run_for("stock_snapshot"),
        _last_run_for("market_pulse_snapshot"),
        _last_run_for("ai_scan_daily"),
        _last_run_for("shareholding_quarterly"),
    ],
}

st.dataframe(pd.DataFrame(schedule_data), use_container_width=True, hide_index=True)

st.markdown("---")

# ── Data coverage summary ──────────────────────────────────────────────────────
st.subheader("Data Coverage")

try:
    con = _db()
    sh_count   = con.execute("SELECT COUNT(DISTINCT symbol) FROM shareholding_pattern").fetchone()[0]
    sh_last    = con.execute(
        "SELECT value FROM shareholding_refresh_meta WHERE key='last_full_refresh'"
    ).fetchone()
    fno_count  = con.execute("SELECT COUNT(*) FROM fno_symbols").fetchone()[0]
    sm_count   = con.execute("SELECT COUNT(DISTINCT symbol) FROM smart_money_history").fetchone()[0]
    con.close()

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Stocks with Shareholding Data", sh_count)
    d2.metric("Last Shareholding Refresh", sh_last[0][:10] if sh_last else "Never")
    d3.metric("F&O Symbols Tracked", fno_count)
    d4.metric("Smart Money History Stocks", sm_count)
except Exception as e:
    st.warning(f"Could not load coverage data: {e}")

st.markdown("---")

# ── Page Health Check ──────────────────────────────────────────────────────────
st.subheader("Page Health Check")
st.caption(
    "Validates data dependencies for every menu page — checks DB table freshness, "
    "row counts, and live market connectivity. Does not render pages in a browser."
)

_STATUS_ICON  = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}
_STATUS_COLOR = {"OK": "green", "WARN": "orange", "FAIL": "red"}

if st.button("🔍 Run Health Check", type="primary", use_container_width=False):
    from backend.health_check import run_health_check
    with st.spinner("Running health checks across all pages…"):
        t_start = time.time()
        results = run_health_check()
        total_elapsed = round(time.time() - t_start, 1)

    # ── Summary bar ──────────────────────────────────────────────────────────
    ok   = sum(1 for r in results if r["status"] == "OK")
    warn = sum(1 for r in results if r["status"] == "WARN")
    fail = sum(1 for r in results if r["status"] == "FAIL")

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Total Pages", len(results))
    sc2.metric("✅ OK",   ok)
    sc3.metric("⚠️ Warn", warn)
    sc4.metric("❌ Fail", fail)

    if fail == 0 and warn == 0:
        st.success(f"All {len(results)} pages healthy — completed in {total_elapsed}s")
    elif fail == 0:
        st.warning(f"{warn} page(s) have warnings — completed in {total_elapsed}s")
    else:
        st.error(f"{fail} page(s) failed, {warn} warning(s) — completed in {total_elapsed}s")

    st.markdown(f"*Checked {sum(len(r['checks']) for r in results)} data points in {total_elapsed}s*")
    st.divider()

    # ── Per-page report ───────────────────────────────────────────────────────
    for r in results:
        icon  = _STATUS_ICON[r["status"]]
        color = _STATUS_COLOR[r["status"]]
        with st.expander(
            f"{icon} {r['page']} — **:{color}[{r['status']}]** · {r['elapsed']}s",
            expanded=(r["status"] != "OK"),
        ):
            for label, status, detail in r["checks"]:
                ci = _STATUS_ICON[status]
                if status == "OK":
                    st.markdown(f"{ci} `{label}` — {detail}")
                elif status == "WARN":
                    st.warning(f"{ci} **{label}** — {detail}")
                else:
                    st.error(f"{ci} **{label}** — {detail}")
