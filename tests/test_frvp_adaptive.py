import numpy as np
import pandas as pd
import pytest

from backend.calculations.frvp_adaptive import (
    f_vp, f_find_cut, f_anchor_asof, f_calc_asof, attach_confirmed_frvp, FRVPParams,
)


def _synthetic_ohlcv(n=120, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    open_ = close + rng.uniform(-1, 1, n)
    volume = rng.uniform(1000, 5000, n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=idx)


def test_f_vp_single_bar_hand_computed():
    """One bar, uniform volume, n_bins=10 -> POC in the lowest bin (tie
    broken to first/lowest index), VA expands upward from a bottom-anchored
    POC (tie-break rule always favors up when lo_b is stuck at 0)."""
    idx = pd.date_range("2024-01-01", periods=1, freq="B")
    df = pd.DataFrame({"Open": [105], "High": [110], "Low": [100], "Close": [108], "Volume": [1000]}, index=idx)
    poc, vah, val = f_vp(df, near_pos=0, far_pos=0, n_bins=10, va_pct=0.70)
    assert poc == pytest.approx(100.5, abs=1e-6)
    assert val == pytest.approx(100.0, abs=1e-6)
    assert vah == pytest.approx(107.0, abs=1e-6)  # 7 bins accumulate exactly 70% -> loop breaks


def test_f_vp_vah_poc_val_ordering_on_random_data():
    df = _synthetic_ohlcv()
    poc, vah, val = f_vp(df, near_pos=100, far_pos=0, n_bins=40, va_pct=0.70)
    assert vah >= poc >= val


def test_f_vp_degenerate_range_returns_nan():
    idx = pd.date_range("2024-01-01", periods=1, freq="B")
    df = pd.DataFrame({"Open": [100], "High": [100], "Low": [100], "Close": [100], "Volume": [1000]}, index=idx)
    poc, vah, val = f_vp(df, 0, 0, n_bins=10, va_pct=0.70)
    assert np.isnan(poc) and np.isnan(vah) and np.isnan(val)


def test_cut_dates_are_unique_and_chronological():
    df = _synthetic_ohlcv(n=150)
    params = FRVPParams(lookback=60, n_bins=20, min_profile_bars=3)
    out = attach_confirmed_frvp(df, params, min_start_pos=params.lookback + 3)
    valid = out.dropna(subset=["confirmed_poc"])
    assert not valid.empty

    def check(row):
        dates = [d for d in (row["cut1_date"], row["cut2_date"], row["cut3_date"]) if pd.notna(d)]
        if len(dates) != len(set(dates)):
            return False
        if pd.notna(row["cut1_date"]) and pd.notna(row["cut2_date"]) and row["cut2_date"] < row["cut1_date"]:
            return False
        if pd.notna(row["cut2_date"]) and pd.notna(row["cut3_date"]) and row["cut3_date"] < row["cut2_date"]:
            return False
        return True

    assert valid.apply(check, axis=1).all()


def test_stop_at_last_valid_cut_no_fake_cut():
    """If cut1 is found but cut2 cannot be (e.g. min_profile_bars makes the
    remaining window too small), completed_cuts must stop at 1 and cut2/cut3
    must be None — never a fabricated cut."""
    df = _synthetic_ohlcv(n=80)
    # A very large min_profile_bars makes it near-impossible to find cut2/cut3
    # while still permitting cut1's search window (which uses the full anchor range).
    params = FRVPParams(lookback=40, n_bins=15, min_profile_bars=25)
    t_pos = 79
    res = f_calc_asof(df, t_pos, params)
    if res["completed_cuts"] >= 1:
        assert res["cut1_pos"] is not None
    if res["completed_cuts"] < 2:
        assert res["cut2_pos"] is None
        assert res["cut3_pos"] is None
    if res["completed_cuts"] < 3:
        assert res["cut3_pos"] is None
    # final_pos must be a real, found position (anchor, cut1, or cut2) — never
    # fabricated beyond what completed_cuts reports.
    assert res["final_pos"] is not None


def test_no_lookahead_mutating_future_never_changes_past():
    """The single most important check: mutating bar t_pos and everything
    after it must never change the confirmed levels computed AT t_pos."""
    df = _synthetic_ohlcv(n=200)
    params = FRVPParams(lookback=60, n_bins=20, min_profile_bars=5)
    t_pos = 150

    res_before = f_calc_asof(df, t_pos, params)

    df_mutated = df.copy()
    for col, factor in [("High", 50), ("Low", 0.02), ("Close", 30), ("Open", 30), ("Volume", 1000)]:
        df_mutated.iloc[t_pos:, df_mutated.columns.get_loc(col)] = df_mutated.iloc[t_pos:][col] * factor

    res_after = f_calc_asof(df_mutated, t_pos, params)

    for key in ("confirmed_poc", "confirmed_vah", "confirmed_val", "completed_cuts",
               "cut1_pos", "cut2_pos", "cut3_pos", "anchor_pos", "final_pos"):
        assert res_before[key] == res_after[key], f"{key} changed: {res_before[key]} -> {res_after[key]}"


def test_anchor_never_uses_bar_t_minus_1_or_later():
    """f_anchor_asof searches strictly positions [t_pos-1-lookback, t_pos-2]
    — never t_pos-1 or t_pos itself."""
    df = _synthetic_ohlcv(n=100)
    t_pos = 80
    lookback = 30
    result = f_anchor_asof(df, t_pos, lookback)
    assert result is not None
    anchor_pos, *_ = result
    assert anchor_pos <= t_pos - 2
    assert anchor_pos >= t_pos - 1 - lookback


def test_find_cut_excludes_duplicate_dates():
    df = _synthetic_ohlcv(n=60)
    poc, _, _ = f_vp(df, near_pos=50, far_pos=10, n_bins=15, va_pct=0.70)
    from backend.calculations.frvp_adaptive import f_date_key
    excluded = f_date_key(df.index[45])
    cut_pos = f_find_cut(df, poc, near_pos=48, far_pos=10, excluded_date1=excluded,
                         excluded_date2=None, tolerance_pct=1.0, min_profile_bars=1,
                         accept_body_cross=True, accept_close_near=True, t_pos=50)
    if cut_pos is not None:
        assert f_date_key(df.index[cut_pos]) != excluded
