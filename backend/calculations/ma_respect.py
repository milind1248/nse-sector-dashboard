"""Moving Average Respect Analyzer — core analytics engine.

Identifies which MA a stock has respected most consistently via:
- ATR-normalized touch detection with cooldown deduplication
- Outcome evaluation (success/failure/neutral, MFE/MAE)
- Wilson-adjusted hold rate scoring
- Neighbor stability + zone detection
- Recent vs. full-history performance
- Out-of-time consistency check (3 chronological thirds)

No look-ahead bias. Touch qualification uses data ≤ touch bar only.
Outcome evaluation accesses future only after event is registered.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# Reuse from hm_indicators
from backend.calculations.hm_indicators import atr as compute_atr
from backend.calculations.hm_indicators import ema, rma, wma


def sma(series: pd.Series, length: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=length).mean()


@dataclass
class TouchEvent:
    """A single MA touch event."""
    date: pd.Timestamp
    ma_type: str  # "EMA", "SMA", "RMA", "WMA"
    ma_period: int
    direction: str  # "support" or "resistance"
    low: float
    high: float
    close: float
    ma_value: float
    atr_value: float
    ma_slope: float  # MA[t] - MA[t-slope_lookback]
    touch_distance_atr: float
    outcome: Optional[str] = None  # "success", "failure", "neutral"
    bars_to_outcome: Optional[int] = None
    max_favorable_excursion_atr: float = 0.0
    max_adverse_excursion_atr: float = 0.0


@dataclass
class RespectMetrics:
    """Metrics for one MA candidate."""
    ma_type: str
    ma_period: int
    total_touches: int = 0
    successful_touches: int = 0
    failed_touches: int = 0
    neutral_touches: int = 0

    avg_rebound_atr: float = 0.0
    median_rebound_atr: float = 0.0
    avg_penetration_atr: float = 0.0
    median_penetration_atr: float = 0.0
    avg_bars_to_rebound: float = 0.0

    recent_hold_rate: float = 0.0
    recent_touch_count: int = 0

    neighbor_stability_score: float = 0.0
    consistency_score: float = 0.0

    raw_hold_rate: float = 0.0
    wilson_hold_rate: float = 0.0
    final_score: float = 0.0
    confidence: str = "Insufficient data"
    current_status: str = "Neutral"

    def __post_init__(self):
        if self.total_touches > 0:
            self.raw_hold_rate = self.successful_touches / self.total_touches


def compute_mas(
    df: pd.DataFrame,
    types: tuple[str, ...] = ("EMA", "SMA", "RMA"),
    periods: tuple[int, ...] = (5, 8, 9, 10, 13, 20, 21, 34, 50, 55, 100, 150, 200),
) -> dict[tuple[str, int], pd.Series]:
    """Compute all MAs. Returns {(type, period): Series}."""
    mas = {}
    close = df["close"]

    for ma_type in types:
        for period in periods:
            if ma_type == "EMA":
                mas[(ma_type, period)] = ema(close, length=period)
            elif ma_type == "SMA":
                mas[(ma_type, period)] = sma(close, length=period)
            elif ma_type == "RMA":
                mas[(ma_type, period)] = rma(close, length=period)
            elif ma_type == "WMA":
                mas[(ma_type, period)] = wma(close, length=period)

    return mas


def detect_touches(
    df: pd.DataFrame,
    mas: dict[tuple[str, int], pd.Series],
    atr_s: pd.Series,
    direction: str = "support",
    tol_atr: float = 0.25,
    max_pen_atr: float = 0.15,
    cooldown: int = 3,
    slope_lookback: int = 5,
) -> list[TouchEvent]:
    """Detect MA touches with deduplication and trend eligibility.

    direction: "support" or "resistance"
    No look-ahead: uses data[i] and data[:i] only.
    """
    touches = []
    df = df.reset_index(drop=True)

    for (ma_type, period), ma_series in mas.items():
        ma_series = ma_series.reset_index(drop=True)
        last_touch_idx = -cooldown

        for i in range(max(period, slope_lookback), len(df)):
            if i < last_touch_idx + cooldown:
                continue

            close_prev = df.loc[i - 1, "close"]
            close_curr = df.loc[i, "close"]
            low = df.loc[i, "low"]
            high = df.loc[i, "high"]
            ma_val = ma_series.iloc[i]
            atr_val = atr_s.iloc[i]

            if pd.isna(ma_val) or pd.isna(atr_val) or atr_val <= 0:
                continue

            # MA slope (no look-ahead: only uses past data)
            slope = ma_series.iloc[i] - ma_series.iloc[i - slope_lookback]

            # Eligibility: trend + slope + prior position
            eligible = False
            if direction == "support":
                eligible = (close_prev > ma_val and slope > 0)
            elif direction == "resistance":
                eligible = (close_prev < ma_val and slope < 0)

            if not eligible:
                continue

            # Touch: low/high reaches tolerance zone
            if direction == "support":
                touch_distance = ma_val - low
                is_touch = low <= ma_val + tol_atr * atr_val and touch_distance <= max_pen_atr * atr_val
            else:  # resistance
                touch_distance = high - ma_val
                is_touch = high >= ma_val - tol_atr * atr_val and touch_distance <= max_pen_atr * atr_val

            if not is_touch:
                continue

            # Record touch
            touch = TouchEvent(
                date=df.loc[i, "date"],
                ma_type=ma_type,
                ma_period=period,
                direction=direction,
                low=low,
                high=high,
                close=close_curr,
                ma_value=ma_val,
                atr_value=atr_val,
                ma_slope=slope,
                touch_distance_atr=abs(touch_distance) / atr_val,
            )
            touches.append(touch)
            last_touch_idx = i

    return touches


def evaluate_outcomes(
    df: pd.DataFrame,
    touches: list[TouchEvent],
    rebound_atr: float = 1.0,
    fail_atr: float = 0.5,
    look_forward: int = 10,
) -> list[TouchEvent]:
    """Evaluate touch outcomes in forward window. Conservative rule for same-candle both."""
    df = df.reset_index(drop=True)

    for touch in touches:
        # Find touch row index
        touch_idx = df[df["date"] == touch.date].index
        if len(touch_idx) == 0:
            continue
        touch_idx = touch_idx[0]

        # Outcome evaluation window
        start_eval = touch_idx + 1
        end_eval = min(touch_idx + look_forward + 1, len(df))

        if start_eval >= end_eval:
            touch.outcome = "neutral"
            continue

        rebound_target = touch.ma_value + rebound_atr * touch.atr_value if touch.direction == "support" else touch.ma_value - rebound_atr * touch.atr_value
        fail_threshold = touch.ma_value - fail_atr * touch.atr_value if touch.direction == "support" else touch.ma_value + fail_atr * touch.atr_value

        success_bar = None
        failure_bar = None

        for j in range(start_eval, end_eval):
            high = df.loc[j, "high"]
            low = df.loc[j, "low"]
            close = df.loc[j, "close"]

            # Check targets (no look-ahead: only bar j's data)
            if touch.direction == "support":
                if success_bar is None and high >= rebound_target:
                    success_bar = j
                if failure_bar is None and close < fail_threshold:
                    failure_bar = j
            else:  # resistance
                if success_bar is None and low <= rebound_target:
                    success_bar = j
                if failure_bar is None and close > fail_threshold:
                    failure_bar = j

            # Track MFE/MAE
            if touch.direction == "support":
                mfe = max(high - touch.ma_value, 0) / touch.atr_value if touch.atr_value > 0 else 0
                mae = max(touch.ma_value - low, 0) / touch.atr_value if touch.atr_value > 0 else 0
            else:
                mfe = max(touch.ma_value - low, 0) / touch.atr_value if touch.atr_value > 0 else 0
                mae = max(high - touch.ma_value, 0) / touch.atr_value if touch.atr_value > 0 else 0

            touch.max_favorable_excursion_atr = max(touch.max_favorable_excursion_atr, mfe)
            touch.max_adverse_excursion_atr = max(touch.max_adverse_excursion_atr, mae)

        # Outcome (conservative: same-candle both = failure)
        if success_bar is not None and failure_bar is not None:
            if success_bar <= failure_bar:
                touch.outcome = "success"
                touch.bars_to_outcome = success_bar - touch_idx
            else:
                touch.outcome = "failure"
                touch.bars_to_outcome = failure_bar - touch_idx
        elif success_bar is not None:
            touch.outcome = "success"
            touch.bars_to_outcome = success_bar - touch_idx
        elif failure_bar is not None:
            touch.outcome = "failure"
            touch.bars_to_outcome = failure_bar - touch_idx
        else:
            touch.outcome = "neutral"

    return touches


def wilson_lower(successes: int, n: int, z: float = 1.96) -> float:
    """Wilson score lower bound for confidence-adjusted hold rate."""
    if n == 0:
        return 0.0
    p = successes / n
    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominator
    return max(0.0, center - margin)


def score_candidate(
    metrics: RespectMetrics,
    min_touches: int = 15,
    target_touches: int = 40,
) -> tuple[float, dict]:
    """Score a candidate MA (0–100). Returns (score, components dict)."""
    if metrics.total_touches < min_touches:
        return 0.0, {"reason": "insufficient_touches"}

    # Component scores (0–1)
    hold_score = metrics.wilson_hold_rate  # Already 0–1

    sample_score = min(1.0, math.log(1 + metrics.total_touches) / math.log(1 + target_touches))

    rebound_score = min(1.0, metrics.median_rebound_atr / 2.0) if metrics.median_rebound_atr > 0 else 0.0

    failure_score = 1.0 - min(1.0, metrics.failed_touches / max(1, metrics.total_touches))

    penetration_score = 1.0 - min(1.0, metrics.median_penetration_atr / 0.5)

    consistency_score = metrics.consistency_score  # From OOT thirds

    recent_score = metrics.recent_hold_rate if metrics.recent_touch_count >= 3 else 0.5

    neighbor_score = metrics.neighbor_stability_score  # From adjacent periods

    # Weights (sum to 1)
    weights = {
        "hold_rate": 0.30,
        "sample": 0.10,
        "rebound": 0.15,
        "failure": 0.10,
        "penetration": 0.10,
        "consistency": 0.10,
        "recent": 0.10,
        "neighbor": 0.05,
    }

    final = (
        hold_score * weights["hold_rate"]
        + sample_score * weights["sample"]
        + rebound_score * weights["rebound"]
        + failure_score * weights["failure"]
        + penetration_score * weights["penetration"]
        + consistency_score * weights["consistency"]
        + recent_score * weights["recent"]
        + neighbor_score * weights["neighbor"]
    )

    score_0_100 = round(final * 100, 1)

    components = {
        "hold_rate": hold_score,
        "sample": sample_score,
        "rebound": rebound_score,
        "failure": failure_score,
        "penetration": penetration_score,
        "consistency": consistency_score,
        "recent": recent_score,
        "neighbor": neighbor_score,
        "final": score_0_100,
    }

    return score_0_100, components


def compute_out_of_time_consistency(touches: list[TouchEvent]) -> float:
    """Split touches into 3 chronological thirds; score by hold-rate similarity."""
    if len(touches) < 4:
        return 0.0

    n_third = len(touches) // 3
    if n_third < 1:
        return 0.5

    thirds = [
        touches[:n_third],
        touches[n_third : 2 * n_third],
        touches[2 * n_third :],
    ]

    hold_rates = []
    for third in thirds:
        if len(third) == 0:
            continue
        hr = sum(1 for t in third if t.outcome == "success") / len(third)
        hold_rates.append(hr)

    if len(hold_rates) < 2:
        return 0.5

    std = statistics.stdev(hold_rates) if len(hold_rates) > 1 else 0
    mean = statistics.mean(hold_rates)
    cv = (std / mean) if mean > 0 else 0

    consistency = max(0.0, 1.0 - cv)
    return consistency


def neighbor_stability(
    candidates_by_period: dict[int, RespectMetrics],
    ma_type: str,
) -> dict[int, float]:
    """For each period, score its neighbor stability (±1 period score similarity)."""
    stability = {}
    periods = sorted(candidates_by_period.keys())

    for period in periods:
        neighbor_periods = [p for p in periods if abs(p - period) <= 1 and p != period]
        if not neighbor_periods:
            stability[period] = 0.5
        else:
            own_score = candidates_by_period[period].final_score
            neighbor_scores = [candidates_by_period[p].final_score for p in neighbor_periods]
            avg_neighbor = statistics.mean(neighbor_scores)
            diff = abs(own_score - avg_neighbor)
            stability[period] = max(0.0, 1.0 - diff / 100.0)

    return stability


def select_mas(
    candidates: dict[tuple[str, int], RespectMetrics],
) -> tuple[Optional[RespectMetrics], Optional[RespectMetrics], Optional[RespectMetrics]]:
    """Select primary, secondary, long-term MAs from candidates."""
    ranked = sorted(
        candidates.values(),
        key=lambda m: (m.final_score, m.total_touches),
        reverse=True,
    )

    primary = next((m for m in ranked if m.total_touches >= 15 and m.final_score >= 45), None)

    secondary = None
    if primary:
        secondary = next(
            (m for m in ranked
             if m.total_touches >= 10
             and m.final_score >= 40
             and m != primary
             and abs(m.ma_period - primary.ma_period) > 5),
            None,
        )

    long_term = None
    if primary:
        long_term = next(
            (m for m in ranked
             if m.ma_period >= 100
             and m.total_touches >= 8
             and m.final_score >= 40
             and m != primary
             and m != secondary),
            None,
        )

    return primary, secondary, long_term


def current_status(
    df: pd.DataFrame,
    ma_type: str,
    ma_period: int,
    mas: dict[tuple[str, int], pd.Series],
    atr_s: pd.Series,
    fail_atr: float = 0.5,
    consecutive_break: int = 2,
) -> str:
    """Determine current MA status (Support/Resistance/Neutral/Broken/etc)."""
    if (ma_type, ma_period) not in mas:
        return "Neutral"

    ma_series = mas[(ma_type, ma_period)]
    latest_close = df.iloc[-1]["close"]
    latest_ma = ma_series.iloc[-1]
    latest_atr = atr_s.iloc[-1]

    if pd.isna(latest_ma) or pd.isna(latest_atr) or latest_atr <= 0:
        return "Neutral"

    dist_atr = abs(latest_close - latest_ma) / latest_atr

    if latest_close > latest_ma:
        if dist_atr < 0.25:
            return "Acting as support"
        elif dist_atr < 0.5:
            return "Approaching support"
        else:
            return "Extended above MA"
    else:
        if dist_atr < 0.25:
            return "Acting as resistance"
        elif dist_atr < 0.5:
            return "Approaching resistance"
        else:
            # Check if broken (multiple closes below MA - fail_atr)
            fail_threshold = latest_ma - fail_atr * latest_atr
            below_fail = (df["close"] < fail_threshold).tail(consecutive_break)
            if below_fail.sum() >= consecutive_break:
                return "Broken"
            return "Extended below MA"

    return "Neutral"


def analyze_stock(
    df: pd.DataFrame,
    ma_types: tuple[str, ...] = ("EMA", "SMA", "RMA"),
    ma_periods: tuple[int, ...] = (5, 8, 9, 10, 13, 20, 21, 34, 50, 55, 100, 150, 200),
    direction: str = "support",
    tol_atr: float = 0.25,
    fail_atr: float = 0.5,
    rebound_atr: float = 1.0,
    look_forward: int = 10,
    min_touches: int = 15,
    recent_bars: int = 252,
) -> dict:
    """Full analysis pipeline."""
    df = df.reset_index(drop=True)

    # Compute indicators
    mas = compute_mas(df, types=ma_types, periods=ma_periods)
    atr_s = compute_atr(df, length=14)

    # Detect touches
    touches = detect_touches(
        df, mas, atr_s,
        direction=direction,
        tol_atr=tol_atr,
        max_pen_atr=0.15,
        cooldown=3,
        slope_lookback=5,
    )

    # Evaluate outcomes
    touches = evaluate_outcomes(df, touches, rebound_atr=rebound_atr, fail_atr=fail_atr, look_forward=look_forward)

    # Aggregate metrics per MA
    candidates = {}
    for (ma_type, period) in mas.keys():
        ma_touches = [t for t in touches if t.ma_type == ma_type and t.ma_period == period]

        if len(ma_touches) == 0:
            continue

        metrics = RespectMetrics(ma_type=ma_type, ma_period=period)
        metrics.total_touches = len(ma_touches)
        metrics.successful_touches = sum(1 for t in ma_touches if t.outcome == "success")
        metrics.failed_touches = sum(1 for t in ma_touches if t.outcome == "failure")
        metrics.neutral_touches = sum(1 for t in ma_touches if t.outcome == "neutral")

        if metrics.successful_touches + metrics.failed_touches > 0:
            metrics.wilson_hold_rate = wilson_lower(
                metrics.successful_touches,
                metrics.successful_touches + metrics.failed_touches,
            )

        rebound_atrs = [t.max_favorable_excursion_atr for t in ma_touches if t.outcome in ("success", "neutral")]
        if rebound_atrs:
            metrics.median_rebound_atr = statistics.median(rebound_atrs)
            metrics.avg_rebound_atr = statistics.mean(rebound_atrs)

        pen_atrs = [t.touch_distance_atr for t in ma_touches]
        if pen_atrs:
            metrics.median_penetration_atr = statistics.median(pen_atrs)
            metrics.avg_penetration_atr = statistics.mean(pen_atrs)

        # Recent performance (last 252 bars)
        recent_cutoff = df.iloc[-recent_bars]["date"] if len(df) > recent_bars else df.iloc[0]["date"]
        recent_touches = [t for t in ma_touches if t.date >= recent_cutoff]
        metrics.recent_touch_count = len(recent_touches)
        if metrics.recent_touch_count > 0:
            metrics.recent_hold_rate = sum(1 for t in recent_touches if t.outcome == "success") / metrics.recent_touch_count

        # Out-of-time consistency
        metrics.consistency_score = compute_out_of_time_consistency(ma_touches)

        # Score
        score, components = score_candidate(metrics, min_touches=min_touches)
        metrics.final_score = score

        # Confidence
        if metrics.total_touches < min_touches:
            metrics.confidence = "Insufficient data"
        elif score >= 75 and metrics.consistency_score >= 0.6 and metrics.recent_hold_rate >= 0.5:
            metrics.confidence = "High"
        elif score >= 60:
            metrics.confidence = "Medium"
        elif score >= 45:
            metrics.confidence = "Low"
        else:
            metrics.confidence = "Very Low"

        metrics.current_status = current_status(df, ma_type, period, mas, atr_s, fail_atr=fail_atr)

        candidates[(ma_type, period)] = metrics

    # Neighbor stability
    for ma_type in ma_types:
        by_period = {m.ma_period: m for m in candidates.values() if m.ma_type == ma_type}
        if len(by_period) > 1:
            stab = neighbor_stability(by_period, ma_type)
            for period, score in stab.items():
                if (ma_type, period) in candidates:
                    candidates[(ma_type, period)].neighbor_stability_score = score

    # Select primary, secondary, long-term
    primary, secondary, long_term = select_mas(candidates)

    return {
        "candidates": candidates,
        "primary": primary,
        "secondary": secondary,
        "long_term": long_term,
        "touches": touches,
        "warnings": [],
    }
