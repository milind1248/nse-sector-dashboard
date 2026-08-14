"""
Daily scheduler job for the Momentum Scanner's virtual portfolio tracker.
Full rebalance (rescan the universe + reclassify) on the first trading day
of each month; cheap mark-to-market on every other trading day. Writes to
momentum_portfolio_nav / momentum_portfolio_holdings via
backend/storage/momentum_portfolio_db.py.

Runs at 22:00 IST Mon-Fri (backend/data_ingestion/scheduler.py).
"""
import logging
from datetime import date

from backend.calculations.momentum_portfolio import rebalance_portfolio, mark_to_market
from backend.storage import momentum_portfolio_db as db

logger = logging.getLogger(__name__)

_BASELINE_NAV = 100.0


def _is_first_trading_day_of_month(today: date) -> bool:
    """True if no earlier date this month has already been snapshotted."""
    prev_row = db.load_latest_nav_row()
    if prev_row is None:
        return True  # very first run ever
    prev_date = date.fromisoformat(prev_row["snapshot_date"])
    return prev_date.month != today.month or prev_date.year != today.year


def run_momentum_portfolio_snapshot(triggered_by: str = "scheduler") -> dict:
    """
    Returns a summary dict: {snapshot_date, is_rebalance_day, n_holdings,
    fund_nav, benchmark_nav}.
    """
    today = date.today()
    today_str = today.isoformat()
    logger.info("Momentum portfolio snapshot started — %s, triggered_by=%s", today_str, triggered_by)

    prev_holdings, prev_snapshot_date = db.load_latest_holdings()
    prev_nav_row = db.load_latest_nav_row()
    is_rebalance = _is_first_trading_day_of_month(today)

    if is_rebalance:
        prev_symbols = {h["symbol"] for h in prev_holdings if h["category"] != "Exit"}
        logger.info("Rebalance day — rescanning universe (prev holdings: %d)", len(prev_symbols))
        classified = rebalance_portfolio(prev_symbols)
        if classified.empty:
            logger.warning("Rebalance produced no rows — skipping snapshot write")
            return {"snapshot_date": today_str, "is_rebalance_day": True, "n_holdings": 0,
                    "fund_nav": None, "benchmark_nav": None}

        holdings = classified.to_dict("records")
        prev_fund_nav = prev_nav_row["fund_nav"] if prev_nav_row else _BASELINE_NAV
        prev_bench_nav = prev_nav_row["benchmark_nav"] if prev_nav_row else _BASELINE_NAV
        # Rebalance day itself: carry forward NAV unchanged (weights reset,
        # no new day has actually traded yet) — next day's mark_to_market
        # applies the first real move under the new book.
        fund_nav, bench_nav = prev_fund_nav, prev_bench_nav
    else:
        logger.info("Non-rebalance day — mark-to-market only (%d holdings)", len(prev_holdings))
        prev_fund_nav = prev_nav_row["fund_nav"] if prev_nav_row else _BASELINE_NAV
        prev_bench_nav = prev_nav_row["benchmark_nav"] if prev_nav_row else _BASELINE_NAV
        fund_nav, bench_nav = mark_to_market(prev_holdings, prev_fund_nav, prev_bench_nav)
        # Re-carry yesterday's categories/ranks; only weight/return/alpha are stale
        # until the next rebalance — acceptable since these are secondary display
        # fields, not what mark_to_market actually computes.
        holdings = prev_holdings

    db.store_snapshot(today_str, fund_nav, bench_nav, is_rebalance, holdings)
    logger.info("Momentum portfolio snapshot complete — %s, rebalance=%s, %d holdings, "
                "fund_nav=%.2f, bench_nav=%.2f", today_str, is_rebalance, len(holdings), fund_nav, bench_nav)

    return {"snapshot_date": today_str, "is_rebalance_day": is_rebalance, "n_holdings": len(holdings),
            "fund_nav": fund_nav, "benchmark_nav": bench_nav}
