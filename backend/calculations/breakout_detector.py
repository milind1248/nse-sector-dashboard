"""
Technical confirmation for the PEAD Scanner — "is the earnings surprise
actually showing up in price action, or is it sitting there unconfirmed?"
(the Rishabh Instruments-vs-Websol Energy distinction from the source
video: same kind of strong result, very different price reaction).

Reuses backend/calculations/indicators.py's EMA stack for the 200-EMA
check, and the swing-pivot/breakout-confirmation pattern already built
and debugged twice this session (backend/calculations/swing_scanner.py,
the standalone gann_strategy_backtest.py) rather than a third from-scratch
version — no dedicated breakout detector existed anywhere in this
codebase before this file (confirmed via explore agent).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BreakoutParams:
    ema_period: int = 200
    lookback_days: int = 50          # N-day-high breakout window
    breakout_confirm_pct: float = 0.5  # % above the N-day high to confirm (avoid noise-level "breakouts")
    volume_avg_period: int = 20
    volume_spike_mult: float = 1.5   # matches the video's implicit "real reaction" bar


def is_above_200ema(df: pd.DataFrame, params: BreakoutParams | None = None) -> dict:
    """df must have a Close column, at least ema_period+1 rows."""
    p = params or BreakoutParams()
    close = df["Close"]
    if len(close) < p.ema_period:
        return {"above_200ema": None, "ema200": None, "dist_pct": None}
    ema = close.ewm(span=p.ema_period, adjust=False).mean()
    last_close = float(close.iloc[-1])
    last_ema = float(ema.iloc[-1])
    return {
        "above_200ema": last_close > last_ema,
        "ema200": round(last_ema, 2),
        "dist_pct": round((last_close - last_ema) / last_ema * 100, 2) if last_ema else None,
    }


def detect_breakout(df: pd.DataFrame, params: BreakoutParams | None = None) -> dict:
    """N-day-high breakout with volume confirmation. `df` must have
    Open/High/Low/Close/Volume. Uses only the trailing `lookback_days`
    window EXCLUDING today's own bar for the resistance level (today's
    high can't be part of its own resistance check), then tests whether
    today's close clears it by breakout_confirm_pct — same causal
    structure as the resistance-level bug fix made earlier this session
    in gann_strategy_backtest.py (resistance must be a level set BEFORE
    today, never including today)."""
    p = params or BreakoutParams()
    if len(df) < p.lookback_days + p.volume_avg_period + 1:
        return {"breakout": None, "resistance_level": None, "volume_confirmed": None, "reason": "insufficient history"}

    close = df["Close"]
    high = df["High"]
    volume = df["Volume"]

    prior_window = high.iloc[-(p.lookback_days + 1):-1]  # excludes today
    resistance = float(prior_window.max())
    last_close = float(close.iloc[-1])

    vol_avg = float(volume.iloc[-(p.volume_avg_period + 1):-1].mean())
    last_vol = float(volume.iloc[-1])
    volume_confirmed = last_vol > vol_avg * p.volume_spike_mult if vol_avg > 0 else False

    breakout = last_close > resistance * (1 + p.breakout_confirm_pct / 100.0)

    return {
        "breakout": bool(breakout),
        "resistance_level": round(resistance, 2),
        "last_close": round(last_close, 2),
        "breakout_pct_above_resistance": round((last_close - resistance) / resistance * 100, 2) if resistance else None,
        "volume_confirmed": bool(volume_confirmed),
        "volume_ratio": round(last_vol / vol_avg, 2) if vol_avg > 0 else None,
    }


def technical_confirmation(df: pd.DataFrame, params: BreakoutParams | None = None) -> dict:
    """Combined check used by the PEAD Scanner's Deep Dive tab — matches
    the video's "is it technically strong" question, not just a single
    signal. `confirmed` is True only when BOTH the trend context (above
    200 EMA) and a real breakout with volume are present — the same
    "core minimal condition, not every optional narrowing" design used
    throughout this session's other scanners."""
    p = params or BreakoutParams()
    ema_result = is_above_200ema(df, p)
    breakout_result = detect_breakout(df, p)
    confirmed = bool(ema_result.get("above_200ema")) and bool(breakout_result.get("breakout")) and bool(breakout_result.get("volume_confirmed"))
    return {**ema_result, **breakout_result, "technically_confirmed": confirmed}
