"""
Daily AI scan pipeline — runs after market close (9 PM IST).
Scans all dashboard stocks with XGBoost + EMA trend, stores results to SQLite.
Called by the scheduler or manually via Admin panel.
"""
import logging
from config import SECTOR_STOCKS
from backend.calculations.ai_forecast import run_market_scan
from backend.storage.ai_scan_db import store_scan

logger = logging.getLogger(__name__)


def _build_stock_list() -> list[tuple[str, str]]:
    """Deduplicated (symbol, sector) list from SECTOR_STOCKS."""
    seen: set = set()
    out: list[tuple[str, str]] = []
    for sector, syms in sorted(SECTOR_STOCKS.items()):
        for sym in syms:
            s = sym.replace(".NS", "")
            if s not in seen:
                seen.add(s)
                out.append((s, sector))
    return out


def run_ai_scan_pipeline(triggered_by: str = "scheduler") -> dict:
    """
    Fetch OHLCV for all dashboard stocks, run XGBoost direction model,
    store aligned signals to ai_scan_results table.

    Returns summary dict with counts for job logging.
    """
    stock_list = _build_stock_list()
    logger.info(f"[ai_scan] Starting daily scan — {len(stock_list)} stocks (triggered_by={triggered_by})")

    results = run_market_scan(forward_days=5, stock_list=stock_list)

    store_scan(results)

    bullish = sum(1 for r in results if r.get("Direction") == "UP")
    bearish = sum(1 for r in results if r.get("Direction") == "DOWN")
    logger.info(
        f"[ai_scan] Done — {len(results)} signals stored "
        f"({bullish} bullish · {bearish} bearish)"
    )
    return {"total": len(results), "bullish": bullish, "bearish": bearish}
