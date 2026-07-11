"""GARCH(1,1) volatility forecast + position-sizing helper.

Volatility is far more predictable than returns — used here for risk
management (stop distance, position size), not direction calls.
Falls back to EWMA (RiskMetrics lambda=0.94) if the arch package is missing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def garch_forecast(close: pd.Series, horizon: int = 30) -> dict:
    """Fit GARCH(1,1) on daily % returns, forecast `horizon` days of vol."""
    s = close.dropna().astype(float)
    if len(s) < 150:
        return {"error": f"Need >=150 bars, got {len(s)}"}
    rets = s.pct_change().dropna() * 100  # in %

    hist_vol_20 = float(rets.tail(20).std() * np.sqrt(TRADING_DAYS))
    hist_vol_full = float(rets.std() * np.sqrt(TRADING_DAYS))

    engine = "GARCH(1,1)"
    try:
        from arch import arch_model
        am = arch_model(rets, vol="Garch", p=1, q=1, dist="t")
        res = am.fit(disp="off", show_warning=False)
        fc = res.forecast(horizon=horizon, reindex=False)
        daily_vol_path = np.sqrt(fc.variance.values[0])          # % per day
        ann_vol_path = daily_vol_path * np.sqrt(TRADING_DAYS)    # annualized %
        persistence = float(res.params.get("alpha[1]", 0) + res.params.get("beta[1]", 0))
    except Exception:
        engine = "EWMA (lambda=0.94)"
        lam = 0.94
        ewma_var = rets.pow(2).ewm(alpha=1 - lam).mean().iloc[-1]
        daily_vol_path = np.full(horizon, np.sqrt(ewma_var))
        ann_vol_path = daily_vol_path * np.sqrt(TRADING_DAYS)
        persistence = lam

    cur = float(ann_vol_path[0])
    end = float(ann_vol_path[-1])
    regime = ("HIGH" if cur > hist_vol_full * 1.25
              else "LOW" if cur < hist_vol_full * 0.75 else "NORMAL")
    trend = "rising" if end > cur * 1.05 else ("falling" if end < cur * 0.95 else "stable")

    # Expected 1-day move at 1 sigma, in ₹ (for stop placement)
    last_price = float(s.iloc[-1])
    exp_daily_move = last_price * float(daily_vol_path[0]) / 100

    return {
        "error": None,
        "engine": engine,
        "ann_vol_path": [round(float(v), 2) for v in ann_vol_path],
        "current_ann_vol": round(cur, 1),
        "forecast_end_vol": round(end, 1),
        "hist_vol_20d": round(hist_vol_20, 1),
        "hist_vol_full": round(hist_vol_full, 1),
        "vol_regime": regime,
        "vol_trend": trend,
        "persistence": round(persistence, 3),
        "last_price": round(last_price, 2),
        "exp_daily_move": round(exp_daily_move, 2),
    }


def position_size(capital: float, risk_pct: float, price: float,
                  exp_daily_move: float, stop_sigmas: float = 2.0) -> dict:
    """Vol-adjusted sizing: stop = stop_sigmas x expected daily move."""
    stop_dist = stop_sigmas * exp_daily_move
    if stop_dist <= 0 or price <= 0:
        return {"qty": 0, "stop_price": price, "risk_amount": 0, "position_value": 0}
    risk_amount = capital * risk_pct / 100
    qty = int(risk_amount / stop_dist)
    return {
        "qty": qty,
        "stop_price": round(price - stop_dist, 2),
        "stop_dist": round(stop_dist, 2),
        "risk_amount": round(risk_amount, 0),
        "position_value": round(qty * price, 0),
    }
