"""
Standalone scanner: exact reproduction of the Chartink screener
"Daily Chart Positional Hilega Toh Milega Indicator by NK Sir"
(https://chartink.com/screener/daily-chart-positional-hilega-toh-milega-indicator-by-nk-sir),
codified directly from the literal filter conditions shown in the
screenshot — not inferred from narration, so no interpretation
ambiguity. Deliberately standalone, not wired into the live website.

The 13 conditions, translated 1:1 (RSI/EMA/WMA all computed exactly as
Chartink computes them — Daily RSI(9), Ema(Rsi(9),3), Wma(Rsi(9),21) —
which is precisely what backend/calculations/hm_indicators.py::
add_indicators() already produces as RSI / HM_EMA / HM_WMA):

  1-5. RSI(9) was <= 50 on EACH of the last 5 trading days (a sustained
       below-midline dip, not a one-day blip).
  6.   Today's WMA(RSI,21) <= 50.
  7.   Yesterday: WMA(RSI,21) > RSI  (red line was above white line).
  8.   Today: WMA(RSI,21) <= RSI     (red line at/below white line NOW —
       combined with #7, RSI has just crossed the WMA today).
  9.   Yesterday: EMA(RSI,3) <= WMA(RSI,21) (green line was at/below red).
  10.  Today: EMA(RSI,3) >= WMA(RSI,21)     (green line at/above red NOW —
       combined with #9, EMA has just crossed the WMA today too).
  11.  Today: EMA(RSI,3) < RSI  (white/RSI is leading the green line —
       a very fresh cross, RSI hasn't been caught up to yet).
  12.  Today: RSI(9) >= 50 (confirms the midline flip actually happened).
  13.  Today: Daily Close < 3500 (price cap).

KNOWN LIMITATION, stated up front: Chartink's own screener runs against
its full NSE cash-segment universe (~2,000 symbols, including many
micro/small-caps outside Nifty 500 — visible in the user's own result
table: Valor Estate, BIL Vyapar, Central Mine Planning, etc., none of
which are Nifty 500 members). This script pulls the same broad universe
from NSE's own EQUITY_L.csv master list (reusing the exact fetch pattern
already proven in backend/data_ingestion/sector_sync.py) rather than the
narrower Nifty 500 list used by every other scanner this session, so the
result can actually be compared apples-to-apples against Chartink's.
Even so, small differences are possible: yfinance vs Chartink's own price
feed can disagree on the last bar for illiquid names, and Chartink may
run its scan at a slightly different point in the session than this
script is run.

Run: python scripts/hm_daily_positional_scanner.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from backend.calculations.hm_positional_setup import (
    add_positional_hm_signal, check_positional_hm_signal_latest, backtest_positional_signal,
)

BENCHMARK = "^NSEI"
HOLD_DAYS = [5, 10, 20]
_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/csv,*/*",
}


def fetch_nse_equity_universe() -> list[str]:
    """All NSE cash-segment ("EQ" series) symbols — the same broad
    universe Chartink's default screener runs against, NOT just Nifty 500."""
    r = requests.get(
        "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
        headers=_NSE_HEADERS, timeout=30,
    )
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    eq = df[df["SERIES"].str.strip() == "EQ"]
    return [f"{s.strip()}.NS" for s in eq["SYMBOL"].dropna()]


def _fetch(symbol: str, period: str = "6mo") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def run(backtest: bool = True, years: float = 3.0):
    print("Fetching NSE cash-segment ('EQ') universe from EQUITY_L.csv…")
    try:
        symbols = fetch_nse_equity_universe()
    except Exception as e:
        print(f"FATAL: could not fetch NSE universe: {e}")
        return
    print(f"Universe size: {len(symbols)} symbols — scanning"
          f"{' + backtesting' if backtest else ''} the exact 13-condition H-M positional setup…\n")

    bench_raw = None
    if backtest:
        try:
            bench_raw = _fetch(BENCHMARK, period=f"{max(1, round(years))}y")
        except Exception as e:
            print(f"WARNING: could not fetch benchmark {BENCHMARK}, excess-return will be unavailable: {e}")

    matches = []
    all_trades = []
    for i, symbol in enumerate(symbols):
        try:
            period = f"{max(1, round(years))}y" if backtest else "6mo"
            df = _fetch(symbol, period=period)
            if len(df) < 30:
                continue
            if check_positional_hm_signal_latest(df):
                matches.append({
                    "symbol": symbol.replace(".NS", ""),
                    "close": round(float(df["Close"].iloc[-1]), 2),
                    "volume": int(df["Volume"].iloc[-1]),
                })

            if backtest and len(df) >= 80:
                sig = add_positional_hm_signal(df)
                t = backtest_positional_signal(sig, symbol.replace(".NS", ""), HOLD_DAYS)
                if not t.empty:
                    all_trades.append(t)
        except Exception:
            continue
        if (i + 1) % 200 == 0:
            print(f"  …{i+1}/{len(symbols)} processed, {len(matches)} live match(es) so far")

    if backtest:
        trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
        print(f"\nTotal historical signals: {len(trades)}\n")
        print("=" * 78)
        print(f"BACKTEST — H-M positional setup, Daily, NSE cash universe ({years:.0f}y)")
        print("=" * 78)
        if trades.empty or bench_raw is None:
            print("  No signals found, or benchmark unavailable.\n")
        else:
            bench_close = bench_raw["Close"]

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
        if not trades.empty:
            trades_path = Path(__file__).parent / "hm_daily_positional_backtest_trades.csv"
            trades.to_csv(trades_path, index=False)
            print(f"Backtest trade log saved to {trades_path}")

    print(f"\n{'=' * 78}\nCURRENT LIVE MATCHES: {len(matches)}\n{'=' * 78}")
    if not matches:
        print("No stock currently satisfies the exact 13-condition setup.")
    else:
        df = pd.DataFrame(matches).sort_values("symbol")
        for _, r in df.iterrows():
            print(f"  {r['symbol']:<16} Close {r['close']:<10} Volume {r['volume']:,}")
        out_path = Path(__file__).parent / "hm_daily_positional_matches.csv"
        df.to_csv(out_path, index=False)
        print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    run()
