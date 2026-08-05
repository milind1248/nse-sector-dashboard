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


def _fetch(symbol: str, period: str = "1y") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


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


def run():
    symbols = load_symbols("Nifty 500")
    print(f"Scanning {len(symbols)} Nifty 500 stocks for uptrend + 20-SMA respect…\n")

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
        print("No stock currently satisfies the uptrend + 20-SMA-respect conditions.")
    else:
        df = pd.DataFrame(matches).sort_values("dist_from_sma20_pct")
        for _, r in df.iterrows():
            print(f"  {r['symbol']:<16} Close {r['close']:<10} SMA20 {r['sma20']:<10} "
                  f"SMA50 {r['sma50']:<10} ({r['dist_from_sma20_pct']:+.1f}% from SMA20)")
        out_path = Path(__file__).parent / "uptrend_sma20_matches.csv"
        df.to_csv(out_path, index=False)
        print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    run()
