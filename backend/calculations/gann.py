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
    highs, lows = [], []
    for i in range(window, len(df) - window):
        sl = slice(i - window, i + window + 1)
        if df["High"].iloc[i] == df["High"].iloc[sl].max():
            highs.append((str(df.index[i].date()), float(df["High"].iloc[i])))
        if df["Low"].iloc[i] == df["Low"].iloc[sl].min():
            lows.append((str(df.index[i].date()), float(df["Low"].iloc[i])))
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
    Result keys:
      atr34, today_range, consumed_pct,
      bt_rows: list of dicts (Date, Signal, Consumed%, Next1d%, Next3d%, Reversed)
    """
    daily_rng = df["High"] - df["Low"]
    atr34       = float(daily_rng.tail(34).mean()) if len(df) >= 34 else 0.0
    today_range = float(daily_rng.iloc[-1])
    consumed    = round(today_range / atr34 * 100, 1) if atr34 else 0.0

    bt_rows = []
    for i in range(34, len(df) - 1):
        atr_i = float(daily_rng.iloc[i - 34:i].mean())
        rng_i = float(daily_rng.iloc[i])
        if atr_i and rng_i / atr_i >= 1.0:
            bull    = df["Close"].iloc[i] > df["Open"].iloc[i]
            r1d     = (df["Close"].iloc[i + 1] - df["Close"].iloc[i]) / df["Close"].iloc[i] * 100
            r3d_idx = min(i + 3, len(df) - 1)
            r3d     = (df["Close"].iloc[r3d_idx] - df["Close"].iloc[i]) / df["Close"].iloc[i] * 100
            rev     = (bull and r1d < 0) or (not bull and r1d > 0)
            bt_rows.append({
                "Date":        str(df.index[i].date()),
                "Signal":      "Bull" if bull else "Bear",
                "Consumed%":   round(rng_i / atr_i * 100, 1),
                "Next1d%":     round(r1d, 2),
                "Next3d%":     round(r3d, 2),
                "Reversed":    rev,
            })

    return {
        "atr34":       round(atr34, 2),
        "today_range": round(today_range, 2),
        "consumed_pct": consumed,
        "cmp":         round(float(df["Close"].iloc[-1]), 2),
        "last_date":   str(df.index[-1].date()),
        "bt_rows":     bt_rows,
    }


# ── Method 2: Degree Levels ───────────────────────────────────────────────────

def compute_degree_levels(df: pd.DataFrame, pivot_window: int = 10) -> dict[str, Any]:
    """
    Returns degree levels from last swing high and low + per-level backtest.
    Result keys:
      ph: (date_str, price) or None
      pl: (date_str, price) or None
      levels_from_high: {deg: {up, dn}} or {}
      levels_from_low:  {deg: {up, dn}} or {}
      bt_high: list of {Level, Price, Touches, BounceRate, Avg3dRet} or []
      bt_low:  same
    """
    pivots  = _find_pivots(df, pivot_window)
    ph_list = pivots["highs"]
    pl_list = pivots["lows"]
    ph      = ph_list[-1] if ph_list else None
    pl      = pl_list[-1] if pl_list else None

    def _bt_levels(lvls: dict) -> list[dict]:
        rows = []
        for deg, lr in lvls.items():
            for side, lvl_price, is_res in [
                (f"R {deg}", lr["up"], True),
                (f"S {deg}", lr["dn"], False),
            ]:
                if lvl_price <= 0:
                    continue
                touches = []
                for i in range(len(df) - 3):
                    h = float(df["High"].iloc[i])
                    l = float(df["Low"].iloc[i])
                    if (abs(h - lvl_price) / lvl_price <= 0.005 or
                            abs(l - lvl_price) / lvl_price <= 0.005):
                        fwd3 = float(df["Close"].iloc[i + 3])
                        cl   = float(df["Close"].iloc[i])
                        bounce = (fwd3 < cl) if is_res else (fwd3 > cl)
                        ret3d  = round((fwd3 - cl) / cl * 100, 2)
                        touches.append({"ret3d": ret3d, "bounce": bounce})
                if touches:
                    acc = round(sum(1 for t in touches if t["bounce"]) / len(touches) * 100, 1)
                    avg = round(sum(t["ret3d"] for t in touches) / len(touches), 2)
                    rows.append({
                        "Level":       side,
                        "Price":       lvl_price,
                        "Touches":     len(touches),
                        "BounceRate":  acc,
                        "Avg3dRet":    avg,
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

def compute_date_projection(df: pd.DataFrame, pivot_window: int = 10) -> dict[str, Any]:
    """
    Top-to-Top / Bottom-to-Bottom projections + backtest.
    Result keys:
      top_proj: list of projection dicts
      bot_proj: list of projection dicts
      bt_highs: list of backtest dicts
      bt_lows:  list of backtest dicts
    """
    pivots  = _find_pivots(df, pivot_window)
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

def compute_price_time_square(df: pd.DataFrame, pivot_window: int = 10) -> dict[str, Any]:
    """
    Price-Time squaring: alert when best-scale variance < 5%.
    Result keys:
      from_high: {label, pivot_date, days, cmp, pivot_price, scales, best_k, best_v, squared}
      from_low:  same
      bt_rows:   list of {Date, Squared, BestVar, Ret5d}
    """
    pivots  = _find_pivots(df, pivot_window)
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

    # Backtest
    bt_rows = []
    for i in range(pivot_window + 1, len(df) - 5):
        bar_date  = df.index[i].date()
        bar_close = float(df["Close"].iloc[i])

        prior_hs = [(t, p) for t, p in ph_list if datetime.date.fromisoformat(t) < bar_date]
        prior_ls = [(t, p) for t, p in pl_list if datetime.date.fromisoformat(t) < bar_date]
        if not prior_hs and not prior_ls:
            continue

        best_var = 999.0
        for pivs in [prior_hs[-1:], prior_ls[-1:]]:
            if not pivs:
                continue
            pt, pp = pivs[0]
            days   = (bar_date - datetime.date.fromisoformat(pt)).days
            if days <= 0:
                continue
            for scale_div in [1, 10, 100]:
                v = abs(bar_close / scale_div - days) / max(days, 0.01) * 100
                best_var = min(best_var, v)

        fwd5 = float(df["Close"].iloc[i + 5])
        ret5 = abs((fwd5 - bar_close) / bar_close * 100)
        bt_rows.append({
            "Date":    str(bar_date),
            "Squared": best_var < 5.0,
            "BestVar": round(best_var, 1),
            "Ret5d":   round(ret5, 2),
        })

    return {
        "from_high": _pt(ph, "High"),
        "from_low":  _pt(pl, "Low"),
        "bt_rows":   bt_rows,
    }


# ── Method 5: Gann Natural Dates ─────────────────────────────────────────────

def compute_natural_dates(df: pd.DataFrame, pivot_window: int = 10) -> dict[str, Any]:
    """
    Upcoming Gann natural dates + hit-rate backtest over the full df window.
    Result keys:
      upcoming: list of {Date, Period, DaysAway}
      hist_rows: list of {GannDate, Period, HitPivot}
      hit_rate_pct: float
    """
    pivots  = _find_pivots(df, pivot_window)
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
    pivot_dates_all = set(
        datetime.date.fromisoformat(t)
        for t, _ in ph_list + pl_list
    )

    hist_rows = []
    for year in range(data_start.year, data_end.year + 1):
        for m, d in GANN_DATES:
            try:
                gd = datetime.date(year, m, d)
                if data_start <= gd <= data_end:
                    window3 = {gd + datetime.timedelta(days=k) for k in range(-3, 4)}
                    hit     = bool(window3 & pivot_dates_all)
                    hist_rows.append({
                        "GannDate": str(gd),
                        "Period":   gd.strftime("%B %d"),
                        "HitPivot": hit,
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

    return {
        "atr":        compute_atr(df),
        "deg":        compute_degree_levels(df, pivot_window),
        "proj":       compute_date_projection(df, pivot_window),
        "pts":        compute_price_time_square(df, pivot_window),
        "dates":      compute_natural_dates(df, pivot_window),
        "updated_at": datetime.date.today().isoformat(),
    }
