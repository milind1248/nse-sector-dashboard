"""
Monthly sector-leadership map — reproduces the "a different sector leads
every period, never the same one twice in a row" chart shown in the Rohan
Mehta interview (see backend/calculations/momentum_alltimehigh.py's
docstring for the full framework this pairs with).

No Streamlit imports here — caching is the caller's responsibility.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from config import SECTOR_INDICES


def monthly_sector_returns(months: int = 24) -> pd.DataFrame:
    """
    Fetches config.SECTOR_INDICES at DAILY resolution and resamples to
    month-end in pandas, then returns a sector x month % return grid
    (rows=sector, columns=month-end date).

    Deliberately does NOT use yfinance's native interval="1mo" — verified
    directly that it returns only 1 row for most of these ^CNX*/NIFTY*
    index tickers (a yfinance quirk on this ticker family, not a
    daily-data problem), while interval="1d" works reliably. Resampling
    daily data ourselves avoids that broken path entirely.

    Sectors whose index ticker fails to fetch at all are silently skipped
    — some entries in SECTOR_INDICES are known to be unavailable on
    yfinance regardless of interval (same limitation already documented
    in config.py itself, e.g. NIFTYCHEM.NS/NIFTYDEF.NS/^CNXFINANCE).
    """
    period = f"{max(2, months // 12 + 1)}y"
    rows: dict[str, pd.Series] = {}
    for sector, ticker in SECTOR_INDICES.items():
        try:
            df = yf.download(ticker, period=period, interval="1d", auto_adjust=True, progress=False)
            if hasattr(df.columns, "levels"):
                df.columns = [c[0] for c in df.columns]
            df = df.dropna(how="all")
            if len(df) < 60:
                continue
            month_end_close = df["Close"].resample("ME").last().dropna()
            if len(month_end_close) < 3:
                continue
            ret = month_end_close.pct_change().dropna() * 100
            rows[sector] = ret.tail(months)
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()

    grid = pd.DataFrame(rows).T
    grid = grid.sort_index(axis=1)
    return grid.round(2)


def sector_leadership_rank(grid: pd.DataFrame) -> pd.DataFrame:
    """Same-shape grid, each cell = that sector's return-rank within its
    month (1 = best that month, N = worst). NaN columns stay NaN."""
    if grid.empty:
        return grid
    return grid.rank(axis=0, ascending=False, method="min")


def monthly_leaders(grid: pd.DataFrame, top_k: int = 1) -> pd.DataFrame:
    """One row per month: the top_k sector(s) by return that month."""
    if grid.empty:
        return pd.DataFrame(columns=["month", "leader", "return_pct"])
    out = []
    for month in grid.columns:
        col = grid[month].dropna()
        if col.empty:
            continue
        top = col.sort_values(ascending=False).head(top_k)
        for sector, ret in top.items():
            out.append({"month": month.strftime("%b %Y"), "leader": sector, "return_pct": round(float(ret), 2)})
    return pd.DataFrame(out)
