"""
Quick launcher. Run: python run.py
Options:
  python run.py          → start Streamlit dashboard (scheduler starts automatically)
  python run.py pipeline → run data pipeline once now
  python run.py schedule → start scheduler only (blocking, no dashboard)
"""
import sys
import logging
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def launch_dashboard():
    # Start background scheduler in this process before Streamlit boots
    try:
        from backend.data_ingestion.scheduler import get_scheduler
        get_scheduler()
        logger.info("Background scheduler started — jobs will fire at configured IST times.")
    except Exception as e:
        logger.error(f"Scheduler failed to start: {e}")

    # Launch Streamlit in the same process (no subprocess — shares memory + scheduler)
    from streamlit.web import cli as stcli
    sys.argv = [
        "streamlit", "run",
        str(ROOT / "app" / "Home.py"),
        "--server.port", "8501",
        "--server.headless", "false",
    ]
    stcli.main()


def run_pipeline():
    from backend.data_ingestion.pipeline import run_all
    run_all()


def run_scheduler():
    from backend.data_ingestion.scheduler import start_scheduler
    start_scheduler()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dashboard"
    if cmd == "pipeline":
        run_pipeline()
    elif cmd == "schedule":
        run_scheduler()
    else:
        launch_dashboard()
