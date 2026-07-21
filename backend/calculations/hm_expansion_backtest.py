"""Ablation-study backtest for the H-M Bullish Expansion + Adaptive FRVP
confluence scanner. Phase 1 scope (per the approved plan): variants A–G,
entry timing modes, and the core metrics list. Monte Carlo, walk-forward,
parameter sensitivity, portfolio simulation, exit-method/stop-loss
comparison, and the extended metrics list are deferred to Phase 2.

Variants
--------
A  existing H-M BUY logic         — hm_indicators.BOTTOM_SIGNAL alone
B  H-M bullish expansion only     — hm_bullish_expansion
C  B + rising EMA20               — hm_bullish_expansion & ema20_rising
D  B + above VAH                  — hm_bullish_expansion & price_above_vah
E  B + EMA20 pullback respected   — hm_bullish_expansion & ema20_respected
F  B + rising EMA20 + above VAH
G  full confluence                — signal_full_confluence

Caveat carried over from the standalone research package's Monte Carlo work
(same limitation, documented honestly): CAGR/max-drawdown here use a simple
sequential-compounding equity curve across a single symbol/variant's trades
— it does not model concurrent, overlapping positions across many stocks.
Treat those two metrics as directional, not a realistic portfolio result;
portfolio-level simulation is explicitly Phase 2 scope.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.calculations.hm_frvp_confluence import compute_confluence, ConfluenceParams
from backend.calculations.hm_expansion_universe import load_symbols

VARIANT_NAMES = ["A", "B", "C", "D", "E", "F", "G"]
VARIANT_LABELS = {
    "A": "Existing H-M BUY logic",
    "B": "H-M bullish expansion only",
    "C": "B + rising EMA20",
    "D": "B + above VAH",
    "E": "B + EMA20 pullback respected",
    "F": "B + rising EMA20 + above VAH",
    "G": "Full confluence",
}
COOLDOWN_BARS = 10
ENTRY_MODES = ("NEXT_OPEN", "NEXT_CLOSE", "SIGNAL_CLOSE")


def _dedup_with_cooldown(raw: pd.Series, cooldown_bars: int = COOLDOWN_BARS) -> np.ndarray:
    fresh = raw.fillna(False) & ~raw.fillna(False).shift(1, fill_value=False)
    keep = np.zeros(len(raw), dtype=bool)
    last_sig = -cooldown_bars - 1
    for i in np.where(fresh.to_numpy())[0]:
        if i - last_sig > cooldown_bars:
            keep[i] = True
            last_sig = i
    return keep


def _variant_raw_signal(out: pd.DataFrame, variant: str) -> pd.Series:
    a = out["BOTTOM_SIGNAL"].fillna(False) if "BOTTOM_SIGNAL" in out.columns else pd.Series(False, index=out.index)
    b = out["hm_bullish_expansion"].fillna(False)
    if variant == "A":
        return a
    if variant == "B":
        return b
    if variant == "C":
        return b & out["ema20_rising"].fillna(False)
    if variant == "D":
        return b & out["price_above_vah"].fillna(False)
    if variant == "E":
        return b & out["ema20_respected"].fillna(False)
    if variant == "F":
        return b & out["ema20_rising"].fillna(False) & out["price_above_vah"].fillna(False)
    if variant == "G":
        return out["signal_full_confluence"].fillna(False)
    raise ValueError(f"Unknown variant: {variant}")


def backtest_symbol(symbol: str, period: str = "20y", hold_days: tuple = (5, 10, 20),
                    entry_mode: str = "NEXT_OPEN", params: ConfluenceParams | None = None
                    ) -> dict[str, pd.DataFrame]:
    """Returns {variant: trades_df} for one stock, all 7 variants computed
    from a single shared indicator pass. Never raises."""
    empty = {v: pd.DataFrame() for v in VARIANT_NAMES}
    try:
        import yfinance as yf
        raw = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
        if raw is None or raw.empty or len(raw) < 320:
            return empty
        if hasattr(raw.columns, "levels"):
            raw.columns = raw.columns.droplevel(1)
        raw = raw.rename(columns={c: c.title() for c in raw.columns})
        df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
        if len(df) < 320:
            return empty

        out = compute_confluence(df, params)
        open_arr = out["Open"].to_numpy()
        close_arr = out["Close"].to_numpy()
        n = len(out)
        sym_clean = symbol.replace(".NS", "")

        results: dict[str, pd.DataFrame] = {}
        for variant in VARIANT_NAMES:
            raw_sig = _variant_raw_signal(out, variant)
            keep = _dedup_with_cooldown(raw_sig)
            sig_idx = np.where(keep)[0]

            rows = []
            for i in sig_idx:
                if entry_mode == "NEXT_OPEN":
                    entry_i = i + 1
                    if entry_i >= n:
                        continue
                    entry = open_arr[entry_i]
                    base_i = entry_i
                elif entry_mode == "NEXT_CLOSE":
                    entry_i = i + 1
                    if entry_i >= n:
                        continue
                    entry = close_arr[entry_i]
                    base_i = entry_i
                else:  # SIGNAL_CLOSE — flagged optimistic by the caller-facing report
                    entry = close_arr[i]
                    base_i = i

                row = {
                    "Symbol": sym_clean, "SignalDate": out.index[i].date(),
                    "EntryDate": out.index[base_i].date(), "EntryPrice": round(float(entry), 2),
                }
                for h in hold_days:
                    j = base_i + h
                    col = f"Ret{h}d%"
                    row[col] = round((close_arr[j] - entry) / entry * 100, 2) if j < n else np.nan
                rows.append(row)
            results[variant] = pd.DataFrame(rows)
        return results
    except Exception:
        return empty


def _max_drawdown_and_streak(returns_pct: pd.Series, initial_capital: float = 100_000.0
                             ) -> tuple[float, float, int]:
    """Simple sequential-compounding equity curve (see module docstring
    caveat). Returns (max_drawdown_pct, cagr_pct, longest_losing_streak)."""
    if returns_pct.empty:
        return 0.0, 0.0, 0
    equity = initial_capital
    peak = initial_capital
    max_dd = 0.0
    streak = 0
    longest_streak = 0
    for r in returns_pct:
        equity *= (1 + r / 100.0)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        if r < 0:
            streak += 1
            longest_streak = max(longest_streak, streak)
        else:
            streak = 0
    n_trades = len(returns_pct)
    years = max(n_trades / 25.0, 0.25)  # rough trades-per-year proxy, avoids div-by-zero on tiny samples
    cagr = ((equity / initial_capital) ** (1 / years) - 1) * 100.0 if equity > 0 else -100.0
    return round(max_dd, 2), round(cagr, 2), longest_streak


def compute_metrics(trades: pd.DataFrame, hold_days: int) -> dict:
    col = f"Ret{hold_days}d%"
    if trades.empty or col not in trades.columns:
        return {"trades": 0, "win_rate_pct": np.nan, "avg_return_pct": np.nan,
                "median_return_pct": np.nan, "avg_winner_pct": np.nan, "avg_loser_pct": np.nan,
                "expectancy_pct": np.nan, "profit_factor": np.nan, "max_drawdown_pct": np.nan,
                "cagr_pct": np.nan, "longest_losing_streak": np.nan}

    valid = trades[col].dropna()
    if valid.empty:
        return {"trades": 0, "win_rate_pct": np.nan, "avg_return_pct": np.nan,
                "median_return_pct": np.nan, "avg_winner_pct": np.nan, "avg_loser_pct": np.nan,
                "expectancy_pct": np.nan, "profit_factor": np.nan, "max_drawdown_pct": np.nan,
                "cagr_pct": np.nan, "longest_losing_streak": np.nan}

    wins = valid[valid > 0]
    losses = valid[valid < 0]
    win_rate = (valid > 0).mean() * 100
    avg_winner = wins.mean() if not wins.empty else 0.0
    avg_loser = losses.mean() if not losses.empty else 0.0
    expectancy = (win_rate / 100 * avg_winner) + ((1 - win_rate / 100) * avg_loser)
    gross_win = wins.sum()
    gross_loss = abs(losses.sum())
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else np.inf if gross_win > 0 else np.nan
    max_dd, cagr, streak = _max_drawdown_and_streak(valid)

    return {
        "trades": len(valid), "win_rate_pct": round(win_rate, 1),
        "avg_return_pct": round(valid.mean(), 2), "median_return_pct": round(valid.median(), 2),
        "avg_winner_pct": round(avg_winner, 2), "avg_loser_pct": round(avg_loser, 2),
        "expectancy_pct": round(expectancy, 3), "profit_factor": round(profit_factor, 2) if np.isfinite(profit_factor) else profit_factor,
        "max_drawdown_pct": max_dd, "cagr_pct": cagr, "longest_losing_streak": streak,
    }


def run_ablation_study(symbols: list[str], period: str = "20y", hold_days: tuple = (5, 10, 20),
                       entry_mode: str = "NEXT_OPEN", max_workers: int = 6,
                       universe_label: str = "custom", params: ConfluenceParams | None = None) -> dict:
    """Full ablation A–G across symbols. Returns
    {"trades": {variant: df}, "metrics": {variant: {hold_days: metrics}}, "warnings": [...]}."""
    if entry_mode not in ENTRY_MODES:
        raise ValueError(f"entry_mode must be one of {ENTRY_MODES}")

    all_trades: dict[str, list[pd.DataFrame]] = {v: [] for v in VARIANT_NAMES}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(backtest_symbol, s, period, hold_days, entry_mode, params): s for s in symbols}
        for fut in as_completed(futs):
            res = fut.result()
            for variant, trades in res.items():
                if not trades.empty:
                    all_trades[variant].append(trades)

    trades_by_variant = {
        v: (pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame())
        for v, dfs in all_trades.items()
    }

    metrics_by_variant = {
        v: {h: compute_metrics(trades_by_variant[v], h) for h in hold_days}
        for v in VARIANT_NAMES
    }

    warnings = []
    if entry_mode == "SIGNAL_CLOSE":
        warnings.append("ENTRY MODE WARNING: SIGNAL_CLOSE entry is potentially optimistic — "
                        "it fills at the same close used to confirm the signal, which is not "
                        "achievable in live trading. Prefer NEXT_OPEN.")
    if universe_label.lower().startswith("nifty 500") or universe_label.lower().startswith("nifty500"):
        warnings.append("SURVIVORSHIP BIAS WARNING: Historical test uses current or incomplete "
                        "Nifty 500 membership. Stocks that were removed from the index over the "
                        "test period are not included, which can inflate results.")

    return {"trades": trades_by_variant, "metrics": metrics_by_variant, "warnings": warnings}


def format_ablation_table(metrics_by_variant: dict, hold_days: int = 20) -> pd.DataFrame:
    rows = []
    for v in VARIANT_NAMES:
        m = metrics_by_variant[v][hold_days]
        rows.append({"Variant": v, "Description": VARIANT_LABELS[v], **m})
    return pd.DataFrame(rows)
