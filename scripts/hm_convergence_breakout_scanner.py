"""
Standalone scanner + backtest: H-M System "convergence breakout" — catches
price right where the three H-M lines (RSI(9) white, EMA(3) green,
WMA(21) red) have squeezed into a tight value-range and RSI is just now
breaking above BOTH of the other two, with price and volume confirming.
Deliberately standalone, not wired into the live website until the
backtest results are reviewed, per explicit instruction.

Reuses backend/calculations/hm_indicators.py's add_indicators() for the
underlying RSI(9)/EMA(3)/WMA(21) computation — the exact same, already
faithfully-ported H-M System used on the live TradingView chart and by
every other H-M scanner in this project — only the entry rule itself is
new.

Entry rule, all four conditions on the SAME bar (spelled out so it's
auditable, not a black box):
  1. CONVERGED: the three H-M lines are bunched within CONVERGENCE_MAX
     of each other — max(RSI, EMA, WMA) - min(RSI, EMA, WMA) <= threshold
     (default 2.0, matching the user's stated "1-2 point range").
  2. PRICE UP: current Close > previous bar's Close.
  3. FRESH CROSS: RSI is now above BOTH EMA and WMA, but on the PREVIOUS
     bar it was NOT above both — i.e. this is the exact bar the squeeze
     resolves upward, not some bar deep into an already-established move.
  4. VOLUME UP: current Volume > previous bar's Volume.

TIMEFRAME IS SELECTABLE — pass --interval on the command line (1d, 1wk,
1h, 30m, 15m, 5m, 1mo). Sub-hourly intervals (5m/15m/30m) are limited by
yfinance to ~60 days of history, so a genuine 2-year backtest is only
possible on 1h and above; the scanner logic itself works identically at
any timeframe, this is purely a data-availability constraint, stated
here rather than silently producing a short, misleading backtest.

Run examples:
  python scripts/hm_convergence_breakout_scanner.py                  # Daily, 2y backtest (default)
  python scripts/hm_convergence_breakout_scanner.py --interval 1wk
  python scripts/hm_convergence_breakout_scanner.py --interval 1h --years 2
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import yfinance as yf

from backend.calculations.universe import load_symbols
from backend.calculations.hm_indicators import add_indicators

BENCHMARK = "^NSEI"
CONVERGENCE_MAX = 2.0          # max(RSI,EMA,WMA) - min(...) must be <= this, per the user's "1-2 point" spec
HOLD_BARS = [5, 10, 20]        # forward-return horizons, in bars of whatever timeframe is selected

# yfinance's practical intraday history limits — used only to size the
# fetch window and to warn if a 2-year backtest isn't actually possible.
_INTERVAL_MAX_HISTORY_DAYS = {
    "1mo": None, "1wk": None, "1d": None,   # effectively unlimited (years of history available)
    "1h": 730, "2h": 730, "4h": 730,
    "30m": 60, "15m": 60, "5m": 60, "1m": 7,
}


def _period_for(interval: str, years: float) -> str:
    max_days = _INTERVAL_MAX_HISTORY_DAYS.get(interval)
    requested_days = int(years * 365)
    if max_days is None:
        return f"{max(1, round(years))}y" if years >= 1 else f"{requested_days}d"
    return f"{min(requested_days, max_days)}d"


def _fetch(symbol: str, interval: str, years: float) -> pd.DataFrame:
    period = _period_for(interval, years)
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def add_convergence_breakout_signal(
    df: pd.DataFrame, convergence_max: float = CONVERGENCE_MAX, direction: str = "up",
    require_above_trend_ma: bool = False,
) -> pd.DataFrame:
    """direction="up": the original breakout rule — RSI freshly crosses
    ABOVE both other lines out of a squeeze (catches a top/continuation
    move starting).
    direction="down": catches a BOTTOM instead — RSI freshly dips BELOW
    both other lines while still converged, i.e. a pullback forming
    inside the squeeze rather than a resolved breakout. Optionally gated
    on Close > SMA50 (require_above_trend_ma) so this only fires as a
    "buy the dip within an uptrend" setup, not a fresh downtrend."""
    out = add_indicators(df)
    if out.empty:
        return out

    line_max = out[["RSI", "HM_EMA", "HM_WMA"]].max(axis=1)
    line_min = out[["RSI", "HM_EMA", "HM_WMA"]].min(axis=1)
    out["LINE_RANGE"] = line_max - line_min
    out["CONVERGED"] = out["LINE_RANGE"] <= convergence_max

    price_up = out["Close"] > out["Close"].shift(1)
    volume_up = out["Volume"] > out["Volume"].shift(1)
    trend_ok = (out["Close"] > out["SMA50"]) if require_above_trend_ma else pd.Series(True, index=out.index)

    if direction == "down":
        below_both = (out["RSI"] < out["HM_EMA"]) & (out["RSI"] < out["HM_WMA"])
        fresh_cross = below_both & ~below_both.shift(1).fillna(False)
    else:
        above_both = (out["RSI"] > out["HM_EMA"]) & (out["RSI"] > out["HM_WMA"])
        fresh_cross = above_both & ~above_both.shift(1).fillna(False)

    out["CONVERGENCE_BREAKOUT"] = (
        out["CONVERGED"].fillna(False) & price_up.fillna(False)
        & fresh_cross.fillna(False) & volume_up.fillna(False) & trend_ok.fillna(False)
    )
    return out


def backtest_signal(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df.empty or "CONVERGENCE_BREAKOUT" not in df.columns:
        return pd.DataFrame()
    positions = np.where(df["CONVERGENCE_BREAKOUT"].fillna(False).to_numpy())[0]
    rows = []
    for pos in positions:
        entry_pos = pos + 1
        if entry_pos >= len(df):
            continue
        entry = float(df["Open"].iloc[entry_pos])
        entry_time = df.index[entry_pos]
        row = {"symbol": symbol, "signal_time": df.index[pos], "entry_time": entry_time, "entry": entry,
               "line_range_at_signal": round(float(df["LINE_RANGE"].iloc[pos]), 2)}
        for h in HOLD_BARS:
            target_pos = entry_pos + h
            if target_pos >= len(df):
                row[f"ret_{h}b"] = None
                row[f"exit_time_{h}b"] = None
                continue
            exit_price = float(df["Close"].iloc[target_pos])
            row[f"ret_{h}b"] = (exit_price / entry - 1) * 100
            row[f"exit_time_{h}b"] = df.index[target_pos]
        rows.append(row)
    return pd.DataFrame(rows)


def run(interval: str, years: float, universe: str, convergence_max: float = CONVERGENCE_MAX,
        direction: str = "up", require_above_trend_ma: bool = False):
    symbols = load_symbols(universe)
    max_days = _INTERVAL_MAX_HISTORY_DAYS.get(interval)
    if max_days is not None and max_days < years * 365:
        print(f"NOTE: yfinance limits '{interval}' history to ~{max_days} days — "
              f"a full {years:.0f}-year backtest isn't possible at this timeframe, "
              f"using the maximum available instead.\n")

    print(f"Scanning/backtesting H-M convergence-breakout on {len(symbols)} {universe} symbols "
          f"({interval} timeframe)…\n")

    try:
        bench = _fetch(BENCHMARK, interval, years)
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

    all_trades = []
    live_watchlist = []

    for i, symbol in enumerate(symbols):
        try:
            raw = _fetch(symbol, interval, years)
            if len(raw) < 60:
                continue
            sig = add_convergence_breakout_signal(
                raw, convergence_max=convergence_max, direction=direction,
                require_above_trend_ma=require_above_trend_ma,
            )
            if sig.empty:
                continue
        except Exception:
            continue

        t = backtest_signal(sig, symbol)
        if not t.empty:
            all_trades.append(t)

        if bool(sig["CONVERGENCE_BREAKOUT"].iloc[-1]):
            live_watchlist.append({
                "symbol": symbol, "close": round(float(sig["Close"].iloc[-1]), 2),
                "rsi": round(float(sig["RSI"].iloc[-1]), 1), "ema": round(float(sig["HM_EMA"].iloc[-1]), 1),
                "wma": round(float(sig["HM_WMA"].iloc[-1]), 1),
                "line_range": round(float(sig["LINE_RANGE"].iloc[-1]), 2),
            })

        if (i + 1) % 50 == 0:
            print(f"  …{i+1}/{len(symbols)} processed")

    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    print(f"\nTotal signals: {len(trades)}\n")

    print("=" * 78)
    print(f"CONVERGENCE BREAKOUT — forward return ({interval} bars)")
    print("=" * 78)
    if trades.empty:
        print("  No signals found in the available history.\n")
    else:
        for h in HOLD_BARS:
            sub = trades[["entry_time", f"exit_time_{h}b", f"ret_{h}b"]].dropna()
            if sub.empty:
                continue
            bench_rets = [_bench_return(row["entry_time"], row[f"exit_time_{h}b"]) for _, row in sub.iterrows()]
            sub = sub.assign(bench_ret=bench_rets)
            sub["excess_ret"] = sub[f"ret_{h}b"] - sub["bench_ret"]
            win_rate = (sub[f"ret_{h}b"] > 0).mean() * 100
            excess = sub["excess_ret"].dropna()
            excess_win = (excess > 0).mean() * 100 if not excess.empty else float("nan")
            print(f"  {h:>2} bars forward: n={len(sub):<5} win-rate {win_rate:5.1f}%  "
                  f"mean {sub[f'ret_{h}b'].mean():+6.2f}%  median {sub[f'ret_{h}b'].median():+6.2f}%   |  "
                  f"excess win-rate {excess_win:5.1f}%  avg excess {excess.mean():+.2f}%")
    print()

    print("=" * 78)
    print(f"LIVE WATCHLIST — convergence breakout on the latest completed bar (n={len(live_watchlist)})")
    print("=" * 78)
    for w in live_watchlist:
        print(f"  {w['symbol']:<16} Close {w['close']:<10} RSI {w['rsi']:<6} EMA {w['ema']:<6} WMA {w['wma']:<6} "
              f"(range {w['line_range']})")

    out_dir = Path(__file__).parent
    if not trades.empty:
        out_path = out_dir / f"hm_convergence_breakout_{interval}_trades.csv"
        trades.to_csv(out_path, index=False)
        print(f"\nDetailed trade log saved to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="H-M convergence-breakout scanner + backtest")
    parser.add_argument("--interval", default="1d", choices=list(_INTERVAL_MAX_HISTORY_DAYS.keys()),
                         help="Timeframe to scan/backtest (default: 1d)")
    parser.add_argument("--years", type=float, default=2.0, help="Backtest lookback in years (default: 2)")
    parser.add_argument("--universe", default="Nifty 500", choices=["Nifty 50", "Nifty 500"])
    parser.add_argument("--convergence", type=float, default=CONVERGENCE_MAX,
                         help="Max spread between the three H-M lines to count as 'converged' (default: 2.0)")
    parser.add_argument("--direction", default="up", choices=["up", "down"],
                         help="'up' = breakout continuation (RSI crosses above both lines); "
                              "'down' = catch a bottom (RSI dips below both lines while still converged)")
    parser.add_argument("--above-trend-ma", action="store_true",
                         help="Require Close > SMA50 — only take signals within an existing uptrend")
    args = parser.parse_args()
    run(args.interval, args.years, args.universe, args.convergence, args.direction, args.above_trend_ma)
