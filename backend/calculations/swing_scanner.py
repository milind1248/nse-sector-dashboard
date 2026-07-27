"""Swing Scanner — trend-pullback strategy detector.

Backtest-validated variant (StockOnly, no sector/RS filters — those
underperformed in a real Nifty 500 2020-2025 backtest, largely due to
several Yahoo Finance sector indices being dead; see the standalone
swing_backtest.py analysis). This module ports the strategy's core
condition checks from that backtest script into this codebase's established
vectorized-column style (matching hm_expansion.py), rather than the
backtest's row-by-row idx loops — a live scan only needs the latest bar's
booleans, but full-history columns are kept for auditability/charting.

Strategy in one line: buy stocks in a confirmed uptrend (Close > SMA50 >
SMA200) that have pulled back from overbought RSI into a 40-55 band near
their 20 EMA, on above-average volume with a bullish candle — risk-managed
with an ATR-based stop, 1:2 reward, 20-day max hold.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class SwingParams:
    sma_short: int = 20
    sma_medium: int = 50
    sma_long: int = 200
    rsi_period: int = 14
    rsi_high_threshold: float = 60.0
    rsi_pullback_low: float = 40.0
    rsi_pullback_high: float = 55.0
    rsi_lookback: int = 10
    ema_proximity_pct: float = 2.0
    volume_avg_period: int = 20
    min_avg_volume: int = 100_000
    min_price: float = 50.0
    stop_loss_atr_mult: float = 1.0
    target_rr: float = 2.0
    max_hold_days: int = 20


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Pure-pandas Wilder RSI — no pandas_ta dependency (it hard-requires
    numba, which doesn't support this project's Python version). Verified
    against pandas_ta's own convention in the standalone backtest script."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    # A pure/near-pure sustained rally (no down days in the smoothing window)
    # makes avg_loss hit exactly 0, which the division guard above turns
    # into NaN instead of the mathematically correct RSI=100. Real momentum
    # stocks can genuinely run without a single down day, so this isn't a
    # rare synthetic edge case — worth fixing rather than leaving as NaN.
    rsi = rsi.where(avg_loss != 0, other=100.0)
    return rsi


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Pure-pandas Wilder ATR."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def add_swing_indicators(df: pd.DataFrame, params: SwingParams | None = None) -> pd.DataFrame:
    """df must have Open/High/Low/Close/Volume columns. Returns a copy with
    SMA_Short/SMA_Med/SMA_Long/EMA_20/RSI/Volume_Avg/ATR/Body/Upper_Shadow/
    Lower_Shadow columns added."""
    p = params or SwingParams()
    out = df.copy()

    out["SMA_Short"] = out["Close"].rolling(window=p.sma_short).mean()
    out["EMA_20"] = out["Close"].ewm(span=p.sma_short, adjust=False).mean()
    out["SMA_Med"] = out["Close"].rolling(window=p.sma_medium).mean()
    out["SMA_Long"] = out["Close"].rolling(window=p.sma_long).mean()
    out["RSI"] = _rsi(out["Close"], length=p.rsi_period)
    out["Volume_Avg"] = out["Volume"].rolling(window=p.volume_avg_period).mean()
    out["ATR"] = _atr(out["High"], out["Low"], out["Close"], length=14)
    out["Body"] = out["Close"] - out["Open"]
    out["Upper_Shadow"] = out["High"] - out[["Open", "Close"]].max(axis=1)
    out["Lower_Shadow"] = out[["Open", "Close"]].min(axis=1) - out["Low"]

    return out


def compute_swing_signal(df: pd.DataFrame, params: SwingParams | None = None) -> pd.DataFrame:
    """df must already have the columns from add_swing_indicators(). Returns
    a copy with the 6 condition booleans, Stock_Score, Stock_Pass, and (for
    every bar — cheap to compute, useful for charting) reference Stop_Loss/
    Target levels derived from that bar's own Close/ATR. These are display
    reference levels only, not an auto-trade instruction."""
    p = params or SwingParams()
    out = df.copy()

    close, sma_med, sma_long = out["Close"], out["SMA_Med"], out["SMA_Long"]
    out["Stock_Trend"] = (close > sma_med) & (close > sma_long) & (sma_med > sma_long)

    rsi = out["RSI"]
    recent_rsi_max = rsi.rolling(window=p.rsi_lookback).max().shift(1)
    was_overbought = recent_rsi_max > p.rsi_high_threshold
    now_pullback = (rsi >= p.rsi_pullback_low) & (rsi <= p.rsi_pullback_high)
    out["RSI_Pullback"] = (was_overbought & now_pullback).fillna(False)

    ema20 = out["EMA_20"]
    out["EMA_Prox"] = ((close - ema20).abs() / ema20.replace(0, np.nan) * 100 <= p.ema_proximity_pct).fillna(False)

    out["Volume_Spike"] = out["Volume"] > out["Volume_Avg"]

    out["Bullish_Candle"] = (close > out["Open"]) & (out["Lower_Shadow"] > out["Upper_Shadow"])

    avg_vol_prior = out["Volume"].rolling(window=p.volume_avg_period).mean().shift(1)
    out["Liquidity"] = (close >= p.min_price) & (avg_vol_prior >= p.min_avg_volume)

    condition_cols = ["Stock_Trend", "RSI_Pullback", "EMA_Prox", "Volume_Spike", "Bullish_Candle", "Liquidity"]
    out["Stock_Score"] = out[condition_cols].fillna(False).sum(axis=1)
    out["Stock_Pass"] = out[condition_cols].fillna(False).all(axis=1)

    out["Stop_Loss"] = close - out["ATR"] * p.stop_loss_atr_mult
    out["Target"] = close + (close - out["Stop_Loss"]) * p.target_rr

    return out
