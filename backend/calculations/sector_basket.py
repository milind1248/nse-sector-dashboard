"""Equal-weighted basket of a sector's constituent stocks, used as a price
series when the data provider's own sector-index history is unavailable."""
from typing import Optional

import pandas as pd

MIN_STOCKS = 3
MIN_BARS = 30
BASE_LEVEL = 1000.0


def build_basket_ohlcv(stock_dfs: dict) -> Optional[pd.DataFrame]:
    """
    stock_dfs: {symbol: OHLCV DataFrame} sharing one kind of index (dates or timestamps).

    Close = daily-rebalanced equal-weight compounding of constituent returns, rebased
    to 1000, so stocks with different history lengths don't distort the series.
    Open/High/Low = basket close scaled by the average per-stock Open/Close,
    High/Close and Low/Close ratios (keeps candles coherent). Volume = sum.
    Returns None when there is not enough usable data.
    """
    rets, o_r, h_r, l_r, vols = [], [], [], [], []
    for df in stock_dfs.values():
        try:
            if df is None or len(df) < MIN_BARS:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df = df.copy()
                df.columns = df.columns.get_level_values(0)
            need = {"Open", "High", "Low", "Close"}
            if not need.issubset(df.columns):
                continue
            d = df.dropna(subset=["Close"])
            if len(d) < MIN_BARS:
                continue
            c = d["Close"].astype(float)
            rets.append(c.pct_change())
            o_r.append(d["Open"].astype(float) / c)
            h_r.append(d["High"].astype(float) / c)
            l_r.append(d["Low"].astype(float) / c)
            if "Volume" in d.columns:
                vols.append(d["Volume"].astype(float))
        except Exception:
            continue

    if len(rets) < MIN_STOCKS:
        return None

    daily = pd.concat(rets, axis=1).mean(axis=1, skipna=True).dropna()
    if len(daily) < MIN_BARS:
        return None
    close = BASE_LEVEL * (1 + daily).cumprod()

    def avg_ratio(frames):
        r = pd.concat(frames, axis=1).mean(axis=1, skipna=True).reindex(close.index)
        return r.fillna(1.0)

    out = pd.DataFrame({
        "Open": close * avg_ratio(o_r),
        "High": close * avg_ratio(h_r),
        "Low": close * avg_ratio(l_r),
        "Close": close,
    })
    out["High"] = out[["Open", "High", "Low", "Close"]].max(axis=1)
    out["Low"] = out[["Open", "High", "Low", "Close"]].min(axis=1)
    out["Volume"] = (pd.concat(vols, axis=1).sum(axis=1).reindex(close.index).fillna(0.0)
                     if vols else 0.0)
    return out
