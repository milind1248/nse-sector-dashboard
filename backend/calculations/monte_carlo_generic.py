"""Generic Monte Carlo robustness testing on an uploaded trade-return series.

Unlike the position-sized version built for the standalone FRVP+H-M research
package, this operates purely on a per-trade return percentage column — no
entry price / stop-loss required, so it works with any trade log a user
uploads (a broker export, a trading journal, another strategy's backtest).

Two tests:
1. Bootstrap resampling (with replacement) — the range of outcomes the
   trade population could plausibly have produced, not just the one
   sequence that actually happened.
2. Trade-order shuffle (without replacement) — same trades, random order;
   isolates sequence-of-returns / drawdown risk from the strategy's edge.

Equity compounds directly off each trade's return% (no position sizing),
so results are what actually happened per the uploaded numbers — no
overlapping-position assumption is being made either way.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Column names commonly used for a "return per trade" field, checked in order.
_RETURN_COLUMN_CANDIDATES = [
    "return", "return%", "return_pct", "returnpct", "ret", "ret%", "pnl%",
    "pnl_pct", "profit%", "profit_pct", "gain%", "gain_pct", "%return", "% return",
]


def detect_return_column(df: pd.DataFrame) -> str | None:
    """Best-effort auto-detect which column holds per-trade return %.
    Returns the column name, or None if nothing obvious is found."""
    normalized = {c.strip().lower().replace(" ", "").replace("_", ""): c for c in df.columns}
    for candidate in _RETURN_COLUMN_CANDIDATES:
        key = candidate.replace(" ", "").replace("_", "")
        if key in normalized:
            return normalized[key]
    # fall back: any numeric column with "ret" or "pnl" or "gain" or "%" in its name
    for col in df.columns:
        low = str(col).strip().lower()
        if any(tok in low for tok in ("ret", "pnl", "gain", "%")) and pd.api.types.is_numeric_dtype(df[col]):
            return col
    return None


def clean_returns(series: pd.Series) -> pd.Series:
    """Coerces to numeric, strips a trailing '%' if present as text, drops NaN.
    Always attempts the string-strip pass regardless of dtype — relying on
    `dtype == object` is unreliable across pandas versions (newer pandas can
    report a dedicated string dtype instead of `object` for the same data,
    which would silently skip the '%' strip and drop otherwise-valid rows)."""
    if pd.api.types.is_numeric_dtype(series):
        return series.dropna()
    s = series.astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False).str.strip()
    s = pd.to_numeric(s, errors="coerce")
    return s.dropna()


def _simulate_equity_path(returns_pct: np.ndarray, initial_capital: float) -> tuple[float, float]:
    equity = initial_capital
    peak = initial_capital
    max_dd = 0.0
    for r in returns_pct:
        equity *= (1 + r / 100.0)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return equity, max_dd


def bootstrap_simulation(returns: pd.Series, n_sims: int = 2000,
                         initial_capital: float = 100_000.0, seed: int = 42) -> pd.DataFrame:
    """Resamples the return series WITH replacement, n_sims times, same
    trade count as the original."""
    values = returns.to_numpy()
    n = len(values)
    if n == 0:
        return pd.DataFrame()
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n_sims):
        sample = values[rng.integers(0, n, size=n)]
        final_eq, max_dd = _simulate_equity_path(sample, initial_capital)
        rows.append({
            "final_equity": final_eq,
            "total_return_pct": (final_eq - initial_capital) / initial_capital * 100.0,
            "max_drawdown_pct": max_dd,
        })
    return pd.DataFrame(rows)


def shuffle_simulation(returns: pd.Series, n_sims: int = 2000,
                       initial_capital: float = 100_000.0, seed: int = 42) -> pd.DataFrame:
    """Shuffles the SAME set of real trades (no replacement) n_sims times.
    Total return is identical every time by construction — only
    max_drawdown_pct varies, isolating sequence-of-returns risk."""
    values = returns.to_numpy()
    n = len(values)
    if n == 0:
        return pd.DataFrame()
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n_sims):
        sample = values[rng.permutation(n)]
        final_eq, max_dd = _simulate_equity_path(sample, initial_capital)
        rows.append({
            "final_equity": final_eq,
            "total_return_pct": (final_eq - initial_capital) / initial_capital * 100.0,
            "max_drawdown_pct": max_dd,
        })
    return pd.DataFrame(rows)


def summarize_simulation(sim_df: pd.DataFrame) -> dict:
    if sim_df.empty:
        return {}
    pct = lambda col, q: round(float(np.percentile(sim_df[col], q)), 2)
    return {
        "n_sims": len(sim_df),
        "total_return_p5": pct("total_return_pct", 5),
        "total_return_p25": pct("total_return_pct", 25),
        "total_return_p50": pct("total_return_pct", 50),
        "total_return_p75": pct("total_return_pct", 75),
        "total_return_p95": pct("total_return_pct", 95),
        "prob_profit_pct": round(float((sim_df["total_return_pct"] > 0).mean() * 100), 2),
        "max_dd_p50": pct("max_drawdown_pct", 50),
        "max_dd_p95": pct("max_drawdown_pct", 95),
        "worst_max_dd": round(float(sim_df["max_drawdown_pct"].max()), 2),
    }


def basic_trade_stats(returns: pd.Series) -> dict:
    if returns.empty:
        return {}
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    return {
        "n_trades": len(returns),
        "win_rate_pct": round((returns > 0).mean() * 100, 1),
        "avg_return_pct": round(returns.mean(), 3),
        "median_return_pct": round(returns.median(), 3),
        "avg_winner_pct": round(wins.mean(), 3) if not wins.empty else 0.0,
        "avg_loser_pct": round(losses.mean(), 3) if not losses.empty else 0.0,
        "best_trade_pct": round(returns.max(), 2),
        "worst_trade_pct": round(returns.min(), 2),
    }
