"""
Nightly Gann pipeline — fetches 2y OHLCV for all dashboard stocks (~185),
computes all 5 Gann methods, stores results in gann_cache table.

Called by scheduler at 9:30 PM IST Mon–Fri (after AI scan).
Also callable manually from Admin page.
"""
import logging
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf
import pandas as pd

from config import SECTOR_STOCKS
from backend.calculations.gann import compute_gann_all
from backend.storage.gann_db import store_gann, purge_old

logger = logging.getLogger(__name__)

_PIVOT_WINDOW = 10
_MAX_WORKERS  = 4


def _all_symbols() -> list[str]:
    seen, out = set(), []
    for syms in SECTOR_STOCKS.values():
        for sym in syms:
            s = sym if sym.endswith(".NS") else sym + ".NS"
            if s not in seen:
                seen.add(s); out.append(s)
    return out


def _fetch_ohlcv(ticker: str) -> pd.DataFrame:
    try:
        df = yf.download(ticker, period="max", interval="1d",
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            return pd.DataFrame()
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.droplevel(1)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return df
    except Exception as e:
        logger.warning(f"yfinance fetch failed for {ticker}: {e}")
        return pd.DataFrame()


def _process_one(ticker: str) -> tuple[str, bool]:
    symbol = ticker.replace(".NS", "")
    try:
        df = _fetch_ohlcv(ticker)
        if df.empty or len(df) < 60:
            logger.warning(f"Skipping {symbol} — insufficient data ({len(df)} bars)")
            return symbol, False
        result = compute_gann_all(symbol, df, _PIVOT_WINDOW)
        if not result:
            return symbol, False
        store_gann(symbol, result)
        return symbol, True
    except Exception as e:
        logger.error(f"Gann pipeline error for {symbol}: {e}")
        return symbol, False


def run_gann_pipeline(triggered_by: str = "scheduler",
                      progress_callback=None) -> dict:
    """
    Fetch + compute + store Gann results for all Nifty50 stocks.

    progress_callback(done, total, symbol) — called after each stock completes.
    Returns summary dict: {total, success, failed, elapsed_sec}
    """
    t_start = datetime.datetime.utcnow()
    logger.info(f"Gann pipeline started (triggered_by={triggered_by})")

    tickers = _all_symbols()
    total = len(tickers)
    logger.info(f"Processing {total} tickers with {_MAX_WORKERS} workers")

    ok_count = 0
    fail_count = 0
    done = 0

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_process_one, t): t for t in tickers}
        for fut in as_completed(futures):
            sym, ok = fut.result()
            done += 1
            if ok:
                ok_count += 1
            else:
                fail_count += 1
            if progress_callback:
                try:
                    progress_callback(done, total, sym)
                except Exception:
                    pass

    # Purge rows older than 7 days to keep DB size constant
    deleted = purge_old(days=7)
    if deleted:
        logger.info(f"Purged {deleted} stale gann_cache rows")

    elapsed = round((datetime.datetime.utcnow() - t_start).total_seconds(), 1)
    logger.info(
        f"Gann pipeline done — {ok_count} OK · {fail_count} failed · {elapsed}s"
    )
    return {
        "total":       len(tickers),
        "success":     ok_count,
        "failed":      fail_count,
        "elapsed_sec": elapsed,
    }
