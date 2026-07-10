from __future__ import annotations

import numpy as np
import pandas as pd


def backtest_signals(
    df: pd.DataFrame,
    symbol: str,
    hold_bars: int = 10,
    stop_atr: float = 1.5,
    target_atr: float = 2.0,
) -> pd.DataFrame:
    if df.empty or "BOTTOM_SIGNAL" not in df.columns:
        return pd.DataFrame()

    rows = []
    signal_positions = np.where(df["BOTTOM_SIGNAL"].fillna(False).to_numpy())[0]
    for pos in signal_positions:
        entry_pos = pos + 1
        exit_pos = min(entry_pos + hold_bars, len(df) - 1)
        if entry_pos >= len(df) or exit_pos <= entry_pos:
            continue
        entry = float(df["Open"].iloc[entry_pos])
        atr_val = float(df["ATR14"].iloc[pos]) if not pd.isna(df["ATR14"].iloc[pos]) else entry * 0.02
        stop = entry - stop_atr * atr_val
        target = entry + target_atr * atr_val
        window = df.iloc[entry_pos : exit_pos + 1]

        outcome = "time_exit"
        exit_price = float(window["Close"].iloc[-1])
        exit_time = window.index[-1]
        for idx, bar in window.iterrows():
            if float(bar["Low"]) <= stop:
                outcome = "stop"
                exit_price = stop
                exit_time = idx
                break
            if float(bar["High"]) >= target:
                outcome = "target"
                exit_price = target
                exit_time = idx
                break

        max_high = float(window["High"].max())
        min_low = float(window["Low"].min())
        rows.append({
            "symbol": symbol,
            "signal_time": df.index[pos],
            "entry_time": df.index[entry_pos],
            "exit_time": exit_time,
            "entry": entry,
            "exit": exit_price,
            "return_pct": (exit_price / entry - 1) * 100,
            "mfe_pct": (max_high / entry - 1) * 100,
            "mae_pct": (min_low / entry - 1) * 100,
            "outcome": outcome,
            "score": float(df["BOTTOM_SCORE"].iloc[pos]),
            "rsi": float(df["RSI"].iloc[pos]),
            "reason": str(df["SIGNAL_REASON"].iloc[pos]),
        })
    return pd.DataFrame(rows)


def backtest_top_signals(
    df: pd.DataFrame,
    symbol: str,
    hold_bars: int = 10,
    stop_atr: float = 1.5,
    target_atr: float = 2.0,
) -> pd.DataFrame:
    if df.empty or "TOP_SIGNAL" not in df.columns:
        return pd.DataFrame()

    rows = []
    signal_positions = np.where(df["TOP_SIGNAL"].fillna(False).to_numpy())[0]
    for pos in signal_positions:
        entry_pos = pos + 1
        exit_pos = min(entry_pos + hold_bars, len(df) - 1)
        if entry_pos >= len(df) or exit_pos <= entry_pos:
            continue
        entry = float(df["Open"].iloc[entry_pos])
        atr_val = float(df["ATR14"].iloc[pos]) if not pd.isna(df["ATR14"].iloc[pos]) else entry * 0.02
        stop = entry + stop_atr * atr_val
        target = entry - target_atr * atr_val
        window = df.iloc[entry_pos : exit_pos + 1]

        outcome = "time_exit"
        exit_price = float(window["Close"].iloc[-1])
        exit_time = window.index[-1]
        for idx, bar in window.iterrows():
            if float(bar["High"]) >= stop:
                outcome = "stop"
                exit_price = stop
                exit_time = idx
                break
            if float(bar["Low"]) <= target:
                outcome = "target"
                exit_price = target
                exit_time = idx
                break

        max_high = float(window["High"].max())
        min_low = float(window["Low"].min())
        rows.append({
            "symbol": symbol,
            "signal_time": df.index[pos],
            "entry_time": df.index[entry_pos],
            "exit_time": exit_time,
            "entry": entry,
            "exit": exit_price,
            "return_pct": (entry / exit_price - 1) * 100,
            "mfe_pct": (entry / min_low - 1) * 100,
            "mae_pct": (entry / max_high - 1) * 100,
            "outcome": outcome,
            "score": float(df["TOP_SCORE"].iloc[pos]),
            "rsi": float(df["RSI"].iloc[pos]),
            "reason": str(df["TOP_SIGNAL_REASON"].iloc[pos]),
        })
    return pd.DataFrame(rows)


def summarize_backtests(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()

    def agg(g: pd.DataFrame) -> pd.Series:
        wins = (g["return_pct"] > 0).mean() * 100
        target_rate = (g["outcome"] == "target").mean() * 100
        avg_ret = g["return_pct"].mean()
        median_mfe = g["mfe_pct"].median()
        response_score = (wins * 0.35) + (target_rate * 0.25) + (max(avg_ret, -10) * 5) + (median_mfe * 3)
        return pd.Series({
            "signals": len(g),
            "win_rate_%": round(wins, 1),
            "target_rate_%": round(target_rate, 1),
            "avg_return_%": round(avg_ret, 1),
            "median_mfe_%": round(median_mfe, 1),
            "avg_score": round(g["score"].mean(), 1),
            "response_score": round(response_score, 1),
        })

    summary = trades.groupby("symbol", as_index=False).apply(agg, include_groups=False).reset_index()
    if "level_1" in summary.columns:
        summary = summary.drop(columns=["level_1"])
    return summary.sort_values(["response_score", "signals"], ascending=False)
