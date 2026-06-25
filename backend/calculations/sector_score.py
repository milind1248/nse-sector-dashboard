"""Compute 0-100 momentum score for each sector."""
from typing import Optional
from config import SCORE_WEIGHTS, SCORE_LABELS


def _norm_rsi(rsi: Optional[float]) -> float:
    """Map RSI 0-100 → score 0-10."""
    if rsi is None:
        return 5.0
    return round(max(0, min(10, (rsi - 30) / 4)), 2)


def _norm_rs(rs: Optional[float]) -> float:
    """Map RS-Ratio (typically 90-110) → score 0-25."""
    if rs is None:
        return 12.5
    return round(max(0, min(25, (rs - 90) / 20 * 25)), 2)


def _norm_momentum(pct_1w: Optional[float], pct_1m: Optional[float]) -> float:
    """Blend 1W and 1M returns → score 0-20."""
    if pct_1w is None and pct_1m is None:
        return 10.0
    blended = 0.0
    if pct_1w is not None:
        blended += pct_1w * 0.4
    if pct_1m is not None:
        blended += pct_1m * 0.6
    return round(max(0, min(20, 10 + blended)), 2)


def _norm_ad(ad_ratio: Optional[float]) -> float:
    """Map A/D ratio → score 0-15."""
    if ad_ratio is None:
        return 7.5
    return round(max(0, min(15, ad_ratio / 4 * 15)), 2)


def _norm_fii(fii_net: Optional[float]) -> float:
    """Map FII net flow → score 0-10."""
    if fii_net is None:
        return 5.0
    if fii_net > 5000:   return 10.0
    if fii_net > 2000:   return 8.0
    if fii_net > 500:    return 6.5
    if fii_net > 0:      return 5.5
    if fii_net > -500:   return 4.0
    if fii_net > -2000:  return 2.5
    return 0.0


def _norm_dii(dii_net: Optional[float]) -> float:
    """Map DII net flow → score 0-5."""
    if dii_net is None:
        return 2.5
    return round(max(0, min(5, 2.5 + dii_net / 4000 * 2.5)), 2)


def _norm_volume(vol_ratio: Optional[float]) -> float:
    """Map volume ratio → score 0-5."""
    if vol_ratio is None:
        return 2.5
    return round(max(0, min(5, vol_ratio / 3 * 5)), 2)


def _price_vs_ema200(close: Optional[float], ema200: Optional[float]) -> float:
    if close is None or ema200 is None:
        return 5.0
    return 10.0 if close > ema200 else 0.0


def compute_sector_score(
    rs_vs_nifty: Optional[float] = None,
    pct_1w: Optional[float] = None,
    pct_1m: Optional[float] = None,
    ad_ratio: Optional[float] = None,
    rsi_14: Optional[float] = None,
    close: Optional[float] = None,
    ema_200: Optional[float] = None,
    fii_flow: Optional[float] = None,
    dii_flow: Optional[float] = None,
    volume_ratio: Optional[float] = None,
) -> float:
    score = (
        _norm_rs(rs_vs_nifty)
        + _norm_momentum(pct_1w, pct_1m)
        + _norm_ad(ad_ratio)
        + _norm_rsi(rsi_14)
        + _price_vs_ema200(close, ema_200)
        + _norm_fii(fii_flow)
        + _norm_dii(dii_flow)
        + _norm_volume(volume_ratio)
    )
    return round(min(100, max(0, score)), 1)


def score_label(score: float) -> tuple[str, str]:
    """Returns (label, color_hex) for a score."""
    for (low, high), (label, color) in SCORE_LABELS.items():
        if low <= score <= high:
            return label, color
    return "Neutral", "#FFD600"
