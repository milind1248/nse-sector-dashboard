"""
AI Forecasting — Prophet (trend) + XGBoost (direction) ensemble for NSE stocks.

Public API
----------
run_prophet_forecast(close_series)  → dict  (30-day price forecast with bands)
run_xgb_direction(df_ohlcv)         → dict  (5-day direction probability + backtest)
"""
from __future__ import annotations

import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _col(df: pd.DataFrame, *names) -> pd.Series | None:
    for n in names:
        if n in df.columns:
            c = df[n]
            return c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
    return None


def _get_close(df: pd.DataFrame) -> pd.Series | None:
    s = _col(df, "Close", "close", "Adj Close")
    if s is None:
        return None
    s = s.dropna()
    return s if not s.empty else None


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build 60+ technical + calendar features from a full OHLCV DataFrame.
    All features are lag-safe (no future leakage).
    """
    close  = _get_close(df)
    high   = _col(df, "High", "high")
    low    = _col(df, "Low",  "low")
    open_  = _col(df, "Open", "open")
    vol    = _col(df, "Volume", "volume")

    if close is None:
        raise ValueError("No Close column found")

    feat = pd.DataFrame(index=close.index)
    feat["close"] = close.values

    # ── Lag returns ──────────────────────────────────────────────────────────
    for lag in [1, 2, 3, 5, 10, 21]:
        feat[f"ret_{lag}d"] = close.pct_change(lag).values

    # ── RSI(14) ──────────────────────────────────────────────────────────────
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rsi   = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
    feat["rsi_14"]       = rsi.values
    feat["rsi_change_3d"] = rsi.diff(3).values

    # ── EMA distances ────────────────────────────────────────────────────────
    ema20  = close.ewm(span=20,  adjust=False).mean()
    ema50  = close.ewm(span=50,  adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    feat["ema20_dist"]  = ((close - ema20)  / ema20  * 100).values
    feat["ema50_dist"]  = ((close - ema50)  / ema50  * 100).values
    feat["ema200_dist"] = ((close - ema200) / ema200 * 100).values
    feat["ema20_slope_5d"]  = ema20.pct_change(5).values * 100
    feat["ema50_slope_10d"] = ema50.pct_change(10).values * 100
    feat["price_above_ema200"] = (close > ema200).astype(int).values

    # ── MACD(12,26,9) ────────────────────────────────────────────────────────
    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_sig  = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_sig
    feat["macd_hist"]        = macd_hist.values
    feat["macd_hist_change"] = macd_hist.diff(3).values
    feat["macd_positive"]    = (macd_hist > 0).astype(int).values

    # ── ADX(14) ──────────────────────────────────────────────────────────────
    if high is not None and low is not None:
        try:
            tr   = pd.concat([(high - low).abs(),
                               (high - close.shift()).abs(),
                               (low  - close.shift()).abs()], axis=1).max(axis=1)
            dm_p = high.diff().clip(lower=0)
            dm_m = (-low.diff()).clip(lower=0)
            atr  = tr.ewm(span=14, adjust=False).mean()
            dip  = 100 * dm_p.ewm(span=14, adjust=False).mean() / atr.replace(0, np.nan)
            dim  = 100 * dm_m.ewm(span=14, adjust=False).mean() / atr.replace(0, np.nan)
            dx   = 100 * (dip - dim).abs() / (dip + dim).replace(0, np.nan)
            adx  = dx.ewm(span=14, adjust=False).mean()
            feat["adx"]          = adx.values
            feat["adx_change_5d"] = adx.diff(5).values
            feat["atr_14"]       = atr.values
            feat["atr_pct"]      = (atr / close * 100).values
        except Exception:
            feat["adx"] = feat["adx_change_5d"] = feat["atr_14"] = feat["atr_pct"] = np.nan
    else:
        feat["adx"] = feat["adx_change_5d"] = feat["atr_14"] = feat["atr_pct"] = np.nan

    # ── Bollinger Bands(20) ──────────────────────────────────────────────────
    bb_mid  = close.rolling(20).mean()
    bb_std  = close.rolling(20).std()
    bb_up   = bb_mid + 2 * bb_std
    bb_lo   = bb_mid - 2 * bb_std
    bb_range = (bb_up - bb_lo).replace(0, np.nan)
    feat["bb_position"] = ((close - bb_lo) / bb_range).values  # 0=lower, 1=upper
    feat["bb_width"]    = (bb_range / bb_mid * 100).values

    # ── Volatility ───────────────────────────────────────────────────────────
    feat["volatility_20d"] = close.pct_change().rolling(20).std().values * 100

    # ── Volume ───────────────────────────────────────────────────────────────
    if vol is not None:
        avg_vol = vol.rolling(20).mean().replace(0, np.nan)
        feat["vol_ratio"]  = (vol / avg_vol).values
        feat["vol_spike"]  = (vol > 1.5 * avg_vol).astype(int).values
        feat["vol_change"] = vol.pct_change(3).values
    else:
        feat["vol_ratio"] = feat["vol_spike"] = feat["vol_change"] = np.nan

    # ── Candlestick ──────────────────────────────────────────────────────────
    if open_ is not None and high is not None and low is not None:
        body       = (close - open_).abs()
        full_range = (high - low).replace(0, np.nan)
        feat["body_pct"]       = (body / full_range).values
        feat["upper_wick_pct"] = ((high - pd.concat([close, open_], axis=1).max(axis=1)) / full_range).values
        feat["lower_wick_pct"] = ((pd.concat([close, open_], axis=1).min(axis=1) - low) / full_range).values
        feat["is_bullish"]     = (close > open_).astype(int).values

        # Bullish engulfing
        prev_bearish = (close.shift(1) < open_.shift(1))
        curr_bullish = (close > open_)
        engulf       = curr_bullish & (close > open_.shift(1)) & (open_ < close.shift(1))
        feat["is_engulfing"] = (prev_bearish & engulf).astype(int).values

        # Hammer: lower wick >= 2x body, small upper wick
        hammer = (feat["lower_wick_pct"] >= 2 * feat["body_pct"]) & (feat["upper_wick_pct"] < 0.3) & (feat["is_bullish"] == 1)
        feat["is_hammer"] = hammer.astype(int) if hasattr(hammer, "astype") else 0
    else:
        for c in ["body_pct", "upper_wick_pct", "lower_wick_pct", "is_bullish", "is_engulfing", "is_hammer"]:
            feat[c] = np.nan

    # ── Calendar features ────────────────────────────────────────────────────
    idx      = pd.to_datetime(feat.index)
    day_arr  = np.array(idx.day,         dtype=int)
    feat["day_of_week"]   = np.array(idx.day_of_week, dtype=int)
    feat["month"]         = np.array(idx.month,       dtype=int)
    feat["week_of_month"] = (day_arr - 1) // 7 + 1
    # NSE monthly expiry ≈ last Thursday → approximate: last 5 trading days of month
    feat["is_expiry_week"] = (day_arr >= 23).astype(int)

    # ── 52-week position ─────────────────────────────────────────────────────
    high52 = close.rolling(252, min_periods=50).max()
    low52  = close.rolling(252, min_periods=50).min()
    feat["pct_from_52w_high"] = ((close - high52) / high52 * 100).values
    feat["pct_from_52w_low"]  = ((close - low52)  / low52  * 100).values

    # ── Higher High / Higher Low (60-day structure) ──────────────────────────
    def _hh_hl(i):
        if i < 60:
            return 0
        seg = close.iloc[i-60:i]
        mid = len(seg) // 2
        hh  = seg.iloc[mid:].max() > seg.iloc[:mid].max()
        hl  = seg.iloc[mid:].min() > seg.iloc[:mid].min()
        return int(hh and hl)
    feat["hh_hl_60d"] = [_hh_hl(i) for i in range(len(feat))]

    feat = feat.drop(columns=["close"])
    return feat


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: Prophet 30-day trend forecast
# ─────────────────────────────────────────────────────────────────────────────

def run_prophet_forecast(close_series: pd.Series, horizon_days: int = 30) -> dict:
    """
    Fit Facebook Prophet on a daily close price series.

    Parameters
    ----------
    close_series : pd.Series  — date-indexed daily close prices (≥180 bars)
    horizon_days : int        — number of future trading days to forecast

    Returns
    -------
    dict with keys:
        history_dates, history_prices  — past 6 months for chart
        forecast_dates, yhat, yhat_lower, yhat_upper  — future forecast
        trend_direction                — "Bullish" | "Bearish" | "Neutral"
        trend_pct                      — % change from today to end of forecast
        error                          — None or error message string
    """
    try:
        from prophet import Prophet

        s = close_series.dropna().copy()
        s.index = pd.to_datetime(s.index)

        if len(s) < 180:
            return {"error": f"Need ≥180 days of data, got {len(s)}"}

        df_p = pd.DataFrame({"ds": s.index, "y": s.values})

        m = Prophet(
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=True,
            changepoint_prior_scale=0.15,       # moderate flexibility
            seasonality_prior_scale=10,
            interval_width=0.80,
        )
        # Indian market: no Saturday/Sunday trading
        m.add_country_holidays(country_name="IN")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m.fit(df_p)

        # Generate future dates (weekdays only approximation)
        future = m.make_future_dataframe(periods=horizon_days, freq="B")
        forecast = m.predict(future)

        # Split history vs forecast
        cutoff = df_p["ds"].max()
        hist   = forecast[forecast["ds"] <= cutoff].tail(126)   # ~6 months history
        fcast  = forecast[forecast["ds"] >  cutoff].head(horizon_days)

        last_price  = float(s.iloc[-1])
        end_price   = float(fcast["yhat"].iloc[-1])
        trend_pct   = (end_price - last_price) / last_price * 100
        if trend_pct > 1.5:
            direction = "Bullish"
        elif trend_pct < -1.5:
            direction = "Bearish"
        else:
            direction = "Neutral"

        return {
            "error":           None,
            "history_dates":   hist["ds"].dt.date.tolist(),
            "history_prices":  hist["yhat"].tolist(),
            "history_actual":  s.tail(126).tolist(),
            "forecast_dates":  fcast["ds"].dt.date.tolist(),
            "yhat":            fcast["yhat"].tolist(),
            "yhat_lower":      fcast["yhat_lower"].tolist(),
            "yhat_upper":      fcast["yhat_upper"].tolist(),
            "trend_direction": direction,
            "trend_pct":       round(trend_pct, 2),
            "last_price":      last_price,
        }
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: XGBoost 5-day direction prediction + walk-forward backtest
# ─────────────────────────────────────────────────────────────────────────────

def run_xgb_direction(df_ohlcv: pd.DataFrame, forward_days: int = 5) -> dict:
    """
    Train XGBoost on technical features to predict 5-day price direction.
    Includes walk-forward backtesting on the last 6 months of held-out data.

    Parameters
    ----------
    df_ohlcv     : full OHLCV DataFrame (≥300 trading days recommended)
    forward_days : prediction horizon in trading days (default 5)

    Returns
    -------
    dict with keys:
        prob_up          — float 0-1, probability price rises in next N days
        direction        — "UP" | "DOWN"
        signal_label     — human-readable label with emoji
        backtest_accuracy — float 0-100 (walk-forward directional accuracy %)
        backtest_monthly  — list of {month, accuracy, n_trades}
        feature_importance — list of {feature, importance} sorted desc (top 15)
        n_features       — int
        n_train_bars     — int
        error            — None or error string
    """
    try:
        from xgboost import XGBClassifier
        from sklearn.preprocessing import RobustScaler
        from sklearn.metrics import accuracy_score

        close = _get_close(df_ohlcv)
        if close is None or len(close) < 300:
            return {"error": f"Need ≥300 days of data, got {len(close) if close is not None else 0}"}

        # ── Feature matrix ────────────────────────────────────────────────────
        feat = _build_features(df_ohlcv)

        # ── Target: did close go UP in next forward_days? ─────────────────────
        fwd_ret = close.pct_change(forward_days).shift(-forward_days)
        target  = (fwd_ret > 0).astype(int)

        # Align and clean
        combined = feat.copy()
        combined["_target"] = target.values
        combined = combined.replace([np.inf, -np.inf], np.nan).dropna()

        X = combined.drop(columns=["_target"])
        y = combined["_target"]

        if len(X) < 200:
            return {"error": f"Insufficient clean rows after NA drop: {len(X)}"}

        feature_names = X.columns.tolist()

        # ── Walk-forward backtest ─────────────────────────────────────────────
        # Train: rolling 252 bars, Test: next 21 bars, slide 21
        TRAIN_WIN  = 252
        TEST_WIN   = 21
        SLIDE      = 21

        monthly_results = []
        all_preds, all_true = [], []

        i = TRAIN_WIN
        while i + TEST_WIN <= len(X):
            X_tr = X.iloc[i - TRAIN_WIN : i]
            y_tr = y.iloc[i - TRAIN_WIN : i]
            X_te = X.iloc[i : i + TEST_WIN]
            y_te = y.iloc[i : i + TEST_WIN]

            scaler = RobustScaler()
            X_tr_s = scaler.fit_transform(X_tr)
            X_te_s = scaler.transform(X_te)

            model = XGBClassifier(
                n_estimators=150,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                use_label_encoder=False,
                eval_metric="logloss",
                verbosity=0,
                random_state=42,
            )
            model.fit(X_tr_s, y_tr)
            preds = model.predict(X_te_s)

            acc = accuracy_score(y_te, preds) * 100
            month_label = pd.to_datetime(X_te.index[0]).strftime("%b %Y")
            monthly_results.append({
                "month":    month_label,
                "accuracy": round(acc, 1),
                "n_bars":   len(y_te),
                "correct":  int((preds == y_te.values).sum()),
            })
            all_preds.extend(preds.tolist())
            all_true.extend(y_te.values.tolist())
            i += SLIDE

        overall_acc = accuracy_score(all_true, all_preds) * 100 if all_true else 50.0

        # ── Final model on all data → predict current bar ─────────────────────
        scaler_final = RobustScaler()
        X_all_s = scaler_final.fit_transform(X)

        final_model = XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            use_label_encoder=False,
            eval_metric="logloss",
            verbosity=0,
            random_state=42,
        )
        final_model.fit(X_all_s, y)

        last_row   = scaler_final.transform(X.iloc[[-1]])
        prob_up    = float(final_model.predict_proba(last_row)[0][1])
        direction  = "UP" if prob_up >= 0.5 else "DOWN"

        # Signal label
        if prob_up >= 0.72:
            sig = "🟢 Strong Buy Signal"
        elif prob_up >= 0.58:
            sig = "🟡 Moderate Buy Signal"
        elif prob_up <= 0.28:
            sig = "🔴 Strong Sell Signal"
        elif prob_up <= 0.42:
            sig = "🟠 Moderate Sell Signal"
        else:
            sig = "⚪ Neutral — No Clear Signal"

        # Feature importance (top 15)
        importances = final_model.feature_importances_
        fi_pairs = sorted(zip(feature_names, importances.tolist()),
                          key=lambda x: x[1], reverse=True)[:15]
        fi_list = [{"feature": k, "importance": round(v * 100, 2)} for k, v in fi_pairs]

        return {
            "error":               None,
            "prob_up":             round(prob_up, 4),
            "direction":           direction,
            "signal_label":        sig,
            "backtest_accuracy":   round(overall_acc, 1),
            "backtest_monthly":    monthly_results,
            "feature_importance":  fi_list,
            "n_features":          len(feature_names),
            "n_train_bars":        len(X),
            "forward_days":        forward_days,
        }

    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: Quick multi-stock scan (no backtest — fast)
# ─────────────────────────────────────────────────────────────────────────────

# Curated list: liquid Nifty 50 / Nifty 100 stocks, one per major sector
_SCAN_STOCKS = [
    ("RELIANCE",   "Energy"),
    ("ONGC",       "Energy"),
    ("TCS",        "IT"),
    ("INFY",       "IT"),
    ("HCLTECH",    "IT"),
    ("WIPRO",      "IT"),
    ("HDFCBANK",   "Banking"),
    ("ICICIBANK",  "Banking"),
    ("SBIN",       "Banking"),
    ("KOTAKBANK",  "Banking"),
    ("AXISBANK",   "Banking"),
    ("HINDUNILVR", "FMCG"),
    ("ITC",        "FMCG"),
    ("NESTLEIND",  "FMCG"),
    ("SUNPHARMA",  "Pharma"),
    ("DRREDDY",    "Pharma"),
    ("BHARTIARTL", "Telecom"),
    ("LT",         "Infra"),
    ("POWERGRID",  "Utilities"),
    ("NTPC",       "Utilities"),
    ("BAJFINANCE", "NBFC"),
    ("MARUTI",     "Auto"),
    ("TATAMOTORS", "Auto"),
    ("ASIANPAINT", "Paints"),
    ("TITAN",      "Consumer"),
    ("ULTRACEMCO", "Cement"),
    ("TATASTEEL",  "Metals"),
    ("JSWSTEEL",   "Metals"),
]


def run_market_scan(forward_days: int = 5, stock_list: list[tuple] | None = None) -> list[dict]:
    """
    Quick XGBoost scan + EMA trend proxy.
    Scans all stocks passed in stock_list (defaults to _SCAN_STOCKS curated list).
    Trend = Bullish if EMA20 slope (5d) > 0 OR EMA50 slope (10d) > 0  (either rising).
    Returns only rows where XGBoost direction and trend AGREE.
    """
    import yfinance as yf
    from xgboost import XGBClassifier
    from sklearn.preprocessing import RobustScaler

    stocks = stock_list if stock_list else _SCAN_STOCKS
    results = []

    for symbol, sector in stocks:
        try:
            raw = yf.download(symbol + ".NS", period="2y", interval="1d",
                              progress=False, auto_adjust=True)
            if raw is None or len(raw) < 200:
                continue
            raw.index = pd.to_datetime(raw.index).date

            close = _get_close(raw)
            if close is None or len(close) < 200:
                continue

            # ── Trend proxy: EMA20 slope (5d) OR EMA50 slope (10d) rising ────
            # Either EMA rising = trend has bullish lean.
            # Removed hard EMA200 requirement — too restrictive in down markets.
            ema20       = close.ewm(span=20,  adjust=False).mean()
            ema50       = close.ewm(span=50,  adjust=False).mean()
            ema20_slope = (ema20.iloc[-1] - ema20.iloc[-6])  / ema20.iloc[-6]  * 100
            ema50_slope = (ema50.iloc[-1] - ema50.iloc[-11]) / ema50.iloc[-11] * 100
            trend = "Bullish" if (ema20_slope > 0 or ema50_slope > 0) else "Bearish"

            # ── XGBoost quick prediction (no backtest) ────────────────────────
            feat    = _build_features(raw)
            fwd_ret = close.pct_change(forward_days).shift(-forward_days)
            target  = (fwd_ret > 0).astype(int)

            combined = feat.copy()
            combined["_target"] = target.values
            combined = combined.replace([np.inf, -np.inf], np.nan).dropna()
            if len(combined) < 150:
                continue

            X = combined.drop(columns=["_target"])
            y = combined["_target"]

            scaler = RobustScaler()
            X_s    = scaler.fit_transform(X)

            model = XGBClassifier(
                n_estimators=100, max_depth=4, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8,
                use_label_encoder=False, eval_metric="logloss",
                verbosity=0, random_state=42,
            )
            model.fit(X_s, y)

            last_row = scaler.transform(X.iloc[[-1]])
            prob_up  = float(model.predict_proba(last_row)[0][1])
            xgb_dir  = "UP" if prob_up >= 0.5 else "DOWN"

            # Only keep aligned signals (both agree)
            aligned = (xgb_dir == "UP"   and trend == "Bullish") or \
                      (xgb_dir == "DOWN" and trend == "Bearish")
            if not aligned:
                continue

            # Label — lowered thresholds so moderate signals show up too
            if prob_up >= 0.65:
                sig = "Strong Buy"
            elif prob_up >= 0.55:
                sig = "Buy"
            elif prob_up <= 0.35:
                sig = "Strong Sell"
            elif prob_up <= 0.45:
                sig = "Sell"
            else:
                continue   # genuinely neutral, skip

            results.append({
                "Symbol":    symbol,
                "Sector":    sector,
                "Price (₹)": round(float(close.iloc[-1]), 1),
                "XGB Prob":  round(prob_up * 100, 1),
                "Direction": xgb_dir,
                "Trend":     trend,
                "Signal":    sig,
            })

        except Exception:
            continue

    bullish = sorted([r for r in results if r["Direction"] == "UP"],
                     key=lambda x: x["XGB Prob"], reverse=True)
    bearish = sorted([r for r in results if r["Direction"] == "DOWN"],
                     key=lambda x: x["XGB Prob"])
    return bullish + bearish


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: Full single-stock forecast (Prophet + XGBoost) — used by nightly job
# ─────────────────────────────────────────────────────────────────────────────

def run_full_stock_forecast(ticker_ns: str, forward_days: int = 5,
                            horizon_days: int = 30) -> dict | None:
    """
    Complete pipeline for one stock: fetch 3y OHLCV, run Prophet + XGBoost with backtest,
    compute EMA/close chart data.  Returns a dict ready for store_forecast(), or None on failure.

    Called by the nightly pipeline (all 185 stocks in parallel) so the AI Forecast page
    reads from DB the next morning — zero Yahoo Finance calls at page load time.
    """
    import yfinance as yf
    from datetime import datetime

    try:
        raw = yf.download(ticker_ns, period="3y", interval="1d",
                          progress=False, auto_adjust=True)
        if raw is None or len(raw) < 300:
            return None
        raw.index = pd.to_datetime(raw.index).date

        close = _get_close(raw)
        if close is None or len(close) < 300:
            return None

        # ── Prophet 30-day forecast ───────────────────────────────────────────
        prophet_res = run_prophet_forecast(close, horizon_days=horizon_days)
        if prophet_res.get("error"):
            prophet_res = None

        # ── XGBoost direction + full walk-forward backtest ────────────────────
        xgb_res = run_xgb_direction(raw, forward_days=forward_days)
        if xgb_res.get("error"):
            xgb_res = None

        if prophet_res is None and xgb_res is None:
            return None

        # ── Chart data: last 6 months of close + EMA overlays ─────────────────
        close_6m = close.tail(126)
        ema20    = close.ewm(span=20,  adjust=False).mean().tail(126)
        ema50    = close.rolling(50, min_periods=1).mean().tail(126)
        ema200   = close.ewm(span=200, adjust=False).mean().tail(126)

        def _series_to_dict(s: pd.Series) -> dict:
            return {"dates": [str(d) for d in s.index], "values": [float(v) for v in s.values]}

        result: dict = {
            "price":       float(close.iloc[-1]),
            "computed_at": datetime.utcnow().isoformat(),
            "close_6m": {
                "dates":  [str(d) for d in close_6m.index],
                "prices": [float(v) for v in close_6m.values],
            },
            "ema": {
                "ema20":  _series_to_dict(ema20),
                "ema50":  _series_to_dict(ema50),
                "ema200": _series_to_dict(ema200),
            },
        }

        # XGBoost fields
        if xgb_res:
            result.update({
                "xgb_prob":            xgb_res["prob_up"],
                "xgb_direction":       xgb_res["direction"],
                "xgb_signal":          xgb_res["signal_label"],
                "xgb_accuracy":        xgb_res["backtest_accuracy"],
                "n_train_bars":        xgb_res["n_train_bars"],
                "n_features":          xgb_res["n_features"],
                "backtest_monthly":    xgb_res["backtest_monthly"],
                "feature_importance":  xgb_res["feature_importance"],
            })

        # Prophet fields
        if prophet_res:
            result.update({
                "prophet_trend":     prophet_res["trend_direction"],
                "prophet_trend_pct": prophet_res["trend_pct"],
                "prophet_forecast": {
                    "history_dates":  [str(d) for d in prophet_res["history_dates"]],
                    "history_prices": prophet_res["history_prices"],
                    "forecast_dates": [str(d) for d in prophet_res["forecast_dates"]],
                    "yhat":           prophet_res["yhat"],
                    "yhat_lower":     prophet_res["yhat_lower"],
                    "yhat_upper":     prophet_res["yhat_upper"],
                },
            })

        return result

    except Exception:
        return None
