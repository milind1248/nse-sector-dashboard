"""
Standalone backtest: does the H-M System's weekly BOTTOM_SIGNAL / TOP_SIGNAL
(the same red-T / green-B flags visible on the "H-M System TB" TradingView
indicator, ported faithfully in backend/calculations/hm_indicators.py —
confirmed this session against a live chart's exact RSI9/EMA3/WMA21 values)
actually catch weekly tops and bottoms on real Nifty 50 stocks?

Walk-forward by construction: generate_signals() only ever looks at bars up
to and including the signal bar (no future data), so every signal here is
exactly what would have fired live at that week's close.

Methodology:
  - Weekly OHLCV, 5 years, for every Nifty 50 symbol.
  - add_indicators() + generate_signals() with the same defaults the live
    HM Scanner page ships with (min_score=70, confirmation_mode="Balanced").
  - For each BOTTOM_SIGNAL week, "win" = price is higher N weeks later than
    at the signal close. For each TOP_SIGNAL week, "win" = price is LOWER
    N weeks later. Both raw and excess-return-vs-NIFTY-50-index (^NSEI) are
    reported, same rigor as scripts/pead_backtest.py.

Run: python scripts/hm_weekly_topbottom_backtest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf

from backend.calculations.universe import load_symbols
from backend.calculations.hm_indicators import add_indicators, generate_signals

HORIZONS_WEEKS = [4, 8, 12]
BENCHMARK = "^NSEI"


def _fetch_weekly(symbol: str) -> pd.DataFrame:
    df = yf.download(symbol, period="5y", interval="1wk", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def _forward_return(close: pd.Series, pos: int, weeks: int) -> float | None:
    target = pos + weeks
    if target >= len(close):
        return None
    return (float(close.iloc[target]) - float(close.iloc[pos])) / float(close.iloc[pos]) * 100.0


def run_backtest():
    symbols = load_symbols("Nifty 50")
    print(f"Backtesting H-M weekly BOTTOM/TOP signals on {len(symbols)} Nifty 50 symbols…\n")

    try:
        bench_df = _fetch_weekly(BENCHMARK)
        bench_close = bench_df["Close"]
    except Exception as e:
        print(f"FATAL: could not fetch benchmark {BENCHMARK}: {e}")
        return

    records = []  # {symbol, date, signal_type, ret_Nw, xret_Nw...}

    for i, symbol in enumerate(symbols):
        try:
            df = _fetch_weekly(symbol)
            if len(df) < 60:
                continue
            ind = add_indicators(df)
            sig = generate_signals(ind)  # library defaults: min_score=70, Balanced
        except Exception:
            continue

        close = sig["Close"]
        for pos in range(len(sig)):
            row = sig.iloc[pos]
            is_bottom = bool(row.get("BOTTOM_SIGNAL", False))
            is_top = bool(row.get("TOP_SIGNAL", False))
            if not (is_bottom or is_top):
                continue

            sig_date = sig.index[pos]
            # nearest benchmark bar on/after the signal date, same trading-week offset logic
            bench_on_or_after = bench_close.index[bench_close.index >= sig_date]
            bench_pos = bench_close.index.get_loc(bench_on_or_after[0]) if len(bench_on_or_after) else None

            rec = {"symbol": symbol, "date": str(sig_date.date()),
                   "signal_type": "BOTTOM" if is_bottom else "TOP"}
            for w in HORIZONS_WEEKS:
                r = _forward_return(close, pos, w)
                rec[f"ret_{w}w"] = r
                if r is not None and bench_pos is not None:
                    br = _forward_return(bench_close, bench_pos, w)
                    rec[f"xret_{w}w"] = (r - br) if br is not None else None
                else:
                    rec[f"xret_{w}w"] = None
            records.append(rec)

        if (i + 1) % 10 == 0:
            print(f"  …{i+1}/{len(symbols)} symbols processed")

    df_res = pd.DataFrame(records)
    if df_res.empty:
        print("No signals found — nothing to report.")
        return

    print(f"\nTotal signals: {len(df_res)} "
          f"({(df_res['signal_type'] == 'BOTTOM').sum()} BOTTOM, "
          f"{(df_res['signal_type'] == 'TOP').sum()} TOP)\n")

    for sig_type, direction_label in [("BOTTOM", "price UP = win"), ("TOP", "price DOWN = win")]:
        sub = df_res[df_res["signal_type"] == sig_type]
        if sub.empty:
            continue
        print("=" * 78)
        print(f"{sig_type} SIGNAL ({direction_label})  — n={len(sub)}")
        print("=" * 78)
        for w in HORIZONS_WEEKS:
            raw = sub[f"ret_{w}w"].dropna()
            xret = sub[f"xret_{w}w"].dropna()
            if raw.empty:
                continue
            if sig_type == "BOTTOM":
                win_raw = (raw > 0).mean() * 100
                win_xret = (xret > 0).mean() * 100 if not xret.empty else float("nan")
            else:
                win_raw = (raw < 0).mean() * 100
                win_xret = (xret < 0).mean() * 100 if not xret.empty else float("nan")
            print(f"  {w:>2}w forward: raw mean {raw.mean():+6.2f}%  median {raw.median():+6.2f}%  "
                  f"win-rate {win_raw:5.1f}%  (n={len(raw)})   |  "
                  f"excess-vs-NIFTY mean {xret.mean():+6.2f}%  win-rate(excess) {win_xret:5.1f}%")
        print()

    out_path = Path(__file__).parent / "hm_weekly_topbottom_results.csv"
    df_res.to_csv(out_path, index=False)
    print(f"Full per-signal data saved to {out_path}")


if __name__ == "__main__":
    run_backtest()
