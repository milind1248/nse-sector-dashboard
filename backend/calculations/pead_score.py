"""
PEAD (Post-Earnings-Announcement-Drift) scoring.

No paid analyst-consensus/estimates feed is used in this project, so
"surprise" is measured self-referentially: how much the latest quarter's
YoY and QoQ Sales/Profit growth ACCELERATES above that same company's own
trailing growth rate — directly matching the framing from the source video
("a company that was doing 5-10% growth and suddenly does 40-50%").

Reads from the quarterly_results table (backend/data_ingestion/
quarterly_results_pipeline.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.storage.db import get_conn


@dataclass
class PEADParams:
    min_score_shortlist: float = 40.0   # matches the ~40 cutoff mentioned in the source video
    trailing_quarters: int = 4          # how many prior quarters define "normal" growth for this company
    weight_yoy_sales: float = 20.0
    weight_qoq_sales: float = 10.0
    weight_yoy_profit: float = 35.0
    weight_qoq_profit: float = 15.0
    weight_acceleration: float = 20.0   # bonus for growth exceeding the company's own trailing average

    # Red-flag thresholds (Phase A — "profit growth >> revenue growth" and
    # "other income drives profit" checks from the earnings-quality spec)
    other_income_contribution_threshold_pct: float = 25.0
    profit_vs_sales_growth_multiple: float = 2.0   # profit growth must exceed sales growth by this multiple...
    profit_vs_sales_growth_min_gap_pts: float = 20.0  # ...AND by at least this many percentage points, to avoid flagging tiny-base noise
    red_flag_penalty: float = 15.0  # score deduction per red flag triggered


def load_quarterly_history(symbol: str) -> pd.DataFrame:
    """Oldest-to-newest quarterly rows for one symbol."""
    con = get_conn()
    try:
        rows = con.execute("""
            SELECT quarter, sales, net_profit, operating_profit, opm_pct, other_income, pbt, eps
            FROM quarterly_results WHERE symbol = %s
        """, (symbol,)).fetchall()
    finally:
        con.close()
    df = pd.DataFrame(rows, columns=["quarter", "sales", "net_profit", "operating_profit", "opm_pct",
                                      "other_income", "pbt", "eps"])
    # quarter labels are "Mon YYYY" — sort chronologically, not alphabetically
    if not df.empty:
        df["_sort_date"] = pd.to_datetime(df["quarter"], format="%b %Y", errors="coerce")
        df = df.sort_values("_sort_date").drop(columns="_sort_date").reset_index(drop=True)
    return df


def _pct_growth(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def compute_pead_score(history: pd.DataFrame, params: PEADParams | None = None) -> dict:
    """history: output of load_quarterly_history(), oldest-to-newest, at
    least 5 quarters recommended (1 latest + 4 trailing + prior-year
    quarter for YoY). Returns a dict with the score (0-100, can exceed 100
    for extreme surprises — not clamped, since a genuine "40-50% growth
    from a 5-10% grower" should be allowed to score very high) and every
    intermediate growth number for auditability."""
    p = params or PEADParams()
    out = {
        "pead_score": None, "yoy_sales_growth": None, "qoq_sales_growth": None,
        "yoy_profit_growth": None, "qoq_profit_growth": None,
        "trailing_avg_profit_growth": None, "acceleration": None,
        "latest_quarter": None, "reason": "",
        "other_income_contribution_pct": None, "red_flags": [],
    }
    if history is None or len(history) < 3:
        out["reason"] = "Not enough quarterly history (need at least 3 quarters)."
        return out

    latest = history.iloc[-1]
    prev_q = history.iloc[-2]
    out["latest_quarter"] = latest["quarter"]

    yoy_row = None
    if len(history) >= 5:
        yoy_row = history.iloc[-5]  # 4 quarters back = same quarter, prior year
    yoy_sales = _pct_growth(latest["sales"], yoy_row["sales"]) if yoy_row is not None else None
    yoy_profit = _pct_growth(latest["net_profit"], yoy_row["net_profit"]) if yoy_row is not None else None
    qoq_sales = _pct_growth(latest["sales"], prev_q["sales"])
    qoq_profit = _pct_growth(latest["net_profit"], prev_q["net_profit"])

    out["yoy_sales_growth"] = round(yoy_sales, 2) if yoy_sales is not None else None
    out["qoq_sales_growth"] = round(qoq_sales, 2) if qoq_sales is not None else None
    out["yoy_profit_growth"] = round(yoy_profit, 2) if yoy_profit is not None else None
    out["qoq_profit_growth"] = round(qoq_profit, 2) if qoq_profit is not None else None

    # Trailing average profit growth (this company's own "normal" pace),
    # computed from the quarters BEFORE the latest one — never includes
    # the quarter being scored, so this is a genuine prior-baseline, not
    # a self-referential leak.
    trailing = history.iloc[max(0, len(history) - 1 - p.trailing_quarters):-1]
    trailing_growths = []
    for i in range(1, len(trailing)):
        g = _pct_growth(trailing.iloc[i]["net_profit"], trailing.iloc[i - 1]["net_profit"])
        if g is not None:
            trailing_growths.append(g)
    trailing_avg = sum(trailing_growths) / len(trailing_growths) if trailing_growths else None
    out["trailing_avg_profit_growth"] = round(trailing_avg, 2) if trailing_avg is not None else None

    acceleration = None
    if qoq_profit is not None and trailing_avg is not None:
        acceleration = qoq_profit - trailing_avg
        out["acceleration"] = round(acceleration, 2)

    score = 0.0
    if yoy_sales is not None:
        score += max(0.0, min(yoy_sales, 100.0)) / 100.0 * p.weight_yoy_sales
    if qoq_sales is not None:
        score += max(0.0, min(qoq_sales, 50.0)) / 50.0 * p.weight_qoq_sales
    if yoy_profit is not None:
        score += max(0.0, min(yoy_profit, 150.0)) / 150.0 * p.weight_yoy_profit
    if qoq_profit is not None:
        score += max(0.0, min(qoq_profit, 75.0)) / 75.0 * p.weight_qoq_profit
    if acceleration is not None:
        score += max(0.0, min(acceleration, 50.0)) / 50.0 * p.weight_acceleration

    # ── Earnings-quality red flags (Phase A) ────────────────────────────
    # "Other income drives profit" — other income as a % of profit before
    # tax. A high ratio means the headline profit growth may be coming
    # from investment gains / one-off items, not the core operating
    # business — exactly the kind of unsustainable-blip risk the PEAD
    # thesis needs to rule out (matches the video's "is it sustainable?"
    # question directly).
    red_flags: list[str] = []
    other_income = latest.get("other_income")
    pbt = latest.get("pbt")
    if other_income is not None and pbt is not None and pbt > 0:
        contribution = other_income / pbt * 100.0
        out["other_income_contribution_pct"] = round(contribution, 1)
        if contribution >= p.other_income_contribution_threshold_pct:
            red_flags.append(
                f"Other income is {contribution:.0f}% of profit before tax — "
                f"headline profit growth may not be from core operations."
            )

    # "Profit growth >> revenue growth" — profit growing much faster than
    # sales, beyond what margin expansion alone would plausibly explain,
    # is a classic earnings-quality flag (could be a low base, a one-time
    # item, or a tax benefit that isn't visible from sales/profit alone —
    # the flag doesn't diagnose WHICH cause, just that it's worth a closer
    # look before trusting the headline growth number).
    if yoy_sales is not None and yoy_profit is not None:
        gap = yoy_profit - yoy_sales
        multiple_ok = yoy_sales <= 0 or (yoy_profit / yoy_sales) >= p.profit_vs_sales_growth_multiple
        if multiple_ok and gap >= p.profit_vs_sales_growth_min_gap_pts and yoy_profit > 0:
            red_flags.append(
                f"YoY profit growth ({yoy_profit:.0f}%) is far ahead of YoY sales growth "
                f"({yoy_sales:.0f}%) — worth checking whether this is margin expansion, "
                f"a low base, or a one-time item."
            )

    out["red_flags"] = red_flags
    score -= len(red_flags) * p.red_flag_penalty

    out["pead_score"] = round(score, 1)
    reason = (
        f"YoY sales {out['yoy_sales_growth']}%, YoY profit {out['yoy_profit_growth']}%, "
        f"QoQ profit {out['qoq_profit_growth']}% vs trailing avg {out['trailing_avg_profit_growth']}%"
    )
    if red_flags:
        reason += f" | {len(red_flags)} earnings-quality flag(s) — see red_flags for detail."
    out["reason"] = reason
    return out


def scan_universe(symbols: list[str], params: PEADParams | None = None) -> pd.DataFrame:
    """Runs compute_pead_score() for every symbol with quarterly_results
    history in the DB, returns a DataFrame sorted by score descending."""
    p = params or PEADParams()
    rows = []
    for sym in symbols:
        hist = load_quarterly_history(sym)
        if hist.empty:
            continue
        result = compute_pead_score(hist, p)
        if result["pead_score"] is None:
            continue
        result["symbol"] = sym
        rows.append(result)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("pead_score", ascending=False).reset_index(drop=True)
