"""
Standalone PEAD (Post-Earnings-Announcement-Drift) backtest — answers the
question directly instead of relying on general finance theory: for stocks
already in this project's quarterly_results table, did a higher PEAD score
(this project's own self-referential surprise measure) actually precede
stronger forward price drift?

Walk-forward, no lookahead: for each symbol/quarter, the PEAD score is
computed using ONLY the quarters up to and including that one (same
compute_pead_score() function the live PEAD Scanner uses), then forward
returns are measured from an approximate announcement date onward.

Known limitation, stated up front rather than hidden: Screener.in's page
only exposes quarter-END dates, not the actual results-announcement date,
and this project doesn't scrape a separate corporate-announcements feed.
Indian companies typically report ~30-50 days after quarter-end, so this
uses quarter-end + a fixed lag (default 45 days) as an approximation, not
the real announcement date. This will blur the drift measurement somewhat
(a company that reports early vs. late shifts the "day 0" a bit), but it's
the same order of imprecision across all symbols, so relative comparisons
between high/low PEAD-score buckets are still meaningful.

Run: python scripts/pead_backtest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import statistics
from datetime import timedelta

import pandas as pd
import yfinance as yf

from backend.calculations.pead_score import load_quarterly_history, compute_pead_score
from backend.storage.db import get_conn

ANNOUNCEMENT_LAG_DAYS = 45
HORIZONS = [20, 40, 60]  # trading days forward
BENCHMARK = "^CRSLDX"  # NIFTY 500 index — matches this backtest's universe


def _symbols_with_data() -> list[str]:
    con = get_conn()
    try:
        rows = con.execute("SELECT DISTINCT symbol FROM quarterly_results").fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _fetch_prices(symbol: str) -> pd.DataFrame:
    df = yf.download(symbol, period="2y", interval="1d", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def _forward_returns(price_df: pd.DataFrame, approx_announce_date: pd.Timestamp) -> dict:
    """Finds the first trading day on/after approx_announce_date as T0, then
    computes forward returns at each horizon in trading-day terms (not
    calendar days) — avoids weekends/holidays distorting the window."""
    idx = price_df.index
    on_or_after = idx[idx >= approx_announce_date]
    if len(on_or_after) == 0:
        return {}
    t0_date = on_or_after[0]
    t0_pos = idx.get_loc(t0_date)
    t0_close = float(price_df["Close"].iloc[t0_pos])

    out = {}
    for h in HORIZONS:
        target_pos = t0_pos + h
        if target_pos >= len(price_df):
            out[h] = None
            continue
        fwd_close = float(price_df["Close"].iloc[target_pos])
        out[h] = (fwd_close - t0_close) / t0_close * 100.0
    return out


def run_backtest():
    symbols = _symbols_with_data()
    print(f"Backtesting {len(symbols)} symbols with quarterly history in DB…")
    print(f"Approximate announcement date = quarter-end + {ANNOUNCEMENT_LAG_DAYS} days "
          f"(Screener.in doesn't expose the real announcement date — see script docstring).")
    print(f"Benchmark: {BENCHMARK} (NIFTY 500) — every return below is EXCESS return "
          f"(stock return minus the index's own return over the identical window), "
          f"isolating stock-specific drift from broad market movement.\n")

    try:
        benchmark_df = _fetch_prices(BENCHMARK)
    except Exception as e:
        print(f"FATAL: could not fetch benchmark {BENCHMARK}: {e}")
        return
    if benchmark_df.empty:
        print(f"FATAL: benchmark {BENCHMARK} returned no data.")
        return

    records = []  # each: {symbol, quarter, pead_score, red_flags, ret_20, ret_40, ret_60, xret_20, xret_40, xret_60}

    for i, symbol in enumerate(symbols):
        hist = load_quarterly_history(symbol)
        if len(hist) < 4:
            continue
        try:
            price_df = _fetch_prices(symbol)
        except Exception:
            continue
        if price_df.empty:
            continue

        # Walk forward: need >=3 quarters up to idx to score it (compute_pead_score's own minimum)
        for idx in range(2, len(hist)):
            point_in_time_hist = hist.iloc[: idx + 1]  # no lookahead past this quarter
            result = compute_pead_score(point_in_time_hist)
            if result["pead_score"] is None:
                continue

            quarter_label = point_in_time_hist.iloc[-1]["quarter"]  # e.g. "Sep 2025"
            try:
                quarter_end = pd.to_datetime(quarter_label, format="%b %Y") + pd.offsets.MonthEnd(0)
            except Exception:
                continue
            approx_announce = quarter_end + timedelta(days=ANNOUNCEMENT_LAG_DAYS)

            fwd = _forward_returns(price_df, approx_announce)
            if not fwd or all(v is None for v in fwd.values()):
                continue
            bench_fwd = _forward_returns(benchmark_df, approx_announce)

            xret = {}
            for h in HORIZONS:
                sr, br = fwd.get(h), bench_fwd.get(h)
                xret[h] = (sr - br) if (sr is not None and br is not None) else None

            records.append({
                "symbol": symbol, "quarter": quarter_label,
                "pead_score": result["pead_score"],
                "red_flags": len(result.get("red_flags") or []),
                **{f"ret_{h}d": fwd.get(h) for h in HORIZONS},
                **{f"xret_{h}d": xret.get(h) for h in HORIZONS},
            })

        if (i + 1) % 10 == 0:
            print(f"  …{i+1}/{len(symbols)} symbols processed")

    df = pd.DataFrame(records)
    if df.empty:
        print("No usable observations — nothing to report.")
        return

    print(f"\nTotal quarter-events with usable forward price data: {len(df)}\n")

    # ── Bucket by PEAD score ────────────────────────────────────────────
    def bucket(score):
        if score >= 60:
            return "High (score >= 60)"
        elif score >= 20:
            return "Medium (20-60)"
        else:
            return "Low/Negative (< 20)"

    df["bucket"] = df["pead_score"].apply(bucket)

    def _report(ret_prefix: str, title: str):
        print("=" * 78)
        print(title)
        print("=" * 78)
        for b in ["High (score >= 60)", "Medium (20-60)", "Low/Negative (< 20)"]:
            sub = df[df["bucket"] == b]
            if sub.empty:
                continue
            print(f"\n{b}  (n={len(sub)})")
            for h in HORIZONS:
                vals = sub[f"{ret_prefix}_{h}d"].dropna()
                if vals.empty:
                    continue
                mean_r = vals.mean()
                median_r = vals.median()
                hit_rate = (vals > 0).mean() * 100
                print(f"  {h:>2}d forward: mean {mean_r:+6.2f}%  median {median_r:+6.2f}%  "
                      f"% positive {hit_rate:5.1f}%  (n={len(vals)})")
        print()

    # ── PRIMARY: excess return vs. NIFTY 500 benchmark ──────────────────
    _report("xret", f"EXCESS RETURN vs {BENCHMARK} BY PEAD-SCORE BUCKET (primary result — market-drift removed)")

    print("=" * 78)
    print(f"CORRELATION: PEAD score vs EXCESS return (Pearson)")
    print("=" * 78)
    for h in HORIZONS:
        sub = df[["pead_score", f"xret_{h}d"]].dropna()
        if len(sub) < 5:
            continue
        corr = sub["pead_score"].corr(sub[f"xret_{h}d"])
        print(f"  {h}d excess return vs PEAD score: r = {corr:+.3f}  (n={len(sub)})")
    print()

    # ── Earnings-quality red flags, on EXCESS return ────────────────────
    print("=" * 78)
    print("EARNINGS-QUALITY RED FLAGS: does a flagged quarter underperform (excess return)?")
    print("=" * 78)
    for flagged, label in [(True, "Flagged (>=1 red flag)"), (False, "Clean (0 red flags)")]:
        sub = df[(df["red_flags"] > 0) == flagged]
        if sub.empty:
            continue
        print(f"\n{label}  (n={len(sub)})")
        for h in HORIZONS:
            vals = sub[f"xret_{h}d"].dropna()
            if vals.empty:
                continue
            print(f"  {h:>2}d excess: mean {vals.mean():+6.2f}%  median {vals.median():+6.2f}%")
    print()

    # ── SECONDARY: raw return, for reference/comparison only ────────────
    _report("ret", "RAW RETURN BY PEAD-SCORE BUCKET (reference only — includes market drift, see excess-return section above for the real read)")

    print("=" * 78)
    print("CORRELATION: PEAD score vs RAW forward return (Pearson, reference only)")
    print("=" * 78)
    for h in HORIZONS:
        sub = df[["pead_score", f"ret_{h}d"]].dropna()
        if len(sub) < 5:
            continue
        corr = sub["pead_score"].corr(sub[f"ret_{h}d"])
        print(f"  {h}d raw return vs PEAD score: r = {corr:+.3f}  (n={len(sub)})")

    out_path = Path(__file__).parent / "pead_backtest_results.csv"
    df.to_csv(out_path, index=False)
    print(f"\nFull per-observation data saved to {out_path}")


if __name__ == "__main__":
    run_backtest()
