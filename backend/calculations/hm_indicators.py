from __future__ import annotations

import numpy as np
import pandas as pd


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [c[0] if isinstance(c, tuple) else c for c in out.columns]
    out = out.rename(columns={c: c.title() for c in out.columns})
    keep = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in out.columns]
    out = out[keep]
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col not in out.columns:
            out[col] = np.nan
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    out.index = pd.to_datetime(out.index)
    return out


def rma(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def rsi_tv(close: pd.Series, length: int = 9) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    avg_up = rma(up, length)
    avg_down = rma(down, length)
    rs = avg_up / avg_down.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_down != 0, 100)
    rsi = rsi.where(avg_up != 0, 0)
    return rsi.clip(0, 100)


def wma(series: pd.Series, length: int = 21) -> pd.Series:
    weights = np.arange(1, length + 1, dtype=float)
    return series.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def ema(series: pd.Series, length: int = 3) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return rma(tr, length)


def bars_since(cond: pd.Series) -> pd.Series:
    idx = pd.Series(np.arange(len(cond)), index=cond.index)
    true_idx = idx.where(cond.fillna(False))
    last_true = true_idx.ffill()
    return idx - last_true


def attach_htf_regime(df: pd.DataFrame, htf_df: pd.DataFrame, prefix: str = "HTF") -> pd.DataFrame:
    out = df.copy()
    if htf_df is None or htf_df.empty or out.empty:
        return out
    htf_cols = htf_df[["HM_BUY_REGIME", "HM_SELL_REGIME"]].rename(
        columns={"HM_BUY_REGIME": f"{prefix}_BUY_REGIME", "HM_SELL_REGIME": f"{prefix}_SELL_REGIME"}
    )
    return pd.merge_asof(out, htf_cols, left_index=True, right_index=True, direction="backward")


def add_indicators(
    df: pd.DataFrame,
    rsi_len: int = 9,
    wma_len: int = 21,
    ema_len: int = 3,
    lookback_low: int = 80,
    short_lookback_low: int = 20,
    min_pullback_pct: float = 0.05,
) -> pd.DataFrame:
    out = normalize_ohlcv(df)
    if out.empty:
        return out

    out["RSI"] = rsi_tv(out["Close"], rsi_len)
    out["HM_WMA"] = wma(out["RSI"], wma_len)
    out["HM_EMA"] = ema(out["RSI"], ema_len)
    out["SMA20"] = out["Close"].rolling(20).mean()
    out["SMA50"] = out["Close"].rolling(50).mean()
    out["ATR14"] = atr(out, 14)
    out["VOL_MA20"] = out["Volume"].rolling(20).mean()
    out["VOL_RATIO"] = out["Volume"] / out["VOL_MA20"].replace(0, np.nan)
    out["RECENT_LOW"] = out["Low"].rolling(lookback_low).min()
    out["RECENT_HIGH"] = out["High"].rolling(lookback_low).max()
    out["RANGE_POS"] = (out["Close"] - out["RECENT_LOW"]) / (out["RECENT_HIGH"] - out["RECENT_LOW"]).replace(0, np.nan)

    short_low = out["Low"].rolling(short_lookback_low).min()
    short_high = out["High"].rolling(short_lookback_low).max()
    short_range_pos = (out["Close"] - short_low) / (short_high - short_low).replace(0, np.nan)
    short_pullback_pct = (short_high - short_low) / short_high
    qualifies_short = short_pullback_pct.shift(1) >= min_pullback_pct
    short_rally_pct = (short_high - short_low) / short_low
    qualifies_rally = short_rally_pct.shift(1) >= min_pullback_pct

    out["EMA_CROSS_WMA"] = (out["HM_EMA"] > out["HM_WMA"]) & (out["HM_EMA"].shift(1) <= out["HM_WMA"].shift(1))
    out["RSI_CROSS_50"] = (out["RSI"] > 50) & (out["RSI"].shift(1) <= 50)
    out["RSI_CROSS_WMA"] = (out["RSI"] > out["HM_WMA"]) & (out["RSI"].shift(1) <= out["HM_WMA"].shift(1))
    out["EMA_RISING"] = out["HM_EMA"] > out["HM_EMA"].shift(1)
    out["WMA_TURNING"] = out["HM_WMA"] > out["HM_WMA"].shift(1)
    out["RSI_SLOPE_UP"] = out["RSI"] > out["RSI"].shift(2)
    out["PRICE_RECOVERY"] = (out["Close"] > out["SMA20"]) | (out["Close"] > out["High"].shift(1))
    out["ABOVE_50_SMA"] = out["Close"] > out["SMA50"]

    trail_low3 = out["Low"].rolling(3).min()
    long_low_test = (trail_low3 <= out["RECENT_LOW"].shift(1) * 1.03) | (out["RANGE_POS"] <= 0.35)
    short_low_test = (trail_low3 <= short_low.shift(1) * 1.03) & qualifies_short
    out["LOW_TEST"] = long_low_test | short_low_test

    long_no_chase = out["RANGE_POS"] <= 0.55
    short_no_chase = (short_range_pos <= 0.55) & qualifies_short
    out["NO_CHASE"] = long_no_chase | short_no_chase

    out["OVERSOLD_MEMORY"] = out["RSI"].rolling(20).min() <= 38
    out["HM_COMPRESSION"] = (out["HM_WMA"].rolling(10).max() - out["HM_WMA"].rolling(10).min()) <= 18

    out["HM_BUY_REGIME"] = out["RSI"] > out["HM_WMA"]
    out["HM_SELL_REGIME"] = out["RSI"] < out["HM_WMA"]

    out["BULL_CANDLE_CONFIRM"] = out["Close"] > out["High"].shift(1)
    out["BEAR_CANDLE_CONFIRM"] = out["Close"] < out["Low"].shift(1)

    out["EMA_CROSS_DOWN_WMA"] = (out["HM_EMA"] < out["HM_WMA"]) & (out["HM_EMA"].shift(1) >= out["HM_WMA"].shift(1))
    out["RSI_CROSS_50_DOWN"] = (out["RSI"] < 50) & (out["RSI"].shift(1) >= 50)
    out["RSI_CROSS_DOWN_WMA"] = (out["RSI"] < out["HM_WMA"]) & (out["RSI"].shift(1) >= out["HM_WMA"].shift(1))
    out["EMA_FALLING"] = out["HM_EMA"] < out["HM_EMA"].shift(1)
    out["WMA_TURNING_DOWN"] = out["HM_WMA"] < out["HM_WMA"].shift(1)
    out["RSI_SLOPE_DOWN"] = out["RSI"] < out["RSI"].shift(2)
    out["PRICE_WEAKNESS"] = (out["Close"] < out["SMA20"]) | (out["Close"] < out["Low"].shift(1))

    trail_high3 = out["High"].rolling(3).max()
    long_high_test = (trail_high3 >= out["RECENT_HIGH"].shift(1) * 0.97) | (out["RANGE_POS"] >= 0.65)
    short_high_test = (trail_high3 >= short_high.shift(1) * 0.97) & qualifies_rally
    out["HIGH_TEST"] = long_high_test | short_high_test

    long_no_dump = out["RANGE_POS"] >= 0.45
    short_no_dump = (short_range_pos >= 0.45) & qualifies_rally
    out["NO_DUMP"] = long_no_dump | short_no_dump

    out["OVERBOUGHT_MEMORY"] = out["RSI"].rolling(20).max() >= 62
    return out


def bottom_score(row: pd.Series) -> float:
    score = 0.0
    checks = {
        "oversold_memory": bool(row.get("OVERSOLD_MEMORY", False)),
        "hm_cross": bool(row.get("EMA_CROSS_WMA", False) or row.get("RSI_CROSS_WMA", False) or row.get("RSI_CROSS_50", False)),
        "rsi_reclaim": float(row.get("RSI", 0) or 0) >= 45,
        "ema_rising": bool(row.get("EMA_RISING", False)),
        "rsi_slope_up": bool(row.get("RSI_SLOPE_UP", False)),
        "wma_turning": bool(row.get("WMA_TURNING", False)),
        "near_bottom": bool(row.get("LOW_TEST", False)),
        "price_recovery": bool(row.get("PRICE_RECOVERY", False)),
        "volume_ok": float(row.get("VOL_RATIO", 0) or 0) >= 0.75,
    }
    weights = {
        "oversold_memory": 15, "hm_cross": 20, "rsi_reclaim": 10,
        "ema_rising": 10, "rsi_slope_up": 10, "wma_turning": 10,
        "near_bottom": 15, "price_recovery": 5, "volume_ok": 5,
    }
    for k, ok in checks.items():
        if ok:
            score += weights[k]
    return min(score, 100)


def top_score(row: pd.Series) -> float:
    score = 0.0
    checks = {
        "overbought_memory": bool(row.get("OVERBOUGHT_MEMORY", False)),
        "hm_cross_down": bool(row.get("EMA_CROSS_DOWN_WMA", False) or row.get("RSI_CROSS_DOWN_WMA", False) or row.get("RSI_CROSS_50_DOWN", False)),
        "rsi_reject": float(row.get("RSI", 100) or 100) <= 55,
        "ema_falling": bool(row.get("EMA_FALLING", False)),
        "rsi_slope_down": bool(row.get("RSI_SLOPE_DOWN", False)),
        "wma_turning_down": bool(row.get("WMA_TURNING_DOWN", False)),
        "near_top": bool(row.get("HIGH_TEST", False)),
        "price_weakness": bool(row.get("PRICE_WEAKNESS", False)),
        "volume_ok": float(row.get("VOL_RATIO", 0) or 0) >= 0.75,
    }
    weights = {
        "overbought_memory": 15, "hm_cross_down": 20, "rsi_reject": 10,
        "ema_falling": 10, "rsi_slope_down": 10, "wma_turning_down": 10,
        "near_top": 15, "price_weakness": 5, "volume_ok": 5,
    }
    for k, ok in checks.items():
        if ok:
            score += weights[k]
    return min(score, 100)


def generate_signals(
    df: pd.DataFrame,
    min_score: int = 70,
    confirmation_mode: str = "Balanced",
    bottom_rsi_min: float = 39.0,
    use_bottom_rsi_max: bool = True,
    bottom_rsi_max: float = 55.0,
    use_top_rsi_min: bool = True,
    top_rsi_min: float = 55.0,
    use_top_rsi_max: bool = False,
    top_rsi_max: float = 80.0,
    use_regime_filter: bool = True,
    use_candle_confirm: bool = True,
    use_price_filter: bool = True,
    use_volume_filter: bool = False,
    early_volume_ratio_min: float = 0.85,
    use_trend_exhaustion_filter: bool = True,
    use_no_chase_filter: bool = True,
    use_htf_filter: bool = False,
    use_htf2_filter: bool = False,
    cooldown_bars: int = 5,
) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        return out
    out["BOTTOM_SCORE"] = out.apply(bottom_score, axis=1)

    exhaustion_gate = (not use_trend_exhaustion_filter) | out["OVERSOLD_MEMORY"]
    no_chase_gate = (not use_no_chase_filter) | out["NO_CHASE"]
    regime_gate = (not use_regime_filter) | out["HM_BUY_REGIME"]
    vol_ratio = out["VOL_RATIO"].fillna(0)
    volume_gate = (not use_volume_filter) | (vol_ratio >= early_volume_ratio_min)
    bottom_rsi_gate = (out["RSI"] >= bottom_rsi_min) & ((not use_bottom_rsi_max) | (out["RSI"] <= bottom_rsi_max))
    htf_bottom_gate = (not use_htf_filter) | out.get("HTF_BUY_REGIME", pd.Series(True, index=out.index)).fillna(True)
    htf2_bottom_gate = (not use_htf2_filter) | out.get("HTF2_BUY_REGIME", pd.Series(True, index=out.index)).fillna(True)

    early = (
        exhaustion_gate & (out["EMA_CROSS_WMA"] | out["RSI_CROSS_WMA"] | out["RSI_CROSS_50"] | out["WMA_TURNING"])
        & out["EMA_RISING"] & out["RSI_SLOPE_UP"] & out["LOW_TEST"]
        & no_chase_gate & regime_gate & bottom_rsi_gate & volume_gate
        & htf_bottom_gate & htf2_bottom_gate
    )

    price_ok = (not use_price_filter) | out["PRICE_RECOVERY"]
    candle_ok = (not use_candle_confirm) | out["BULL_CANDLE_CONFIRM"]
    balanced = early & price_ok & candle_ok & ((out["RSI"] > 50) | out["RSI_CROSS_50"] | out["WMA_TURNING"])

    strict = (
        balanced & (out["RSI"] >= 48) & (out["Close"] > out["SMA20"])
        & out["BULL_CANDLE_CONFIRM"] & (vol_ratio >= 0.85)
    )

    mode = confirmation_mode.lower()
    if mode.startswith("early"):
        base = early
    elif mode.startswith("strict"):
        base = strict
    else:
        base = balanced

    if cooldown_bars and cooldown_bars > 0:
        bars_since_raw = bars_since(base.shift(1, fill_value=False))
        cooldown_ok = bars_since_raw.isna() | (bars_since_raw > cooldown_bars)
    else:
        cooldown_ok = True

    out["BOTTOM_RAW"] = base
    out["BOTTOM_SIGNAL"] = base & (out["BOTTOM_SCORE"] >= min_score) & cooldown_ok
    reason_parts = []
    for _, r in out.iterrows():
        parts = []
        if bool(r.get("OVERSOLD_MEMORY", False)):
            parts.append("oversold-memory")
        if bool(r.get("EMA_CROSS_WMA", False)):
            parts.append("EMA3>WMA21")
        if bool(r.get("RSI_CROSS_WMA", False)):
            parts.append("RSI>WMA21")
        if bool(r.get("RSI_CROSS_50", False)):
            parts.append("RSI>50")
        if bool(r.get("LOW_TEST", False)):
            parts.append("near-recent-low")
        if bool(r.get("PRICE_RECOVERY", False)):
            parts.append("price-recovery")
        reason_parts.append(", ".join(parts))
    out["SIGNAL_REASON"] = reason_parts

    out["TOP_SCORE"] = out.apply(top_score, axis=1)

    top_exhaustion_gate = (not use_trend_exhaustion_filter) | out["OVERBOUGHT_MEMORY"]
    top_no_dump_gate = (not use_no_chase_filter) | out["NO_DUMP"]
    top_regime_gate = (not use_regime_filter) | out["HM_SELL_REGIME"]
    top_volume_gate = (not use_volume_filter) | (vol_ratio >= early_volume_ratio_min)
    top_rsi_gate = ((not use_top_rsi_min) | (out["RSI"] >= top_rsi_min)) & ((not use_top_rsi_max) | (out["RSI"] <= top_rsi_max))
    htf_top_gate = (not use_htf_filter) | out.get("HTF_SELL_REGIME", pd.Series(True, index=out.index)).fillna(True)
    htf2_top_gate = (not use_htf2_filter) | out.get("HTF2_SELL_REGIME", pd.Series(True, index=out.index)).fillna(True)

    top_early = (
        top_exhaustion_gate & (out["EMA_CROSS_DOWN_WMA"] | out["RSI_CROSS_DOWN_WMA"] | out["RSI_CROSS_50_DOWN"] | out["WMA_TURNING_DOWN"])
        & out["EMA_FALLING"] & out["RSI_SLOPE_DOWN"] & out["HIGH_TEST"]
        & top_no_dump_gate & top_regime_gate & top_rsi_gate & top_volume_gate
        & htf_top_gate & htf2_top_gate
    )

    top_price_ok = (not use_price_filter) | out["PRICE_WEAKNESS"]
    top_candle_ok = (not use_candle_confirm) | out["BEAR_CANDLE_CONFIRM"]
    top_balanced = top_early & top_price_ok & top_candle_ok & ((out["RSI"] < 50) | out["RSI_CROSS_50_DOWN"] | out["WMA_TURNING_DOWN"])
    top_strict = top_balanced & (out["RSI"] < 50) & (out["Close"] < out["SMA20"]) & out["BEAR_CANDLE_CONFIRM"]

    if mode.startswith("early"):
        top_base = top_early
    elif mode.startswith("strict"):
        top_base = top_strict
    else:
        top_base = top_balanced

    if cooldown_bars and cooldown_bars > 0:
        top_bars_since_raw = bars_since(top_base.shift(1, fill_value=False))
        top_cooldown_ok = top_bars_since_raw.isna() | (top_bars_since_raw > cooldown_bars)
    else:
        top_cooldown_ok = True

    out["TOP_RAW"] = top_base
    out["TOP_SIGNAL"] = top_base & (out["TOP_SCORE"] >= min_score) & top_cooldown_ok
    top_reason_parts = []
    for _, r in out.iterrows():
        parts = []
        if bool(r.get("OVERBOUGHT_MEMORY", False)):
            parts.append("overbought-memory")
        if bool(r.get("EMA_CROSS_DOWN_WMA", False)):
            parts.append("EMA3<WMA21")
        if bool(r.get("RSI_CROSS_DOWN_WMA", False)):
            parts.append("RSI<WMA21")
        if bool(r.get("RSI_CROSS_50_DOWN", False)):
            parts.append("RSI<50")
        if bool(r.get("HIGH_TEST", False)):
            parts.append("near-recent-high")
        if bool(r.get("PRICE_WEAKNESS", False)):
            parts.append("price-weakness")
        top_reason_parts.append(", ".join(parts))
    out["TOP_SIGNAL_REASON"] = top_reason_parts
    return out
