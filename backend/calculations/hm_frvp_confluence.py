"""H-M Bullish Expansion + Adaptive FRVP + EMA-20 confluence scanner.

Wires together:
  - backend.calculations.hm_indicators  — existing, faithful H-M lines + the
    existing single-stock scanner's BOTTOM_SIGNAL (ablation variant A)
  - backend.calculations.hm_expansion   — new bullish-expansion detector
  - backend.calculations.frvp_adaptive  — faithful Adaptive FRVP port

into three signal tiers (hm_only / hm_trend / full_confluence), a 0-100
confluence score, a classification bucket, and a human-readable rejection
reason — matching the output schema and defaults from the spec exactly.

Hidden behind config.ENABLE_HM_FRVP_EXPANSION_SCANNER — see run.py's
hm_expansion_scan/hm_expansion_backtest subcommands for the only entry
points. Not wired into any Streamlit page.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.calculations.hm_indicators import add_indicators, generate_signals
from backend.calculations.hm_expansion import compute_expansion, ExpansionParams
from backend.calculations.frvp_adaptive import attach_confirmed_frvp, FRVPParams


# ─────────────────────────────────────────────────────────────────────────
# EMA-20 rising / pullback / respected
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class EMAParams:
    ema_period: int = 20
    ema_slope_lookback: int = 5
    min_ema_slope_pct: float = 0.25
    require_consecutive_ema_rise: bool = True

    ema_pullback_lookback: int = 5
    ema_touch_tolerance_above: float = 0.01
    ema_break_tolerance_below: float = 0.02

    respect_mode: str = "BASIC"  # BASIC | PREVIOUS_HIGH | STRONG_CLOSE | TWO_CLOSES
    max_close_above_ema_pct: float = 5.0


def compute_ema_conditions(df: pd.DataFrame, params: EMAParams | None = None) -> pd.DataFrame:
    p = params or EMAParams()
    out = df.copy()

    ema20 = out["Close"].ewm(span=p.ema_period, adjust=False).mean()
    out["ema20"] = ema20

    slope_pct = (ema20 / ema20.shift(p.ema_slope_lookback) - 1) * 100
    out["ema20_slope_pct"] = slope_pct
    rising = slope_pct >= p.min_ema_slope_pct
    if p.require_consecutive_ema_rise:
        rising = rising & (ema20 > ema20.shift(1)) & (ema20.shift(1) > ema20.shift(2))
    out["ema20_rising"] = rising.fillna(False)

    touch_now = out["Low"] <= ema20 * (1 + p.ema_touch_tolerance_above)
    no_breakdown = out["Low"] >= ema20 * (1 - p.ema_break_tolerance_below)
    touch_ok_now = touch_now & no_breakdown
    out["ema20_touched"] = touch_ok_now.rolling(p.ema_pullback_lookback, min_periods=1).max().astype(bool)

    was_above = (out["Close"].shift(1) > ema20.shift(1))
    out["was_above_ema_before_pullback"] = (
        was_above.rolling(p.ema_pullback_lookback, min_periods=1).max().astype(bool).fillna(False)
    )

    close, open_ = out["Close"], out["Open"]
    basic = out["ema20_touched"] & out["was_above_ema_before_pullback"] & (close > ema20) & (close > open_)

    if p.respect_mode == "PREVIOUS_HIGH":
        respected = basic & (close > out["High"].shift(1))
    elif p.respect_mode == "STRONG_CLOSE":
        rng = (out["High"] - out["Low"]).replace(0, np.nan)
        close_pos = (close - out["Low"]) / rng
        respected = basic & (close_pos >= 0.65).fillna(False)
    elif p.respect_mode == "TWO_CLOSES":
        respected = basic & (close > ema20) & (close.shift(1) > ema20.shift(1))
    else:  # BASIC
        respected = basic

    ema_distance_pct = (close / ema20 - 1) * 100
    out["ema_distance_pct"] = ema_distance_pct
    respected = respected & (ema_distance_pct <= p.max_close_above_ema_pct)
    out["ema20_respected"] = respected.fillna(False)

    return out


# ─────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────

SCORE_WEIGHTS = {
    "oversold_origin": 10, "bullish_ordering": 10, "all_lines_rising": 15,
    "minimum_separation_met": 10, "gaps_expanding": 10, "strong_upward_slopes": 15,
    "price_above_vah": 10, "ema20_rising": 10, "ema20_respected": 10,
}
MINIMUM_SCORE = 70


def _classify(score: float) -> str:
    if score >= 85:
        return "STRONG BUY CANDIDATE"
    if score >= 70:
        return "BUY CANDIDATE"
    if score >= 55:
        return "WATCHLIST"
    return "REJECT"


def _rejection_reason(row: pd.Series) -> str:
    reasons = []
    if not row.get("oversold_origin"):
        reasons.append("No oversold origin within lookback")
    if not row.get("bullish_ordering"):
        reasons.append("H-M lines not in bullish order (white>green>red)")
    if not row.get("all_lines_rising"):
        reasons.append("Not all three H-M lines rising")
    if not row.get("minimum_separation_met"):
        reasons.append("H-M lines not sufficiently separated")
    if not row.get("lines_not_touching"):
        reasons.append("H-M lines touching")
    if not row.get("gaps_expanding"):
        reasons.append("H-M line gaps contracting")
    if not row.get("strong_upward_slopes"):
        reasons.append("H-M line slope below threshold")
    if not row.get("price_above_vah"):
        reasons.append("Price below confirmed VAH")
    if not row.get("ema20_rising"):
        reasons.append("EMA20 not rising")
    if not row.get("ema20_respected"):
        reasons.append("EMA pullback not respected")
    if row.get("ema_distance_pct") is not None and row.get("ema_distance_pct", 0) > EMAParams().max_close_above_ema_pct:
        reasons.append("Price too extended above EMA20")
    return "; ".join(reasons) if reasons else ""


# ─────────────────────────────────────────────────────────────────────────
# Full pipeline for one stock
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class ConfluenceParams:
    expansion: ExpansionParams = field(default_factory=ExpansionParams)
    frvp: FRVPParams = field(default_factory=FRVPParams)
    ema: EMAParams = field(default_factory=EMAParams)
    vah_buffer_pct: float = 0.0
    require_two_closes_above_vah: bool = False
    min_score: int = MINIMUM_SCORE


def compute_confluence(df: pd.DataFrame, params: ConfluenceParams | None = None) -> pd.DataFrame:
    """df must have Open/High/Low/Close/Volume, ascending date index.
    Returns a copy with every column from the output schema attached."""
    p = params or ConfluenceParams()

    hm = add_indicators(df[["Open", "High", "Low", "Close", "Volume"]])
    hm = generate_signals(hm, min_score=70, confirmation_mode="Balanced")

    exp = compute_expansion(hm, p.expansion)
    frvp = attach_confirmed_frvp(exp, p.frvp)
    out = compute_ema_conditions(frvp, p.ema)

    vah_threshold = out["confirmed_vah"] * (1 + p.vah_buffer_pct / 100.0)
    price_above_vah = out["Close"] > vah_threshold
    if p.require_two_closes_above_vah:
        prev_vah_threshold = out["confirmed_vah"].shift(1) * (1 + p.vah_buffer_pct / 100.0)
        price_above_vah = price_above_vah & (out["Close"].shift(1) > prev_vah_threshold)
    out["price_above_vah"] = price_above_vah.fillna(False)

    out["signal_hm_only"] = out["hm_bullish_expansion"]
    out["signal_hm_trend"] = out["hm_bullish_expansion"] & out["ema20_rising"] & (out["Close"] > out["ema20"])
    out["signal_full_confluence"] = (
        out["hm_bullish_expansion"]
        & out["price_above_vah"]
        & out["ema20_rising"]
        & out["ema20_respected"]
        & (out["Close"] > out["ema20"])
        & (out["ema_distance_pct"] <= p.ema.max_close_above_ema_pct)
    )

    score = pd.Series(0.0, index=out.index)
    for col, weight in SCORE_WEIGHTS.items():
        score = score + out[col].fillna(False).astype(int) * weight
    out["confluence_score"] = score
    out["classification"] = score.apply(_classify)

    return out


def scan_stock(symbol: str, period: str = "2y", params: ConfluenceParams | None = None) -> dict | None:
    """Live/current-state scan for one stock. Never raises — returns None
    on any failure so a batch scan can't be brought down by one stock."""
    try:
        import yfinance as yf
        raw = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
        if raw is None or raw.empty or len(raw) < 320:
            return None
        if hasattr(raw.columns, "levels"):
            raw.columns = raw.columns.droplevel(1)
        raw = raw.rename(columns={c: c.title() for c in raw.columns})
        df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
        if len(df) < 320:
            return None

        out = compute_confluence(df, params)
        last = out.iloc[-1]

        return {
            "symbol": symbol.replace(".NS", ""),
            "signal_date": str(out.index[-1])[:10],
            "open": round(float(last["Open"]), 2), "high": round(float(last["High"]), 2),
            "low": round(float(last["Low"]), 2), "close": round(float(last["Close"]), 2),
            "volume": float(last["Volume"]),
            "white_line": round(float(last["white_line"]), 2) if pd.notna(last["white_line"]) else None,
            "green_line": round(float(last["green_line"]), 2) if pd.notna(last["green_line"]) else None,
            "red_line": round(float(last["red_line"]), 2) if pd.notna(last["red_line"]) else None,
            "oversold_origin": bool(last["oversold_origin"]),
            "oversold_origin_date": str(last["oversold_origin_date"])[:10] if pd.notna(last["oversold_origin_date"]) else None,
            "bars_since_oversold": float(last["bars_since_oversold"]) if pd.notna(last["bars_since_oversold"]) else None,
            "white_rising": bool(last["white_rising"]), "green_rising": bool(last["green_rising"]),
            "red_rising": bool(last["red_rising"]), "all_lines_rising": bool(last["all_lines_rising"]),
            "bullish_ordering": bool(last["bullish_ordering"]),
            "minimum_separation_met": bool(last["minimum_separation_met"]),
            "white_green_gap": round(float(last["white_green_gap"]), 3) if pd.notna(last["white_green_gap"]) else None,
            "green_red_gap": round(float(last["green_red_gap"]), 3) if pd.notna(last["green_red_gap"]) else None,
            "total_gap": round(float(last["total_gap"]), 3) if pd.notna(last["total_gap"]) else None,
            "gaps_expanding": bool(last["gaps_expanding"]),
            "lines_not_touching": bool(last["lines_not_touching"]),
            "white_slope": round(float(last["white_slope"]), 3) if pd.notna(last["white_slope"]) else None,
            "green_slope": round(float(last["green_slope"]), 3) if pd.notna(last["green_slope"]) else None,
            "red_slope": round(float(last["red_slope"]), 3) if pd.notna(last["red_slope"]) else None,
            "strong_upward_slopes": bool(last["strong_upward_slopes"]),
            "hm_bullish_expansion": bool(last["hm_bullish_expansion"]),
            "ema20": round(float(last["ema20"]), 2) if pd.notna(last["ema20"]) else None,
            "ema20_slope_pct": round(float(last["ema20_slope_pct"]), 3) if pd.notna(last["ema20_slope_pct"]) else None,
            "ema20_rising": bool(last["ema20_rising"]),
            "ema20_touched": bool(last["ema20_touched"]),
            "was_above_ema_before_pullback": bool(last["was_above_ema_before_pullback"]),
            "ema20_respected": bool(last["ema20_respected"]),
            "ema_distance_pct": round(float(last["ema_distance_pct"]), 3) if pd.notna(last["ema_distance_pct"]) else None,
            "confirmed_vah": round(float(last["confirmed_vah"]), 2) if pd.notna(last["confirmed_vah"]) else None,
            "confirmed_poc": round(float(last["confirmed_poc"]), 2) if pd.notna(last["confirmed_poc"]) else None,
            "confirmed_val": round(float(last["confirmed_val"]), 2) if pd.notna(last["confirmed_val"]) else None,
            "price_above_vah": bool(last["price_above_vah"]),
            "signal_hm_only": bool(last["signal_hm_only"]),
            "signal_hm_trend": bool(last["signal_hm_trend"]),
            "signal_full_confluence": bool(last["signal_full_confluence"]),
            "confluence_score": float(last["confluence_score"]),
            "classification": last["classification"],
            "rejection_reason": _rejection_reason(last),
        }
    except Exception:
        return None


def scan_universe(symbols: list[str], period: str = "2y", max_workers: int = 6,
                  params: ConfluenceParams | None = None) -> pd.DataFrame:
    rows = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(scan_stock, s, period, params): s for s in symbols}
        for fut in as_completed(futs):
            r = fut.result()
            if r is not None:
                rows.append(r)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("confluence_score", ascending=False).reset_index(drop=True)


def execution_summary(scan_df: pd.DataFrame, total_requested: int) -> dict:
    if scan_df.empty:
        return {"total_stocks_scanned": total_requested, "note": "no results"}
    return {
        "total_stocks_scanned": total_requested,
        "stocks_with_valid_data": len(scan_df),
        "stocks_with_oversold_origin": int(scan_df["oversold_origin"].sum()),
        "stocks_with_bullish_line_order": int(scan_df["bullish_ordering"].sum()),
        "stocks_with_all_lines_rising": int(scan_df["all_lines_rising"].sum()),
        "stocks_with_valid_separation": int(scan_df["minimum_separation_met"].sum()),
        "stocks_with_strong_slopes": int(scan_df["strong_upward_slopes"].sum()),
        "stocks_passing_hm_bullish_expansion": int(scan_df["hm_bullish_expansion"].sum()),
        "stocks_above_confirmed_vah": int(scan_df["price_above_vah"].sum()),
        "stocks_with_rising_ema20": int(scan_df["ema20_rising"].sum()),
        "stocks_respecting_ema20_pullback": int(scan_df["ema20_respected"].sum()),
        "stocks_passing_full_confluence": int(scan_df["signal_full_confluence"].sum()),
    }
