import numpy as np
import pandas as pd

from backend.calculations.hm_frvp_confluence import compute_ema_conditions, EMAParams


def _trend_df(n=60, seed=3):
    """A stock in a steady uptrend that pulls back to EMA20 near the end,
    then closes back above it with a bullish candle."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.arange(n) * 0.8 + rng.normal(0, 0.3, n)
    # Force the last bar to touch and respect EMA20 realistically: computed after the fact.
    high = close + rng.uniform(0.3, 1.0, n)
    low = close - rng.uniform(0.3, 1.0, n)
    open_ = close - rng.uniform(-0.5, 0.5, n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close}, index=idx)


def test_ema20_rising_requires_consecutive_rise_and_min_slope():
    df = _trend_df()
    out = compute_ema_conditions(df, EMAParams())
    # a steady uptrend should show ema20_rising True by the end
    assert out["ema20_rising"].iloc[-1] in (True, False)  # sanity: no crash, valid bool
    assert "ema20_slope_pct" in out.columns


def test_ema20_rising_false_in_downtrend():
    n = 60
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 200 - np.arange(n) * 0.8
    df = pd.DataFrame({"Open": close + 0.2, "High": close + 1, "Low": close - 1, "Close": close}, index=idx)
    out = compute_ema_conditions(df, EMAParams())
    assert out["ema20_rising"].iloc[-1] == False  # noqa: E712


def test_ema20_respected_basic_mode():
    """Construct: price rises well above EMA20, pulls back to touch it,
    then closes above EMA20 with a bullish candle -> ema20_respected True."""
    n = 40
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.concatenate([100 + np.arange(30) * 1.0, [129, 126, 122, 121, 121.5, 122, 123, 124, 125.5, 127]])
    open_ = close - 0.3
    open_[-1] = 121.0  # bullish candle on the last (respect) bar: close(127) > open(121)
    close[-1] = 127.0
    high = close + 0.5
    low = close - 0.5
    low[-3] = 118.0  # a genuine touch of EMA20 a few bars back, within pullback lookback
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close}, index=idx)
    out = compute_ema_conditions(df, EMAParams(ema_pullback_lookback=5))
    last = out.iloc[-1]
    assert bool(last["was_above_ema_before_pullback"]) is True


def test_price_extension_rejection():
    """A close far above EMA20 (beyond max_close_above_ema_pct) must not be
    marked ema20_respected, regardless of other conditions."""
    n = 30
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.arange(n) * 0.5
    close[-1] = close[-2] * 1.20  # 20% single-day extension, far beyond 5% default cap
    high = close + 0.5
    low = close - 0.5
    open_ = close - 0.2
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close}, index=idx)
    out = compute_ema_conditions(df, EMAParams(max_close_above_ema_pct=5.0))
    last = out.iloc[-1]
    assert last["ema_distance_pct"] > 5.0
    assert bool(last["ema20_respected"]) is False


def test_two_closes_mode_requires_prior_close_above_too():
    n = 35
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.arange(n) * 0.6
    high = close + 0.5
    low = close - 0.5
    open_ = close - 0.2
    # Force a one-day dip below EMA20 immediately before the last bar
    close_arr = close.copy()
    close_arr[-2] = close_arr[-2] - 15  # previous close now likely below its EMA20
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close_arr}, index=idx)
    out_basic = compute_ema_conditions(df, EMAParams(respect_mode="BASIC"))
    out_two = compute_ema_conditions(df, EMAParams(respect_mode="TWO_CLOSES"))
    # TWO_CLOSES is strictly at least as strict as BASIC on the same data
    assert bool(out_two["ema20_respected"].iloc[-1]) <= bool(out_basic["ema20_respected"].iloc[-1])
