"""H-M Bullish Expansion pattern detector.

New pattern — does not exist in the Pine source or the site's existing
hm_indicators.py — built fresh per spec, using the site's already-faithful
H-M line columns (RSI=white, HM_EMA=green, HM_WMA=red, produced by
backend.calculations.hm_indicators.add_indicators()) as input.

Detects a bullish "expansion": the three momentum lines originate from an
oversold region, fan out in bullish order (white > green > red), all three
rise, the gaps between them are wide enough and not contracting, and the
slopes are strong — a materially stronger condition than a simple
white/green/red crossover.

Every intermediate boolean/numeric is emitted as its own column for
auditing — never collapse straight to the final signal.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ExpansionParams:
    # Oversold origin
    oversold_level: float = 9.0
    oversold_lookback: int = 10
    oversold_mode: str = "ANY_LINE"  # ANY_LINE | WHITE_ONLY | ALL_LINES | RSI_SOURCE

    # Ordering
    ordering_confirmation_bars: int = 2

    # Rising
    rising_confirmation_bars: int = 2

    # Separation
    min_white_green_gap: float = 0.50
    min_green_red_gap: float = 0.50
    min_total_gap: float = 1.25

    # Touch
    touch_tolerance: float = 0.25
    non_touch_confirmation_bars: int = 2

    # Gap expansion
    gap_expansion_mode: str = "STABLE_OR_EXPANDING"  # STRICT | TOTAL_ONLY | STABLE_OR_EXPANDING | DISABLED
    max_gap_contraction: float = 0.10

    # Slope
    slope_lookback: int = 3
    slope_mode: str = "ABSOLUTE"  # ABSOLUTE | NORMALIZED
    min_white_slope: float = 1.00
    min_green_slope: float = 0.60
    min_red_slope: float = 0.25
    require_slope_order: bool = False


def is_strictly_rising(series: pd.Series, bars: int) -> pd.Series:
    """current > previous > ... > (bars) bars ago, using only completed
    candles (no shift(0) — the caller's series is already as-of-close)."""
    if bars < 1:
        return pd.Series(True, index=series.index)
    cond = series > series.shift(1)
    for k in range(1, bars):
        cond = cond & (series.shift(k) > series.shift(k + 1))
    return cond.fillna(False)


def _held_for_bars(cond: pd.Series, bars: int) -> pd.Series:
    """cond has held True for `bars` consecutive completed candles ending now."""
    if bars <= 1:
        return cond.fillna(False)
    out = cond.copy()
    for k in range(1, bars):
        out = out & cond.shift(k)
    return out.fillna(False)


def compute_expansion(df: pd.DataFrame, params: ExpansionParams | None = None) -> pd.DataFrame:
    """df must already have RSI, HM_EMA, HM_WMA columns (from
    hm_indicators.add_indicators()). Returns a copy with every auditable
    expansion column plus the final hm_bullish_expansion boolean."""
    p = params or ExpansionParams()
    out = df.copy()

    white = out["RSI"]
    green = out["HM_EMA"]
    red = out["HM_WMA"]
    out["white_line"] = white
    out["green_line"] = green
    out["red_line"] = red

    # ── Oversold origin ─────────────────────────────────────────────────
    if p.oversold_mode == "WHITE_ONLY":
        touched = white <= p.oversold_level
    elif p.oversold_mode == "ALL_LINES":
        touched = (white <= p.oversold_level) & (green <= p.oversold_level) & (red <= p.oversold_level)
    elif p.oversold_mode == "RSI_SOURCE":
        touched = white <= p.oversold_level  # RSI is the raw source in this codebase
    else:  # ANY_LINE
        touched = (white <= p.oversold_level) | (green <= p.oversold_level) | (red <= p.oversold_level)

    touched_np = touched.to_numpy()
    n = len(out)
    oversold_origin = np.zeros(n, dtype=bool)
    bars_since = np.full(n, np.nan)
    origin_idx = np.full(n, -1, dtype=int)
    for i in range(n):
        lo = max(0, i - p.oversold_lookback)
        window = touched_np[lo:i + 1]
        hits = np.where(window)[0]
        if len(hits):
            most_recent = lo + hits[-1]
            oversold_origin[i] = True
            bars_since[i] = i - most_recent
            origin_idx[i] = most_recent
    out["oversold_origin"] = oversold_origin
    out["bars_since_oversold"] = bars_since
    out["oversold_origin_date"] = [out.index[o] if o >= 0 else None for o in origin_idx]

    # ── Bullish ordering (white > green > red), held N completed bars ────
    ordering_now = (white > green) & (green > red)
    out["bullish_ordering"] = _held_for_bars(ordering_now, p.ordering_confirmation_bars)

    # ── All lines rising ─────────────────────────────────────────────────
    out["white_rising"] = is_strictly_rising(white, p.rising_confirmation_bars)
    out["green_rising"] = is_strictly_rising(green, p.rising_confirmation_bars)
    out["red_rising"] = is_strictly_rising(red, p.rising_confirmation_bars)
    out["all_lines_rising"] = out["white_rising"] & out["green_rising"] & out["red_rising"]

    # ── Separation ───────────────────────────────────────────────────────
    wg_gap = white - green
    gr_gap = green - red
    tot_gap = white - red
    out["white_green_gap"] = wg_gap
    out["green_red_gap"] = gr_gap
    out["total_gap"] = tot_gap
    out["minimum_separation_met"] = (
        (wg_gap >= p.min_white_green_gap) & (gr_gap >= p.min_green_red_gap) & (tot_gap >= p.min_total_gap)
    )

    # ── Not touching (no exact equality; tolerance-based) ────────────────
    not_touching_now = (wg_gap.abs() >= p.touch_tolerance) & (gr_gap.abs() >= p.touch_tolerance)
    out["lines_not_touching"] = _held_for_bars(not_touching_now, p.non_touch_confirmation_bars)

    # ── Gap expansion ────────────────────────────────────────────────────
    wg_change = wg_gap - wg_gap.shift(1)
    gr_change = gr_gap - gr_gap.shift(1)
    tot_change = tot_gap - tot_gap.shift(1)
    out["white_green_gap_change"] = wg_change
    out["green_red_gap_change"] = gr_change
    out["total_gap_change"] = tot_change

    if p.gap_expansion_mode == "STRICT":
        gaps_expanding = (wg_change > 0) & (gr_change > 0) & (tot_change > 0)
    elif p.gap_expansion_mode == "TOTAL_ONLY":
        gaps_expanding = tot_change > 0
    elif p.gap_expansion_mode == "DISABLED":
        gaps_expanding = pd.Series(True, index=out.index)
    else:  # STABLE_OR_EXPANDING
        gaps_expanding = (
            (wg_gap >= wg_gap.shift(1) - p.max_gap_contraction)
            & (gr_gap >= gr_gap.shift(1) - p.max_gap_contraction)
            & (tot_gap > tot_gap.shift(1))
        )
    out["gaps_expanding"] = gaps_expanding.fillna(False)

    # ── Slope ────────────────────────────────────────────────────────────
    white_slope_raw = (white - white.shift(p.slope_lookback)) / p.slope_lookback
    green_slope_raw = (green - green.shift(p.slope_lookback)) / p.slope_lookback
    red_slope_raw = (red - red.shift(p.slope_lookback)) / p.slope_lookback

    if p.slope_mode == "NORMALIZED":
        white_std = white.rolling(20).std().replace(0, np.nan)
        green_std = green.rolling(20).std().replace(0, np.nan)
        red_std = red.rolling(20).std().replace(0, np.nan)
        white_slope = (white_slope_raw / white_std).fillna(0.0)
        green_slope = (green_slope_raw / green_std).fillna(0.0)
        red_slope = (red_slope_raw / red_std).fillna(0.0)
    else:
        white_slope, green_slope, red_slope = white_slope_raw, green_slope_raw, red_slope_raw

    out["white_slope"] = white_slope
    out["green_slope"] = green_slope
    out["red_slope"] = red_slope

    strong = (
        (white_slope >= p.min_white_slope) & (green_slope >= p.min_green_slope) & (red_slope >= p.min_red_slope)
    )
    if p.require_slope_order:
        strong = strong & (white_slope > green_slope) & (green_slope > red_slope)
    out["strong_upward_slopes"] = strong.fillna(False)

    # ── Final signal ─────────────────────────────────────────────────────
    out["hm_bullish_expansion"] = (
        out["oversold_origin"]
        & out["bullish_ordering"]
        & out["all_lines_rising"]
        & out["minimum_separation_met"]
        & out["lines_not_touching"]
        & out["gaps_expanding"]
        & out["strong_upward_slopes"]
    )

    return out
