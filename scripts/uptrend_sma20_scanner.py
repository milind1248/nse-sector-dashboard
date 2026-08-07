"""
Standalone scanner: stocks in a confirmed uptrend that are "respecting"
their 20-day SMA — i.e. using it as support on pullbacks rather than
breaking down through it. Deliberately standalone, not wired into the
live website, matching every other one-off scanner built this session.

Definition used (auditable, not a black box):
  - Uptrend: Close > SMA20 > SMA50, and SMA50 itself has risen over the
    last TREND_LOOKBACK bars (a genuinely rising trend, not just a
    momentary stack).
  - "Respects the 20 SMA": over the last RESPECT_LOOKBACK bars, price
    never closed meaningfully below SMA20 (allows brief wicks below,
    since that's a normal pullback, but the CLOSE must have stayed at or
    above SMA20 * (1 - BREACH_TOLERANCE_PCT) every day) AND price has
    actually come close to SMA20 at least once recently (proving it's
    being used as a real support level, not just floating far above it
    where the "respect" claim would be untestable).

Run: python scripts/uptrend_sma20_scanner.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import yfinance as yf

from backend.calculations.universe import load_symbols

TREND_LOOKBACK = 20            # bars over which SMA50 must have risen
RESPECT_LOOKBACK = 15          # bars checked for "didn't break below SMA20"
BREACH_TOLERANCE_PCT = 1.0     # a close can be up to this % below SMA20 without counting as a breach
MAX_BREACH_DAYS = 2            # a couple of brief undercuts is normal noise, not a broken trend — zero-tolerance was too strict
PROXIMITY_PCT = 3.0            # price must have come within this % of SMA20 at least once recently
MIN_PRICE = 20.0
MIN_AVG_VOLUME = 100_000
BENCHMARK = "^NSEI"
HOLD_DAYS = [5, 10, 20]
SIGNAL_COOLDOWN_DAYS = 10      # min gap between accepted signals for the same stock — avoids re-flagging one ongoing pullback


def _fetch(symbol: str, period: str = "1y") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def add_uptrend_sma20_signal(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized version of scan_symbol()'s conditions, computed across
    the WHOLE history (not just the latest bar) so it can be backtested —
    same rules, same thresholds, just applied at every bar causally
    (every rolling window only looks backward from that bar)."""
    out = df.copy()
    if out.empty:
        return out

    out["SMA20"] = out["Close"].rolling(20).mean()
    out["SMA50"] = out["Close"].rolling(50).mean()
    out["AVG_VOL"] = out["Volume"].rolling(20).mean()

    uptrend = (out["Close"] > out["SMA20"]) & (out["SMA20"] > out["SMA50"])
    sma50_rising = out["SMA50"] > out["SMA50"].shift(TREND_LOOKBACK)
    liquid = (out["Close"] >= MIN_PRICE) & (out["AVG_VOL"] >= MIN_AVG_VOLUME)

    breach_floor = out["SMA20"] * (1 - BREACH_TOLERANCE_PCT / 100)
    breach = out["Close"] < breach_floor
    breach_days = breach.rolling(RESPECT_LOOKBACK).sum()
    no_breach = breach_days <= MAX_BREACH_DAYS

    proximity = (out["Low"] - out["SMA20"]).abs() / out["SMA20"] * 100
    touched_recently = (proximity <= PROXIMITY_PCT).rolling(RESPECT_LOOKBACK).sum() > 0

    raw_signal = (
        uptrend.fillna(False) & sma50_rising.fillna(False) & liquid.fillna(False)
        & no_breach.fillna(False) & touched_recently.fillna(False)
    )
    out["SIGNAL_RAW"] = raw_signal

    # De-dupe into discrete entries with a real COOLDOWN, not just "skip if
    # yesterday was also True" — the breach-count condition flickers on/off
    # near its own threshold from day to day (confirmed directly: a naive
    # shift(1) dedup still produced 166 "signals" for one stock in 3 years,
    # almost one every 5 trading days — clearly re-flagging the same
    # ongoing pullback repeatedly, not 166 independent setups). Only count
    # a bar as a new signal if the condition wasn't true at all in the
    # preceding SIGNAL_COOLDOWN_DAYS bars.
    signal_positions = np.where(raw_signal.to_numpy())[0]
    accepted = np.zeros(len(out), dtype=bool)
    last_accepted_pos = -SIGNAL_COOLDOWN_DAYS - 1
    for pos in signal_positions:
        if pos - last_accepted_pos > SIGNAL_COOLDOWN_DAYS:
            accepted[pos] = True
            last_accepted_pos = pos
    out["SIGNAL"] = accepted
    return out


def backtest_signal(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
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
        for h in HOLD_DAYS:
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


def scan_symbol(symbol: str) -> dict | None:
    df = _fetch(symbol)
    if df.empty or len(df) < 60:
        return None

    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["AVG_VOL"] = df["Volume"].rolling(20).mean()

    row = df.iloc[-1]
    if pd.isna(row["SMA20"]) or pd.isna(row["SMA50"]):
        return None
    if row["Close"] < MIN_PRICE or (pd.notna(row["AVG_VOL"]) and row["AVG_VOL"] < MIN_AVG_VOLUME):
        return None

    uptrend = (row["Close"] > row["SMA20"] > row["SMA50"])
    sma50_rising = df["SMA50"].iloc[-1] > df["SMA50"].iloc[-1 - TREND_LOOKBACK] if len(df) > TREND_LOOKBACK else False
    if not (uptrend and sma50_rising):
        return None

    recent = df.iloc[-RESPECT_LOOKBACK:]
    breach_floor = recent["SMA20"] * (1 - BREACH_TOLERANCE_PCT / 100)
    breach_days = int((recent["Close"] < breach_floor).sum())
    if breach_days > MAX_BREACH_DAYS:
        return None

    proximity = ((recent["Low"] - recent["SMA20"]).abs() / recent["SMA20"] * 100)
    touched_recently = bool((proximity <= PROXIMITY_PCT).any())
    if not touched_recently:
        return None

    dist_from_sma20_pct = (row["Close"] - row["SMA20"]) / row["SMA20"] * 100
    return {
        "symbol": symbol,
        "close": round(float(row["Close"]), 2),
        "sma20": round(float(row["SMA20"]), 2),
        "sma50": round(float(row["SMA50"]), 2),
        "dist_from_sma20_pct": round(float(dist_from_sma20_pct), 2),
        "breach_days_last_15": breach_days,
    }


def run(backtest_years: float = 3.0):
    symbols = load_symbols("Nifty 500")
    print(f"Scanning + backtesting {len(symbols)} Nifty 500 stocks for uptrend + 20-SMA respect "
          f"({backtest_years:.0f}y history)…\n")

    try:
        bench = _fetch(BENCHMARK, period=f"{max(1, round(backtest_years))}y")
        bench_close = bench["Close"]
    except Exception as e:
        print(f"FATAL: could not fetch benchmark {BENCHMARK}: {e}")
        return

    def _bench_return(entry_time, exit_time):
        if exit_time is None:
            return None
        idx = bench_close.index
        e_on_after = idx[idx >= entry_time]
        x_on_after = idx[idx >= exit_time]
        if len(e_on_after) == 0 or len(x_on_after) == 0:
            return None
        b_entry, b_exit = float(bench_close.loc[e_on_after[0]]), float(bench_close.loc[x_on_after[0]])
        return (b_exit / b_entry - 1) * 100 if b_entry else None

    matches = []
    all_trades = []
    for i, symbol in enumerate(symbols):
        try:
            result = scan_symbol(symbol)
            if result:
                matches.append(result)

            hist = _fetch(symbol, period=f"{max(1, round(backtest_years))}y")
            if len(hist) >= 80:
                sig = add_uptrend_sma20_signal(hist)
                t = backtest_signal(sig, symbol)
                if not t.empty:
                    all_trades.append(t)
        except Exception:
            continue
        if (i + 1) % 50 == 0:
            print(f"  …{i+1}/{len(symbols)} processed, {len(matches)} live match(es) so far")

    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    print(f"\nTotal historical signals: {len(trades)}\n")

    print("=" * 78)
    print(f"BACKTEST — uptrend + 20-SMA-respect forward return ({backtest_years:.0f}y, Nifty 500)")
    print("=" * 78)
    if trades.empty:
        print("  No signals found in the available history.\n")
    else:
        for h in HOLD_DAYS:
            sub = trades[["entry_time", f"exit_time_{h}d", f"ret_{h}d"]].dropna()
            if sub.empty:
                continue
            bench_rets = [_bench_return(row["entry_time"], row[f"exit_time_{h}d"]) for _, row in sub.iterrows()]
            sub = sub.assign(bench_ret=bench_rets)
            sub["excess_ret"] = sub[f"ret_{h}d"] - sub["bench_ret"]
            win_rate = (sub[f"ret_{h}d"] > 0).mean() * 100
            excess = sub["excess_ret"].dropna()
            excess_win = (excess > 0).mean() * 100 if not excess.empty else float("nan")
            print(f"  {h:>2}d forward: n={len(sub):<5} win-rate {win_rate:5.1f}%  "
                  f"mean {sub[f'ret_{h}d'].mean():+6.2f}%  median {sub[f'ret_{h}d'].median():+6.2f}%   |  "
                  f"excess win-rate {excess_win:5.1f}%  avg excess {excess.mean():+.2f}%")
    print()

    print("=" * 78)
    print(f"LIVE MATCHES (today): {len(matches)}")
    print("=" * 78)
    if not matches:
        print("No stock currently satisfies the uptrend + 20-SMA-respect conditions.")
    else:
        df = pd.DataFrame(matches).sort_values("dist_from_sma20_pct")
        for _, r in df.iterrows():
            print(f"  {r['symbol']:<16} Close {r['close']:<10} SMA20 {r['sma20']:<10} "
                  f"SMA50 {r['sma50']:<10} ({r['dist_from_sma20_pct']:+.1f}% from SMA20)")
        out_path = Path(__file__).parent / "uptrend_sma20_matches.csv"
        df.to_csv(out_path, index=False)
        print(f"\nSaved to {out_path}")

    if not trades.empty:
        trades_path = Path(__file__).parent / "uptrend_sma20_backtest_trades.csv"
        trades.to_csv(trades_path, index=False)
        print(f"Backtest trade log saved to {trades_path}")


if __name__ == "__main__":
    run()
