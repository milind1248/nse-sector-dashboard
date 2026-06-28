"""
Nightly AI forecast pipeline — Prophet + XGBoost for all dashboard stocks.

Runs as a scheduled job at 9 PM IST Mon–Fri.
Uses 4 parallel workers: each worker fetches 3y OHLCV, trains Prophet + XGBoost,
stores full forecast to ai_forecast_cache, then derives aligned signals for ai_scan_results.

After the pipeline completes the AI Forecast page reads entirely from DB — zero
Yahoo Finance calls at page-load time.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import SECTOR_STOCKS

logger = logging.getLogger(__name__)


def _build_stock_list() -> list[tuple[str, str]]:
    """Deduplicated (symbol_clean, sector) list from SECTOR_STOCKS."""
    seen: set = set()
    out: list[tuple[str, str]] = []
    for sector, syms in sorted(SECTOR_STOCKS.items()):
        for sym in syms:
            s = sym.replace(".NS", "")
            if s not in seen:
                seen.add(s)
                out.append((s, sector))
    return out


def _process_one(symbol: str, sector: str) -> tuple[str, str, dict] | None:
    """Fetch 3y OHLCV + Prophet + XGBoost for one stock. Returns (symbol, sector, result) or None."""
    from backend.calculations.ai_forecast import run_full_stock_forecast
    result = run_full_stock_forecast(symbol + ".NS", forward_days=5, horizon_days=30)
    if result is None:
        return None
    return symbol, sector, result


def run_ai_scan_pipeline(triggered_by: str = "scheduler") -> dict:
    """
    Full nightly pipeline:
      1. Fetch 3y OHLCV + run Prophet + XGBoost for all dashboard stocks (4 parallel workers).
      2. Store full forecast to ai_forecast_cache so the AI Forecast page needs no Yahoo Finance calls.
      3. Derive aligned signals (XGBoost + Prophet agree) → store to ai_scan_results.

    Logging (log_start/log_finish) is the caller's responsibility.
    Returns summary dict: {total, bullish, bearish, failed, cached}.
    """
    from backend.storage.ai_forecast_db import store_forecast, ensure_table as _ensure_cache
    from backend.storage.ai_scan_db import store_scan, ensure_table as _ensure_scan

    _ensure_cache()
    _ensure_scan()

    # Truncate before loading — table stays at exactly 185 rows (~4.5 MB constant)
    from backend.storage.ai_forecast_db import truncate_forecasts
    truncate_forecasts()

    stock_list = _build_stock_list()
    logger.info(f"AI scan pipeline started — {len(stock_list)} stocks, triggered_by={triggered_by}")

    cache_results: list[tuple[str, str, dict]] = []
    failed = 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_process_one, sym, sec): (sym, sec) for sym, sec in stock_list}
        done = 0
        for fut in as_completed(futs):
            sym, sec = futs[fut]
            done += 1
            try:
                r = fut.result()
                if r:
                    cache_results.append(r)
                    store_forecast(r[0], r[1], r[2])
                    logger.debug(f"[{done}/{len(stock_list)}] {sym} cached")
                else:
                    failed += 1
                    logger.warning(f"[{done}/{len(stock_list)}] {sym} — no result")
            except Exception as e:
                failed += 1
                logger.error(f"[{done}/{len(stock_list)}] {sym} failed: {e}")

    # ── Derive aligned signals (XGBoost + Prophet agree) → ai_scan_results ───
    scan_rows = []
    for symbol, sector, res in cache_results:
        xgb_dir    = res.get("xgb_direction")
        prophet_tr = res.get("prophet_trend")
        xgb_prob   = res.get("xgb_prob")
        xgb_sig    = res.get("xgb_signal", "")

        if not xgb_dir or not prophet_tr or xgb_prob is None:
            continue

        aligned = (xgb_dir == "UP"   and prophet_tr == "Bullish") or \
                  (xgb_dir == "DOWN" and prophet_tr == "Bearish")
        if not aligned:
            continue

        sig_map = {
            "🟢 Strong Buy Signal":    "Strong Buy",
            "🟡 Moderate Buy Signal":  "Buy",
            "🔴 Strong Sell Signal":   "Strong Sell",
            "🟠 Moderate Sell Signal": "Sell",
        }
        sig = sig_map.get(xgb_sig)
        if not sig:
            continue

        scan_rows.append({
            "Symbol":    symbol,
            "Sector":    sector,
            "Price (₹)": round(res.get("price", 0), 1),
            "XGB Prob":  round(xgb_prob * 100, 1),
            "Direction": xgb_dir,
            "Trend":     prophet_tr,
            "Signal":    sig,
        })

    store_scan(scan_rows)

    bullish = sum(1 for r in scan_rows if r["Direction"] == "UP")
    bearish = sum(1 for r in scan_rows if r["Direction"] == "DOWN")

    logger.info(
        f"AI scan pipeline complete — {len(cache_results)} cached, {failed} failed, "
        f"{bullish} bullish signals, {bearish} bearish signals"
    )
    return {
        "total":   len(scan_rows),
        "bullish": bullish,
        "bearish": bearish,
        "failed":  failed,
        "cached":  len(cache_results),
    }
