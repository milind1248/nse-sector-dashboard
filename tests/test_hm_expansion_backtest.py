import numpy as np
import pandas as pd
import pytest

from backend.calculations.hm_expansion_backtest import (
    _dedup_with_cooldown, _variant_raw_signal, compute_metrics,
    VARIANT_NAMES, run_ablation_study,
)


def test_dedup_cooldown_collapses_persistent_signal():
    """A signal that stays True for many consecutive bars must only count
    once per cooldown window, not once per bar (no double-counting an
    overlapping/persistent regime as separate trades)."""
    raw = pd.Series([False] * 5 + [True] * 20 + [False] * 5)
    keep = _dedup_with_cooldown(raw, cooldown_bars=10)
    fired_positions = np.where(keep)[0]
    # first fire at index 5 (first True), and no fire again within 10 bars after that
    assert len(fired_positions) >= 1
    assert fired_positions[0] == 5
    if len(fired_positions) > 1:
        assert fired_positions[1] - fired_positions[0] > 10


def test_dedup_cooldown_separate_events_both_fire():
    raw = pd.Series([False, True, False] + [False] * 15 + [True, False])
    keep = _dedup_with_cooldown(raw, cooldown_bars=10)
    fired_positions = np.where(keep)[0]
    assert len(fired_positions) == 2


def test_variant_raw_signal_variant_a_uses_existing_bottom_signal():
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    df = pd.DataFrame({
        "BOTTOM_SIGNAL": [False, True, False, False, True],
        "hm_bullish_expansion": [False, False, True, False, False],
        "ema20_rising": [True] * 5,
        "price_above_vah": [True] * 5,
        "ema20_respected": [True] * 5,
        "signal_full_confluence": [False] * 5,
    }, index=idx)
    sig_a = _variant_raw_signal(df, "A")
    assert list(sig_a) == [False, True, False, False, True]
    sig_b = _variant_raw_signal(df, "B")
    assert list(sig_b) == [False, False, True, False, False]


def test_variant_raw_signal_stacks_conditions_correctly():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    df = pd.DataFrame({
        "BOTTOM_SIGNAL": [False] * 3,
        "hm_bullish_expansion": [True, True, True],
        "ema20_rising": [True, False, True],
        "price_above_vah": [True, True, False],
        "ema20_respected": [True, True, True],
        "signal_full_confluence": [True, False, False],
    }, index=idx)
    # F = B & ema20_rising & price_above_vah
    sig_f = _variant_raw_signal(df, "F")
    assert list(sig_f) == [True, False, False]


def test_compute_metrics_win_rate_and_expectancy():
    trades = pd.DataFrame({"Ret20d%": [10.0, -5.0, 20.0, -10.0, np.nan]})
    m = compute_metrics(trades, 20)
    assert m["trades"] == 4  # NaN excluded
    assert m["win_rate_pct"] == 50.0
    assert m["avg_return_pct"] == pytest.approx(3.75)
    assert m["avg_winner_pct"] == pytest.approx(15.0)
    assert m["avg_loser_pct"] == pytest.approx(-7.5)


def test_compute_metrics_empty_trades_returns_nan_not_crash():
    m = compute_metrics(pd.DataFrame(), 20)
    assert m["trades"] == 0
    assert np.isnan(m["win_rate_pct"])


def test_ablation_study_reports_all_seven_variants_and_survivorship_warning():
    """Uses a tiny synthetic universe via a monkeypatched backtest_symbol to
    avoid network calls — verifies the aggregation/warning wiring, not the
    per-stock math (that's covered elsewhere)."""
    import backend.calculations.hm_expansion_backtest as mod

    def fake_backtest_symbol(symbol, period, hold_days, entry_mode, params=None):
        trades = pd.DataFrame({
            "Symbol": [symbol] * 2,
            "SignalDate": [pd.Timestamp("2024-01-01").date()] * 2,
            "EntryDate": [pd.Timestamp("2024-01-02").date()] * 2,
            "EntryPrice": [100.0, 100.0],
            "Ret5d%": [2.0, -1.0], "Ret10d%": [3.0, -2.0], "Ret20d%": [5.0, -3.0],
        })
        return {v: trades.copy() for v in VARIANT_NAMES}

    original = mod.backtest_symbol
    mod.backtest_symbol = fake_backtest_symbol
    try:
        result = run_ablation_study(["FAKE1.NS", "FAKE2.NS"], period="1y", hold_days=(5, 10, 20),
                                    entry_mode="NEXT_OPEN", max_workers=2, universe_label="Nifty 500")
    finally:
        mod.backtest_symbol = original

    assert set(result["metrics"].keys()) == set(VARIANT_NAMES)
    for v in VARIANT_NAMES:
        assert result["metrics"][v][20]["trades"] == 4  # 2 stocks x 2 trades each
    assert any("SURVIVORSHIP BIAS WARNING" in w for w in result["warnings"])


def test_signal_close_entry_mode_flagged_optimistic():
    import backend.calculations.hm_expansion_backtest as mod

    def fake_backtest_symbol(symbol, period, hold_days, entry_mode, params=None):
        return {v: pd.DataFrame() for v in VARIANT_NAMES}

    original = mod.backtest_symbol
    mod.backtest_symbol = fake_backtest_symbol
    try:
        result = run_ablation_study(["FAKE.NS"], period="1y", hold_days=(20,),
                                    entry_mode="SIGNAL_CLOSE", max_workers=1, universe_label="custom")
    finally:
        mod.backtest_symbol = original

    assert any("ENTRY MODE WARNING" in w and "SIGNAL_CLOSE" in w for w in result["warnings"])
