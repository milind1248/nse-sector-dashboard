import pandas as pd

from backend.calculations.pead_score import compute_pead_score, PEADParams


def _hist(sales, net_profit, other_income, pbt):
    n = len(sales)
    quarters = ["Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026"][:n]
    return pd.DataFrame({
        "quarter": quarters,
        "sales": sales,
        "net_profit": net_profit,
        "operating_profit": [150] * n,
        "opm_pct": [15] * n,
        "other_income": other_income,
        "pbt": pbt,
        "eps": [1] * n,
    })


def test_other_income_driven_profit_flags():
    hist = _hist(
        sales=[1000, 1010, 1020, 1030, 1040],
        net_profit=[100, 102, 105, 108, 130],
        other_income=[5, 5, 5, 5, 50],  # sudden spike in the latest quarter
        pbt=[130, 132, 135, 138, 160],
    )
    res = compute_pead_score(hist)
    assert any("Other income" in f for f in res["red_flags"])
    assert res["other_income_contribution_pct"] is not None
    assert res["other_income_contribution_pct"] > 25


def test_profit_growth_far_exceeds_sales_growth_flags():
    hist = _hist(
        sales=[1000, 1005, 1010, 1015, 1030],       # ~3% YoY
        net_profit=[100, 101, 102, 103, 160],        # ~60% YoY — huge gap vs sales
        other_income=[2, 2, 2, 2, 2],
        pbt=[110, 111, 112, 113, 170],
    )
    res = compute_pead_score(hist)
    assert any("far ahead" in f for f in res["red_flags"])


def test_clean_matched_growth_does_not_flag():
    hist = _hist(
        sales=[1000, 1050, 1100, 1150, 1200],
        net_profit=[100, 105, 110, 115, 120],
        other_income=[3, 3, 3, 3, 3],
        pbt=[130, 135, 140, 145, 150],
    )
    res = compute_pead_score(hist)
    assert res["red_flags"] == []


def test_red_flag_penalty_reduces_score():
    """Confirm the penalty actually lowers the score, not just annotates it —
    same underlying growth numbers, only other_income differs."""
    base = _hist(
        sales=[1000, 1010, 1020, 1030, 1040],
        net_profit=[100, 102, 105, 108, 130],
        other_income=[5, 5, 5, 5, 5],  # no spike — should NOT flag
        pbt=[130, 132, 135, 138, 160],
    )
    flagged = _hist(
        sales=[1000, 1010, 1020, 1030, 1040],
        net_profit=[100, 102, 105, 108, 130],
        other_income=[5, 5, 5, 5, 50],  # spike — should flag
        pbt=[130, 132, 135, 138, 160],
    )
    res_base = compute_pead_score(base)
    res_flagged = compute_pead_score(flagged)
    assert res_flagged["pead_score"] < res_base["pead_score"]


def test_missing_other_income_pbt_does_not_crash():
    """Older/incompletely-scraped rows may not have other_income/pbt —
    must degrade gracefully, not raise."""
    hist = _hist(
        sales=[1000, 1010, 1020, 1030, 1040],
        net_profit=[100, 102, 105, 108, 130],
        other_income=[None, None, None, None, None],
        pbt=[None, None, None, None, None],
    )
    res = compute_pead_score(hist)
    assert res["other_income_contribution_pct"] is None
    assert res["pead_score"] is not None
