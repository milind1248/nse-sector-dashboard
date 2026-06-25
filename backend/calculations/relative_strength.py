"""Relative strength vs Nifty and RRG coordinate computation."""
from typing import Optional
import pandas as pd
import numpy as np


def _close(df: pd.DataFrame) -> pd.Series:
    if isinstance(df.columns, pd.MultiIndex):
        for lv in ["Close", "close"]:
            if lv in df.columns.get_level_values(0):
                s = df[lv]
                return (s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s).dropna()
    for col in ["Close", "close"]:
        if col in df.columns:
            s = df[col]
            return (s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s).dropna()
    return pd.Series(dtype=float)


def compute_rs_ratio(sector_df: pd.DataFrame, nifty_df: pd.DataFrame,
                     period: int = 30) -> Optional[float]:
    """RS-Ratio: sector performance relative to Nifty over `period` days."""
    try:
        s_close = _close(sector_df)
        n_close = _close(nifty_df)
        common  = s_close.index.intersection(n_close.index)
        if len(common) < period + 1:
            return None
        s = s_close.loc[common].iloc[-(period+1):]
        n = n_close.loc[common].iloc[-(period+1):]
        rs = (s / s.iloc[0]) / (n / n.iloc[0])
        # Normalize to 100-based scale (JdK style)
        rs_ratio = 100 + (rs.iloc[-1] - rs.mean()) / rs.std() * 10
        return round(float(rs_ratio), 2)
    except Exception:
        return None


def compute_rs_momentum(sector_df: pd.DataFrame, nifty_df: pd.DataFrame,
                        rs_period: int = 30, roc_period: int = 5) -> Optional[float]:
    """RS-Momentum: rate of change of RS-Ratio."""
    try:
        s_close = _close(sector_df)
        n_close = _close(nifty_df)
        common  = s_close.index.intersection(n_close.index)
        if len(common) < rs_period + roc_period + 5:
            return None

        rs_series = []
        idx = list(common)
        for i in range(roc_period + 1):
            end_idx = len(idx) - i
            start_idx = max(0, end_idx - rs_period - 1)
            s_slice = s_close.loc[idx[start_idx:end_idx]]
            n_slice = n_close.loc[idx[start_idx:end_idx]]
            if len(s_slice) < 5:
                continue
            rs = (s_slice / s_slice.iloc[0]) / (n_slice / n_slice.iloc[0])
            rs_ratio = 100 + (rs.iloc[-1] - rs.mean()) / (rs.std() + 1e-9) * 10
            rs_series.append(float(rs_ratio))

        if len(rs_series) < 2:
            return None
        momentum = 100 + (rs_series[0] - rs_series[-1])
        return round(float(momentum), 2)
    except Exception:
        return None


def compute_rrg_coordinates(sector_prices: dict[str, pd.DataFrame],
                             nifty_df: pd.DataFrame) -> list[dict]:
    """
    Returns list of dicts with: sector, rs_ratio, rs_momentum, quadrant, trail (list of past points).
    """
    result = []
    for sector, df in sector_prices.items():
        trail = []
        for weeks_back in range(4, -1, -1):
            # Simulate price data shifted back in time
            if weeks_back == 0:
                s_df = df
            else:
                cutoff = len(df) - weeks_back * 5
                if cutoff <= 30:
                    continue
                s_df = df.iloc[:cutoff]

            rs_r = compute_rs_ratio(s_df, nifty_df)
            rs_m = compute_rs_momentum(s_df, nifty_df)
            if rs_r is not None and rs_m is not None:
                trail.append({"rs_ratio": rs_r, "rs_momentum": rs_m})

        if not trail:
            continue

        latest = trail[-1]
        rs_r   = latest["rs_ratio"]
        rs_m   = latest["rs_momentum"]

        if rs_r >= 100 and rs_m >= 100:
            quadrant = "Leading"
        elif rs_r < 100 and rs_m >= 100:
            quadrant = "Improving"
        elif rs_r < 100 and rs_m < 100:
            quadrant = "Lagging"
        else:
            quadrant = "Weakening"

        result.append({
            "sector":       sector,
            "rs_ratio":     rs_r,
            "rs_momentum":  rs_m,
            "quadrant":     quadrant,
            "trail":        trail,
        })
    return result
