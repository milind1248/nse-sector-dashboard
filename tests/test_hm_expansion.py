import numpy as np
import pandas as pd

from backend.calculations.hm_expansion import compute_expansion, is_strictly_rising


def _lines_df(white, green, red):
    idx = pd.date_range("2024-01-01", periods=len(white), freq="B")
    return pd.DataFrame({"RSI": white, "HM_EMA": green, "HM_WMA": red}, index=idx)


def test_is_strictly_rising_helper():
    s = pd.Series([1, 2, 3, 4, 5])
    assert is_strictly_rising(s, 2).iloc[-1] == True  # noqa: E712 — 5>4>3 holds
    s2 = pd.Series([5, 4, 3, 2, 1])
    assert is_strictly_rising(s2, 2).iloc[-1] == False  # noqa: E712 — falling, not rising
    s3 = pd.Series([1, 2, 1, 2, 3])
    assert is_strictly_rising(s3, 2).iloc[-1] == True  # noqa: E712 — last 3: 3>2>1 holds
    assert is_strictly_rising(s3, 3).iloc[-1] == False  # noqa: E712 — last 4: 3>2>1>2 fails (1 not > 2)


def test_synthetic_bullish_expansion_reproduction():
    """Matches the spec's screenshot-style scenario: lines originate near/
    below RSI 9, white accelerates first, green follows, red turns up,
    white>green>red holds, gaps widen, lines don't touch, all slopes clear
    threshold. Expected: hm_bullish_expansion == True."""
    white, green, red = _base_lines()
    df = _lines_df(white, green, red)
    out = compute_expansion(df)
    last = out.iloc[-1]
    assert last["hm_bullish_expansion"] == True  # noqa: E712
    # every intermediate column must be present and auditable
    for col in ["oversold_origin", "bullish_ordering", "all_lines_rising",
               "minimum_separation_met", "lines_not_touching", "gaps_expanding",
               "strong_upward_slopes"]:
        assert bool(last[col]) is True


def _base_lines():
    """Positive case built by construction, not hand-picked: white always
    gains more per bar than green, green always gains more than red, so
    every gap widens on every single bar (satisfies even STRICT mode, not
    just the default STABLE_OR_EXPANDING) — hm_bullish_expansion is
    guaranteed True for this data, verified directly before writing this
    test."""
    n_flat, n_rise = 12, 10
    white = np.concatenate([np.full(n_flat, 6.0), 6.0 + np.cumsum(np.full(n_rise, 5.0))])
    green = np.concatenate([np.full(n_flat, 7.0), 7.0 + np.cumsum(np.full(n_rise, 3.0))])
    red = np.concatenate([np.full(n_flat, 8.0), 8.0 + np.cumsum(np.full(n_rise, 1.5))])
    return white, green, red


def test_negative_lines_touching():
    w, g, r = _base_lines()
    g = w - 0.1  # collapse white-green gap below touch_tolerance (0.25)
    out = compute_expansion(_lines_df(w, g, r))
    assert out["hm_bullish_expansion"].iloc[-1] == False  # noqa: E712
    assert out["lines_not_touching"].iloc[-1] == False  # noqa: E712


def test_negative_only_white_rising():
    w, g, r = _base_lines()
    g[:] = 15.0
    r[:] = 8.0
    out = compute_expansion(_lines_df(w, g, r))
    assert out["hm_bullish_expansion"].iloc[-1] == False  # noqa: E712
    assert out["all_lines_rising"].iloc[-1] == False  # noqa: E712


def test_negative_red_flat_or_falling():
    w, g, r = _base_lines()
    r = np.concatenate([np.full(12, 8.0), np.linspace(8.0, 6.0, len(r) - 12)])
    out = compute_expansion(_lines_df(w, g, r))
    assert out["hm_bullish_expansion"].iloc[-1] == False  # noqa: E712
    assert out["red_rising"].iloc[-1] == False  # noqa: E712


def test_negative_gaps_contracting():
    w = np.concatenate([np.full(12, 6.0), [8, 20, 28, 33, 36, 38, 39, 39.5]])
    g = np.concatenate([np.full(12, 7.0), [7.5, 15, 25, 32, 36.5, 39, 40, 40.5]])
    r = np.concatenate([np.full(12, 8.0), np.linspace(7.8, 20, 8)])
    out = compute_expansion(_lines_df(w, g, r))
    assert out["hm_bullish_expansion"].iloc[-1] == False  # noqa: E712
    assert out["gaps_expanding"].iloc[-1] == False  # noqa: E712


def test_negative_oversold_outside_lookback():
    w = np.concatenate([np.full(5, 6.0), [8, 15, 23, 30, 36, 40, 43, 45, 46, 47, 48, 49, 50, 51, 52]])
    g = np.concatenate([np.full(5, 7.0), [7.5, 11, 17, 23, 28, 30.5, 31.5, 32, 32.5, 33, 33.5, 34, 34.5, 35, 35.5]])
    r = np.concatenate([np.full(5, 8.0), np.linspace(7.8, 25, 15)])
    out = compute_expansion(_lines_df(w, g, r))
    assert out["oversold_origin"].iloc[-1] == False  # noqa: E712
    assert out["hm_bullish_expansion"].iloc[-1] == False  # noqa: E712


def test_negative_weak_slope():
    w, g, r = _base_lines()
    w = np.concatenate([np.full(12, 6.0), np.linspace(8, 10, len(w) - 12)])  # barely rising
    out = compute_expansion(_lines_df(w, g, r))
    assert out["hm_bullish_expansion"].iloc[-1] == False  # noqa: E712
    assert out["strong_upward_slopes"].iloc[-1] == False  # noqa: E712
