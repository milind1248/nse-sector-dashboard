"""Admin Dashboard — job monitoring and manual pipeline triggers. Login required."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import sqlite3
import time
from datetime import datetime, date, timezone, timedelta

# Ensure all app-managed tables exist before any inventory queries run
from backend.storage.ai_scan_db import ensure_table as _ensure_ai_scan_table
_ensure_ai_scan_table()

_IST = timezone(timedelta(hours=5, minutes=30))
from config import DB_PATH as _DB_PATH

def _to_ist(ts) -> str:
    """Convert a UTC ISO timestamp string to IST display string."""
    if not ts or not isinstance(ts, str):
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_ist = dt.astimezone(_IST)
        return dt_ist.strftime("%d %b %Y %H:%M:%S IST")
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
import json

# ── Auth gate ─────────────────────────────────────────────────────────────────
require_admin()

# ── Announcement JSON helpers ─────────────────────────────────────────────────
_ANN_PATH = Path(__file__).parent.parent.parent / "data" / "announcement.json"

# ── Schedule config JSON helpers ──────────────────────────────────────────────
_SCH_PATH = Path(__file__).parent.parent.parent / "data" / "schedule_config.json"
_SCH_DEFAULTS = {
    "sector_snapshot":       {"hour": 18, "minute": 0},
    "stock_snapshot":        {"hour": 18, "minute": 30},
    "smart_money":           {"hour": 19, "minute": 0},
    "market_pulse_snapshot": {"hour": 20, "minute": 0},
    "ai_scan_daily":         {"hour": 21, "minute": 0},
    "gann_daily":            {"hour": 21, "minute": 30},
}

def _read_schedule_config() -> dict:
    try:
        return json.loads(_SCH_PATH.read_text())
    except Exception:
        return _SCH_DEFAULTS.copy()

def _write_schedule_config(cfg: dict):
    _SCH_PATH.write_text(json.dumps(cfg, indent=2))

def _read_announcement() -> dict:
    try:
        return json.loads(_ANN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False, "text": ""}

def _write_announcement(enabled: bool, text: str) -> None:
    _ANN_PATH.write_text(
        json.dumps({"enabled": enabled, "text": text.strip()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

# ── DB ────────────────────────────────────────────────────────────────────────
def _db():
    return sqlite3.connect(_DB_PATH)

# ── Header ────────────────────────────────────────────────────────────────────
h1, h2 = st.columns([5, 1])
with h1:
    st.title("🔐 Admin Dashboard")
with h2:
    st.write("")
    if st.button("🚪 Logout", width='stretch'):
        logout()
        st.rerun()

st.caption(
    f"Logged in · Session expires in **{session_remaining_minutes()} min** · "
    "All actions are logged. For internal use only."
)
st.markdown("---")

# ── Home Page Announcement ────────────────────────────────────────────────────
st.subheader("📢 Home Page Announcement")
_ann = _read_announcement()
ann_col1, ann_col2 = st.columns([5, 1])
with ann_col1:
    ann_text = st.text_area(
        "Announcement text (leave blank to show nothing)",
        value=_ann.get("text", ""),
        height=80,
        placeholder="e.g. Markets closed on 15 Aug 2026 — Independence Day holiday",
        key="ann_text",
    )
with ann_col2:
    st.write("")
    st.write("")
    ann_enabled = st.toggle("Enabled", value=_ann.get("enabled", False), key="ann_enabled")

if st.button("💾 Save Announcement", key="ann_save"):
    _write_announcement(ann_enabled, ann_text)
    st.success("Announcement saved." if (ann_enabled and ann_text.strip()) else "Announcement cleared / disabled.")
    st.cache_data.clear()

if _ann.get("enabled") and _ann.get("text", "").strip():
    st.caption(f"Currently live on Home page: **{_ann['text']}**")
else:
    st.caption("No announcement currently shown on Home page.")

st.markdown("---")

# ── Scheduler Status ───────────────────────────────────────────────────────────
st.subheader("🕐 Scheduler Status")

try:
    from backend.data_ingestion.scheduler import get_scheduler
    from datetime import timezone, timedelta
    _sched = get_scheduler()
    _IST_TZ = timezone(timedelta(hours=5, minutes=30))

    if _sched and _sched.running:
        st.success("🟢 Scheduler is **Running** — jobs will fire at configured IST times.")
        _jobs = _sched.get_jobs()
        if _jobs:
            _job_rows = []
            for j in _jobs:
                nrt = j.next_run_time
                if nrt:
                    nrt_ist = nrt.astimezone(_IST_TZ).strftime("%d %b %Y %H:%M IST")
                else:
                    nrt_ist = "—"
                _job_rows.append({"Job": j.name, "Next Fire (IST)": nrt_ist})
            st.dataframe(pd.DataFrame(_job_rows), width='stretch', hide_index=True)
    else:
        st.error("🔴 Scheduler is **Not Running** — no jobs will fire automatically. Restart the app.")
except Exception as e:
    st.error(f"🔴 Scheduler is **Not Running** — could not connect: {e}")

st.markdown("---")

# ── Job Run Log ────────────────────────────────────────────────────────────────
st.subheader("Job Run History")

@st.cache_data(ttl=30, show_spinner=False)
def _load_job_log() -> pd.DataFrame:
    try:
        con = _db()
        df = pd.read_sql_query(
            "SELECT job_id, job_name, triggered_by, started_at, finished_at, status, records_done, error_msg "
            "FROM job_run_log ORDER BY started_at DESC LIMIT 100",
            con,
        )
        con.close()
        return df
    except Exception:
        return pd.DataFrame()

try:
    from backend.data_ingestion.job_logger import purge_old_logs
    purge_old_logs(days=7)
except Exception:
    pass

job_df = _load_job_log()

if job_df.empty:
    st.info("No job runs recorded yet. Runs will appear here after the scheduler fires or you trigger a manual run below.")
else:
    # ── Today's summary cards (IST date) ─────────────────────────────────────
    _DAILY_JOB_IDS = {
        "sector_snapshot", "stock_snapshot", "market_pulse_snapshot",
        "ai_scan_daily", "gann_daily", "smart_money",
    }

    def _ist_date(ts) -> str:
        if not ts or not isinstance(ts, str):
            return ""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(_IST).date().isoformat()
        except Exception:
            return ""

    today_ist = datetime.now(_IST).date().isoformat()
    today_df  = job_df[job_df["started_at"].apply(_ist_date) == today_ist]

    manual_today  = today_df[today_df["triggered_by"] == "admin"]
    sched_today   = today_df[
        (today_df["triggered_by"] == "scheduler") &
        (today_df["job_id"].isin(_DAILY_JOB_IDS))
    ]

    man_success   = int((manual_today["status"] == "success").sum())
    man_total     = len(manual_today)
    sched_ran     = sched_today["job_id"].nunique()
    sched_success = int((sched_today["status"] == "success").sum())
    failed_today  = int((today_df["status"] == "failed").sum())
    running_now   = int((job_df["status"] == "running").sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Manual Today",    f"{man_success} ✓ / {man_total} runs",
              help="Admin-triggered runs today (IST) — success / total")
    c2.metric("Scheduled Today", f"{sched_ran} / 6 jobs",
              delta=f"{sched_success} success",
              help="Daily scheduler jobs that ran today out of 6 expected")
    c3.metric("Failed Today",    failed_today,
              help="Failed runs today (manual + scheduled)")
    c4.metric("Running Now",     running_now,
              help="Jobs currently in 'running' state")

    st.caption(f"Today (IST): **{today_ist}**  ·  Stats above are for today only · Full log below")

    # Format display — convert UTC timestamps to IST
    display = job_df.copy()
    display.columns = ["job_id_raw", "Job", "Triggered By", "started_raw", "finished_raw", "Status", "Records", "Error"]
    display = display.drop(columns=["job_id_raw"])
    display["Started (IST)"]  = display["started_raw"].apply(_to_ist)
    display["Finished (IST)"] = display["finished_raw"].apply(_to_ist)
    display = display.drop(columns=["started_raw", "finished_raw"])
    display["Triggered By"] = display["Triggered By"].map({
        "admin":     "👤 Admin",
        "scheduler": "🤖 Scheduler",
    }).fillna(display["Triggered By"])
    display = display[["Job", "Triggered By", "Started (IST)", "Finished (IST)", "Status", "Records", "Error"]]

    def _status_color(val):
        if val == "success":  return "color: #43A047; font-weight:600"
        if val == "failed":   return "color: #E53935; font-weight:600"
        if val == "running":  return "color: #FB8C00; font-weight:600"
        return ""

    def _trigger_color(val):
        if "Admin"     in str(val): return "color: #64B5F6; font-weight:600"
        if "Scheduler" in str(val): return "color: #aaaaaa; font-weight:500"
        return ""

    styled = (
        display.style
        .map(_status_color,  subset=["Status"])
        .map(_trigger_color, subset=["Triggered By"])
        .format({"Records": lambda v: f"{int(v):,}" if v and not pd.isna(v) else "–",
                 "Started (IST)": lambda v: v or "—",
                 "Finished (IST)": lambda v: v or "—"}, na_rep="—")
    )
    st.dataframe(styled, width='stretch', height=320, hide_index=True)

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


def _call_pipeline(job_id: str, detail_ph) -> None:
    """Dispatch a single pipeline by job_id. Raises on failure."""
    _db_path = str(_DB_PATH)
    if job_id == "market_pulse_snapshot":
        from backend.data_ingestion.market_pulse_pipeline import run_market_pulse_pipeline
        run_market_pulse_pipeline(triggered_by="admin")

    elif job_id == "sector_snapshot":
        from backend.data_ingestion.pipeline import (
            run_fii_dii_pipeline, run_breadth_pipeline, run_sector_pipeline)
        from backend.storage.cache import invalidate_all
        invalidate_all()
        run_fii_dii_pipeline()
        run_breadth_pipeline()
        run_sector_pipeline()

    elif job_id == "index_stocks_sync":
        from backend.data_ingestion.sector_sync import sync_all
        sync_all(_db_path)

    elif job_id == "stock_snapshot":
        from backend.data_ingestion.pipeline import run_stock_pipeline
        run_stock_pipeline()

    elif job_id == "shareholding_quarterly":
        from backend.data_ingestion.shareholding_pipeline import run_shareholding_pipeline
        run_shareholding_pipeline(triggered_by="admin")

    elif job_id == "ai_scan_daily":
        from backend.data_ingestion.ai_scan_pipeline import run_ai_scan_pipeline
        run_ai_scan_pipeline(triggered_by="admin")

    elif job_id == "gann_daily":
        from backend.data_ingestion.gann_pipeline import run_gann_pipeline, _all_symbols
        _total = len(_all_symbols())

        def _cb(done, tot, sym):
            pct = int(done / tot * 100)
            detail_ph.caption(f"Gann: {done}/{tot} stocks ({pct}%) — last: **{sym}**")

        run_gann_pipeline(triggered_by="admin", progress_callback=_cb)


def _run_master_job() -> None:
    """Run all 7 pipelines sequentially with live status table."""
    from backend.data_ingestion.job_logger import log_start, log_finish

    MASTER_JOBS = [
        {"id": "market_pulse_snapshot", "name": "Market Pulse Snapshot",
         "job_name": "Market Pulse Snapshot (Breadth + Heatmap + RRG)"},
        {"id": "sector_snapshot",       "name": "Sector Snapshot",
         "job_name": "Sector Snapshot (FII/DII + Breadth + Prices)"},
        {"id": "index_stocks_sync",     "name": "Index Stocks Sync",
         "job_name": "Index Stocks Sync (NSE + Yahoo Finance)"},
        {"id": "stock_snapshot",        "name": "Stock Snapshot",
         "job_name": "Stock Snapshot (Delivery + OI)"},
        {"id": "smart_money",           "name": "Smart Money Signals",
         "job_name": "Smart Money Signals (F&O Delivery + OI)"},
        {"id": "ai_scan_daily",         "name": "AI Scan",
         "job_name": "AI Scan — XGBoost Direction (All Dashboard Stocks)"},
        {"id": "gann_daily",            "name": "Gann Cache",
         "job_name": "Gann Analysis — All 5 Methods (All Dashboard Stocks)"},
    ]
    n = len(MASTER_JOBS)

    overall_bar  = st.progress(0, text="Starting Master Job…")
    status_table = st.empty()
    job_detail   = st.empty()

    results = [{"status": "⏳ Pending", "duration": "—"} for _ in MASTER_JOBS]

    def _render_table():
        rows = ["| # | Job | Frequency | Scheduled At | Status | Duration |",
                "|---|---|---|---|---|---|"]
        meta = [
            ("Daily (Mon–Fri)", "8:00 PM"),
            ("Daily (Mon–Fri)", "6:00 PM"),
            ("Manual only",     "—"),
            ("Daily (Mon–Fri)", "6:30 PM"),
            ("Daily (Mon–Fri)", "Manual trigger"),
            ("Daily (Mon–Fri)", "9:00 PM"),
            ("Daily (Mon–Fri)", "9:30 PM"),
        ]
        for i, job in enumerate(MASTER_JOBS):
            freq, sched = meta[i]
            rows.append(
                f"| {i+1} | {job['name']} | {freq} | {sched} | {results[i]['status']} | {results[i]['duration']} |"
            )
        status_table.markdown("\n".join(rows))

    _render_table()

    for idx, job in enumerate(MASTER_JOBS):
        pct_start = int(idx / n * 100)
        overall_bar.progress(pct_start, text=f"Job {idx+1}/{n} — {job['name']}…")
        results[idx]["status"] = "🔄 Running…"
        _render_table()

        t0 = time.time()
        _rid = None
        try:
            _rid = log_start(job["id"], job["job_name"], triggered_by="admin")
            _call_pipeline(job["id"], job_detail)
            elapsed = round(time.time() - t0)
            log_finish(_rid, "success")
            results[idx]["status"]   = "✅ Done"
            results[idx]["duration"] = f"{elapsed // 60}m {elapsed % 60}s"
        except Exception as e:
            elapsed = round(time.time() - t0)
            if _rid:
                try:
                    log_finish(_rid, "failed", error_msg=str(e))
                except Exception:
                    pass
            results[idx]["status"]   = "❌ Failed"
            results[idx]["duration"] = f"{elapsed // 60}m {elapsed % 60}s"
            st.warning(f"⚠️ **{job['name']}** failed: {e} — continuing with next job.")
        finally:
            job_detail.empty()
            _render_table()

    overall_bar.progress(100, text=f"✅ Master Job complete — all {n} jobs finished.")
    st.cache_data.clear()
    st.success("All pipelines refreshed successfully. Page will reload now.")
    st.rerun()


# ── Master Job ─────────────────────────────────────────────────────────────────
with st.expander("🚀 Master Job — Refresh All Data", expanded=False):
    st.caption(
        "Runs all 7 pipelines sequentially. Each job starts only after the previous one finishes. "
        "Use when the site is out of sync after downtime. Estimated runtime: 40–60 minutes."
    )
    _mj_cfg = _read_schedule_config()
    def _mj_t(job_id):
        c = _mj_cfg.get(job_id, _SCH_DEFAULTS[job_id])
        h, m = c["hour"], c["minute"]
        suffix = "AM" if h < 12 else "PM"
        return f"{h % 12 or 12}:{m:02d} {suffix}"
    st.markdown(
        "| # | Pipeline | Frequency | Scheduled At (IST) | Est. Time |\n"
        "|---|---|---|---|---|\n"
        f"| 1 | Market Pulse Snapshot | Daily (Mon–Fri) | {_mj_t('market_pulse_snapshot')} | 3–5 min |\n"
        f"| 2 | Sector Snapshot | Daily (Mon–Fri) | {_mj_t('sector_snapshot')} | 2–3 min |\n"
        "| 3 | Index Stocks Sync | Manual only | — | 5–8 min |\n"
        f"| 4 | Stock Snapshot | Daily (Mon–Fri) | {_mj_t('stock_snapshot')} | 2–3 min |\n"
        f"| 5 | Smart Money Signals | Daily (Mon–Fri) | {_mj_t('smart_money')} | 5–10 min |\n"
        f"| 6 | AI Scan | Daily (Mon–Fri) | {_mj_t('ai_scan_daily')} | 15–27 min |\n"
        f"| 7 | Gann Cache | Daily (Mon–Fri) | {_mj_t('gann_daily')} | 10–15 min |"
    )
    if st.button("▶ Run Master Job", type="primary", key="master_job_btn"):
        _run_master_job()

st.markdown("---")

# ── Page Test Runner ────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent.parent


def _render_test_report(results: list[dict]) -> None:
    """Render a page-wise test report table inside the Page Test Runner expander."""
    if not results:
        return

    ok_n   = sum(1 for r in results if r["status"] == "OK")
    warn_n = sum(1 for r in results if r["status"] == "WARN")
    fail_n = sum(1 for r in results if r["status"] == "FAIL")
    total_tabs = sum(r.get("tabs", 0) for r in results)
    total_secs = sum(r.get("elapsed") or 0 for r in results)
    tested_at  = results[0].get("tested_at", "") if results else ""

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("✅ OK",    ok_n)
    sc2.metric("⚠️ WARN", warn_n)
    sc3.metric("❌ FAIL",  fail_n)
    sc4.metric("Tabs Covered", total_tabs)

    mins, secs = divmod(int(total_secs), 60)
    st.caption(
        f"{len(results)} pages tested · {total_tabs} tabs covered · "
        f"Total time: {mins}m {secs}s" +
        (f" · Tested at: {_to_ist(tested_at)}" if tested_at else "")
    )

    # Per-page table
    rows = ["| Page | Status | Load (s) | Tabs | Errors |",
            "|------|--------|----------|------|--------|"]
    for r in results:
        icon = "✅" if r["status"] == "OK" else ("⚠️" if r["status"] == "WARN" else "❌")
        err_count = len(r.get("errors", []))
        err_cell  = str(err_count) if err_count else "—"
        rows.append(
            f"| {r['page']} | {icon} {r['status']} | {r.get('elapsed', '—')} "
            f"| {r.get('tabs', 0)} | {err_cell} |"
        )
    st.markdown("\n".join(rows))

    # Expandable error details for failed/warn pages
    for r in results:
        if r.get("errors"):
            with st.expander(f"{'❌' if r['status']=='FAIL' else '⚠️'} {r['page']} — error details"):
                for err in r["errors"]:
                    st.error(f"**{err['type']}:** {err['message']}")


def _load_latest_test_run() -> list[dict]:
    try:
        from app.utils.page_test_db import load_latest_run
        return load_latest_run()
    except Exception:
        return []


with st.expander("🧪 Page Test Runner", expanded=False):
    st.caption(
        "Loads all 16 pages using Streamlit's AppTest — catches rendering errors and tab failures. "
        "All tab content is exercised in a single run per page. Add new pages to `backend/page_tester.py`."
    )

    # Show previous run results if available
    _prior_results = st.session_state.get("_page_test_results") or _load_latest_test_run()
    if _prior_results:
        st.markdown("**Last Run Results:**")
        _render_test_report(_prior_results)
        st.markdown("---")

    if st.button("▶ Run Page Tests", type="primary", key="btn_page_tests"):
        from backend.data_ingestion.job_logger import log_start, log_finish
        _pt_rid = log_start("page_test", "Page Test Runner (All Pages)", triggered_by="admin")
        try:
            from backend.page_tester import run_page_tests
            from app.utils.page_test_db import store_test_results
            with st.spinner("Testing all pages — this takes 5–15 minutes…"):
                _pt_results = run_page_tests(str(_ROOT))
            store_test_results(run_id=_pt_rid, results=_pt_results)
            _fail_n = sum(1 for r in _pt_results if r["status"] == "FAIL")
            log_finish(_pt_rid, "success", records_done=len(_pt_results))
            st.session_state["_page_test_results"] = _pt_results
            st.rerun()
        except Exception as _pt_e:
            log_finish(_pt_rid, "failed", error_msg=str(_pt_e))
            st.error(f"Page test runner failed: {_pt_e}")

st.markdown("---")

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
if r1c5.button("▶ Run", key="btn_mps", width='stretch'):
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
if r2c5.button("▶ Run", key="btn_sector", width='stretch'):
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
if r3c5.button("▶ Run", key="btn_idx", width='stretch'):
    with st.spinner("Syncing Index Stocks from NSE India + market price feeds…"):
        try:
            from backend.data_ingestion.sector_sync import sync_all
            from backend.data_ingestion.job_logger import log_start, log_finish
            rid = log_start("index_stocks_sync", "Index Stocks Sync (NSE + Yahoo Finance)", "admin")
            result = sync_all(str(_DB_PATH))
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
if r4c5.button("▶ Run", key="btn_stock", width='stretch'):
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

# ── Row 4b: Smart Money Signals ───────────────────────────────────────────────
r4bc1, r4bc2, r4bc3, r4bc4, r4bc5 = st.columns([2, 3, 4, 3, 2])
r4bc1.markdown("4b")
r4bc2.markdown("💰 Smart Money")
r4bc3.markdown("Smart Money Signals — F&O delivery %, futures OI for all F&O symbols (90-day rolling)")
r4bc4.markdown(_last_run_for("smart_money"))
if r4bc5.button("▶ Run", key="btn_sm_signals", width='stretch'):
    with st.spinner("Running Smart Money Signals pipeline (~3–5 min)…"):
        rid = None
        try:
            from backend.data_ingestion.smart_money_pipeline import run_smart_money_pipeline
            from backend.data_ingestion.job_logger import log_start, log_finish
            rid = log_start("smart_money", "Smart Money Signals (F&O Delivery + OI)", "admin")
            summary = run_smart_money_pipeline(triggered_by="admin")
            log_finish(rid, "success", records_done=summary.get("rows_added", 0))
            st.cache_data.clear()
            st.success(
                f"✅ Smart Money updated — {summary.get('total', 0)} symbols · "
                f"{summary.get('rows_added', 0)} new rows in {summary.get('elapsed_sec', 0)}s"
            )
        except Exception as e:
            if rid:
                log_finish(rid, "failed", error_msg=str(e))
            st.error(f"Pipeline failed: {e}")
    st.rerun()

# ── Row 5: Shareholding Refresh ───────────────────────────────────────────────
r5c1, r5c2, r5c3, r5c4, r5c5 = st.columns([2, 3, 4, 3, 2])
r5c1.markdown("5")
r5c2.markdown("📊 FII Accumulation")
r5c3.markdown("Shareholding Refresh — FII/DII/Promoter quarterly data for all sector stocks (~3–5 min)")
r5c4.markdown(_last_run_for("shareholding_quarterly"))
if r5c5.button("▶ Run", key="btn_sh", width='stretch'):
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
if r6c5.button("▶ Run", key="btn_ai", width='stretch'):
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

# ── Row 7: Gann Analysis Cache ───────────────────────────────────────────────
r7c1, r7c2, r7c3, r7c4, r7c5 = st.columns([2, 3, 4, 3, 2])
r7c1.markdown("7")
r7c2.markdown("🔢 Gann Analysis")
from backend.data_ingestion.gann_pipeline import _all_symbols as _gann_symbols
_gann_total = len(_gann_symbols())
r7c3.markdown(f"Gann Cache — all 5 methods for all {_gann_total} dashboard stocks · stored to DB (~5–8 min)")
r7c4.markdown(_last_run_for("gann_daily"))
if r7c5.button("▶ Run", key="btn_gann", width='stretch'):
    _gann_rid = None
    try:
        from backend.data_ingestion.gann_pipeline import run_gann_pipeline
        from backend.data_ingestion.job_logger import log_start, log_finish
        _gann_rid = log_start("gann_daily",
                        f"Gann Analysis — All 5 Methods ({_gann_total} Dashboard Stocks)", "admin")
        _gann_bar = st.progress(0, text=f"Starting Gann pipeline — {_gann_total} stocks to process…")
        _gann_status = st.empty()

        def _gann_progress(done, total, sym):
            pct = int(done / total * 100)
            _gann_bar.progress(pct, text=f"Processing {done} / {total} stocks ({pct}%)…")
            _gann_status.caption(f"Last completed: **{sym}**  ·  {total - done} remaining")

        summary = run_gann_pipeline(triggered_by="admin",
                                     progress_callback=_gann_progress)
        log_finish(_gann_rid, "success", records_done=summary.get("success", 0))
        _gann_bar.progress(100, text=f"Done! All {_gann_total} stocks processed.")
        _gann_status.empty()
        st.cache_data.clear()
        st.success(
            f"✅ Gann pipeline complete — "
            f"{summary.get('success', 0)} cached · {summary.get('failed', 0)} failed "
            f"· {summary.get('elapsed_sec', 0):.0f}s"
        )
        st.rerun()
    except Exception as e:
        if _gann_rid:
            try:
                log_finish(_gann_rid, "failed", error_msg=str(e))
            except Exception:
                pass
        st.error(f"❌ Gann pipeline error: {e}")
        st.exception(e)

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
    ("💰 Smart Money",     "smart_money_history",    "trade_date", "Smart Money Signals",       "smart_money"),
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
    elif key == "smart_money":
        from backend.data_ingestion.smart_money_pipeline import run_smart_money_pipeline
        rid = log_start("smart_money", "Smart Money Signals (F&O Delivery + OI)", "admin")
        summary = run_smart_money_pipeline(triggered_by="admin")
        log_finish(rid, "success", records_done=summary.get("rows_added", 0))
        st.cache_data.clear()
        return (f"Smart Money updated — {summary.get('total', 0)} symbols · "
                f"{summary.get('rows_added', 0)} new rows · {summary.get('elapsed_sec', 0)}s")
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
    if rc[6].button("▶ Fix", key=btn_key, width='stretch'):
        with st.spinner(f"Running pipeline for {label}…"):
            try:
                msg = _run_pipeline(pipe_key)
                st.success(f"✅ {msg}")
            except Exception as e:
                st.error(f"Failed: {e}")
        st.rerun()

st.markdown("---")

# ── Schedule Configuration ─────────────────────────────────────────────────────
st.subheader("⏰ Schedule Configuration")
st.caption("Set the daily trigger time (IST) for each scheduled job. Save → changes reflect in the calendar below. Restart the scheduler process to apply new times to the live runner.")

_sch_msg = st.session_state.pop("_sch_saved_msg", None)
if _sch_msg:
    if _sch_msg[0] == "ok":
        st.success(_sch_msg[1])
    else:
        st.warning(_sch_msg[1])

_sch_cfg = _read_schedule_config()

_SCH_JOBS = [
    ("sector_snapshot",       "Sector Snapshot (FII/DII + Breadth + Prices)", "6:00 PM"),
    ("stock_snapshot",        "Stock Snapshot (Delivery + OI)",                "6:30 PM"),
    ("smart_money",           "Smart Money Signals (F&O Delivery + OI)",       "7:00 PM"),
    ("market_pulse_snapshot", "Market Pulse Snapshot (Breadth + Heatmap + RRG)", "8:00 PM"),
    ("ai_scan_daily",         "AI Scan — XGBoost Direction (All Stocks)",      "9:00 PM"),
    ("gann_daily",            "Gann Cache — All 5 Methods (All Stocks)",        "9:30 PM"),
]

_hour_options   = list(range(0, 24))
_minute_options = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]

with st.form("schedule_config_form"):
    new_cfg = {}
    hdr1, hdr2, hdr3, hdr4 = st.columns([3, 1, 1, 2])
    hdr1.markdown("**Job**")
    hdr2.markdown("**Hour (IST)**")
    hdr3.markdown("**Minute**")
    hdr4.markdown("**Current Time**")

    for job_id, label, _default_label in _SCH_JOBS:
        cur_h = _sch_cfg.get(job_id, _SCH_DEFAULTS[job_id])["hour"]
        cur_m = _sch_cfg.get(job_id, _SCH_DEFAULTS[job_id])["minute"]
        c1, c2, c3, c4 = st.columns([3, 1, 1, 2])
        c1.markdown(label)
        sel_h = c2.selectbox("H", _hour_options, index=_hour_options.index(cur_h),
                              key=f"sch_h_{job_id}", label_visibility="collapsed")
        # nearest supported minute
        nearest_m = min(_minute_options, key=lambda x: abs(x - cur_m))
        sel_m = c3.selectbox("M", _minute_options, index=_minute_options.index(nearest_m),
                              key=f"sch_m_{job_id}", label_visibility="collapsed")
        c4.markdown(f"`{cur_h:02d}:{cur_m:02d}` → `{sel_h:02d}:{sel_m:02d}`")
        new_cfg[job_id] = {"hour": sel_h, "minute": sel_m}

    if st.form_submit_button("💾 Save Schedule", type="primary"):
        _write_schedule_config(new_cfg)
        try:
            from backend.data_ingestion.scheduler import reschedule_job
            failed = []
            for job_id, times in new_cfg.items():
                ok = reschedule_job(job_id, times["hour"], times["minute"])
                if not ok:
                    failed.append(job_id)
            if failed:
                st.session_state["_sch_saved_msg"] = ("warn", f"✅ Saved to config. Could not reschedule live: {', '.join(failed)} — restart app to apply.")
            else:
                st.session_state["_sch_saved_msg"] = ("ok", "✅ Schedule saved and applied to live scheduler instantly. No restart needed.")
        except Exception as e:
            st.session_state["_sch_saved_msg"] = ("warn", f"✅ Saved to config. Live reschedule failed ({e}) — restart app to apply.")
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

_cal_cfg = _read_schedule_config()

def _hm(job_id):
    c = _cal_cfg.get(job_id, _SCH_DEFAULTS[job_id])
    return c["hour"], c["minute"]

def _fmt_time(job_id):
    h, m = _hm(job_id)
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h:02d}:{m:02d}  ({h12}:{m:02d} {suffix})"

schedule_data = {
    "Job": [
        "Sector Snapshot (FII/DII + Breadth + Prices)",
        "Stock Snapshot (Delivery + OI)",
        "Smart Money Signals (F&O Delivery + OI)",
        "Market Pulse Snapshot (Breadth + Heatmap + RRG)",
        "AI Scan — XGBoost Direction (All Dashboard Stocks)",
        "Quarterly Shareholding Refresh",
    ],
    "Pages": [
        "Home · Sector Analysis · FII DII Flow · FII Sectors",
        "Smart Money",
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
        "Mon–Fri daily",
        "4× per year",
    ],
    "Cron (IST)": [
        _fmt_time("sector_snapshot"),
        _fmt_time("stock_snapshot"),
        _fmt_time("smart_money"),
        _fmt_time("market_pulse_snapshot"),
        _fmt_time("ai_scan_daily"),
        "27th Jan / Apr / Jul / Oct @ 07:00",
    ],
    "Next Run": [
        _next_weekday(*_hm("sector_snapshot")),
        _next_weekday(*_hm("stock_snapshot")),
        _next_weekday(*_hm("smart_money")),
        _next_weekday(*_hm("market_pulse_snapshot")),
        _next_weekday(*_hm("ai_scan_daily")),
        _next_quarterly("1,4,7,10", 27),
    ],
    "Last Run": [
        _last_run_for("sector_snapshot"),
        _last_run_for("stock_snapshot"),
        _last_run_for("smart_money"),
        _last_run_for("market_pulse_snapshot"),
        _last_run_for("ai_scan_daily"),
        _last_run_for("shareholding_quarterly"),
    ],
}

st.dataframe(pd.DataFrame(schedule_data), width='stretch', hide_index=True)

st.markdown("---")

# ── Data coverage summary ──────────────────────────────────────────────────────
st.subheader("Data Coverage")

def _safe_query(sql, default=0):
    try:
        con = _db(); r = con.execute(sql).fetchone(); con.close()
        return r[0] if r else default
    except Exception:
        return default

sh_count  = _safe_query("SELECT COUNT(DISTINCT symbol) FROM shareholding_pattern")
sh_last   = _safe_query("SELECT value FROM shareholding_refresh_meta WHERE key='last_full_refresh'", None)
fno_count = _safe_query("SELECT COUNT(*) FROM fno_symbols")
sm_count  = _safe_query("SELECT COUNT(DISTINCT symbol) FROM smart_money_history")

d1, d2, d3, d4 = st.columns(4)
d1.metric("Stocks with Shareholding Data", sh_count or "—")
d2.metric("Last Shareholding Refresh", sh_last[:10] if sh_last else "Never")
d3.metric("F&O Symbols Tracked", fno_count or "—")
d4.metric("Smart Money History Stocks", sm_count or "—")

st.markdown("---")

# ── Page Health Check ──────────────────────────────────────────────────────────
st.subheader("Page Health Check")
st.caption(
    "Validates data dependencies for every menu page — checks DB table freshness, "
    "row counts, and live market connectivity. Does not render pages in a browser."
)

_STATUS_ICON  = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}
_STATUS_COLOR = {"OK": "green", "WARN": "orange", "FAIL": "red"}

if st.button("🔍 Run Health Check", type="primary", width='content'):
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
