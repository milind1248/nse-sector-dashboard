"""
Quick launcher. Run: python run.py
Options:
  python run.py          → start Streamlit dashboard
  python run.py pipeline → run data pipeline once now
  python run.py schedule → start background scheduler
"""
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent


def launch_dashboard():
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        str(ROOT / "app" / "main.py"),
        "--server.port", "8501",
        "--server.headless", "false",
    ], cwd=str(ROOT))


def run_pipeline():
    sys.path.insert(0, str(ROOT))
    from backend.data_ingestion.pipeline import run_all
    run_all()


def run_scheduler():
    sys.path.insert(0, str(ROOT))
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
