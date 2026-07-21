"""Adaptive FRVP (Fixed-Range Volume Profile) — faithful Python port of
adaptive_frvp_confirmed_signals_v4_circle_status.pine (user-supplied source,
19-Jul-2026), functions f_vp / f_find_cut / f_anchor_asof / f_calc_asof.

This supersedes three earlier, non-faithful Python approximations that
existed in this codebase's history (none of them implemented the real
cut-acceptance rule or the no-lookahead evalOff=1 semantics correctly).

Pine bar-offset -> pandas position mapping
-------------------------------------------
Pine's `[k]` means "k bars back from the reference bar". The whole system is
always invoked as `f_calc_asof(1)`, i.e. evalOff=1 — the reference bar for
offset purposes is the evaluation bar `t_pos`, and offset 0 (`t_pos` itself)
is NEVER read anywhere in this module. Offset `k` maps to pandas position
`t_pos - k` (ascending date order assumed, i.e. df.iloc[-1] is most recent).

Confirmed FRVP levels for a signal being evaluated at position `t_pos`
therefore only ever look at bars `t_pos-1` and older — position `t_pos`
itself is excluded from every volume-profile input and every cut search.
This is the no-lookahead guarantee: mutating bar `t_pos` or anything after
it can never change the confirmed_poc/vah/val computed for `t_pos`.

Defaults match the Pine script's `input.*` declarations exactly.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_LOOKBACK = 300
DEFAULT_N_BINS = 40
DEFAULT_VA_PCT = 0.70
DEFAULT_CUT_TOLERANCE_PCT = 0.30
DEFAULT_MIN_PROFILE_BARS = 10
DEFAULT_ACCEPT_BODY_CROSS = True
DEFAULT_ACCEPT_CLOSE_NEAR = True


@dataclass
class FRVPParams:
    lookback: int = DEFAULT_LOOKBACK
    n_bins: int = DEFAULT_N_BINS
    va_pct: float = DEFAULT_VA_PCT
    cut_tolerance_pct: float = DEFAULT_CUT_TOLERANCE_PCT
    min_profile_bars: int = DEFAULT_MIN_PROFILE_BARS
    accept_body_cross: bool = DEFAULT_ACCEPT_BODY_CROSS
    accept_close_near: bool = DEFAULT_ACCEPT_CLOSE_NEAR


# ─────────────────────────────────────────────────────────────────────────
# f_vp — uniform-density volume profile over an inclusive position range
# ─────────────────────────────────────────────────────────────────────────

def f_vp(df: pd.DataFrame, near_pos: int, far_pos: int, n_bins: int = DEFAULT_N_BINS,
         va_pct: float = DEFAULT_VA_PCT) -> tuple[float, float, float]:
    """Volume profile over pandas positions [far_pos, near_pos] inclusive
    (far_pos <= near_pos; older..newer). Direct port of Pine's f_vp —
    proportional per-candle volume distribution across overlapping bins,
    POC = first argmax bin, VA expands from POC with ties favoring UP.
    Returns (poc, vah, val) — all NaN if the range is degenerate."""
    if far_pos > near_pos or far_pos < 0:
        return np.nan, np.nan, np.nan

    sl = slice(far_pos, near_pos + 1)
    high = df["High"].to_numpy()[sl]
    low = df["Low"].to_numpy()[sl]
    vol = df["Volume"].to_numpy()[sl]

    p_min = low.min()
    p_max = high.max()
    price_range = p_max - p_min
    if price_range <= 0:
        return np.nan, np.nan, np.nan
    bin_width = price_range / n_bins

    bins = np.zeros(n_bins)
    candle_range = np.maximum(high - low, 1e-6)
    vol_per_point = np.nan_to_num(vol, nan=0.0) / candle_range
    low_bin = np.clip(np.floor((low - p_min) / bin_width).astype(int), 0, n_bins - 1)
    high_bin = np.clip(np.floor((high - p_min) / bin_width).astype(int), 0, n_bins - 1)

    for j in range(len(high)):
        lb, hb = low_bin[j], high_bin[j]
        for b in range(lb, hb + 1):
            bin_lo = p_min + b * bin_width
            bin_hi = bin_lo + bin_width
            overlap = min(high[j], bin_hi) - max(low[j], bin_lo)
            if overlap > 0:
                bins[b] += vol_per_point[j] * overlap

    total_vol = bins.sum()
    max_bin_vol = bins.max()
    if total_vol <= 0 or max_bin_vol <= 0:
        return np.nan, np.nan, np.nan

    poc_bin = int(np.argmax(bins))  # first match on ties, matching Pine's array.indexof
    poc = p_min + (poc_bin + 0.5) * bin_width

    target_vol = total_vol * va_pct
    accumulated = bins[poc_bin]
    lo_b = hi_b = poc_bin
    for _ in range(n_bins * 2):
        if accumulated >= target_vol:
            break
        lower_vol = bins[lo_b - 1] if lo_b > 0 else -1.0
        upper_vol = bins[hi_b + 1] if hi_b < n_bins - 1 else -1.0
        if upper_vol >= lower_vol and hi_b < n_bins - 1:  # tie favors UP, matches Pine
            hi_b += 1
            accumulated += bins[hi_b]
        elif lo_b > 0:
            lo_b -= 1
            accumulated += bins[lo_b]
        else:
            break

    vah = p_min + (hi_b + 1) * bin_width
    val = p_min + lo_b * bin_width
    return float(poc), float(vah), float(val)


# ─────────────────────────────────────────────────────────────────────────
# f_find_cut — nearest-to-now scan for a valid POC cut
# ─────────────────────────────────────────────────────────────────────────

def f_date_key(ts) -> int | None:
    if ts is None or pd.isna(ts):
        return None
    d = pd.Timestamp(ts)
    return d.year * 10000 + d.month * 100 + d.day


def f_find_cut(df: pd.DataFrame, poc: float, near_pos: int, far_pos: int,
               excluded_date1: int | None, excluded_date2: int | None,
               tolerance_pct: float = DEFAULT_CUT_TOLERANCE_PCT,
               min_profile_bars: int = DEFAULT_MIN_PROFILE_BARS,
               accept_body_cross: bool = DEFAULT_ACCEPT_BODY_CROSS,
               accept_close_near: bool = DEFAULT_ACCEPT_CLOSE_NEAR,
               t_pos: int | None = None) -> int | None:
    """Scans pandas positions from near_pos down to far_pos (nearest-to-now
    first, matching Pine's "searches from nearest eligible candle toward the
    older anchor"). Accepts the first candidate whose candle body crosses
    poc OR whose close is within tolerance_pct of poc, has enough bars
    remaining, and falls on a calendar date not already used by an earlier
    cut. Returns the accepted position, or None if no fake cut is possible."""
    if pd.isna(poc) or near_pos < far_pos or t_pos is None:
        return None

    tolerance = abs(poc) * tolerance_pct / 100.0
    dates = df.index

    for cpos in range(near_pos, far_pos - 1, -1):
        pine_offset_i = t_pos - cpos  # Pine's "i" for this candidate
        enough_bars = (pine_offset_i - 1) >= min_profile_bars  # i - startOff(=1) >= minProfileBars

        o = df["Open"].iloc[cpos]
        c = df["Close"].iloc[cpos]
        body_cross = min(o, c) <= poc <= max(o, c)
        close_near = abs(c - poc) <= tolerance
        accepted = (accept_body_cross and body_cross) or (accept_close_near and close_near)

        candidate_date = f_date_key(dates[cpos])
        unique_date = (excluded_date1 is None or candidate_date != excluded_date1) and \
                      (excluded_date2 is None or candidate_date != excluded_date2)

        if enough_bars and accepted and unique_date:
            return cpos

    return None


# ─────────────────────────────────────────────────────────────────────────
# f_anchor_asof — swing TOP/BOT anchor selection, strictly before t_pos-1
# ─────────────────────────────────────────────────────────────────────────

def f_anchor_asof(df: pd.DataFrame, t_pos: int, lookback: int = DEFAULT_LOOKBACK
                  ) -> tuple[int, str, float, float] | None:
    """Searches pandas positions [t_pos-1-lookback, t_pos-2] (Pine offsets
    [2, lookback+1] relative to evalOff=1) for the swing extreme (High max
    or Low min) with the larger %-distance from close at position t_pos-1
    (Pine's close[evalOff]=close[1]). Ties favor TOP. Returns
    (anchor_pos, "TOP"|"BOT", price, pct) or None if out of range."""
    start_pos = t_pos - 1 - lookback
    end_pos = t_pos - 2
    if start_pos < 0 or end_pos < start_pos:
        return None

    high = df["High"].to_numpy()
    low = df["Low"].to_numpy()
    sub_high = high[start_pos:end_pos + 1]
    sub_low = low[start_pos:end_pos + 1]

    hi_idx = int(np.argmax(sub_high))
    lo_idx = int(np.argmin(sub_low))
    highest_price = float(sub_high[hi_idx])
    lowest_price = float(sub_low[lo_idx])
    highest_pos = start_pos + hi_idx
    lowest_pos = start_pos + lo_idx

    comparison_close = float(df["Close"].iloc[t_pos - 1])
    pct_from_high = abs(highest_price - comparison_close) / highest_price * 100.0 if highest_price != 0 else np.nan
    pct_from_low = abs(comparison_close - lowest_price) / lowest_price * 100.0 if lowest_price != 0 else np.nan

    if pd.isna(pct_from_high) or pd.isna(pct_from_low):
        return None

    use_top = pct_from_high >= pct_from_low  # tie favors TOP, matches Pine
    if use_top:
        return highest_pos, "TOP", highest_price, pct_from_high
    return lowest_pos, "BOT", lowest_price, pct_from_low


# ─────────────────────────────────────────────────────────────────────────
# f_calc_asof — full adaptive 3-cut chain, evaluated as of t_pos (evalOff=1)
# ─────────────────────────────────────────────────────────────────────────

def f_calc_asof(df: pd.DataFrame, t_pos: int, params: FRVPParams | None = None) -> dict:
    """Full port of f_calc_asof(1) for evaluation position t_pos. Missing
    cuts remain None. If a next cut cannot be found, the last valid cut (or
    the anchor itself, if no cuts were found at all) becomes the final
    profile boundary — never a fake/duplicate cut. Every input to this
    function comes from positions < t_pos (never t_pos itself)."""
    p = params or FRVPParams()

    out = {
        "anchor_pos": None, "anchor_type": None, "anchor_price": None, "anchor_pct": None,
        "cut1_pos": None, "cut2_pos": None, "cut3_pos": None,
        "poc1": None, "poc2": None, "poc3": None,
        "confirmed_poc": None, "confirmed_vah": None, "confirmed_val": None,
        "completed_cuts": 0, "final_pos": None, "profile_bars": None,
    }

    anchor = f_anchor_asof(df, t_pos, p.lookback)
    if anchor is None:
        return out
    anchor_pos, anchor_type, anchor_price, anchor_pct = anchor
    out.update(anchor_pos=anchor_pos, anchor_type=anchor_type,
               anchor_price=anchor_price, anchor_pct=anchor_pct)
    final_pos = anchor_pos

    near_edge = t_pos - 1  # Pine offset 1

    # Step 1
    poc1, _, _ = f_vp(df, near_edge, anchor_pos, p.n_bins, p.va_pct)
    out["poc1"] = poc1
    cut1_pos = f_find_cut(df, poc1, t_pos - 2, anchor_pos, None, None,
                          p.cut_tolerance_pct, p.min_profile_bars,
                          p.accept_body_cross, p.accept_close_near, t_pos)

    if cut1_pos is not None:
        out["cut1_pos"] = cut1_pos
        final_pos = cut1_pos
        out["completed_cuts"] = 1
        cut1_date = f_date_key(df.index[cut1_pos])

        # Step 2
        poc2, _, _ = f_vp(df, near_edge, cut1_pos, p.n_bins, p.va_pct)
        out["poc2"] = poc2
        cut2_pos = f_find_cut(df, poc2, t_pos - 2, cut1_pos, cut1_date, None,
                              p.cut_tolerance_pct, p.min_profile_bars,
                              p.accept_body_cross, p.accept_close_near, t_pos)

        if cut2_pos is not None:
            out["cut2_pos"] = cut2_pos
            final_pos = cut2_pos
            out["completed_cuts"] = 2
            cut2_date = f_date_key(df.index[cut2_pos])

            # Step 3
            poc3, _, _ = f_vp(df, near_edge, cut2_pos, p.n_bins, p.va_pct)
            out["poc3"] = poc3
            cut3_pos = f_find_cut(df, poc3, t_pos - 2, cut2_pos, cut1_date, cut2_date,
                                  p.cut_tolerance_pct, p.min_profile_bars,
                                  p.accept_body_cross, p.accept_close_near, t_pos)

            if cut3_pos is not None:
                out["cut3_pos"] = cut3_pos
                final_pos = cut3_pos
                out["completed_cuts"] = 3

    final_poc, final_vah, final_val = f_vp(df, near_edge, final_pos, p.n_bins, p.va_pct)
    out["confirmed_poc"] = final_poc
    out["confirmed_vah"] = final_vah
    out["confirmed_val"] = final_val
    out["final_pos"] = final_pos
    out["profile_bars"] = near_edge - final_pos + 1
    return out


# ─────────────────────────────────────────────────────────────────────────
# Batch attach — rolling confirmed FRVP for a full price history
# ─────────────────────────────────────────────────────────────────────────

def attach_confirmed_frvp(df: pd.DataFrame, params: FRVPParams | None = None,
                          min_start_pos: int | None = None) -> pd.DataFrame:
    """Adds confirmed_poc/confirmed_vah/confirmed_val + audit columns
    (anchor_date, cut1_date, cut2_date, cut3_date, completed_cuts) to a
    copy of df, computed as-of each row's t_pos (using only data strictly
    before that row — see module docstring for the no-lookahead guarantee).
    Sequential by construction (each day's cut chain depends on the prior
    days' bars, same as the Pine source) — this is the one part of the
    pipeline that cannot be vectorized away."""
    p = params or FRVPParams()
    n = len(df)
    min_pos = min_start_pos if min_start_pos is not None else (p.lookback + 3)

    cols = {
        "confirmed_poc": np.full(n, np.nan), "confirmed_vah": np.full(n, np.nan),
        "confirmed_val": np.full(n, np.nan), "completed_cuts": np.zeros(n, dtype=int),
    }
    anchor_date = [None] * n
    cut1_date = [None] * n
    cut2_date = [None] * n
    cut3_date = [None] * n

    for t_pos in range(min_pos, n):
        res = f_calc_asof(df, t_pos, p)
        cols["confirmed_poc"][t_pos] = res["confirmed_poc"] if res["confirmed_poc"] is not None else np.nan
        cols["confirmed_vah"][t_pos] = res["confirmed_vah"] if res["confirmed_vah"] is not None else np.nan
        cols["confirmed_val"][t_pos] = res["confirmed_val"] if res["confirmed_val"] is not None else np.nan
        cols["completed_cuts"][t_pos] = res["completed_cuts"]
        if res["anchor_pos"] is not None:
            anchor_date[t_pos] = df.index[res["anchor_pos"]]
        if res["cut1_pos"] is not None:
            cut1_date[t_pos] = df.index[res["cut1_pos"]]
        if res["cut2_pos"] is not None:
            cut2_date[t_pos] = df.index[res["cut2_pos"]]
        if res["cut3_pos"] is not None:
            cut3_date[t_pos] = df.index[res["cut3_pos"]]

    out = df.copy()
    out["confirmed_poc"] = cols["confirmed_poc"]
    out["confirmed_vah"] = cols["confirmed_vah"]
    out["confirmed_val"] = cols["confirmed_val"]
    out["completed_cuts"] = cols["completed_cuts"]
    out["anchor_date"] = anchor_date
    out["cut1_date"] = cut1_date
    out["cut2_date"] = cut2_date
    out["cut3_date"] = cut3_date
    return out
