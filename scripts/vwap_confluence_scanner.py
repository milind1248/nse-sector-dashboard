"""
Standalone scanner + backtest for a VWAP/moving-average confluence
breakout strategy (Chartink-style screener conditions, screenshots
provided by the user — no separate transcript this time, so this is
built directly from the literal boolean filter logic shown, which is
fully self-contained and doesn't need narration to interpret). Deliberately
standalone — NOT wired into the live website, matching the pattern
established for the other one-off strategy validations in this project
(scripts/pead_backtest.py, scripts/hm_weekly_topbottom_backtest.py,
scripts/hm_volume_mismatch_scanner.py).

Two screeners, read directly off the screenshots:

SETUP / WATCHLIST screener (finds a stock "coiling" before a move):
    [0] 1h VWAP - 1h SMA(1h High, 9)   < 1
    [0] 1h VWAP - 1h SMA(1h Close, 20) < 1
    [0] 1h SMA(1h Close,20) - 1h SMA(1h High,9) < 1
    [0] 1h Close - 1h VWAP < 3
    Daily Close > 20        (liquidity — no penny stocks)
    Daily Volume > 100000   (liquidity — tradeable volume)
  These are SIGNED differences, not absolute value — read literally, they
  cap VWAP/SMA20/Close from running too far AHEAD of SMA(High,9) (which
  normally sits above the other two), i.e. they detect a still-compressed,
  not-yet-extended state, not a "some in the top price and some in the
  bottom" arbitrary combination.

BUY / TRIGGER screener (the actual entry signal):
    [0] 1h Close > Daily VWAP
    Daily VWAP crossed above Daily SMA(Daily Close, 20)
    Daily VWAP crossed above Daily SMA(Daily High, 9)
  "Daily VWAP" here is a distinct concept from the hourly VWAP above — one
  aggregate VWAP value PER DAY (computed from that day's own intraday
  bars), forming its own daily time series that can be compared against
  daily-frequency SMAs and checked for a crossover, day over day.

yfinance intraday-hour data only goes back roughly 2-3 years (confirmed
directly: ~3y available for NSE symbols today), so this backtest's history
is meaningfully shorter than the weekly backtests done elsewhere in this
project — stated explicitly in the report, not glossed over.

Run: python scripts/vwap_confluence_scanner.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import yfinance as yf

from backend.calculations.universe import load_symbols

BENCHMARK = "^NSEI"
HOLD_DAYS = [3, 5, 10]           # forward-return horizons after a BUY trigger
MIN_DAILY_CLOSE = 20             # liquidity filter, per screenshot
MIN_DAILY_VOLUME = 100_000       # liquidity filter, per screenshot
SETUP_VWAP_HIGH9_MAX = 1.0
SETUP_VWAP_CLOSE20_MAX = 1.0
SETUP_CLOSE20_HIGH9_MAX = 1.0
SETUP_CLOSE_VWAP_MAX = 3.0


# ─────────────────────────────────────────────────────────────────────────
# Data + VWAP reconstruction (yfinance has no native VWAP field)
# ─────────────────────────────────────────────────────────────────────────

def _fetch_hourly(symbol: str, period: str = "730d") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1h", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def _fetch_daily(symbol: str, period: str = "3y") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def add_intraday_vwap(hourly: pd.DataFrame) -> pd.DataFrame:
    """Running VWAP that resets every calendar day — what a live hourly
    chart's VWAP indicator shows at each bar ("[0] 1h VWAP" in the
    screenshot)."""
    out = hourly.copy()
    if out.empty:
        return out
    typical = (out["High"] + out["Low"] + out["Close"]) / 3.0
    day = out.index.date
    pv = typical * out["Volume"]
    out["_day"] = day
    out["INTRADAY_VWAP"] = (
        pv.groupby(out["_day"]).cumsum() / out["Volume"].groupby(out["_day"]).cumsum()
    )
    out = out.drop(columns=["_day"])
    return out


def compute_daily_vwap_series(hourly: pd.DataFrame) -> pd.Series:
    """ONE VWAP value per calendar day (the whole day's own VWAP, not a
    running one) — "Daily VWAP" in the BUY screener, forms its own daily
    time series comparable to SMA(Daily Close) etc."""
    if hourly.empty:
        return pd.Series(dtype=float)
    typical = (hourly["High"] + hourly["Low"] + hourly["Close"]) / 3.0
    day = pd.Series(hourly.index.date, index=hourly.index)
    pv = typical * hourly["Volume"]
    daily_pv = pv.groupby(day).sum()
    daily_vol = hourly["Volume"].groupby(day).sum()
    vwap = daily_pv / daily_vol.replace(0, np.nan)
    vwap.index = pd.to_datetime(vwap.index)
    return vwap


def _crossed_above(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


# ─────────────────────────────────────────────────────────────────────────
# SETUP / WATCHLIST screener (hourly)
# ─────────────────────────────────────────────────────────────────────────

def add_setup_signal(hourly: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    out = add_intraday_vwap(hourly)
    if out.empty:
        return out

    sma9_high = out["High"].rolling(9).mean()
    sma20_close = out["Close"].rolling(20).mean()

    cond1 = (out["INTRADAY_VWAP"] - sma9_high) < SETUP_VWAP_HIGH9_MAX
    cond2 = (out["INTRADAY_VWAP"] - sma20_close) < SETUP_VWAP_CLOSE20_MAX
    cond3 = (sma20_close - sma9_high) < SETUP_CLOSE20_HIGH9_MAX
    cond4 = (out["Close"] - out["INTRADAY_VWAP"]) < SETUP_CLOSE_VWAP_MAX

    # Broadcast the daily liquidity filters onto each hourly bar of that day.
    daily_close_by_day = daily["Close"].copy()
    daily_close_by_day.index = daily_close_by_day.index.date
    daily_vol_by_day = daily["Volume"].copy()
    daily_vol_by_day.index = daily_vol_by_day.index.date
    day_key = pd.Series(out.index.date, index=out.index)
    liquid_close = day_key.map(daily_close_by_day) > MIN_DAILY_CLOSE
    liquid_vol = day_key.map(daily_vol_by_day) > MIN_DAILY_VOLUME

    out["SETUP_SIGNAL"] = (cond1 & cond2 & cond3 & cond4 & liquid_close.fillna(False) & liquid_vol.fillna(False))
    return out


# ─────────────────────────────────────────────────────────────────────────
# BUY / TRIGGER screener (daily, with one hourly condition)
# ─────────────────────────────────────────────────────────────────────────

def add_buy_signal(hourly: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Returns the DAILY dataframe with a BUY_SIGNAL column — evaluated
    once per day, at that day's LAST hourly bar (i.e. as if scanning near
    the close), since "[0] 1h Close" needs a specific intraday bar to
    compare against that day's Daily VWAP."""
    daily_vwap = compute_daily_vwap_series(hourly)
    out = daily.copy()
    out["DAILY_VWAP"] = daily_vwap.reindex(out.index)

    sma20_close_daily = out["Close"].rolling(20).mean()
    sma9_high_daily = out["High"].rolling(9).mean()
    out["VWAP_CROSS_SMA20CLOSE"] = _crossed_above(out["DAILY_VWAP"], sma20_close_daily)
    out["VWAP_CROSS_SMA9HIGH"] = _crossed_above(out["DAILY_VWAP"], sma9_high_daily)

    last_hourly_close = hourly["Close"].groupby(hourly.index.date).last()
    last_hourly_close.index = pd.to_datetime(last_hourly_close.index)
    out["LAST_HOURLY_CLOSE"] = last_hourly_close.reindex(out.index)
    price_above_daily_vwap = out["LAST_HOURLY_CLOSE"] > out["DAILY_VWAP"]

    out["BUY_SIGNAL"] = (
        price_above_daily_vwap & out["VWAP_CROSS_SMA20CLOSE"] & out["VWAP_CROSS_SMA9HIGH"]
    ).fillna(False)
    return out


# ─────────────────────────────────────────────────────────────────────────
# Backtest
# ─────────────────────────────────────────────────────────────────────────

def backtest_buy_signal(daily: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if daily.empty or "BUY_SIGNAL" not in daily.columns:
        return pd.DataFrame()
    positions = np.where(daily["BUY_SIGNAL"].fillna(False).to_numpy())[0]
    rows = []
    for pos in positions:
        entry_pos = pos + 1
        if entry_pos >= len(daily):
            continue
        entry = float(daily["Open"].iloc[entry_pos])
        entry_time = daily.index[entry_pos]
        row = {"symbol": symbol, "signal_time": daily.index[pos], "entry_time": entry_time, "entry": entry}
        for h in HOLD_DAYS:
            target_pos = entry_pos + h
            if target_pos >= len(daily):
                row[f"ret_{h}d"] = None
                row[f"exit_time_{h}d"] = None
                continue
            exit_price = float(daily["Close"].iloc[target_pos])
            row[f"ret_{h}d"] = (exit_price / entry - 1) * 100
            row[f"exit_time_{h}d"] = daily.index[target_pos]
        rows.append(row)
    return pd.DataFrame(rows)


def run():
    symbols = load_symbols("Nifty 50")
    print(f"Scanning/backtesting VWAP-confluence Setup + Buy screeners on {len(symbols)} Nifty 50 symbols…\n")

    try:
        bench_daily = _fetch_daily(BENCHMARK)
        bench_close = bench_daily["Close"]
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

    all_trades = []
    setup_watchlist, buy_watchlist = [], []

    for i, symbol in enumerate(symbols):
        try:
            hourly = _fetch_hourly(symbol)
            daily = _fetch_daily(symbol)
            if hourly.empty or len(daily) < 30:
                continue
            hourly_setup = add_setup_signal(hourly, daily)
            daily_buy = add_buy_signal(hourly, daily)
        except Exception:
            continue

        t = backtest_buy_signal(daily_buy, symbol)
        if not t.empty:
            all_trades.append(t)

        if bool(hourly_setup["SETUP_SIGNAL"].iloc[-1]):
            setup_watchlist.append(symbol)
        if bool(daily_buy["BUY_SIGNAL"].iloc[-1]):
            buy_watchlist.append({
                "symbol": symbol, "close": round(float(daily_buy["Close"].iloc[-1]), 2),
                "daily_vwap": round(float(daily_buy["DAILY_VWAP"].iloc[-1]), 2),
            })

        if (i + 1) % 10 == 0:
            print(f"  …{i+1}/{len(symbols)} symbols processed")

    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    print(f"\nTotal BUY signals across universe: {len(trades)}\n")

    print("=" * 78)
    print("BUY SIGNAL — forward return (raw vs excess-vs-NIFTY)")
    print("=" * 78)
    if trades.empty:
        print("  No signals found in the available ~2-3y of hourly history.\n")
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
    print(f"CURRENT SETUP WATCHLIST (compression, pre-breakout) — n={len(setup_watchlist)}")
    print("=" * 78)
    print(", ".join(setup_watchlist) if setup_watchlist else "  None currently.")
    print()

    print("=" * 78)
    print(f"CURRENT BUY TRIGGER (today) — n={len(buy_watchlist)}")
    print("=" * 78)
    for w in buy_watchlist:
        print(f"  {w['symbol']:<16} Close {w['close']:<10} Daily VWAP {w['daily_vwap']}")

    out_dir = Path(__file__).parent
    if not trades.empty:
        trades.to_csv(out_dir / "vwap_confluence_trades.csv", index=False)
        print(f"\nDetailed trade log saved to {out_dir / 'vwap_confluence_trades.csv'}")


if __name__ == "__main__":
    run()
