"""APScheduler-based daily job runner."""
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from backend.data_ingestion.pipeline import (
    run_fii_dii_pipeline, run_breadth_pipeline,
    run_sector_pipeline, run_stock_pipeline,
)
from backend.data_ingestion.shareholding_pipeline import run_shareholding_pipeline
from backend.data_ingestion.market_pulse_pipeline import run_market_pulse_pipeline
from backend.data_ingestion.job_logger import log_start, log_finish
from backend.storage.cache import invalidate_all
from config import SCHEDULE_TZ

logger = logging.getLogger(__name__)


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


def start_scheduler():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    scheduler = BlockingScheduler(timezone=SCHEDULE_TZ)

    # 6:00 PM IST — price + breadth snapshot
    scheduler.add_job(
        _logged(
            "sector_snapshot",
            "Sector Snapshot (FII/DII + Breadth + Prices)",
            lambda: (invalidate_all(), run_fii_dii_pipeline(), run_breadth_pipeline(), run_sector_pipeline()),
        ),
        CronTrigger(hour=18, minute=0, day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        id="sector_snapshot",
        name="Sector snapshot @ 6 PM",
    )

    # 6:30 PM IST — stock-level detail
    scheduler.add_job(
        _logged("stock_snapshot", "Stock Snapshot (Delivery + OI)", run_stock_pipeline),
        CronTrigger(hour=18, minute=30, day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        id="stock_snapshot",
        name="Stock snapshot @ 6:30 PM",
    )

    # 8:00 PM IST — Market Pulse snapshot (after Bhavcopy is published by NSE)
    # Bhavcopy is published ~6–7 PM; 8 PM gives buffer for NSE to publish
    scheduler.add_job(
        _logged(
            "market_pulse_snapshot",
            "Market Pulse Snapshot (Breadth + Heatmap + RRG)",
            lambda: run_market_pulse_pipeline(triggered_by="scheduler"),
        ),
        CronTrigger(hour=20, minute=0, day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        id="market_pulse_snapshot",
        name="Market Pulse snapshot @ 8 PM IST",
    )

    # Quarterly shareholding refresh — 27th of Jan, Apr, Jul, Oct at 7:00 AM IST
    # SEBI deadline is 21 days after quarter end; 27th gives 6 days buffer
    # Covers: Q4 (Apr 27), Q1 (Jul 27), Q2 (Oct 27), Q3 (Jan 27)
    scheduler.add_job(
        _logged(
            "shareholding_quarterly",
            "Quarterly Shareholding Refresh (All Sector Stocks)",
            run_shareholding_pipeline,
        ),
        CronTrigger(month="1,4,7,10", day=27, hour=7, minute=0, timezone=SCHEDULE_TZ),
        id="shareholding_quarterly",
        name="Quarterly shareholding refresh @ 7 AM IST on 27th Jan/Apr/Jul/Oct",
        misfire_grace_time=86400,  # run within 24h if server was down on the 27th
    )

    logger.info("Scheduler started. Waiting for triggers...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    start_scheduler()
