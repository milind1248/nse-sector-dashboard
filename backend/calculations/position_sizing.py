"""Position-sizing calculator — pure math, no market data or trade signal
of its own. Two standard sizing methods:

- Risk-based (fixed-fractional): size so a stop-out loses exactly a chosen
  % of capital, regardless of how far the stop is from entry.
- Capital-based (fixed allocation): size so the position uses exactly a
  chosen % of capital, regardless of stop distance — then reports what %
  of capital that position would actually risk if the stop is hit.
"""
from __future__ import annotations

import math


def risk_based_size(capital: float, risk_pct: float, entry: float, stop: float) -> dict:
    """Shares sized so a stop-out loses exactly risk_pct of capital."""
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0 or entry <= 0 or capital <= 0:
        return {}
    risk_amount = capital * (risk_pct / 100.0)
    shares = math.floor(risk_amount / risk_per_share)
    position_value = shares * entry
    return {
        "shares": shares,
        "risk_amount": round(risk_amount, 2),
        "risk_per_share": round(risk_per_share, 4),
        "position_value": round(position_value, 2),
        "pct_of_capital": round(position_value / capital * 100, 2) if capital > 0 else 0.0,
        "exceeds_capital": position_value > capital,
    }


def capital_based_size(capital: float, allocation_pct: float, entry: float,
                       stop: float | None = None) -> dict:
    """Shares sized to use exactly allocation_pct of capital. If a stop is
    given, also reports the resulting risk % of capital if stopped out."""
    if entry <= 0 or capital <= 0:
        return {}
    alloc_amount = capital * (allocation_pct / 100.0)
    shares = math.floor(alloc_amount / entry)
    position_value = shares * entry
    out = {
        "shares": shares,
        "alloc_amount": round(alloc_amount, 2),
        "position_value": round(position_value, 2),
        "pct_of_capital": round(position_value / capital * 100, 2) if capital > 0 else 0.0,
    }
    if stop is not None and stop > 0:
        risk_per_share = abs(entry - stop)
        risk_amount = shares * risk_per_share
        out["risk_amount"] = round(risk_amount, 2)
        out["risk_pct_of_capital"] = round(risk_amount / capital * 100, 2) if capital > 0 else 0.0
    return out


def reward_risk(entry: float, stop: float, target: float | None) -> dict:
    """Reward:Risk ratio and potential P&L if a target is given."""
    if target is None or entry <= 0:
        return {}
    risk_per_share = abs(entry - stop)
    reward_per_share = abs(target - entry)
    if risk_per_share <= 0:
        return {}
    return {
        "reward_risk_ratio": round(reward_per_share / risk_per_share, 2),
        "reward_per_share": round(reward_per_share, 4),
    }


def scenario_table(capital: float, entry: float, stop: float,
                   risk_levels: tuple = (0.5, 1.0, 1.5, 2.0, 3.0)) -> list[dict]:
    """Quick side-by-side comparison across common risk-% levels."""
    rows = []
    for r in risk_levels:
        res = risk_based_size(capital, r, entry, stop)
        if not res:
            continue
        rows.append({
            "Risk %": r, "Shares": res["shares"], "Position Value (₹)": res["position_value"],
            "% of Capital": res["pct_of_capital"], "Risk Amount (₹)": res["risk_amount"],
        })
    return rows
