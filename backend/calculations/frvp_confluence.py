"""FRVP + H-M + 20-EMA-Pullback confluence scanner — the validated "complete"
strategy from the standalone ablation study (20y Nifty 500 backtest: 60.4%
win rate / +2.67% avg return at 20-day hold, std dev 9.50 — the best
risk-adjusted variant of 7 tested. See the research package for full
methodology at D:\\Trading\\2026\\frvp_hm_ema_scanner\\).

Entry condition (all three simultaneously true, fresh signal + 10-bar
cooldown to avoid re-counting a persistent regime):
    H-M buy regime (RSI trending above its WMA)
    AND Close > VAH (Fixed-Range Volume Profile, rolling 60-bar window)
    AND EMA-20 pullback (within 1% of a rising EMA20, bullish candle,
        rising SMA50, price above SMA200)

Every network/compute call here is wrapped so a single stock's failure
can never take down a batch scan or crash the page.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.calculations.hm_indicators import add_indicators, generate_signals

COOLDOWN_BARS = 10
EMA_TOLERANCE_PCT = 1.0
ATR_PERIOD = 14
ATR_BUFFER_MULT = 0.5


def compute_frvp(df: pd.DataFrame, window: int = 60, n_bins: int = 40, va_pct: float = 0.70) -> pd.DataFrame:
    """Rolling fixed-window volume profile (POC/VAH/VAL). Trailing window
    EXCLUDES the current bar — no lookahead."""
    high = df["High"].to_numpy()
    low = df["Low"].to_numpy()
    vol = df["Volume"].to_numpy()
    n = len(df)
    poc = np.full(n, np.nan)
    vah = np.full(n, np.nan)
    val = np.full(n, np.nan)

    for i in range(window, n):
        sl = slice(i - window, i)
        h, l, v = high[sl], low[sl], vol[sl]
        p_min, p_max = l.min(), h.max()
        price_range = p_max - p_min
        if price_range <= 0:
            continue
        bin_width = price_range / n_bins
        bins = np.zeros(n_bins)
        candle_range = np.maximum(h - l, 1e-6)
        vol_per_point = v / candle_range
        low_bin = np.clip(((l - p_min) / bin_width).astype(int), 0, n_bins - 1)
        high_bin = np.clip(((h - p_min) / bin_width).astype(int), 0, n_bins - 1)
        for j in range(len(h)):
            lb, hb = low_bin[j], high_bin[j]
            for b in range(lb, hb + 1):
                bin_lo = p_min + b * bin_width
                bin_hi = bin_lo + bin_width
                overlap = min(h[j], bin_hi) - max(l[j], bin_lo)
                if overlap > 0:
                    bins[b] += vol_per_point[j] * overlap

        total_vol = bins.sum()
        if total_vol <= 0:
            continue
        poc_bin = int(np.argmax(bins))
        poc[i] = p_min + (poc_bin + 0.5) * bin_width

        target_vol = total_vol * va_pct
        accumulated = bins[poc_bin]
        lo_b, hi_b = poc_bin, poc_bin
        for _ in range(n_bins * 2):
            if accumulated >= target_vol:
                break
            lower_vol = bins[lo_b - 1] if lo_b > 0 else -1.0
            upper_vol = bins[hi_b + 1] if hi_b < n_bins - 1 else -1.0
            if upper_vol >= lower_vol and hi_b < n_bins - 1:
                hi_b += 1
                accumulated += bins[hi_b]
            elif lo_b > 0:
                lo_b -= 1
                accumulated += bins[lo_b]
            else:
                break
        vah[i] = p_min + (hi_b + 1) * bin_width
        val[i] = p_min + lo_b * bin_width

    out = df.copy()
    out["POC"] = poc
    out["VAH"] = vah
    out["VAL"] = val
    return out


def compute_ema_pullback(df: pd.DataFrame) -> pd.DataFrame:
    """Within 1% of a rising EMA20, bullish candle confirmation, rising
    SMA50, price above SMA200."""
    out = df.copy()
    out["EMA20"] = out["Close"].ewm(span=20, adjust=False).mean()
    out["SMA50"] = out["Close"].rolling(50).mean()
    out["SMA200"] = out["Close"].rolling(200).mean()

    out["sma50_rising"] = out["SMA50"] > out["SMA50"].shift(5)
    out["ema20_slope_10"] = out["EMA20"] > out["EMA20"].shift(10)
    out["s200_ok"] = out["Close"] > out["SMA200"]

    ema_dist_pct = (out["Close"] - out["EMA20"]).abs() / out["EMA20"] * 100
    within_tolerance = ema_dist_pct <= EMA_TOLERANCE_PCT
    close_above_ema = out["Close"] > out["EMA20"]
    bullish_candle = out["Close"] > out["Open"]

    out["EMA_PULLBACK_OK"] = (
        within_tolerance
        & close_above_ema
        & bullish_candle
        & out["ema20_slope_10"]
        & out["sma50_rising"]
    )
    return out


def _atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _dedup_with_cooldown(raw: pd.Series, cooldown_bars: int = COOLDOWN_BARS) -> np.ndarray:
    fresh = raw & ~raw.shift(1, fill_value=False)
    keep = np.zeros(len(raw), dtype=bool)
    last_sig = -cooldown_bars - 1
    for i in np.where(fresh.to_numpy())[0]:
        if i - last_sig > cooldown_bars:
            keep[i] = True
            last_sig = i
    return keep


def compute_confluence(df: pd.DataFrame) -> pd.DataFrame:
    """Attaches HM_BUY_REGIME, ABOVE_VAH, EMA_PULLBACK_OK, CONFLUENCE_SIGNAL
    (deduped fresh + 10-bar cooldown), ATR, and StopLoss columns."""
    out = compute_frvp(df)
    out = compute_ema_pullback(out)
    out["ATR"] = _atr(out)

    try:
        hm = add_indicators(out[["Open", "High", "Low", "Close", "Volume"]])
        hm = generate_signals(hm, min_score=70, confirmation_mode="Balanced")
        out["HM_BUY_REGIME"] = hm["HM_BUY_REGIME"].reindex(out.index).fillna(False)
    except Exception:
        out["HM_BUY_REGIME"] = False

    out["ABOVE_VAH"] = out["Close"] > out["VAH"]
    raw_confluence = out["HM_BUY_REGIME"] & out["ABOVE_VAH"] & out["EMA_PULLBACK_OK"]
    out["CONFLUENCE_SIGNAL"] = _dedup_with_cooldown(raw_confluence.fillna(False))

    low_arr = out["Low"].to_numpy()
    atr_arr = out["ATR"].to_numpy()
    stop = low_arr - ATR_BUFFER_MULT * atr_arr
    out["StopLoss"] = stop
    return out


def scan_current_state(symbol: str, period: str = "2y") -> dict | None:
    """Live state for one stock — used by the scanner table. Returns the
    latest bar's status plus the most recent fresh confluence signal (if
    any within the fetched window). Never raises."""
    try:
        import yfinance as yf
        raw = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
        if raw is None or raw.empty or len(raw) < 60:
            return None
        if hasattr(raw.columns, "levels"):
            raw.columns = raw.columns.droplevel(1)
        raw = raw.rename(columns={c: c.title() for c in raw.columns})
        df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
        if len(df) < 60:
            return None

        sig = compute_confluence(df)
        last = sig.iloc[-1]
        fresh_idx = np.where(sig["CONFLUENCE_SIGNAL"].to_numpy())[0]
        last_signal_date = str(sig.index[fresh_idx[-1]])[:10] if len(fresh_idx) else None
        days_since = (len(sig) - 1 - fresh_idx[-1]) if len(fresh_idx) else None

        return {
            "Symbol": symbol.replace(".NS", ""),
            "CMP": round(float(last["Close"]), 2),
            "VAH": round(float(last["VAH"]), 2) if pd.notna(last["VAH"]) else None,
            "EMA20": round(float(last["EMA20"]), 2) if pd.notna(last["EMA20"]) else None,
            "HM Regime": bool(last["HM_BUY_REGIME"]),
            "Above VAH": bool(last["ABOVE_VAH"]) if pd.notna(last["ABOVE_VAH"]) else False,
            "EMA Pullback": bool(last["EMA_PULLBACK_OK"]) if pd.notna(last["EMA_PULLBACK_OK"]) else False,
            "Fresh Today": bool(last["CONFLUENCE_SIGNAL"]),
            "Last Signal Date": last_signal_date,
            "Days Since Signal": days_since,
            "StopLoss": round(float(last["StopLoss"]), 2) if pd.notna(last["StopLoss"]) else None,
        }
    except Exception:
        return None


def backtest_symbol(symbol: str, period: str = "3y", hold_days: tuple = (5, 10, 20)) -> pd.DataFrame:
    """Historical confluence trades for one stock — Symbol, SignalDate,
    EntryPrice, StopLoss, Ret5d%/Ret10d%/Ret20d%. Never raises."""
    try:
        import yfinance as yf
        raw = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
        if raw is None or raw.empty or len(raw) < 300:
            return pd.DataFrame()
        if hasattr(raw.columns, "levels"):
            raw.columns = raw.columns.droplevel(1)
        raw = raw.rename(columns={c: c.title() for c in raw.columns})
        df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
        if len(df) < 300:
            return pd.DataFrame()

        sig = compute_confluence(df)
        close_arr = sig["Close"].to_numpy()
        low_arr = sig["Low"].to_numpy()
        stop_arr = sig["StopLoss"].to_numpy()
        n = len(sig)
        sym_clean = symbol.replace(".NS", "")

        rows = []
        for i in np.where(sig["CONFLUENCE_SIGNAL"].to_numpy())[0]:
            row = {
                "Symbol": sym_clean,
                "SignalDate": sig.index[i].date() if hasattr(sig.index[i], "date") else sig.index[i],
                "EntryPrice": round(float(close_arr[i]), 2),
                "StopLoss": round(float(stop_arr[i]), 2) if not np.isnan(stop_arr[i]) else None,
            }
            for h in hold_days:
                j = i + h
                col = f"Ret{h}d%"
                if j < n:
                    row[col] = round((close_arr[j] - close_arr[i]) / close_arr[i] * 100, 2)
                else:
                    row[col] = np.nan
            rows.append(row)
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()
