"""
Standalone scan + backtest of the EXISTING, already-verified H-M
BOTTOM_SIGNAL (backend/calculations/hm_indicators.py::generate_signals())
on the DAILY timeframe across Nifty 500 — not a new rule, the same logic
already live on the site's HM Scanner page (confirmed directly against
GODREJPROP.NS's real 12-Jun-2026 signal, which matched the live
TradingView "B" flag exactly, score 100/100). That backtest was only run
on Weekly so far this session; this is the Daily version, standalone
until reviewed, per the established workflow this session.

Run: python scripts/hm_bottom_signal_daily_scan.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf

from backend.calculations.universe import load_symbols
from backend.calculations.hm_indicators import add_indicators, generate_signals
from backend.calculations.hm_backtest import backtest_signals, summarize_backtests, add_benchmark_excess_return

BENCHMARK = "^NSEI"


def _fetch(symbol: str, period: str = "3y") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def run():
    symbols = load_symbols("Nifty 500")
    print(f"Scanning + backtesting the existing H-M BOTTOM_SIGNAL on {len(symbols)} Nifty 500 "
          f"symbols (Daily timeframe, 3y)…\n")

    try:
        bench_raw = _fetch(BENCHMARK)
    except Exception as e:
        print(f"FATAL: could not fetch benchmark {BENCHMARK}: {e}")
        return

    all_trades = []
    live_watchlist = []

    for i, symbol in enumerate(symbols):
        try:
            raw = _fetch(symbol)
            if len(raw) < 60:
                continue
            ind = add_indicators(raw)
            if ind.empty:
                continue
            sig = generate_signals(ind)
        except Exception:
            continue

        trades = backtest_signals(sig, symbol, hold_bars=10)
        if not trades.empty:
            all_trades.append(trades)

        if bool(sig["BOTTOM_SIGNAL"].iloc[-1]):
            live_watchlist.append({
                "symbol": symbol, "close": round(float(sig["Close"].iloc[-1]), 2),
                "rsi": round(float(sig["RSI"].iloc[-1]), 1),
                "score": round(float(sig["BOTTOM_SCORE"].iloc[-1]), 1),
                "reason": str(sig["SIGNAL_REASON"].iloc[-1]),
            })

        if (i + 1) % 50 == 0:
            print(f"  …{i+1}/{len(symbols)} processed")

    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    if not trades.empty:
        trades = add_benchmark_excess_return(trades, bench_raw, is_short=False)
    print(f"\nTotal historical BOTTOM_SIGNAL trades: {len(trades)}\n")

    print("=" * 78)
    print("BACKTEST — H-M BOTTOM_SIGNAL, Daily, 10-bar hold, Nifty 500 (3y)")
    print("=" * 78)
    if trades.empty:
        print("  No signals found.\n")
    else:
        win_rate = (trades["return_pct"] > 0).mean() * 100
        excess = trades["excess_return_pct"].dropna()
        excess_win = (excess > 0).mean() * 100 if not excess.empty else float("nan")
        print(f"  n={len(trades)}  win-rate {win_rate:.1f}%  avg return {trades['return_pct'].mean():+.2f}%  "
              f"median {trades['return_pct'].median():+.2f}%")
        print(f"  Excess-vs-NIFTY win-rate {excess_win:.1f}%  avg excess {excess.mean():+.2f}%"
              if not excess.empty else "  Excess data unavailable")
        print(f"  Outcome breakdown: {trades['outcome'].value_counts().to_dict()}")
    print()

    print("=" * 78)
    print(f"CURRENT LIVE SIGNAL — BOTTOM_SIGNAL on latest completed Daily bar (n={len(live_watchlist)})")
    print("=" * 78)
    if not live_watchlist:
        print("No stock currently triggers the Daily BOTTOM_SIGNAL.")
    else:
        df = pd.DataFrame(live_watchlist).sort_values("score", ascending=False)
        for _, r in df.iterrows():
            print(f"  {r['symbol']:<16} Close {r['close']:<10} RSI {r['rsi']:<6} Score {r['score']:<6} {r['reason']}")
        out_path = Path(__file__).parent / "hm_bottom_signal_daily_watchlist.csv"
        df.to_csv(out_path, index=False)
        print(f"\nSaved to {out_path}")

    if not trades.empty:
        trades_path = Path(__file__).parent / "hm_bottom_signal_daily_trades.csv"
        trades.to_csv(trades_path, index=False)
        print(f"Backtest trade log saved to {trades_path}")


if __name__ == "__main__":
    run()
