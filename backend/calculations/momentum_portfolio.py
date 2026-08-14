"""
Virtual portfolio logic for the Momentum Scanner's "Performance Breakdown"
tab — reproduces the "Stock Selection Process" / "Performance Breakdown"
slides from the source video's own deck (Turtle Wealth PMS), on top of the
already-built 3-criteria scan (backend/calculations/momentum_alltimehigh.py).

HONESTY NOTE, stated up front: the source deck's exact category thresholds
(what precisely separates "Crown & Add" from "Hold" from "Replace") are not
disclosed anywhere in the video or slides — only the bucket *names* and
their approximate meaning ("Crown & Add" = a strong new/growing position,
"Hold" = steady performer, "Replace" = a weak holding flagged for rotation,
"Exit" = cut from the book). This module's classify_holdings() is an honest,
documented approximation of that meaning using the already-validated 3/2/1/0
score from run_momentum_scan(), NOT a claimed reproduction of proprietary
thresholds. Treat category labels as illustrative, not exact.

No Streamlit imports here — caching/DB persistence is the caller's
responsibility (backend/data_ingestion/momentum_portfolio_pipeline.py).
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from backend.calculations.momentum_alltimehigh import (
    run_momentum_scan, universe_symbols, resolve_benchmark, DEFAULT_ATH_TOLERANCE_PCT,
)

DEFAULT_TOP_N = 15


def classify_holdings(scan_df: pd.DataFrame, prev_symbols: set[str], top_n: int = DEFAULT_TOP_N) -> pd.DataFrame:
    """
    Assigns each row in scan_df (run_momentum_scan()'s output) one of 4
    categories, then keeps only the current top_n-by-rank BUY/HOLD-worthy
    rows plus anything being actively exited (so the caller can show the
    Exit bucket too, before dropping those rows from next month's weights).

    Rules (see module docstring for the disclosure on why these are an
    approximation, not an exact reproduction):
      Crown & Add : score == 3 AND symbol not in prev_symbols (fresh entrant
                    at the strongest score) OR (score == 3 AND em_rank <= top_n/3,
                    i.e. a top-tier existing holding worth adding to).
      Hold        : score >= 2 AND em_rank <= top_n (steady, keep as-is).
      Replace     : em_rank <= top_n but score <= 1 (still ranked in, but
                    weak on the fundamental/relative-strength checks —
                    flagged, not yet cut).
      Exit        : was in prev_symbols but no longer ranks in the top_n at
                    all, OR score == 0.
    """
    df = scan_df.copy()
    in_top_n = df["em_rank"] <= top_n
    is_prev = df["symbol"].isin(prev_symbols)

    def _category(row):
        if row["em_rank"] <= top_n:
            if row["score"] == 3 and (row["symbol"] not in prev_symbols or row["em_rank"] <= max(1, top_n // 3)):
                return "Crown & Add"
            if row["score"] >= 2:
                return "Hold"
            return "Replace"
        if row["symbol"] in prev_symbols:
            return "Exit"
        return None  # not held, not previously held — irrelevant row

    df["category"] = df.apply(_category, axis=1)
    result = df[df["category"].notna()].copy()
    result["alpha_pct"] = result["ret_1y_pct"] - result["bench_ret_1y_pct"]
    return result


def rebalance_portfolio(prev_symbols: set[str] | None, top_n: int = DEFAULT_TOP_N,
                         ath_tolerance_pct: float = DEFAULT_ATH_TOLERANCE_PCT) -> pd.DataFrame:
    """
    Full rebalance: run the 3-criteria scan, classify, drop Exit rows from
    the live weighted book (they're returned for display but carry
    weight_pct=0), equal-weight the rest — matching the already-validated
    backtest's own weighting scheme (backend/calculations/momentum_alltimehigh.py's
    backtest used equal-weighted top-N, not a rank-tilted scheme).
    """
    prev_symbols = prev_symbols or set()
    symbols = tuple(universe_symbols())
    scan_df = run_momentum_scan(symbols, ath_tolerance_pct=ath_tolerance_pct, top_n=top_n)
    if scan_df.empty:
        return scan_df

    classified = classify_holdings(scan_df, prev_symbols, top_n=top_n)
    live = classified[classified["category"] != "Exit"]
    n_live = len(live)
    weight_each = round(100.0 / n_live, 2) if n_live > 0 else 0.0

    classified["weight_pct"] = classified["category"].apply(lambda c: 0.0 if c == "Exit" else weight_each)
    classified["return_pct"] = classified["ret_1y_pct"]
    return classified[["symbol", "category", "weight_pct", "return_pct", "alpha_pct", "em_rank"]]


def _fetch_last_two_closes(symbol: str) -> tuple[float, float] | None:
    """One fetch, returns (previous_close, latest_close) for a 1-day return."""
    try:
        df = yf.download(symbol, period="5d", interval="1d", auto_adjust=True, progress=False)
        if hasattr(df.columns, "levels"):
            df.columns = [c[0] for c in df.columns]
        df = df.dropna(how="all")
        if len(df) < 2:
            return None
        return float(df["Close"].iloc[-2]), float(df["Close"].iloc[-1])
    except Exception:
        return None


def mark_to_market(prev_holdings: list[dict], prev_fund_nav: float, prev_bench_nav: float) -> tuple[float, float]:
    """
    Cheap daily update: one fetch per currently-held symbol + the benchmark,
    apply yesterday's weights to today's price move. Does NOT re-scan the
    full universe — that only happens on rebalance days.
    """
    if not prev_holdings:
        return prev_fund_nav, prev_bench_nav

    weighted_return = 0.0
    total_weight = 0.0
    for h in prev_holdings:
        if h["weight_pct"] <= 0:
            continue
        sym = h["symbol"] + ".NS" if not h["symbol"].endswith(".NS") else h["symbol"]
        closes = _fetch_last_two_closes(sym)
        if closes is None or closes[0] <= 0:
            continue
        close_prev, close_today = closes
        day_ret = (close_today / close_prev) - 1
        weighted_return += day_ret * (h["weight_pct"] / 100.0)
        total_weight += h["weight_pct"] / 100.0

    fund_day_ret = weighted_return if total_weight > 0 else 0.0

    bench_ticker, bench_df = resolve_benchmark()
    bench_close = bench_df["Close"]
    bench_day_ret = float(bench_close.pct_change().iloc[-1]) if len(bench_close) > 1 else 0.0

    new_fund_nav = prev_fund_nav * (1 + fund_day_ret)
    new_bench_nav = prev_bench_nav * (1 + bench_day_ret)
    return round(new_fund_nav, 4), round(new_bench_nav, 4)
