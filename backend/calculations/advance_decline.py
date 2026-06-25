"""Compute advance/decline ratios per sector from stock price data."""
from typing import Optional
import pandas as pd
from datetime import date, timedelta


def compute_sector_advance_decline(
    stock_prices: dict[str, pd.DataFrame],
    lookback_days: int = 1,
) -> dict:
    """
    Given {symbol: ohlcv_df}, return advance/decline counts.
    lookback_days=1 → today vs yesterday (daily A/D)
    lookback_days=5 → this week
    lookback_days=30 → this month
    """
    advance = 0
    decline = 0
    unchanged = 0

    for sym, df in stock_prices.items():
        if df is None or df.empty or len(df) < lookback_days + 1:
            continue
        try:
            close = df["Close"].dropna()
            if len(close) < lookback_days + 1:
                continue
            now  = float(close.iloc[-1])
            past = float(close.iloc[-(lookback_days + 1)])
            diff = now - past
            if diff > 0:
                advance += 1
            elif diff < 0:
                decline += 1
            else:
                unchanged += 1
        except Exception:
            continue

    total = advance + decline + unchanged
    ad_ratio = round(advance / decline, 2) if decline > 0 else float("inf")
    return {
        "advance":   advance,
        "decline":   decline,
        "unchanged": unchanged,
        "total":     total,
        "ad_ratio":  ad_ratio,
    }
