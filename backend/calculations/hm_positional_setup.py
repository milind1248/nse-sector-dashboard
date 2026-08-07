"""
H-M "positional setup" — exact reproduction of the Chartink screener
"Daily Chart Positional Hilega Toh Milega Indicator by NK Sir"
(https://chartink.com/screener/daily-chart-positional-hilega-toh-milega-indicator-by-nk-sir),
codified directly from its literal filter conditions. Confirmed against
Chartink's own live result table: 10/13 exact stock overlap, with the
remainder explained by data-source timing/liquidity differences on thin
small-caps, not a logic error.

Shared by scripts/hm_daily_positional_scanner.py (standalone backtest —
found NO real edge: win rate 40-45%, negative excess return vs NIFTY at
every horizon, n=8,811 over 3 years) and the live HM Scanner page's
"Positional Setup" tab. Kept here, not duplicated, so both always agree.

The 13 conditions (RSI/EMA/WMA computed exactly as Chartink does — Daily
RSI(9), Ema(Rsi(9),3), Wma(Rsi(9),21) — precisely what
backend/calculations/hm_indicators.py::add_indicators() already produces
as RSI / HM_EMA / HM_WMA):
  1-5. RSI(9) was <= 50 on EACH of the last 5 trading days.
  6.   Today's WMA(RSI,21) <= 50.
  7.   Yesterday: WMA(RSI,21) > RSI.
  8.   Today: WMA(RSI,21) <= RSI (combined with #7 — RSI crossed WMA today).
  9.   Yesterday: EMA(RSI,3) <= WMA(RSI,21).
  10.  Today: EMA(RSI,3) >= WMA(RSI,21) (combined with #9 — EMA crossed WMA today).
  11.  Today: EMA(RSI,3) < RSI (RSI still leading — a fresh cross).
  12.  Today: RSI(9) >= 50.
  13.  Today: Daily Close < 3500.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.calculations.hm_indicators import add_indicators

RSI_BELOW_DAYS = 5
RSI_BELOW_LEVEL = 50.0
CLOSE_MAX = 3500.0
SIGNAL_COOLDOWN_DAYS = 5   # safety-valve dedup — the rule's own dual-cross structure already makes back-to-back repeats rare


def add_positional_hm_signal(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized across the whole history (not just the latest bar) so
    it's backtestable — every rolling/shift op only looks backward from
    each bar, no lookahead. A COOLDOWN dedup is applied (lesson learned
    from this session's uptrend/SMA20 scanner, where a naive day-to-day
    dedup still produced dozens of overlapping, highly-correlated
    pseudo-signals for one ongoing setup)."""
    out = add_indicators(df)
    if out.empty:
        return out

    rsi, ema, wma, close = out["RSI"], out["HM_EMA"], out["HM_WMA"], out["Close"]

    cond_5day_below = rsi.shift(1).rolling(RSI_BELOW_DAYS).max() <= RSI_BELOW_LEVEL
    cond6 = wma <= RSI_BELOW_LEVEL
    cond7 = wma.shift(1) > rsi.shift(1)
    cond8 = wma <= rsi
    cond9 = ema.shift(1) <= wma.shift(1)
    cond10 = ema >= wma
    cond11 = ema < rsi
    cond12 = rsi >= RSI_BELOW_LEVEL
    cond13 = close < CLOSE_MAX

    raw_signal = (
        cond_5day_below.fillna(False) & cond6.fillna(False) & cond7.fillna(False)
        & cond8.fillna(False) & cond9.fillna(False) & cond10.fillna(False)
        & cond11.fillna(False) & cond12.fillna(False) & cond13.fillna(False)
    )
    out["SIGNAL_RAW"] = raw_signal

    signal_positions = np.where(raw_signal.to_numpy())[0]
    accepted = np.zeros(len(out), dtype=bool)
    last_accepted_pos = -SIGNAL_COOLDOWN_DAYS - 1
    for pos in signal_positions:
        if pos - last_accepted_pos > SIGNAL_COOLDOWN_DAYS:
            accepted[pos] = True
            last_accepted_pos = pos
    out["SIGNAL"] = accepted
    return out


def check_positional_hm_signal_latest(df: pd.DataFrame) -> bool:
    """Cheap single-bar check for a live scan — same 13 conditions,
    evaluated only on the most recent bar (no need to vectorize the whole
    history when scanning a wide universe for "does it match today")."""
    ind = add_indicators(df)
    if ind.empty or len(ind) < RSI_BELOW_DAYS + 5:
        return False

    rsi, ema, wma, close = ind["RSI"], ind["HM_EMA"], ind["HM_WMA"], ind["Close"]

    cond_5day_below = all(bool(rsi.iloc[-1 - k] <= RSI_BELOW_LEVEL) for k in range(1, RSI_BELOW_DAYS + 1))
    cond6 = bool(wma.iloc[-1] <= RSI_BELOW_LEVEL)
    cond7 = bool(wma.iloc[-2] > rsi.iloc[-2])
    cond8 = bool(wma.iloc[-1] <= rsi.iloc[-1])
    cond9 = bool(ema.iloc[-2] <= wma.iloc[-2])
    cond10 = bool(ema.iloc[-1] >= wma.iloc[-1])
    cond11 = bool(ema.iloc[-1] < rsi.iloc[-1])
    cond12 = bool(rsi.iloc[-1] >= RSI_BELOW_LEVEL)
    cond13 = bool(close.iloc[-1] < CLOSE_MAX)

    return all([cond_5day_below, cond6, cond7, cond8, cond9, cond10, cond11, cond12, cond13])


def backtest_positional_signal(df: pd.DataFrame, symbol: str, hold_days: list[int]) -> pd.DataFrame:
    if df.empty or "SIGNAL" not in df.columns:
        return pd.DataFrame()
    positions = np.where(df["SIGNAL"].fillna(False).to_numpy())[0]
    rows = []
    for pos in positions:
        entry_pos = pos + 1
        if entry_pos >= len(df):
            continue
        entry = float(df["Open"].iloc[entry_pos])
        entry_time = df.index[entry_pos]
        row = {"symbol": symbol, "signal_time": df.index[pos], "entry_time": entry_time, "entry": entry}
        for h in hold_days:
            target_pos = entry_pos + h
            if target_pos >= len(df):
                row[f"ret_{h}d"] = None
                row[f"exit_time_{h}d"] = None
                continue
            exit_price = float(df["Close"].iloc[target_pos])
            row[f"ret_{h}d"] = (exit_price / entry - 1) * 100
            row[f"exit_time_{h}d"] = df.index[target_pos]
        rows.append(row)
    return pd.DataFrame(rows)
