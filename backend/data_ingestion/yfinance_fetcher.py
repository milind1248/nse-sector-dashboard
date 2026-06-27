"""Fetches OHLCV price data from Yahoo Finance for NSE indices and stocks."""
import logging
import time
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from backend.storage.cache import timed_cache
from config import (
    NIFTY_SYMBOL, BANKNIFTY_SYMBOL, MIDCAP_SYMBOL,
    SMALLCAP_SYMBOL, VIX_SYMBOL, SECTOR_INDICES, SECTOR_STOCKS,
)

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 5  # seconds


def _download_with_retry(symbol: str, period: str = "1y", interval: str = "1d") -> Optional[pd.DataFrame]:
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            df = yf.download(symbol, period=period, interval=interval,
                             progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed for {symbol}: {e}")
            time.sleep(_RETRY_DELAY * (2 ** attempt))
    logger.error(f"All retries failed for {symbol}")
    return None


def _download_multi_with_retry(symbols: list[str], period: str = "1y") -> Optional[pd.DataFrame]:
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            df = yf.download(symbols, period=period, interval="1d",
                             progress=False, auto_adjust=True, group_by="ticker")
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed for batch download: {e}")
            time.sleep(_RETRY_DELAY * (2 ** attempt))
    logger.error("All retries failed for batch download")
    return None


@timed_cache(ttl_seconds=3600)
def fetch_index_ohlcv(symbol: str, period: str = "6mo") -> Optional[pd.DataFrame]:
    """Returns OHLCV DataFrame for a single index symbol."""
    df = _download_with_retry(symbol, period=period)
    if df is None:
        return None
    df.index = pd.to_datetime(df.index).date
    df.index.name = "date"
    return df


def fetch_market_summary() -> dict:
    """Returns current-day summary for Nifty, BankNifty, VIX etc."""
    symbols = {
        "Nifty50":    NIFTY_SYMBOL,
        "BankNifty":  BANKNIFTY_SYMBOL,
        "Midcap100":  MIDCAP_SYMBOL,
        "VIX":        VIX_SYMBOL,
    }
    result = {}
    for name, sym in symbols.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            if hist.empty:
                result[name] = {}
                continue
            close_s = _get_close(hist) if not isinstance(hist.columns, pd.MultiIndex) else None
            if close_s is None:
                for col in ["Close", "close"]:
                    if col in hist.columns:
                        c = hist[col]
                        close_s = (c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c).dropna()
                        break
            if close_s is None or close_s.empty:
                result[name] = {}
                continue
            now_v  = float(close_s.iloc[-1])
            prev_v = float(close_s.iloc[-2]) if len(close_s) >= 2 else now_v
            chg    = now_v - prev_v
            pct    = (chg / prev_v) * 100 if prev_v else 0
            result[name] = {
                "close":  round(now_v, 2),
                "change": round(chg, 2),
                "pct":    round(pct, 2),
                "volume": 0,
            }
        except Exception as e:
            logger.error(f"Error fetching {name} ({sym}): {e}")
            result[name] = {}
    return result


def _get_close(df: pd.DataFrame) -> Optional[pd.Series]:
    """Extract 1-D close series, handling MultiIndex columns from yfinance."""
    if isinstance(df.columns, pd.MultiIndex):
        for lv in ["Close", "close"]:
            if lv in df.columns.get_level_values(0):
                s = df[lv]
                return (s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s).dropna()
    for col in ["Close", "close", "Adj Close"]:
        if col in df.columns:
            s = df[col]
            return (s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s).dropna()
    return None


def compute_pct_returns(df: pd.DataFrame) -> dict:
    """Given daily OHLCV df, return % returns for standard periods."""
    if df is None or df.empty:
        return {}
    close = _get_close(df)
    if close is None or close.empty:
        return {}
    now   = float(close.iloc[-1])
    today = close.index[-1]

    def pct_ago(days):
        target = today - timedelta(days=days)
        past = close[close.index <= target]
        if past.empty:
            return None
        past_val = float(past.iloc[-1])
        return round(((now - past_val) / past_val) * 100, 2) if past_val else None

    return {
        "pct_1d":  pct_ago(1),
        "pct_1w":  pct_ago(7),
        "pct_2w":  pct_ago(14),
        "pct_1m":  pct_ago(30),
        "pct_3m":  pct_ago(90),
        "pct_6m":  pct_ago(180),
        "pct_1y":  pct_ago(365),
    }


@timed_cache(ttl_seconds=3600)
def fetch_all_sector_prices() -> dict[str, pd.DataFrame]:
    """Batch-fetch 1y daily OHLCV for all sector indices."""
    result = {}
    symbols = list(SECTOR_INDICES.values())
    batch = _download_multi_with_retry(symbols, period="1y")

    for sector, sym in SECTOR_INDICES.items():
        try:
            df = None
            if batch is not None and sym in batch.columns.get_level_values(0):
                df = batch[sym].dropna(how="all")
            if df is None or df.empty:
                df = _download_with_retry(sym, period="1y")
            if df is not None and not df.empty:
                df.index = pd.to_datetime(df.index).date
                result[sector] = df
            else:
                # Index symbol not available in yfinance — build equal-weighted composite
                stocks = SECTOR_STOCKS.get(sector, [])
                if stocks:
                    logger.warning(f"Sector index {sym} unavailable; building composite for {sector}")
                    sb = _download_multi_with_retry(stocks, period="1y")
                    closes = []
                    for s in stocks:
                        try:
                            if sb is not None and s in sb.columns.get_level_values(0):
                                c = sb[s]["Close"].dropna()
                            else:
                                c = (_download_with_retry(s, period="1y") or pd.DataFrame()).get("Close", pd.Series()).dropna()
                            if c is not None and not c.empty:
                                closes.append(c.rename(s))
                        except Exception:
                            pass
                    if closes:
                        composite = pd.concat(closes, axis=1).dropna(how="all")
                        composite = composite.div(composite.iloc[0]).mean(axis=1) * 1000
                        df = pd.DataFrame({"Close": composite, "Open": composite, "High": composite, "Low": composite})
                        df.index = pd.to_datetime(df.index).date
                        result[sector] = df
        except Exception as e:
            logger.error(f"Failed to get sector {sector} ({sym}): {e}")
    return result


@timed_cache(ttl_seconds=3600)
def fetch_sector_stocks(sector: str) -> dict[str, pd.DataFrame]:
    """Fetch 1y OHLCV for all stocks in a sector."""
    symbols = SECTOR_STOCKS.get(sector, [])
    if not symbols:
        return {}
    batch = _download_multi_with_retry(symbols, period="1y")
    result = {}
    for sym in symbols:
        try:
            if batch is not None and sym in batch.columns.get_level_values(0):
                df = batch[sym].dropna(how="all")
            else:
                df = _download_with_retry(sym, period="1y")
            if df is not None and not df.empty:
                df.index = pd.to_datetime(df.index).date
                result[sym] = df
        except Exception as e:
            logger.warning(f"Stock fetch failed {sym}: {e}")
    return result


def fetch_stock_info(symbol: str) -> dict:
    """Fetch fundamental info for a single stock."""
    try:
        t = yf.Ticker(symbol)
        info = t.info
        holders = t.institutional_holders
        fii_pct, dii_pct, mf_pct = None, None, None
        try:
            sh = t.get_shares_full()
        except Exception:
            pass
        return {
            "name":            info.get("longName", symbol),
            "market_cap":      info.get("marketCap"),
            "pe":              info.get("trailingPE"),
            "52w_high":        info.get("fiftyTwoWeekHigh"),
            "52w_low":         info.get("fiftyTwoWeekLow"),
            "promoter_pct":    None,
            "fii_holding_pct": None,
            "dii_holding_pct": None,
            "mf_pct":          None,
        }
    except Exception as e:
        logger.error(f"Info fetch failed for {symbol}: {e}")
        return {}
