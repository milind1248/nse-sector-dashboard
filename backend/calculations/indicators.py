"""Technical indicator calculations using pandas-ta."""
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _ensure_close(df: pd.DataFrame) -> Optional[pd.Series]:
    # yfinance >=0.2.x may return MultiIndex columns like ("Close", "TICKER")
    if isinstance(df.columns, pd.MultiIndex):
        for level0 in ["Close", "close", "Adj Close"]:
            if level0 in df.columns.get_level_values(0):
                s = df[level0]
                if isinstance(s, pd.DataFrame):
                    s = s.iloc[:, 0]
                return s.dropna()
    for col in ["Close", "close", "Adj Close"]:
        if col in df.columns:
            s = df[col]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            return s.dropna()
    return None


def _rsi_pure(close: pd.Series, period: int = 14) -> Optional[float]:
    """Pure-pandas RSI fallback."""
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, float("nan"))
    rsi   = 100 - (100 / (1 + rs))
    v = rsi.dropna()
    return round(float(v.iloc[-1]), 2) if not v.empty else None


def _ema_pure(close: pd.Series, period: int) -> Optional[float]:
    """Pure-pandas EMA fallback."""
    if len(close) < period:
        return None
    ema = close.ewm(span=period, adjust=False).mean()
    v = ema.dropna()
    return round(float(v.iloc[-1]), 2) if not v.empty else None


def compute_rsi(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    close = _ensure_close(df)
    if close is None or len(close) < period + 1:
        return None
    try:
        import pandas_ta as ta
        s = ta.rsi(close, length=period)
        val = s.dropna().iloc[-1] if s is not None and not s.dropna().empty else None
        return round(float(val), 2) if val is not None else None
    except Exception:
        return _rsi_pure(close, period)


def compute_ema(df: pd.DataFrame, period: int) -> Optional[float]:
    close = _ensure_close(df)
    if close is None or len(close) < period:
        return None
    try:
        import pandas_ta as ta
        s = ta.ema(close, length=period)
        val = s.dropna().iloc[-1] if s is not None and not s.dropna().empty else None
        return round(float(val), 2) if val is not None else None
    except Exception:
        return _ema_pure(close, period)


def compute_macd(df: pd.DataFrame) -> tuple[Optional[float], Optional[float]]:
    """Returns (macd_line, signal_line)."""
    close = _ensure_close(df)
    if close is None or len(close) < 26:
        return None, None
    try:
        import pandas_ta as ta
        result = ta.macd(close)
        if result is None or result.empty:
            raise ValueError("empty")
        macd_col = [c for c in result.columns if "MACD_" in c and "h" not in c.lower() and "s" not in c.lower()]
        sig_col  = [c for c in result.columns if "MACDs_" in c]
        macd_val = round(float(result[macd_col[0]].dropna().iloc[-1]), 4) if macd_col else None
        sig_val  = round(float(result[sig_col[0]].dropna().iloc[-1]), 4) if sig_col else None
        return macd_val, sig_val
    except Exception:
        # Pure-pandas MACD fallback
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd  = ema12 - ema26
        sig   = macd.ewm(span=9, adjust=False).mean()
        return round(float(macd.iloc[-1]), 4), round(float(sig.iloc[-1]), 4)


def compute_adx(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    try:
        import pandas_ta as ta
        high  = df.get("High", df.get("high"))
        low   = df.get("Low",  df.get("low"))
        close = _ensure_close(df)
        if high is None or low is None or close is None or len(close) < period * 2:
            return None
        result = ta.adx(high, low, close, length=period)
        if result is None or result.empty:
            return None
        adx_col = [c for c in result.columns if "ADX_" in c]
        return round(float(result[adx_col[0]].dropna().iloc[-1]), 2) if adx_col else None
    except Exception as e:
        logger.debug(f"ADX skipped (pandas_ta unavailable): {e}")
        return None


def compute_volume_ratio(df: pd.DataFrame, avg_period: int = 20) -> Optional[float]:
    vol = None
    for col in ["Volume", "volume"]:
        if col in df.columns:
            v = df[col]
            vol = (v.iloc[:, 0] if isinstance(v, pd.DataFrame) else v).dropna()
            break
    if vol is None or len(vol) < avg_period + 1:
        return None
    avg  = float(vol.iloc[-(avg_period + 1):-1].mean())
    last = float(vol.iloc[-1])
    return round(last / avg, 2) if avg > 0 else None


def compute_all_indicators(df: pd.DataFrame) -> dict:
    """Compute all needed indicators from OHLCV df. Returns dict."""
    return {
        "rsi_14":      compute_rsi(df, 14),
        "ema_20":      compute_ema(df, 20),
        "ema_50":      compute_ema(df, 50),
        "ema_100":     compute_ema(df, 100),
        "ema_200":     compute_ema(df, 200),
        "macd":        compute_macd(df)[0],
        "macd_signal": compute_macd(df)[1],
        "adx":         compute_adx(df, 14),
        "volume_ratio": compute_volume_ratio(df, 20),
    }


def ema_signal(close: float, ema20: Optional[float], ema50: Optional[float],
               ema200: Optional[float]) -> str:
    """Returns 'Bullish', 'Bearish', or 'Neutral' based on EMA stack."""
    if None in (ema20, ema50, ema200):
        return "Neutral"
    if close > ema20 > ema50 > ema200:
        return "Bullish"
    if close < ema20 < ema50 < ema200:
        return "Bearish"
    return "Neutral"
