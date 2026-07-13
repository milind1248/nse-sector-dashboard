"""APScheduler-based daily job runner."""
import hashlib
import json
import logging
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_SCHEDULE_CFG_PATH = Path(__file__).parent.parent.parent / "data" / "schedule_config.json"

def _load_schedule_config() -> dict:
    """Load job times from JSON config. Falls back to defaults if file missing."""
    _defaults = {
        "sector_snapshot":       {"hour": 18, "minute": 0},
        "stock_snapshot":        {"hour": 18, "minute": 30},
        "smart_money":           {"hour": 19, "minute": 0},
        "market_pulse_snapshot": {"hour": 20, "minute": 0},
        "ai_scan_daily":         {"hour": 21, "minute": 0},
        "gann_daily":            {"hour": 21, "minute": 30},
    }
    try:
        return json.loads(_SCHEDULE_CFG_PATH.read_text())
    except Exception:
        return _defaults
from backend.data_ingestion.pipeline import (
    run_fii_dii_pipeline, run_breadth_pipeline,
    run_sector_pipeline, run_stock_pipeline,
)
from backend.data_ingestion.shareholding_pipeline import run_shareholding_pipeline
from backend.data_ingestion.ai_scan_pipeline import run_ai_scan_pipeline
from backend.data_ingestion.market_pulse_pipeline import run_market_pulse_pipeline
from backend.data_ingestion.gann_pipeline import run_gann_pipeline
from backend.data_ingestion.smart_money_pipeline import run_smart_money_pipeline
from backend.data_ingestion.job_logger import log_start, log_finish
from backend.storage.cache import invalidate_all
from backend.storage.db import get_conn
from config import SCHEDULE_TZ

logger = logging.getLogger(__name__)

# Cluster-wide advisory lock key — one process, anywhere, holds this at a time.
# Derived from a fixed name via sha256 (not Python's hash(), which is randomized
# per-process and would never match across processes).
_ADVISORY_LOCK_NAME = "nse_dashboard_scheduler"
_ADVISORY_LOCK_KEY = int.from_bytes(
    hashlib.sha256(_ADVISORY_LOCK_NAME.encode()).digest()[:8], "big", signed=True
)

# Held open for the process lifetime once acquired — never closed explicitly.
# Postgres session-level advisory locks release automatically when the holding
# connection disconnects, so a crashed process can't leave the lock stuck.
_lock_conn = None


def _try_acquire_scheduler_lock() -> bool:
    """Try to grab the cluster-wide scheduler advisory lock via a dedicated
    connection. Returns True (and keeps the connection open) if this process
    now owns it; False if another process already holds it."""
    global _lock_conn
    conn = get_conn()
    cur = conn.execute("SELECT pg_try_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
    acquired = bool(cur.fetchone()[0])
    if acquired:
        _lock_conn = conn
        return True
    conn.close()
    return False


def _logged(job_id: str, job_name: str, fn):
    """Wrap a pipeline function with job_run_log DB logging."""
    def _run():
        row_id = log_start(job_id, job_name, triggered_by="scheduler")
        try:
            fn()
            log_finish(row_id, "success")
        except Exception as e:
            log_finish(row_id, "failed", error_msg=str(e))
            logger.error(f"Job {job_id} failed: {e}")
            raise
    return _run


def _register_jobs(scheduler):
    """Register all cron jobs onto a scheduler instance (blocking or background)."""
    cfg = _load_schedule_config()
    logger.info(f"Schedule config loaded: {cfg}")

    def _t(job_id):
        return cfg[job_id]["hour"], cfg[job_id]["minute"]

    h, m = _t("sector_snapshot")
    scheduler.add_job(
        _logged(
            "sector_snapshot",
            "Sector Snapshot (FII/DII + Breadth + Prices)",
            lambda: (invalidate_all(), run_fii_dii_pipeline(), run_breadth_pipeline(), run_sector_pipeline()),
        ),
        CronTrigger(hour=h, minute=m, day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        id="sector_snapshot",
        name=f"Sector snapshot @ {h:02d}:{m:02d}",
    )

    h, m = _t("stock_snapshot")
    scheduler.add_job(
        _logged("stock_snapshot", "Stock Snapshot (Delivery + OI)", run_stock_pipeline),
        CronTrigger(hour=h, minute=m, day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        id="stock_snapshot",
        name=f"Stock snapshot @ {h:02d}:{m:02d}",
    )

    h, m = _t("smart_money")
    scheduler.add_job(
        _logged(
            "smart_money",
            "Smart Money Signals (F&O Delivery + OI)",
            lambda: run_smart_money_pipeline(triggered_by="scheduler"),
        ),
        CronTrigger(hour=h, minute=m, day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        id="smart_money",
        name=f"Smart Money Signals @ {h:02d}:{m:02d}",
    )

    h, m = _t("market_pulse_snapshot")
    scheduler.add_job(
        _logged(
            "market_pulse_snapshot",
            "Market Pulse Snapshot (Breadth + Heatmap + RRG)",
            lambda: run_market_pulse_pipeline(triggered_by="scheduler"),
        ),
        CronTrigger(hour=h, minute=m, day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        id="market_pulse_snapshot",
        name=f"Market Pulse snapshot @ {h:02d}:{m:02d}",
    )

    h, m = _t("ai_scan_daily")
    scheduler.add_job(
        _logged(
            "ai_scan_daily",
            "AI Scan — XGBoost Direction (All Dashboard Stocks)",
            run_ai_scan_pipeline,
        ),
        CronTrigger(hour=h, minute=m, day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        id="ai_scan_daily",
        name=f"AI scan @ {h:02d}:{m:02d}",
    )

    h, m = _t("gann_daily")
    scheduler.add_job(
        _logged(
            "gann_daily",
            "Gann Analysis — All 5 Methods (All Dashboard Stocks)",
            run_gann_pipeline,
        ),
        CronTrigger(hour=h, minute=m, day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        id="gann_daily",
        name=f"Gann analysis @ {h:02d}:{m:02d}",
    )

    scheduler.add_job(
        _logged(
            "shareholding_quarterly",
            "Quarterly Shareholding Refresh (All Sector Stocks)",
            run_shareholding_pipeline,
        ),
        CronTrigger(month="1,4,7,10", day=27, hour=7, minute=0, timezone=SCHEDULE_TZ),
        id="shareholding_quarterly",
        name="Quarterly shareholding refresh @ 7 AM IST on 27th Jan/Apr/Jul/Oct",
        misfire_grace_time=86400,
    )


def start_scheduler_background():
    """Start scheduler as a background thread — called once from run.py at boot."""
    scheduler = BackgroundScheduler(timezone=SCHEDULE_TZ)
    _register_jobs(scheduler)
    scheduler.start()
    logger.info("Background scheduler started inside Streamlit process.")
    return scheduler


# Module-level singleton — guarantees exactly one scheduler per Python process.
# No Streamlit dependency — backend modules must not import st.
_scheduler_instance = None


def get_scheduler():
    """Return the singleton BackgroundScheduler, starting it if not yet running.

    Guards startup with a Postgres advisory lock so only one process cluster-wide
    (across separate local Streamlit instances, stray leftover processes, etc.)
    ever runs the scheduler against the shared DB. If another process already
    holds the lock, returns None instead of starting a competing scheduler.
    """
    global _scheduler_instance
    if _scheduler_instance is not None and _scheduler_instance.running:
        return _scheduler_instance
    if not _try_acquire_scheduler_lock():
        logger.info(
            "Scheduler advisory lock already held by another process — "
            "skipping scheduler start here."
        )
        return None
    _scheduler_instance = start_scheduler_background()
    return _scheduler_instance


def reschedule_job(job_id: str, hour: int, minute: int):
    """Update a running job's trigger without restarting the app."""
    try:
        sched = get_scheduler()
        sched.reschedule_job(
            job_id,
            trigger=CronTrigger(hour=hour, minute=minute,
                                day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        )
        logger.info(f"Rescheduled {job_id} → {hour:02d}:{minute:02d} IST")
        return True
    except Exception as e:
        logger.error(f"Failed to reschedule {job_id}: {e}")
        return False


def start_scheduler():
    """Start scheduler as a blocking process — used when running: python run.py schedule."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    scheduler = BlockingScheduler(timezone=SCHEDULE_TZ)
    _register_jobs(scheduler)
    logger.info("Scheduler started. Waiting for triggers...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    start_scheduler()
