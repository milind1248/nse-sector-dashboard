"""
Nightly news-sentiment pipeline — VADER scoring of Google News RSS headlines
for all dashboard stocks.

Runs as a scheduled job (Mon-Fri, after the AI scan + Gann jobs). Network-bound
(RSS fetches, not model training) so this uses more parallel workers than the
CPU-bound ai_scan_pipeline. Each stock's fetch+score is wrapped so a single
feed timeout/failure can never take down the batch — it just contributes a
"no news"/neutral row for that stock and the run continues.

After the pipeline completes, the AI Forecast page reads sentiment entirely
from DB — zero live Google News RSS calls at page-load time.
"""
import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import SECTOR_STOCKS

logger = logging.getLogger(__name__)


def _build_stock_list() -> list[tuple[str, str]]:
    seen: set = set()
    out: list[tuple[str, str]] = []
    for sector, syms in sorted(SECTOR_STOCKS.items()):
        for sym in syms:
            s = sym.replace(".NS", "")
            if s not in seen:
                seen.add(s)
                out.append((s, sector))
    return out


def _process_one(symbol: str, sector: str) -> tuple[str, str, dict, list] | None:
    from backend.calculations.news_sentiment import analyze_stock_news
    try:
        res = analyze_stock_news(symbol)
        summary = res["summary"]
        summary["computed_at"] = datetime.datetime.utcnow().isoformat()
        headlines_df = res["headlines"]
        headlines = (
            headlines_df.to_dict(orient="records") if hasattr(headlines_df, "to_dict") else []
        )
        # Trim/serialize published timestamps to strings for JSON storage
        for h in headlines:
            if h.get("published") is not None:
                h["published"] = str(h["published"])
        return symbol, sector, summary, headlines[:15]
    except Exception as e:
        logger.warning("Sentiment failed for %s: %s", symbol, e)
        return None


def run_sentiment_scan_pipeline(triggered_by: str = "scheduler", max_workers: int = 8) -> dict:
    """
    Full nightly pipeline: fetch + score Google News RSS headlines for every
    dashboard stock, store to sentiment_cache.

    Logging (log_start/log_finish) is the caller's responsibility.
    Returns summary dict: {total, bullish, bearish, neutral, failed}.
    """
    from backend.storage.sentiment_db import store_sentiment, truncate_sentiment

    truncate_sentiment()

    stock_list = _build_stock_list()
    logger.info("Sentiment scan pipeline started — %d stocks, triggered_by=%s",
                len(stock_list), triggered_by)

    bullish = bearish = neutral = failed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_process_one, sym, sec): (sym, sec) for sym, sec in stock_list}
        done = 0
        for fut in as_completed(futs):
            sym, sec = futs[fut]
            done += 1
            try:
                r = fut.result()
                if r:
                    symbol, sector, summary, headlines = r
                    store_sentiment(symbol, sector, summary, headlines)
                    label = summary.get("label")
                    if label == "Bullish":
                        bullish += 1
                    elif label == "Bearish":
                        bearish += 1
                    else:
                        neutral += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                logger.error("[%d/%d] %s failed: %s", done, len(stock_list), sym, e)
            if done % 50 == 0 or done == len(stock_list):
                logger.info("Sentiment scan progress: %d/%d", done, len(stock_list))

    logger.info(
        "Sentiment scan pipeline complete — %d bullish, %d bearish, %d neutral, %d failed",
        bullish, bearish, neutral, failed,
    )
    return {
        "total": len(stock_list), "bullish": bullish, "bearish": bearish,
        "neutral": neutral, "failed": failed,
    }
