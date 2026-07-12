"""
Nightly AI forecast pipeline — Prophet + XGBoost for all dashboard stocks.

Runs as a scheduled job at 9 PM IST Mon–Fri.
Downloads all 185 symbols in a single yf.download batch call, then runs
4 parallel workers for CPU-bound model training (Prophet + XGBoost + ARIMA).
Stores full forecasts to ai_forecast_cache; derives aligned signals for ai_scan_results.

After the pipeline completes the AI Forecast page reads entirely from DB — zero
Yahoo Finance calls at page-load time.
"""
import logging
import pandas as pd
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


def _batch_fetch(tickers: list[str]) -> "pd.DataFrame | None":
    """
    Download 3y daily OHLCV for all tickers in a single yf.download call.
    Returns a MultiIndex DataFrame (ticker → OHLCV) or None on failure.
    threads=False avoids spawning parallel HTTP connections that trigger rate limits.
    """
    import yfinance as yf
    try:
        df = yf.download(
            tickers, period="3y", interval="1d",
            group_by="ticker", threads=False,
            progress=False, auto_adjust=True,
        )
        if df is None or df.empty:
            return None
        logger.info("Batch download complete — %d tickers", len(tickers))
        return df
    except Exception as e:
        logger.warning("Batch download failed (%s) — workers will fall back to individual calls", e)
        return None


def _slice_ticker(batch: "pd.DataFrame | None", ticker_ns: str) -> "pd.DataFrame | None":
    """Extract single-ticker DataFrame from the batch MultiIndex result."""
    if batch is None:
        return None
    try:
        if not isinstance(batch.columns, pd.MultiIndex):
            return None
        if ticker_ns not in batch.columns.get_level_values(0):
            return None
        sliced = batch[ticker_ns].dropna(how="all")
        return sliced if not sliced.empty else None
    except Exception:
        return None


def _process_one(symbol: str, sector: str,
                 prefetched_df: "pd.DataFrame | None" = None) -> tuple[str, str, dict] | None:
    """
    Train Prophet + XGBoost + ARIMA for one stock.
    Uses prefetched_df when available (no network call); falls back to individual yf.download.
    """
    from backend.calculations.ai_forecast import run_full_stock_forecast
    result = run_full_stock_forecast(
        symbol + ".NS", forward_days=5, horizon_days=30,
        prefetched_df=prefetched_df,
    )
    if result is None:
        return None
    return symbol, sector, result


def run_ai_scan_pipeline(triggered_by: str = "scheduler") -> dict:
    """
    Full nightly pipeline:
      1. Batch-fetch 3y OHLCV for all stocks in one yf.download call (reduces rate-limit hits).
      2. Run Prophet + XGBoost + ARIMA in 4 parallel workers (CPU-bound, no network calls).
      3. Store full forecast to ai_forecast_cache so the AI Forecast page needs no Yahoo Finance calls.
      4. Derive aligned signals (XGBoost + Prophet agree) → store to ai_scan_results.

    Logging (log_start/log_finish) is the caller's responsibility.
    Returns summary dict: {total, bullish, bearish, failed, cached}.
    """
    from backend.storage.ai_forecast_db import store_forecast
    from backend.storage.ai_scan_db import store_scan

    # Truncate before loading — table stays at exactly 185 rows (~4.5 MB constant)
    from backend.storage.ai_forecast_db import truncate_forecasts
    truncate_forecasts()

    stock_list = _build_stock_list()
    logger.info("AI scan pipeline started — %d stocks, triggered_by=%s", len(stock_list), triggered_by)

    # ── Single batch download for all symbols ─────────────────────────────────
    all_tickers = [sym + ".NS" for sym, _ in stock_list]
    logger.info("Batch-fetching %d symbols (3y daily) …", len(all_tickers))
    batch_raw = _batch_fetch(all_tickers)

    # Identify tickers missing from batch result and retry as a second batch
    # so workers never need to fall back to individual yf.download() calls
    missing = [t for t in all_tickers
               if _slice_ticker(batch_raw, t) is None]
    if missing:
        logger.info("Retry batch for %d tickers missing from first fetch …", len(missing))
        retry_raw = _batch_fetch(missing)
    else:
        retry_raw = None

    # Build prefetch map: ticker_ns → sliced DataFrame (None if both batches failed)
    prefetch: dict[str, "pd.DataFrame | None"] = {}
    for t in all_tickers:
        df = _slice_ticker(batch_raw, t)
        if df is None and retry_raw is not None:
            df = _slice_ticker(retry_raw, t)
        prefetch[t] = df

    logger.info("Prefetch complete — %d/%d tickers have data",
                sum(1 for v in prefetch.values() if v is not None), len(all_tickers))

    cache_results: list[tuple[str, str, dict]] = []
    failed = 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {
            pool.submit(
                _process_one, sym, sec,
                prefetch.get(sym + ".NS"),
            ): (sym, sec)
            for sym, sec in stock_list
        }
        done = 0
        for fut in as_completed(futs):
            sym, sec = futs[fut]
            done += 1
            try:
                r = fut.result()
                if r:
                    cache_results.append(r)
                    store_forecast(r[0], r[1], r[2])
                    logger.debug("[%d/%d] %s cached", done, len(stock_list), sym)
                else:
                    failed += 1
                    logger.warning("[%d/%d] %s — no result", done, len(stock_list), sym)
            except Exception as e:
                failed += 1
                logger.error("[%d/%d] %s failed: %s", done, len(stock_list), sym, e)

    # ── Derive aligned signals (XGBoost + Prophet agree) → ai_scan_results ───
    scan_rows = []
    for symbol, sector, res in cache_results:
        xgb_dir    = res.get("xgb_direction")
        prophet_tr = res.get("prophet_trend")
        xgb_prob   = res.get("xgb_prob")
        xgb_sig    = res.get("xgb_signal", "")

        if not xgb_dir or not prophet_tr or xgb_prob is None:
            continue

        arima_dir = res.get("arima_direction")  # None if ARIMA failed → falls back to 2-way
        aligned = (
            (xgb_dir == "UP"   and prophet_tr == "Bullish" and arima_dir in ("Bullish", None)) or
            (xgb_dir == "DOWN" and prophet_tr == "Bearish" and arima_dir in ("Bearish", None))
        )
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
