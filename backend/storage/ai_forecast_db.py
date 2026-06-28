"""
SQLite persistence for full AI forecast results (Prophet + XGBoost + chart data).
Cook-once pattern: nightly pipeline writes; page reads instantly from DB.

Tables
------
ai_forecast_cache : one row per (symbol, scan_date)
                    stores full Prophet forecast, XGBoost prediction + backtest,
                    and last-6-months chart data so the page never calls Yahoo Finance.
"""
import sqlite3
import json
from datetime import date
from config import DB_PATH


def _conn():
    return sqlite3.connect(DB_PATH)


def ensure_table():
    con = _conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS ai_forecast_cache (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol                  TEXT    NOT NULL,
            sector                  TEXT,
            scan_date               TEXT    NOT NULL,
            price                   REAL,
            -- XGBoost
            xgb_prob                REAL,
            xgb_direction           TEXT,
            xgb_signal              TEXT,
            xgb_accuracy            REAL,
            n_train_bars            INTEGER,
            n_features              INTEGER,
            backtest_monthly_json   TEXT,
            feature_importance_json TEXT,
            -- Prophet
            prophet_trend           TEXT,
            prophet_trend_pct       REAL,
            prophet_forecast_json   TEXT,
            -- Chart data (last 6 months so page needs no Yahoo call)
            close_6m_json           TEXT,
            ema_json                TEXT,
            -- Meta
            computed_at             TEXT,
            UNIQUE(symbol, scan_date)
        )
    """)
    con.commit()
    con.close()


ensure_table()


def store_forecast(symbol: str, sector: str, result: dict,
                   scan_date: str | None = None) -> None:
    """Upsert one stock's full forecast result for today (or given date)."""
    today = scan_date or date.today().isoformat()
    con = _conn()
    con.execute("""
        INSERT OR REPLACE INTO ai_forecast_cache
            (symbol, sector, scan_date, price,
             xgb_prob, xgb_direction, xgb_signal, xgb_accuracy,
             n_train_bars, n_features, backtest_monthly_json, feature_importance_json,
             prophet_trend, prophet_trend_pct, prophet_forecast_json,
             close_6m_json, ema_json, computed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        symbol, sector, today,
        result.get("price"),
        result.get("xgb_prob"),
        result.get("xgb_direction"),
        result.get("xgb_signal"),
        result.get("xgb_accuracy"),
        result.get("n_train_bars"),
        result.get("n_features"),
        json.dumps(result.get("backtest_monthly") or []),
        json.dumps(result.get("feature_importance") or []),
        result.get("prophet_trend"),
        result.get("prophet_trend_pct"),
        json.dumps(result.get("prophet_forecast") or {}),
        json.dumps(result.get("close_6m") or {}),
        json.dumps(result.get("ema") or {}),
        result.get("computed_at"),
    ))
    con.commit()
    con.close()


def load_forecast(symbol: str) -> tuple[dict | None, str | None]:
    """
    Load the latest cached full forecast for one symbol.
    Returns (result_dict, scan_date_str) or (None, None) if never cached.

    result_dict keys match the shape expected by the AI Forecast page:
        prophet_res  — same structure as run_prophet_forecast() output
        xgb_res      — same structure as run_xgb_direction() output
        close_6m     — {dates: [...], prices: [...]}
        ema          — {ema20: {dates,values}, ema50: {dates,values}, ema200: {dates,values}}
        price        — latest close price
    """
    con = _conn()
    try:
        row = con.execute("""
            SELECT scan_date, price,
                   xgb_prob, xgb_direction, xgb_signal, xgb_accuracy,
                   n_train_bars, n_features,
                   backtest_monthly_json, feature_importance_json,
                   prophet_trend, prophet_trend_pct, prophet_forecast_json,
                   close_6m_json, ema_json
            FROM ai_forecast_cache
            WHERE symbol = ?
            ORDER BY scan_date DESC LIMIT 1
        """, (symbol,)).fetchone()
        if not row:
            return None, None

        scan_date = row[0]
        pf        = json.loads(row[12] or "{}")
        bt        = json.loads(row[8]  or "[]")
        fi        = json.loads(row[9]  or "[]")
        c6m       = json.loads(row[13] or "{}")
        ema       = json.loads(row[14] or "{}")

        # Reconstruct prophet_res in same shape as run_prophet_forecast()
        prophet_res = {
            "error":           None,
            "history_dates":   pf.get("history_dates", []),
            "history_prices":  pf.get("history_prices", []),
            "forecast_dates":  pf.get("forecast_dates", []),
            "yhat":            pf.get("yhat", []),
            "yhat_lower":      pf.get("yhat_lower", []),
            "yhat_upper":      pf.get("yhat_upper", []),
            "trend_direction": row[10],
            "trend_pct":       row[11],
            "last_price":      row[1],
        }

        # Reconstruct xgb_res in same shape as run_xgb_direction()
        xgb_res = {
            "error":              None,
            "prob_up":            row[2],
            "direction":          row[3],
            "signal_label":       row[4],
            "backtest_accuracy":  row[5],
            "n_train_bars":       row[6],
            "n_features":         row[7],
            "backtest_monthly":   bt,
            "feature_importance": fi,
            "forward_days":       5,
        }

        result = {
            "prophet_res": prophet_res,
            "xgb_res":     xgb_res,
            "close_6m":    c6m,
            "ema":         ema,
            "price":       row[1],
        }
        return result, scan_date
    finally:
        con.close()


def load_all_latest() -> list[dict]:
    """
    Load latest cached forecast summary for all symbols.
    Used by the pre-populated scan table on the AI Forecast page.
    """
    con = _conn()
    try:
        latest = con.execute(
            "SELECT MAX(scan_date) FROM ai_forecast_cache"
        ).fetchone()[0]
        if not latest:
            return []
        rows = con.execute("""
            SELECT symbol, sector, price, xgb_prob, xgb_direction,
                   xgb_signal, xgb_accuracy, prophet_trend, scan_date
            FROM ai_forecast_cache
            WHERE scan_date = ?
            ORDER BY xgb_prob DESC
        """, (latest,)).fetchall()
        return [
            {
                "Symbol":        r[0],
                "Sector":        r[1],
                "Price (₹)":    r[2],
                "XGB Prob":      round(r[3] * 100, 1) if r[3] else None,
                "Direction":     r[4],
                "Signal":        r[5],
                "Accuracy %":    r[6],
                "Prophet Trend": r[7],
                "scan_date":     r[8],
            }
            for r in rows
        ]
    finally:
        con.close()


def cache_age_days() -> int | None:
    """Days since last full cache run. None if never run."""
    con = _conn()
    try:
        row = con.execute(
            "SELECT MAX(scan_date) FROM ai_forecast_cache"
        ).fetchone()
        if not row or not row[0]:
            return None
        return (date.today() - date.fromisoformat(row[0])).days
    finally:
        con.close()


def stock_cache_age_days(symbol: str) -> int | None:
    """Days since this specific symbol was last cached."""
    con = _conn()
    try:
        row = con.execute(
            "SELECT MAX(scan_date) FROM ai_forecast_cache WHERE symbol=?", (symbol,)
        ).fetchone()
        if not row or not row[0]:
            return None
        return (date.today() - date.fromisoformat(row[0])).days
    finally:
        con.close()


def truncate_forecasts() -> None:
    """Delete all rows from ai_forecast_cache before a fresh nightly load.
    Table stays at exactly one row per stock (~4.5 MB constant)."""
    con = _conn()
    try:
        con.execute("DELETE FROM ai_forecast_cache")
        con.commit()
    finally:
        con.close()
