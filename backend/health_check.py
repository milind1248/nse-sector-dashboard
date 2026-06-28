"""
Page Health Checker — tests each menu page's data dependencies.
Runs from the Admin page. Does NOT render pages via browser;
instead validates: DB table freshness, required row counts, and
lightweight external connectivity (yfinance index ping).

Each check returns a dict:
  {
    "page":    str,          # menu label
    "status":  "OK" | "WARN" | "FAIL",
    "checks":  [(label, status, detail), ...],
    "elapsed": float,        # seconds
  }
"""
import sqlite3
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent / "data" / "nse_dashboard.db"
_MAX_STALE_DAYS = 4   # weekends = up to 3 days gap; 4 gives buffer


def _db():
    return sqlite3.connect(_DB_PATH)


def _check_table(tbl: str, date_col: str | None = None,
                 min_rows: int = 1, max_stale_days: int = _MAX_STALE_DAYS):
    """Return (status, detail) for a single table."""
    try:
        con = _db()
        count = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        if count < min_rows:
            con.close()
            return "FAIL", f"{tbl}: only {count} rows (need ≥{min_rows})"

        if date_col:
            latest = con.execute(
                f"SELECT MAX({date_col}) FROM {tbl}"
            ).fetchone()[0]
            con.close()
            if not latest:
                return "FAIL", f"{tbl}: no date in {date_col}"
            latest_date = date.fromisoformat(latest[:10])
            stale = (date.today() - latest_date).days
            if stale > max_stale_days:
                return "WARN", f"{tbl}: latest data {latest[:10]} ({stale}d old)"
            return "OK", f"{tbl}: {count:,} rows · latest {latest[:10]}"
        con.close()
        return "OK", f"{tbl}: {count:,} rows"
    except Exception as e:
        return "FAIL", f"{tbl}: {e}"


def _check_yfinance(symbol: str, label: str):
    """Lightweight yfinance ping — download 5 days, check non-empty."""
    try:
        import yfinance as yf
        import numpy as np
        df = yf.download(symbol, period="5d", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return "FAIL", f"{label}: no data returned"
        close = df["Close"]
        # flatten MultiIndex columns if present
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        last = float(np.squeeze(close.iloc[-1]))
        return "OK", f"{label}: last close {last:,.1f}"
    except Exception as e:
        return "FAIL", f"{label}: {e}"


def _check_import(module: str, label: str):
    """Verify a backend module imports cleanly."""
    try:
        __import__(module)
        return "OK", f"{label}: import OK"
    except Exception as e:
        return "FAIL", f"{label}: import error — {e}"


def _agg_status(checks):
    statuses = [s for _, s, _ in checks]
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "OK"


# ── Per-page checks ───────────────────────────────────────────────────────────

def _check_market_pulse():
    checks = []
    checks.append(("Breadth table",     *_check_table("market_breadth",      "trade_date", 1)))
    checks.append(("Sector Heatmap",    *_check_table("sector_heatmap",      "trade_date", 10)))
    checks.append(("RRG Snapshot",      *_check_table("rrg_snapshot",        "trade_date", 10)))
    checks.append(("Nifty50 live",      *_check_yfinance("^NSEI",  "Nifty50")))
    checks.append(("BankNifty live",    *_check_yfinance("^NSEBANK", "BankNifty")))
    return checks


def _check_sector_analysis():
    checks = []
    checks.append(("Sector snapshot",   *_check_table("daily_sector_snapshot", "date", 10)))
    checks.append(("FII/DII daily",     *_check_table("fii_dii_daily",         "date",  5)))
    checks.append(("Sector intelligence",*_check_table("sector_intelligence",  None,   10)))
    return checks


def _check_index_stocks():
    checks = []
    checks.append(("Sector sync log",   *_check_table("sector_sync_log", None, 1)))
    checks.append(("FNO symbols",       *_check_table("fno_symbols",     None, 50)))
    checks.append(("Import sector_sync",*_check_import("backend.data_ingestion.sector_sync", "sector_sync")))
    return checks


def _check_fii_dii_flow():
    checks = []
    checks.append(("FII/DII daily",     *_check_table("fii_dii_daily", "date", 20)))
    checks.append(("Sector snapshot",   *_check_table("daily_sector_snapshot", "date", 10)))
    return checks


def _check_fii_sectors():
    checks = []
    checks.append(("NSDL FII sector",   *_check_table("nsdl_fii_sector", None, 100)))
    return checks


def _check_fpi_sectors():
    checks = []
    checks.append(("NSDL FII sector",   *_check_table("nsdl_fii_sector", None, 100)))
    return checks


def _check_stock_picker():
    checks = []
    checks.append(("Sector snapshot",   *_check_table("daily_sector_snapshot", "date", 10)))
    checks.append(("Nifty50 live",      *_check_yfinance("^NSEI", "Nifty50")))
    checks.append(("Import yfinance_fetcher",
                   *_check_import("backend.data_ingestion.yfinance_fetcher", "yfinance_fetcher")))
    return checks


def _check_smart_money():
    checks = []
    checks.append(("Stock snapshot",    *_check_table("daily_stock_snapshot",  "date",       100)))
    checks.append(("Smart money hist",  *_check_table("smart_money_history",   "trade_date", 100)))
    checks.append(("FNO symbols",       *_check_table("fno_symbols",           None,          50)))
    return checks


def _check_fii_accumulation():
    checks = []
    checks.append(("Shareholding data", *_check_table("shareholding_pattern", None, 100)))
    checks.append(("Refresh meta",      *_check_table("shareholding_refresh_meta", None, 1)))
    return checks


def _check_alerts():
    checks = []
    checks.append(("Sector snapshot",   *_check_table("daily_sector_snapshot", "date", 10)))
    checks.append(("Smart money hist",  *_check_table("smart_money_history",   "trade_date", 100)))
    checks.append(("Import indicators", *_check_import("backend.calculations.indicators", "indicators")))
    return checks


def _check_export():
    checks = []
    checks.append(("Sector snapshot",   *_check_table("daily_sector_snapshot", "date", 10)))
    checks.append(("Shareholding data", *_check_table("shareholding_pattern",  None,  100)))
    return checks


# ── Main entry point ──────────────────────────────────────────────────────────

_PAGES = [
    ("📡 Market Pulse",      _check_market_pulse),
    ("📈 Sector Analysis",   _check_sector_analysis),
    ("🏛️ Index Stocks",      _check_index_stocks),
    ("🏦 FII DII Flow",      _check_fii_dii_flow),
    ("🏢 FII Sectors",       _check_fii_sectors),
    ("🌏 FPI Sectors",       _check_fpi_sectors),
    ("🎯 Stock Picker",      _check_stock_picker),
    ("💰 Smart Money",       _check_smart_money),
    ("📊 FII Accumulation",  _check_fii_accumulation),
    ("🔔 Alerts",            _check_alerts),
    ("📤 Export",            _check_export),
]


def run_health_check() -> list[dict]:
    """
    Run all page health checks. Returns list of result dicts ordered by menu.
    Each dict: {page, status, checks [(label, status, detail)], elapsed}
    """
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).parent.parent))

    results = []
    for page, fn in _PAGES:
        t0 = time.time()
        try:
            checks = fn()
        except Exception as e:
            checks = [("Unexpected error", "FAIL", traceback.format_exc(limit=3))]
        elapsed = round(time.time() - t0, 2)
        results.append({
            "page":    page,
            "status":  _agg_status(checks),
            "checks":  checks,
            "elapsed": elapsed,
        })
    return results
