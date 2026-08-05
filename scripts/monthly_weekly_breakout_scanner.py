"""
Standalone scanner: monthly breakout from a tight consolidation, on
above-average volume, with a bullish (green) candle — confirmed by the
SAME pattern also showing up on the weekly timeframe. Deliberately
standalone, not wired into the live website, matching the pattern for
every other one-off strategy scanner built this session.

Definition used (spelled out so it's auditable, not a black box):
  - "Consolidation" = the N bars BEFORE the current one traded in a tight
    range (high-to-low spread, as % of the range low, under a threshold).
  - "Breakout" = the current bar's Close clears that prior range's high.
  - "High volume" = current bar's Volume is at least VOL_MULT x the
    average of the preceding VOL_LOOKBACK bars.
  - "Green candle" = Close > Open on the breakout bar itself.
  - A stock only qualifies when this fires on its MOST RECENT completed
    Monthly bar AND at least one of its last few Weekly bars (the weeks
    that fall inside/around that same month) — i.e. the bigger monthly
    move is corroborated by real weekly-level buying, not just one
    coarse candle.

Run: python scripts/monthly_weekly_breakout_scanner.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf

from backend.calculations.universe import load_symbols

CONSOLIDATION_LOOKBACK = 6     # bars before the breakout bar defining the "base"
CONSOLIDATION_TIGHTNESS_PCT = 20.0   # (range high - range low) / range low must be under this %
VOLUME_LOOKBACK = 10
VOLUME_MULT = 1.5
WEEKLY_CONFIRM_WINDOW = 4       # how many of the most recent weekly bars count as "same period"


def _fetch(symbol: str, interval: str, period: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def detect_consolidation_breakout(df: pd.DataFrame) -> pd.DataFrame:
    """Adds BREAKOUT_SIGNAL (+ intermediate columns for auditability)."""
    out = df.copy()
    if out.empty or len(out) < CONSOLIDATION_LOOKBACK + VOLUME_LOOKBACK + 2:
        out["BREAKOUT_SIGNAL"] = False
        return out

    prior_high = out["High"].rolling(CONSOLIDATION_LOOKBACK).max().shift(1)
    prior_low = out["Low"].rolling(CONSOLIDATION_LOOKBACK).min().shift(1)
    range_pct = (prior_high - prior_low) / prior_low.replace(0, pd.NA) * 100
    out["CONSOLIDATION_TIGHT"] = range_pct < CONSOLIDATION_TIGHTNESS_PCT
    out["PRIOR_RANGE_HIGH"] = prior_high

    vol_avg = out["Volume"].rolling(VOLUME_LOOKBACK).mean().shift(1)
    out["VOLUME_CONFIRMED"] = out["Volume"] > (vol_avg * VOLUME_MULT)
    out["GREEN_CANDLE"] = out["Close"] > out["Open"]
    out["BROKE_OUT"] = out["Close"] > prior_high

    out["BREAKOUT_SIGNAL"] = (
        out["CONSOLIDATION_TIGHT"].fillna(False)
        & out["BROKE_OUT"].fillna(False)
        & out["VOLUME_CONFIRMED"].fillna(False)
        & out["GREEN_CANDLE"].fillna(False)
    )
    return out


def scan_symbol(symbol: str) -> dict | None:
    monthly = _fetch(symbol, "1mo", "10y")
    weekly = _fetch(symbol, "1wk", "3y")
    if monthly.empty or weekly.empty or len(monthly) < 20 or len(weekly) < 20:
        return None

    # BUGFIX: yfinance's LAST monthly/weekly bar is often an in-progress
    # period, not a completed one — confirmed directly (e.g. RELIANCE.NS's
    # "last" monthly bar was dated the 1st of the next month with only a
    # single day's volume, ~10x lower than a real month's, which silently
    # zeroed out every volume-confirmation check across the whole universe).
    # Always evaluate on the last FULLY COMPLETED bar instead.
    monthly = monthly.iloc[:-1]
    weekly = weekly.iloc[:-1]
    if len(monthly) < 20 or len(weekly) < 20:
        return None

    monthly_sig = detect_consolidation_breakout(monthly)
    weekly_sig = detect_consolidation_breakout(weekly)

    monthly_breakout_now = bool(monthly_sig["BREAKOUT_SIGNAL"].iloc[-1])
    if not monthly_breakout_now:
        return None

    weekly_recent = weekly_sig["BREAKOUT_SIGNAL"].iloc[-WEEKLY_CONFIRM_WINDOW:]
    weekly_confirmed = bool(weekly_recent.any())
    if not weekly_confirmed:
        return None

    m_row = monthly_sig.iloc[-1]
    w_confirm_idx = weekly_recent[weekly_recent].index[-1]
    w_row = weekly_sig.loc[w_confirm_idx]

    return {
        "symbol": symbol,
        "monthly_close": round(float(m_row["Close"]), 2),
        "monthly_range_high": round(float(m_row["PRIOR_RANGE_HIGH"]), 2),
        "monthly_volume_x_avg": round(
            float(m_row["Volume"]) / float(monthly["Volume"].rolling(VOLUME_LOOKBACK).mean().shift(1).loc[m_row.name]), 2
        ) if pd.notna(monthly["Volume"].rolling(VOLUME_LOOKBACK).mean().shift(1).loc[m_row.name]) else None,
        "weekly_confirm_date": str(w_confirm_idx.date()),
        "weekly_close": round(float(w_row["Close"]), 2),
    }


def run():
    symbols = load_symbols("Nifty 500")
    print(f"Scanning {len(symbols)} Nifty 500 stocks for monthly consolidation breakout, "
          f"confirmed on weekly, both on above-average volume with a green candle…\n")

    matches = []
    for i, symbol in enumerate(symbols):
        try:
            result = scan_symbol(symbol)
            if result:
                matches.append(result)
        except Exception:
            continue
        if (i + 1) % 50 == 0:
            print(f"  …{i+1}/{len(symbols)} processed, {len(matches)} match(es) so far")

    print(f"\n{'=' * 78}\nMATCHES: {len(matches)}\n{'=' * 78}")
    if not matches:
        print("No stock currently satisfies both the monthly and weekly breakout conditions.")
    else:
        df = pd.DataFrame(matches).sort_values("monthly_volume_x_avg", ascending=False)
        for _, r in df.iterrows():
            print(f"  {r['symbol']:<16} Monthly Close {r['monthly_close']:<10} "
                  f"(broke {r['monthly_range_high']}, vol {r['monthly_volume_x_avg']}x avg)   "
                  f"Weekly confirm {r['weekly_confirm_date']} @ {r['weekly_close']}")
        out_path = Path(__file__).parent / "monthly_weekly_breakout_matches.csv"
        df.to_csv(out_path, index=False)
        print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    run()
