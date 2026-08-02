"""
Standalone scanner + backtest for the "H-M + Volume Mismatch" position-buying
strategy described by the trader in the YouTube podcast (transcript reviewed,
Hindi, ~2026). Deliberately a standalone script — NOT wired into the live
website, per explicit instruction.

Three distinct, codifiable rules pulled directly from the transcript:

1. H-M "V-SHAPE" BUY ENTRY (the core correction to a common mistake he
   calls out explicitly): don't buy just because RSI(9) crosses above the
   WMA(21) "red line" — most people jump in early and get stopped out
   repeatedly in a range-bound market. The rule he gives: wait for RSI to
   dip, form a full "V" recovery, and cross above 55 (not the default 50)
   before entering. Stop-loss trails the 20-period SMA/EMA of price ("your
   stop-loss IS your target — let it run until the average is broken").

2. VOLUME MISMATCH validation (his newer addition, and what he calls the
   single most under-rated tool in the market), codified precisely per
   his OFSS worked example — NOT a flat "volume above average" threshold
   (an earlier version of this script used that shortcut; it added noise
   instead of signal because it demanded big volume even on ordinary,
   perfectly valid candles that were never claiming to be a big move):
     a) Volume is only checked once a candle's own RANGE is unusually
        large (>= BIG_CANDLE_MULT x the recent average) — normal candles
        need no validation at all.
     b) Once a candle IS big, its volume must ALSO be proportionally big
        (>= BIG_VOLUME_MULT x the recent average) — "jitni badi candle,
        utni badi volume". Big price move on thin volume = MISMATCH.
     c) A real big-volume move must extend market structure — the candle
        must actually break the recent N-bar high (bullish) or low
        (bearish). Big volume on a candle that doesn't break structure
        is "not real" either (his own words: "agar real hota to iska low
        bhi break kar deta").
   Used as a confirmation filter on the H-M entry, tested with/without.

3. "OLD LOW BREAKS" short setup: if H-M flips into the BUY regime and then
   flips straight back to SELL without a sustained rally, the prior swing
   low will very likely break, hard — his own claim from experience is
   "8 times out of 10." Backtested directly here rather than taken on
   faith.

Reuses backend/calculations/hm_indicators.py's add_indicators() for the
underlying RSI(9)/EMA(3)/WMA(21)/SMA20 computation (already a faithful,
already-verified port of the same H-M System used on the live TradingView
chart) — only the entry/exit/short rules here are new, since the video's
specific V-shape/volume-mismatch/old-low-break rules aren't the same as
the existing generate_signals() logic already on the site.

Run: python scripts/hm_volume_mismatch_scanner.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import yfinance as yf

from backend.calculations.universe import load_symbols
from backend.calculations.hm_indicators import add_indicators

BENCHMARK = "^NSEI"
RSI_RECOVERY_LEVEL = 55.0     # video: raised from the usual 50 to avoid early/false entries
V_SHAPE_LOOKBACK = 6          # bars RSI must have dipped below the level within, to count as a real "V"
VOLUME_LOOKBACK = 10           # window for both candle-size and volume "average" comparisons
BIG_CANDLE_MULT = 1.5          # a candle only needs volume validation once its range is this x the recent average
BIG_VOLUME_MULT = 1.5          # once a candle IS "big", its volume must be at least this x the recent average
MAX_HOLD_BARS = 52            # ~1 year of weekly bars, matches the video's "minimum ~1 year holding" for position trades
OLD_LOW_LOOKBACK = 10         # bars searched back for the swing low that preceded a failed BUY flip
OLD_LOW_FLIP_WINDOW = 3       # BUY regime must flip back to SELL within this many bars to count as "failed"
OLD_LOW_CHECK_FORWARD = 15    # bars forward to check whether the old low actually broke


# ─────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────

def _fetch_weekly(symbol: str, period: str = "10y") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1wk", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


# ─────────────────────────────────────────────────────────────────────────
# 1) H-M V-shape entry + volume-mismatch confirmation
# ─────────────────────────────────────────────────────────────────────────

def compute_volume_mismatch(df: pd.DataFrame, lookback: int = VOLUME_LOOKBACK) -> pd.DataFrame:
    """His exact rule, as stated with the OFSS example — codified precisely,
    not as a flat volume threshold:

      1. Volume only needs to be validated on a candle that's actually
         "big" (range clearly larger than recent normal) — an ordinary
         candle doesn't need big volume to be trustworthy. This is the
         piece the previous flat-threshold version got wrong: it demanded
         above-average volume on EVERY entry, including perfectly valid
         quiet V-shape recoveries that were never claiming to be a big
         move in the first place.
      2. When a candle IS big, its volume must ALSO be proportionally big
         (>= BIG_VOLUME_MULT x the recent average) — "jitni badi candle,
         utni badi volume" ("candle size 4x, volume should also be
         way bigger"). A big candle on thin volume is a MISMATCH — the
         move isn't real, don't trust it.
      3. A real big-volume move must also extend market structure — the
         candle's High must clear the recent N-bar high (bullish) or its
         Low must clear the recent N-bar low (bearish). Volume spiking on
         a candle that does NOT break structure is "not real" either
         (his own words: "agar real hota to iska low bhi break kar deta").

    Adds: IS_BIG_CANDLE, IS_BIG_VOLUME, BREAKS_UP, BREAKS_DOWN,
    VOLUME_MISMATCH (True = don't trust this candle), VOLUME_VALID
    (the inverse — True on every bar that either isn't "big" at all, or
    is big AND has the volume + structure-break to back it up)."""
    out = df.copy()
    if out.empty:
        return out

    candle_range = out["High"] - out["Low"]
    range_avg_prior = candle_range.rolling(lookback).mean().shift(1)
    vol_avg_prior = out["Volume"].rolling(lookback).mean().shift(1)
    prior_high = out["High"].rolling(lookback).max().shift(1)
    prior_low = out["Low"].rolling(lookback).min().shift(1)

    out["IS_BIG_CANDLE"] = candle_range > (range_avg_prior * BIG_CANDLE_MULT)
    out["IS_BIG_VOLUME"] = out["Volume"] > (vol_avg_prior * BIG_VOLUME_MULT)
    out["BREAKS_UP"] = out["High"] > prior_high
    out["BREAKS_DOWN"] = out["Low"] < prior_low
    bullish = out["Close"] > out["Open"]

    # Mismatch #1: big price move, volume didn't back it up.
    size_mismatch = out["IS_BIG_CANDLE"] & ~out["IS_BIG_VOLUME"]
    # Mismatch #2: big volume AND big candle, but price never actually broke
    # structure in that candle's own direction — the "fake" pattern from
    # his example (volume spiked but the low/high wasn't taken out).
    structure_mismatch = (
        out["IS_BIG_CANDLE"] & out["IS_BIG_VOLUME"]
        & ((bullish & ~out["BREAKS_UP"]) | (~bullish & ~out["BREAKS_DOWN"]))
    )
    out["VOLUME_MISMATCH"] = (size_mismatch | structure_mismatch).fillna(False)
    out["VOLUME_VALID"] = ~out["VOLUME_MISMATCH"]
    return out


def add_vshape_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Adds VSHAPE_BUY (entry trigger) to an already-add_indicators()'d +
    compute_volume_mismatch()'d dataframe. VSHAPE_BUY fires only on the
    exact bar RSI crosses above RSI_RECOVERY_LEVEL, AND it dipped below
    that level within the last V_SHAPE_LOOKBACK bars (the "V" — not just
    any upward touch), AND price is in the H-M BUY regime (RSI > WMA21,
    i.e. the "red line" is below RSI, matching the video's "red line
    andar chala gaya" description)."""
    out = df.copy()
    if out.empty:
        return out

    was_below = out["RSI"].rolling(V_SHAPE_LOOKBACK).min() < RSI_RECOVERY_LEVEL
    crossed_above = (out["RSI"] > RSI_RECOVERY_LEVEL) & (out["RSI"].shift(1) <= RSI_RECOVERY_LEVEL)
    out["VSHAPE_BUY"] = was_below.shift(1).fillna(False) & crossed_above & out["HM_BUY_REGIME"]

    # A signal is only as trustworthy as its own trigger bar AND the bar
    # right before it (a fake breakout candle sitting just ahead of an
    # entry undermines it even if the entry bar itself looks clean).
    no_recent_mismatch = ~(out["VOLUME_MISMATCH"] | out["VOLUME_MISMATCH"].shift(1).fillna(False))
    out["VOLUME_CONFIRMED"] = no_recent_mismatch  # kept name for backward-compat with the rest of the script

    return out


def backtest_vshape(df: pd.DataFrame, symbol: str, require_volume: bool) -> pd.DataFrame:
    """Entry: next bar's open after a VSHAPE_BUY trigger (require_volume
    additionally gates on VOLUME_CONFIRMED). Exit (matches the video's
    "stop-loss is your target, trail the 20 SMA"): first bar where Close
    closes below SMA20, or MAX_HOLD_BARS elapsed, whichever comes first."""
    if df.empty or "VSHAPE_BUY" not in df.columns:
        return pd.DataFrame()

    trigger = df["VSHAPE_BUY"] & (df["VOLUME_CONFIRMED"] if require_volume else True)
    positions = np.where(trigger.fillna(False).to_numpy())[0]
    rows = []
    for pos in positions:
        entry_pos = pos + 1
        if entry_pos >= len(df):
            continue
        entry = float(df["Open"].iloc[entry_pos])
        entry_time = df.index[entry_pos]

        exit_pos, exit_price, outcome = None, None, "time_exit"
        max_scan = min(entry_pos + MAX_HOLD_BARS, len(df) - 1)
        for j in range(entry_pos, max_scan + 1):
            close_j = float(df["Close"].iloc[j])
            sma20_j = df["SMA20"].iloc[j]
            if pd.notna(sma20_j) and close_j < float(sma20_j) and j > entry_pos:
                exit_pos, exit_price, outcome = j, close_j, "trail_stop"
                break
        if exit_pos is None:
            exit_pos = max_scan
            exit_price = float(df["Close"].iloc[exit_pos])

        rows.append({
            "symbol": symbol, "signal_time": df.index[pos], "entry_time": entry_time,
            "exit_time": df.index[exit_pos], "entry": entry, "exit": exit_price,
            "return_pct": (exit_price / entry - 1) * 100, "outcome": outcome,
            "rsi_at_entry": float(df["RSI"].iloc[pos]),
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────
# 2) "Old low breaks" short setup
# ─────────────────────────────────────────────────────────────────────────

def add_old_low_flip_signal(df: pd.DataFrame) -> pd.DataFrame:
    """Flags OLD_LOW_FLIP_FAIL: HM entered the BUY regime, then flipped
    straight back to SELL within OLD_LOW_FLIP_WINDOW bars (no sustained
    rally) — the video's specific "failed bounce" pattern. old_low_level
    is the swing low that preceded the original buy-flip, which the video
    claims breaks hard afterward."""
    out = df.copy()
    if out.empty:
        return out

    buy_regime = out["HM_BUY_REGIME"].fillna(False)
    just_turned_buy = buy_regime & ~buy_regime.shift(1).fillna(False)

    flip_fail = pd.Series(False, index=out.index)
    old_low_level = pd.Series(np.nan, index=out.index)

    turn_positions = np.where(just_turned_buy.to_numpy())[0]
    for t_pos in turn_positions:
        window_end = min(t_pos + OLD_LOW_FLIP_WINDOW, len(out) - 1)
        window = out["HM_BUY_REGIME"].iloc[t_pos: window_end + 1]
        # did it flip back to SELL within the window (i.e. buy regime didn't sustain)?
        fail_positions = window[~window.fillna(False)].index
        if len(fail_positions) > 1:  # first bar in window is the turn itself (True); look for a later False
            fail_idx = out.index.get_loc(fail_positions[-1])
            if fail_idx > t_pos:
                lb_start = max(0, t_pos - OLD_LOW_LOOKBACK)
                swing_low = float(out["Low"].iloc[lb_start:t_pos].min()) if t_pos > lb_start else np.nan
                flip_fail.iloc[fail_idx] = True
                old_low_level.iloc[fail_idx] = swing_low

    out["OLD_LOW_FLIP_FAIL"] = flip_fail
    out["OLD_LOW_LEVEL"] = old_low_level
    return out


def backtest_old_low_break(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """For each OLD_LOW_FLIP_FAIL signal, checks whether the flagged old
    low actually broke within OLD_LOW_CHECK_FORWARD bars, and the price
    move (%) from the old-low level to the lowest point reached in that
    window — a direct test of the video's "8 out of 10 times" claim."""
    if df.empty or "OLD_LOW_FLIP_FAIL" not in df.columns:
        return pd.DataFrame()

    positions = np.where(df["OLD_LOW_FLIP_FAIL"].fillna(False).to_numpy())[0]
    rows = []
    for pos in positions:
        old_low = df["OLD_LOW_LEVEL"].iloc[pos]
        if pd.isna(old_low):
            continue
        fwd_end = min(pos + OLD_LOW_CHECK_FORWARD, len(df) - 1)
        window = df.iloc[pos: fwd_end + 1]
        broke = bool((window["Low"] < old_low).any())
        lowest = float(window["Low"].min())
        move_pct_from_old_low = (lowest / old_low - 1) * 100 if old_low else None
        rows.append({
            "symbol": symbol, "signal_time": df.index[pos], "old_low_level": round(old_low, 2),
            "broke_within_window": broke,
            "lowest_reached": round(lowest, 2),
            "move_pct_below_old_low": round(move_pct_from_old_low, 2) if move_pct_from_old_low is not None else None,
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────

def run():
    symbols = load_symbols("Nifty 50")
    print(f"Scanning/backtesting H-M V-shape + Volume Mismatch + Old-Low-Break on {len(symbols)} Nifty 50 symbols (weekly)…\n")

    try:
        bench_df = _fetch_weekly(BENCHMARK)
        bench_close = bench_df["Close"]
    except Exception as e:
        print(f"FATAL: could not fetch benchmark {BENCHMARK}: {e}")
        return

    def _bench_return(entry_time, exit_time):
        idx = bench_close.index
        e_on_after = idx[idx >= entry_time]
        x_on_after = idx[idx >= exit_time]
        if len(e_on_after) == 0 or len(x_on_after) == 0:
            return None
        b_entry, b_exit = float(bench_close.loc[e_on_after[0]]), float(bench_close.loc[x_on_after[0]])
        return (b_exit / b_entry - 1) * 100 if b_entry else None

    all_vshape_novol, all_vshape_vol, all_oldlow = [], [], []
    current_watchlist = []

    for i, symbol in enumerate(symbols):
        try:
            raw = _fetch_weekly(symbol)
            if len(raw) < 60:
                continue
            ind = add_indicators(raw)
            if ind.empty:
                continue
            ind = compute_volume_mismatch(ind)
            sig = add_vshape_signals(ind)
            sig = add_old_low_flip_signal(sig)
        except Exception:
            continue

        t_novol = backtest_vshape(sig, symbol, require_volume=False)
        t_vol = backtest_vshape(sig, symbol, require_volume=True)
        t_oldlow = backtest_old_low_break(sig, symbol)
        if not t_novol.empty:
            all_vshape_novol.append(t_novol)
        if not t_vol.empty:
            all_vshape_vol.append(t_vol)
        if not t_oldlow.empty:
            all_oldlow.append(t_oldlow)

        # Live scan: did a V-shape BUY trigger on the most recent completed bar?
        if bool(sig["VSHAPE_BUY"].iloc[-1]):
            current_watchlist.append({
                "symbol": symbol,
                "rsi": round(float(sig["RSI"].iloc[-1]), 1),
                "volume_confirmed": bool(sig["VOLUME_CONFIRMED"].iloc[-1]),
                "close": round(float(sig["Close"].iloc[-1]), 2),
                "sma20_stop": round(float(sig["SMA20"].iloc[-1]), 2) if pd.notna(sig["SMA20"].iloc[-1]) else None,
            })

        if (i + 1) % 10 == 0:
            print(f"  …{i+1}/{len(symbols)} symbols processed")

    # ── Report: V-shape entry, with vs without volume confirmation ─────
    for label, trades_list in [("WITHOUT volume-mismatch filter", all_vshape_novol),
                                ("WITH volume-mismatch filter", all_vshape_vol)]:
        trades = pd.concat(trades_list, ignore_index=True) if trades_list else pd.DataFrame()
        print("=" * 78)
        print(f"H-M V-SHAPE BUY ENTRY — {label}  (n={len(trades)})")
        print("=" * 78)
        if trades.empty:
            print("  No trades.\n")
            continue
        trades["bench_ret"] = [
            _bench_return(row["entry_time"], row["exit_time"]) for _, row in trades.iterrows()
        ]
        trades["excess_ret"] = trades["return_pct"] - trades["bench_ret"]
        win_rate = (trades["return_pct"] > 0).mean() * 100
        excess = trades["excess_ret"].dropna()
        excess_win_rate = (excess > 0).mean() * 100 if not excess.empty else float("nan")
        print(f"  Win rate: {win_rate:.1f}%   Avg return: {trades['return_pct'].mean():+.2f}%   "
              f"Median return: {trades['return_pct'].median():+.2f}%")
        print(f"  Excess-vs-NIFTY win rate: {excess_win_rate:.1f}%   "
              f"Avg excess return: {excess.mean():+.2f}%" if not excess.empty else "  Excess data unavailable")
        print(f"  Outcome breakdown: {trades['outcome'].value_counts().to_dict()}\n")

    # ── Report: Old-low-break short setup ───────────────────────────────
    oldlow = pd.concat(all_oldlow, ignore_index=True) if all_oldlow else pd.DataFrame()
    print("=" * 78)
    print(f"'OLD LOW BREAKS' SHORT SETUP  (n={len(oldlow)})")
    print("=" * 78)
    if not oldlow.empty:
        broke_rate = oldlow["broke_within_window"].mean() * 100
        broke_only = oldlow[oldlow["broke_within_window"]]
        print(f"  Old low actually broke within {OLD_LOW_CHECK_FORWARD} weeks: {broke_rate:.1f}% of the time "
              f"(video's claim: ~80%)")
        if not broke_only.empty:
            print(f"  When it broke, avg move below the old low: {broke_only['move_pct_below_old_low'].mean():+.2f}%  "
                  f"median: {broke_only['move_pct_below_old_low'].median():+.2f}%")
    else:
        print("  No signals found.")
    print()

    # ── Current live watchlist ──────────────────────────────────────────
    print("=" * 78)
    print(f"CURRENT WATCHLIST — V-shape BUY triggered on the latest completed weekly bar (n={len(current_watchlist)})")
    print("=" * 78)
    for w in current_watchlist:
        vol_tag = "[volume confirmed]" if w["volume_confirmed"] else "[volume NOT confirmed]"
        print(f"  {w['symbol']:<16} Close {w['close']:<10} RSI {w['rsi']:<6} Stop(20SMA) {w['sma20_stop']}  {vol_tag}")

    out_dir = Path(__file__).parent
    if all_vshape_vol:
        pd.concat(all_vshape_vol, ignore_index=True).to_csv(out_dir / "hm_vshape_volume_trades.csv", index=False)
    if all_oldlow:
        oldlow.to_csv(out_dir / "hm_old_low_break_signals.csv", index=False)
    print(f"\nDetailed trade logs saved to {out_dir}")


if __name__ == "__main__":
    run()
