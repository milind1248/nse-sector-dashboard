"""APScheduler-based daily job runner."""
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from backend.data_ingestion.pipeline import (
    run_fii_dii_pipeline, run_breadth_pipeline,
    run_sector_pipeline, run_stock_pipeline,
)
from backend.storage.cache import invalidate_all
from config import SCHEDULE_TZ

logger = logging.getLogger(__name__)


def start_scheduler():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    scheduler = BlockingScheduler(timezone=SCHEDULE_TZ)

    # 6:00 PM IST — price + breadth snapshot
    scheduler.add_job(
        lambda: (invalidate_all(), run_fii_dii_pipeline(), run_breadth_pipeline(), run_sector_pipeline()),
        CronTrigger(hour=18, minute=0, day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        id="sector_snapshot",
        name="Sector snapshot @ 6 PM",
    )

    # 6:30 PM IST — stock-level detail
    scheduler.add_job(
        run_stock_pipeline,
        CronTrigger(hour=18, minute=30, day_of_week="mon-fri", timezone=SCHEDULE_TZ),
        id="stock_snapshot",
        name="Stock snapshot @ 6:30 PM",
    )

    logger.info("Scheduler started. Waiting for triggers...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    start_scheduler()
