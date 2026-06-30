"""
Gann Analysis — pure calculation engine (no Streamlit imports).
Returns JSON-serialisable dicts that can be stored in SQLite and
read back by the UI page without any Yahoo Finance calls.

Public API
----------
compute_gann_all(symbol, df, pivot_window=10) -> dict
  Keys: atr, deg, proj, pts, dates
  Each value is a JSON-serialisable dict ready to pass to store_gann().
"""
import datetime
import numpy as np
import pandas as pd
from typing import Any

# ── Constants ──────────────────────────────────────────────────────────────────

GANN_DATES = [
    (2, 4), (2, 5), (2, 6), (2, 7), (2, 8),
    (3, 20), (3, 21), (3, 22), (3, 23),
    (5, 3), (5, 4), (5, 5), (5, 6), (5, 7),
    (6, 20), (6, 21), (6, 22),
    (8, 5), (8, 6), (8, 7), (8, 8),
    (9, 22), (9, 23), (9, 24),
    (11, 7), (11, 8), (11, 9),
    (12, 21), (12, 22), (12, 23),
]

DEG = {
    "90°":  0.500,
    "120°": 0.667,
    "180°": 1.000,
    "240°": 1.333,
    "270°": 1.500,
    "360°": 2.000,
}


# ── Core helpers ───────────────────────────────────────────────────────────────

def _find_pivots(df: pd.DataFrame, window: int) -> dict:
    """Vectorised swing pivot detection using rolling max/min."""
    high_v = df["High"].values
    low_v  = df["Low"].values
    n      = len(high_v)

    roll_max = pd.Series(high_v).rolling(2 * window + 1, center=True).max().values
    roll_min = pd.Series(low_v ).rolling(2 * window + 1, center=True).min().values

    dates = [str(df.index[i].date()) for i in range(n)]

    highs = [
        (dates[i], float(high_v[i]))
        for i in range(window, n - window)
        if high_v[i] == roll_max[i]
    ]
    lows = [
        (dates[i], float(low_v[i]))
        for i in range(window, n - window)
        if low_v[i] == roll_min[i]
    ]
    return {"highs": highs, "lows": lows}


def _sq9_levels(price: float) -> dict[str, dict]:
    r = float(np.sqrt(price))
    return {
        deg: {"up": round((r + f) ** 2, 2), "dn": round(max(r - f, 0.0) ** 2, 2)}
        for deg, f in DEG.items()
    }


# ── Method 1: ATR Range Completion ────────────────────────────────────────────

def compute_atr(df: pd.DataFrame) -> dict[str, Any]:
    """
    Returns current ATR signal + backtest rows.
    Fully vectorised — no Python loops over bars.
    """
    daily_rng = (df["High"] - df["Low"]).values
    close_v   = df["Close"].values
    open_v    = df["Open"].values
    n         = len(df)

    atr_rolling = np.array([
        daily_rng[i - 34:i].mean() if i >= 34 else np.nan
        for i in range(n)
    ])  # only 7k iterations of a simple slice — fast

    atr34       = float(daily_rng[-34:].mean()) if n >= 34 else 0.0
    today_range = float(daily_rng[-1])
    consumed    = round(today_range / atr34 * 100, 1) if atr34 else 0.0

    # Signal days: range >= ATR and not within 1 bar of end
    valid = (atr_rolling > 0) & (daily_rng >= atr_rolling)
    sig_idx = np.where(valid)[0]
    sig_idx = sig_idx[sig_idx < n - 1]  # need next-day bar

    if len(sig_idx) == 0:
        bt_rows = []
    else:
        bull   = close_v[sig_idx] > open_v[sig_idx]
        atr_at = atr_rolling[sig_idx]
        rng_at = daily_rng[sig_idx]
        r1d    = (close_v[sig_idx + 1] - close_v[sig_idx]) / close_v[sig_idx] * 100
        r3d_idx = np.minimum(sig_idx + 3, n - 1)
        r3d    = (close_v[r3d_idx] - close_v[sig_idx]) / close_v[sig_idx] * 100
        rev    = (bull & (r1d < 0)) | (~bull & (r1d > 0))
        dates  = [str(df.index[i].date()) for i in sig_idx]

        bt_rows = [
            {
                "Date":      dates[k],
                "Signal":    "Bull" if bull[k] else "Bear",
                "Consumed%": round(float(rng_at[k] / atr_at[k] * 100), 1),
                "Next1d%":   round(float(r1d[k]), 2),
                "Next3d%":   round(float(r3d[k]), 2),
                "Reversed":  bool(rev[k]),
            }
            for k in range(len(sig_idx))
        ]

    return {
        "atr34":        round(atr34, 2),
        "today_range":  round(today_range, 2),
        "consumed_pct": consumed,
        "cmp":          round(float(close_v[-1]), 2),
        "last_date":    str(df.index[-1].date()),
        "bt_rows":      bt_rows,
    }


# ── Method 2: Degree Levels ───────────────────────────────────────────────────

def compute_degree_levels(df: pd.DataFrame, pivot_window: int = 10,
                          pivots: dict | None = None) -> dict[str, Any]:
    """
    Returns degree levels from last swing high and low + per-level backtest.
    pass pivots= to avoid recomputing _find_pivots for every method.
    """
    pivots  = pivots or _find_pivots(df, pivot_window)
    ph_list = pivots["highs"]
    pl_list = pivots["lows"]
    ph      = ph_list[-1] if ph_list else None
    pl      = pl_list[-1] if pl_list else None

    def _bt_levels(lvls: dict) -> list[dict]:
        # Vectorised: no Python loop over bars
        high_v  = df["High"].values
        low_v   = df["Low"].values
        close_v = df["Close"].values
        n = len(close_v)
        rows = []
        for deg, lr in lvls.items():
            for side, lvl_price, is_res in [
                (f"R {deg}", lr["up"], True),
                (f"S {deg}", lr["dn"], False),
            ]:
                if lvl_price <= 0:
                    continue
                touch_mask = (
                    (np.abs(high_v  - lvl_price) / lvl_price <= 0.005) |
                    (np.abs(low_v   - lvl_price) / lvl_price <= 0.005)
                )
                touch_mask[n - 3:] = False   # need 3 forward bars
                idx = np.where(touch_mask)[0]
                if len(idx) == 0:
                    continue
                cl   = close_v[idx]
                fwd3 = close_v[idx + 3]
                bounce = (fwd3 < cl) if is_res else (fwd3 > cl)
                ret3d  = (fwd3 - cl) / cl * 100
                rows.append({
                    "Level":      side,
                    "Price":      lvl_price,
                    "Touches":    int(len(idx)),
                    "BounceRate": round(float(bounce.mean() * 100), 1),
                    "Avg3dRet":   round(float(ret3d.mean()), 2),
                })
        return rows

    lvls_h = _sq9_levels(ph[1]) if ph else {}
    lvls_l = _sq9_levels(pl[1]) if pl else {}

    return {
        "ph":              list(ph) if ph else None,
        "pl":              list(pl) if pl else None,
        "levels_from_high": lvls_h,
        "levels_from_low":  lvls_l,
        "bt_high":          _bt_levels(lvls_h) if lvls_h else [],
        "bt_low":           _bt_levels(lvls_l) if lvls_l else [],
        "cmp":              round(float(df["Close"].iloc[-1]), 2),
    }


# ── Method 3: Date Projection ─────────────────────────────────────────────────

def compute_date_projection(df: pd.DataFrame, pivot_window: int = 10,
                            pivots: dict | None = None) -> dict[str, Any]:
    """
    Top-to-Top / Bottom-to-Bottom projections + backtest.
    pass pivots= to avoid recomputing _find_pivots for every method.
    """
    pivots  = pivots or _find_pivots(df, pivot_window)
    ph_list = pivots["highs"]
    pl_list = pivots["lows"]
    today   = datetime.date.today()

    def _project_list(pivot_list):
        out = []
        for i in range(len(pivot_list) - 1):
            d1   = datetime.date.fromisoformat(pivot_list[i][0])
            d2   = datetime.date.fromisoformat(pivot_list[i + 1][0])
            diff = (d2 - d1).days
            proj = d2 + datetime.timedelta(days=diff)
            out.append({
                "Pivot1":      str(d1),
                "Price1":      round(pivot_list[i][1], 1),
                "Pivot2":      str(d2),
                "Price2":      round(pivot_list[i + 1][1], 1),
                "DaysApart":   diff,
                "Projected":   str(proj),
                "DaysAway":    (proj - today).days,
            })
        return out

    def _backtest_proj(pivot_list, label):
        rows = []
        if len(pivot_list) < 3:
            return rows
        for i in range(len(pivot_list) - 2):
            d1     = datetime.date.fromisoformat(pivot_list[i][0])
            d2     = datetime.date.fromisoformat(pivot_list[i + 1][0])
            d3_act = datetime.date.fromisoformat(pivot_list[i + 2][0])
            diff   = (d2 - d1).days
            d3_hat = d2 + datetime.timedelta(days=diff)
            err    = abs((d3_act - d3_hat).days)
            rows.append({
                "HL":        label,
                "Pivot1":    str(d1),
                "Pivot2":    str(d2),
                "Projected": str(d3_hat),
                "Actual":    str(d3_act),
                "ErrDays":   err,
                "Within3d":  err <= 3,
                "Within7d":  err <= 7,
            })
        return rows

    return {
        "top_proj": _project_list(ph_list),
        "bot_proj": _project_list(pl_list),
        "bt_highs": _backtest_proj(ph_list, "High"),
        "bt_lows":  _backtest_proj(pl_list, "Low"),
    }


# ── Method 4: Price-Time Square Out ──────────────────────────────────────────

def compute_price_time_square(df: pd.DataFrame, pivot_window: int = 10,
                              pivots: dict | None = None) -> dict[str, Any]:
    """
    Price-Time squaring: alert when best-scale variance < 5%.
    pass pivots= to avoid recomputing _find_pivots for every method.
    """
    pivots  = pivots or _find_pivots(df, pivot_window)
    ph_list = pivots["highs"]
    pl_list = pivots["lows"]
    ph      = ph_list[-1] if ph_list else None
    pl      = pl_list[-1] if pl_list else None
    today   = datetime.date.today()
    cmp     = round(float(df["Close"].iloc[-1]), 2)

    def _pt(pivot, label):
        if not pivot:
            return None
        pdate = datetime.date.fromisoformat(pivot[0])
        days  = (today - pdate).days

        def pct(a, b):
            return round(abs(a - b) / max(b, 0.01) * 100, 2)

        scales = {
            "Price vs Days":     pct(cmp, days),
            "Price÷10 vs Days":  pct(cmp / 10, days),
            "Price÷100 vs Days": pct(cmp / 100, days),
        }
        best_k = min(scales, key=scales.get)
        best_v = scales[best_k]
        return {
            "label":        label,
            "pivot_date":   str(pdate),
            "days":         days,
            "cmp":          cmp,
            "pivot_price":  round(float(pivot[1]), 2),
            "scales":       scales,
            "best_k":       best_k,
            "best_v":       best_v,
            "squared":      best_v < 5.0,
        }

    # Backtest — vectorised per-bar price-time variance
    close_v   = df["Close"].values
    bar_dates = np.array([d.date() for d in df.index])
    n         = len(close_v)

    # Convert pivot date strings to date objects once
    h_dates = np.array([datetime.date.fromisoformat(t) for t, _ in ph_list])
    h_prices = np.array([p for _, p in ph_list])
    l_dates  = np.array([datetime.date.fromisoformat(t) for t, _ in pl_list])
    l_prices = np.array([p for _, p in pl_list])

    bt_rows = []
    for i in range(pivot_window + 1, n - 5):
        bar_date  = bar_dates[i]
        bar_close = close_v[i]
        best_var  = 999.0

        for pivot_ds, pivot_ps in [(h_dates, h_prices), (l_dates, l_prices)]:
            prior = pivot_ds < bar_date
            if not prior.any():
                continue
            last_idx = np.where(prior)[0][-1]
            days = (bar_date - pivot_ds[last_idx]).days
            if days <= 0:
                continue
            for sd in (1, 10, 100):
                v = abs(bar_close / sd - days) / days * 100
                if v < best_var:
                    best_var = v

        fwd5 = close_v[i + 5]
        ret5 = abs((fwd5 - bar_close) / bar_close * 100)
        bt_rows.append({
            "Date":    str(bar_date),
            "Squared": best_var < 5.0,
            "BestVar": round(best_var, 1),
            "Ret5d":   round(float(ret5), 2),
        })

    return {
        "from_high": _pt(ph, "High"),
        "from_low":  _pt(pl, "Low"),
        "bt_rows":   bt_rows,
    }


# ── Method 5: Gann Natural Dates ─────────────────────────────────────────────

def compute_natural_dates(df: pd.DataFrame, pivot_window: int = 10,
                          pivots: dict | None = None) -> dict[str, Any]:
    """
    Upcoming Gann natural dates + hit-rate backtest.
    pass pivots= to avoid recomputing _find_pivots for every method.
    """
    pivots  = pivots or _find_pivots(df, pivot_window)
    ph_list = pivots["highs"]
    pl_list = pivots["lows"]
    today   = datetime.date.today()

    upcoming = []
    for year in [today.year, today.year + 1]:
        for m, d in GANN_DATES:
            try:
                dt   = datetime.date(year, m, d)
                diff = (dt - today).days
                if 0 <= diff <= 90:
                    upcoming.append({
                        "Date":     str(dt),
                        "Period":   dt.strftime("%B %d"),
                        "DaysAway": diff,
                    })
            except ValueError:
                pass
    upcoming.sort(key=lambda x: x["DaysAway"])

    data_start = df.index[0].date()
    data_end   = df.index[-1].date()

    # Build pivot date set with ±3-day offsets pre-expanded for fast O(1) lookup
    pivot_dates_all = set(
        datetime.date.fromisoformat(t) + datetime.timedelta(days=k)
        for t, _ in ph_list + pl_list
        for k in range(-3, 4)
    )

    hist_rows = []
    for year in range(data_start.year, data_end.year + 1):
        for m, d in GANN_DATES:
            try:
                gd = datetime.date(year, m, d)
                if data_start <= gd <= data_end:
                    hist_rows.append({
                        "GannDate": str(gd),
                        "Period":   gd.strftime("%B %d"),
                        "HitPivot": gd in pivot_dates_all,
                    })
            except ValueError:
                pass

    total   = len(hist_rows)
    hits    = sum(1 for r in hist_rows if r["HitPivot"])
    hit_pct = round(hits / total * 100, 1) if total else 0.0

    return {
        "upcoming":      upcoming,
        "hist_rows":     hist_rows,
        "hit_rate_pct":  hit_pct,
        "total_dates":   total,
        "total_hits":    hits,
    }


# ── Accuracy aggregation ──────────────────────────────────────────────────────

def compute_accuracy(result: dict) -> dict[str, Any]:
    """
    Derive pre-aggregated accuracy metrics from a compute_gann_all() result.
    Returns a flat dict of 10 fields (5 accuracy %, 5 signal counts).
    Safe to call even when result keys are missing.
    """
    acc: dict[str, Any] = {}

    # ATR Range: % of signal bars where price reversed next day
    atr_rows = result.get("atr", {}).get("bt_rows", [])
    if atr_rows:
        acc["atr_accuracy_pct"] = round(
            sum(1 for r in atr_rows if r.get("Reversed")) / len(atr_rows) * 100, 1
        )
        acc["atr_signals"] = len(atr_rows)
    else:
        acc["atr_accuracy_pct"] = None
        acc["atr_signals"] = 0

    # Degree Levels: weighted-average BounceRate (weight = Touches per level)
    deg = result.get("deg", {})
    all_lvls = deg.get("bt_high", []) + deg.get("bt_low", [])
    total_w = sum(x.get("Touches", 0) for x in all_lvls)
    if total_w:
        acc["deg_accuracy_pct"] = round(
            sum(x.get("BounceRate", 0) * x.get("Touches", 0) for x in all_lvls) / total_w, 1
        )
        acc["deg_signals"] = total_w
    else:
        acc["deg_accuracy_pct"] = None
        acc["deg_signals"] = 0

    # Date Projection: % pivot triplets where projected date landed Within3d
    proj = result.get("proj", {})
    all_bt = proj.get("bt_highs", []) + proj.get("bt_lows", [])
    if all_bt:
        acc["proj_accuracy_pct"] = round(
            sum(1 for r in all_bt if r.get("Within3d")) / len(all_bt) * 100, 1
        )
        acc["proj_signals"] = len(all_bt)
    else:
        acc["proj_accuracy_pct"] = None
        acc["proj_signals"] = 0

    # Price-Time Square: % valid bars (BestVar < 999) that were Squared
    pts_rows = result.get("pts", {}).get("bt_rows", [])
    valid = [r for r in pts_rows if r.get("BestVar", 999) < 999]
    if valid:
        acc["pts_accuracy_pct"] = round(
            sum(1 for r in valid if r.get("Squared")) / len(valid) * 100, 1
        )
        acc["pts_signals"] = len(valid)
    else:
        acc["pts_accuracy_pct"] = None
        acc["pts_signals"] = 0

    # Natural Dates: hit_rate_pct already computed in compute_natural_dates()
    dates = result.get("dates", {})
    acc["nat_accuracy_pct"] = dates.get("hit_rate_pct")
    acc["nat_signals"] = dates.get("total_dates", 0)

    return acc


# ── Master function ───────────────────────────────────────────────────────────

def compute_gann_all(symbol: str, df: pd.DataFrame, pivot_window: int = 10) -> dict[str, Any]:
    """
    Compute all 5 Gann methods for one stock.
    Returns dict with keys: atr, deg, proj, pts, dates, updated_at.
    All values are JSON-serialisable.
    """
    if df is None or len(df) < 60:
        return {}

    # Compute pivots once — shared by all 4 methods that need them
    pivots = _find_pivots(df, pivot_window)

    return {
        "atr":        compute_atr(df),
        "deg":        compute_degree_levels(df, pivot_window, pivots=pivots),
        "proj":       compute_date_projection(df, pivot_window, pivots=pivots),
        "pts":        compute_price_time_square(df, pivot_window, pivots=pivots),
        "dates":      compute_natural_dates(df, pivot_window, pivots=pivots),
        "updated_at": datetime.date.today().isoformat(),
    }
