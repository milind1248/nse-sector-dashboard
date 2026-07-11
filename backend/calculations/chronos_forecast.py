"""Zero-shot price forecast using Amazon Chronos-Bolt (time-series foundation model).

No per-stock training — the pre-trained model reads the recent price series
and outputs quantile forecasts. Model (~190 MB) downloads once, then cached.
Gracefully unavailable when torch/chronos aren't installed (e.g. Streamlit Cloud).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_PIPELINE = None
_FAILED: str | None = None
MODEL_NAME = "amazon/chronos-bolt-small"


def is_available() -> bool:
    try:
        import torch  # noqa: F401
        import chronos  # noqa: F401
        return True
    except Exception:
        return False


def _load():
    global _PIPELINE, _FAILED
    if _PIPELINE is not None or _FAILED:
        return _PIPELINE
    try:
        from chronos import BaseChronosPipeline
        _PIPELINE = BaseChronosPipeline.from_pretrained(MODEL_NAME, device_map="cpu")
    except Exception as e:
        _FAILED = str(e)
    return _PIPELINE


def chronos_price_forecast(close: pd.Series, horizon: int = 30) -> dict:
    """Forecast `horizon` trading days ahead. Returns median + 10/90% band."""
    pipe = _load()
    if pipe is None:
        return {"error": f"Chronos unavailable: {_FAILED or 'not installed'}"}

    import torch

    s = close.dropna().astype(float)
    if len(s) < 60:
        return {"error": f"Need >=60 bars, got {len(s)}"}
    context = torch.tensor(s.values[-512:], dtype=torch.float32)

    try:
        quantiles, mean = pipe.predict_quantiles(
            context, prediction_length=horizon,
            quantile_levels=[0.1, 0.5, 0.9],
        )
    except Exception as e:
        return {"error": str(e)}

    q = quantiles[0].numpy()  # (horizon, 3)
    last_date = pd.Timestamp(s.index[-1])
    fdates = pd.bdate_range(last_date + pd.Timedelta(days=1), periods=horizon)

    last_price = float(s.iloc[-1])
    end_med = float(q[-1, 1])
    trend_pct = (end_med - last_price) / last_price * 100
    direction = ("Bullish" if trend_pct > 1.5 else
                 "Bearish" if trend_pct < -1.5 else "Neutral")

    return {
        "error": None,
        "model": MODEL_NAME.split("/")[-1],
        "forecast_dates": [d.date() for d in fdates],
        "yhat":       [round(float(v), 2) for v in q[:, 1]],
        "yhat_lower": [round(float(v), 2) for v in q[:, 0]],
        "yhat_upper": [round(float(v), 2) for v in q[:, 2]],
        "last_price": round(last_price, 2),
        "trend_pct": round(trend_pct, 2),
        "direction": direction,
        "context_bars": int(len(context)),
    }
