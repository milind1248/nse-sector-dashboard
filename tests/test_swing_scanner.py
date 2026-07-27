import numpy as np
import pandas as pd

from backend.calculations.swing_scanner import add_swing_indicators, compute_swing_signal, SwingParams, _rsi


def _build_df(uptrend=True, rally=True, pullback=True, bullish=True, vol_spike=True,
              low_liquidity=False, n_rally=6, rally_gain=0.8, n_pull=11, pull_step=-0.3):
    """Synthetic OHLCV: a long warm-up trend (for SMA200), a rally phase that
    pushes RSI overbought, a pullback phase that brings RSI back into the
    40-55 band near EMA20, and a bullish reversal candle with a volume spike
    on the final bar — built by construction (positive case verified
    directly, not hand-picked) to satisfy every Stock_Pass condition."""
    n_base = 220
    base = 100 + np.arange(n_base) * (0.15 if uptrend else -0.1)

    rg = rally_gain if rally else 0.05
    rally_seg = base[-1] + np.cumsum(np.full(n_rally, rg))

    ps = pull_step if pullback else 0.05
    pull_seg = rally_seg[-1] + np.cumsum(np.full(n_pull, ps))

    close = np.concatenate([base, rally_seg, pull_seg])
    n = len(close)
    open_ = close - 0.1
    high = close + 0.3
    low = close - 0.3
    vol = np.full(n, 20000.0 if low_liquidity else 100000.0)

    if bullish:
        open_[-1] = close[-1] - 1.0
        low[-1] = open_[-1] - 1.5
        high[-1] = close[-1] + 0.2
    if vol_spike:
        vol[-1] = 40000.0 if low_liquidity else 300000.0

    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


def _signal(df: pd.DataFrame) -> pd.Series:
    return compute_swing_signal(add_swing_indicators(df)).iloc[-1]


def test_rsi_pure_rally_is_100_not_nan():
    """A sustained rally with zero down days in the smoothing window must
    give RSI=100, not NaN — the naive avg_loss==0 division guard used to
    swallow this real (not just synthetic) edge case."""
    close = pd.Series(np.arange(1, 40, dtype=float))  # strictly rising, no down days
    rsi = _rsi(close, length=14)
    assert rsi.iloc[-1] == 100.0


def test_positive_all_conditions_pass():
    df = _build_df()
    last = _signal(df)
    assert bool(last["Stock_Pass"]) is True
    for col in ["Stock_Trend", "RSI_Pullback", "EMA_Prox", "Volume_Spike", "Bullish_Candle", "Liquidity"]:
        assert bool(last[col]) is True
    assert last["Stock_Score"] == 6


def test_negative_no_uptrend():
    last = _signal(_build_df(uptrend=False))
    assert bool(last["Stock_Trend"]) is False
    assert bool(last["Stock_Pass"]) is False


def test_negative_never_overbought():
    """RSI never crossed the overbought threshold, so the 'pullback FROM
    overbought' condition can't be satisfied even though RSI ends up in the
    40-55 band by coincidence."""
    last = _signal(_build_df(rally=False))
    assert bool(last["RSI_Pullback"]) is False
    assert bool(last["Stock_Pass"]) is False


def test_negative_no_pullback_still_overbought():
    last = _signal(_build_df(pullback=False))
    assert last["RSI"] == 100.0
    assert bool(last["RSI_Pullback"]) is False
    assert bool(last["Stock_Pass"]) is False


def test_negative_too_far_from_ema20():
    last = _signal(_build_df(n_pull=25, pull_step=-1.0))
    assert bool(last["EMA_Prox"]) is False
    assert bool(last["Stock_Pass"]) is False


def test_negative_no_volume_spike():
    last = _signal(_build_df(vol_spike=False))
    assert bool(last["Volume_Spike"]) is False
    assert bool(last["Stock_Pass"]) is False


def test_negative_not_bullish_candle():
    last = _signal(_build_df(bullish=False))
    assert bool(last["Bullish_Candle"]) is False
    assert bool(last["Stock_Pass"]) is False


def test_negative_low_liquidity():
    last = _signal(_build_df(low_liquidity=True))
    assert bool(last["Liquidity"]) is False
    assert bool(last["Stock_Pass"]) is False


def test_stop_loss_and_target_reference_levels():
    df = _build_df()
    last = _signal(df)
    p = SwingParams()
    expected_sl = last["Close"] - last["ATR"] * p.stop_loss_atr_mult
    expected_target = last["Close"] + (last["Close"] - expected_sl) * p.target_rr
    assert abs(last["Stop_Loss"] - expected_sl) < 1e-9
    assert abs(last["Target"] - expected_target) < 1e-9
    assert last["Target"] > last["Close"] > last["Stop_Loss"]
