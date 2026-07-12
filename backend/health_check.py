"""
Page Health Checker (Option C) — calls the actual backend data functions
each page depends on, validates their output shape and content.

Does NOT touch Streamlit UI code. Works identically on local and cloud.

Each check returns:
  (label: str, status: "OK"|"WARN"|"FAIL", detail: str)
"""
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

from backend.storage.db import get_conn
_MAX_STALE_DAYS = 4   # allow Fri→Mon gap + 1 buffer day


def _db():
    return get_conn()


def _agg(checks):
    statuses = [s for _, s, _ in checks]
    if "FAIL" in statuses: return "FAIL"
    if "WARN" in statuses: return "WARN"
    return "OK"


def _stale(date_str) -> int:
    """Days since a date value (native date object or YYYY-MM-DD string)."""
    try:
        d = date_str if isinstance(date_str, date) else date.fromisoformat(str(date_str)[:10])
        return (date.today() - d).days
    except Exception:
        return 999


# ─────────────────────────────────────────────────────────────────────────────
# 1. MARKET PULSE
# ─────────────────────────────────────────────────────────────────────────────
def _check_market_pulse():
    checks = []
    import sys; sys.path.insert(0, str(Path(__file__).parent.parent))

    # 1a. Live indices via fetch_market_summary
    try:
        from backend.data_ingestion.yfinance_fetcher import fetch_market_summary
        summary = fetch_market_summary()
        if not summary:
            checks.append(("Live indices", "FAIL", "fetch_market_summary() returned empty dict"))
        else:
            missing = [k for k, v in summary.items() if not v or not v.get("close")]
            if missing:
                checks.append(("Live indices", "WARN", f"No price for: {', '.join(missing)}"))
            else:
                sample = next(iter(summary.items()))
                checks.append(("Live indices", "OK",
                                f"{len(summary)} indices loaded · e.g. {sample[0]}={sample[1]['close']:,.0f}"))
    except Exception as e:
        checks.append(("Live indices", "FAIL", f"fetch_market_summary() error: {e}"))

    # 1b. Breadth from SQLite
    try:
        con = _db()
        row = con.execute(
            "SELECT trade_date, advance, decline, ad_ratio FROM market_breadth "
            "ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        con.close()
        if not row:
            checks.append(("Market breadth", "FAIL", "market_breadth table is empty"))
        else:
            stale = _stale(row[0])
            if row[1] is None or row[2] is None:
                checks.append(("Market breadth", "FAIL", f"advance/decline is NULL for {row[0]}"))
            elif stale > _MAX_STALE_DAYS:
                checks.append(("Market breadth", "WARN",
                                f"Data is {stale} days old (latest: {row[0]})"))
            else:
                checks.append(("Market breadth", "OK",
                                f"A={row[1]} D={row[2]} ratio={row[3]:.2f} as of {row[0]}"))
    except Exception as e:
        checks.append(("Market breadth", "FAIL", str(e)))

    # 1c. Sector heatmap from SQLite
    try:
        con = _db()
        rows = con.execute(
            "SELECT COUNT(*), MAX(trade_date) FROM sector_heatmap"
        ).fetchone()
        con.close()
        count, latest = rows
        if not count:
            checks.append(("Sector heatmap", "FAIL", "sector_heatmap table is empty"))
        else:
            stale = _stale(latest)
            null_check = get_conn().execute(
                "SELECT COUNT(*) FROM sector_heatmap WHERE ret_1m IS NULL"
            ).fetchone()[0]
            if null_check > count * 0.5:
                checks.append(("Sector heatmap", "WARN",
                                f"{null_check}/{count} rows have NULL ret_1m"))
            elif stale > _MAX_STALE_DAYS:
                checks.append(("Sector heatmap", "WARN",
                                f"{count} rows, latest {latest} ({stale}d old)"))
            else:
                checks.append(("Sector heatmap", "OK",
                                f"{count} sector-day rows · latest {latest}"))
    except Exception as e:
        checks.append(("Sector heatmap", "FAIL", str(e)))

    # 1d. RRG snapshot from SQLite
    try:
        con = _db()
        rows = con.execute(
            "SELECT COUNT(*), MAX(trade_date) FROM rrg_snapshot"
        ).fetchone()
        con.close()
        count, latest = rows
        if not count:
            checks.append(("RRG snapshot", "FAIL", "rrg_snapshot table is empty"))
        else:
            stale = _stale(latest)
            quad_check = get_conn().execute(
                "SELECT COUNT(DISTINCT quadrant) FROM rrg_snapshot WHERE trade_date=%s", (latest,)
            ).fetchone()[0]
            if quad_check < 2:
                checks.append(("RRG snapshot", "WARN",
                                f"Only {quad_check} quadrant(s) populated — data may be partial"))
            elif stale > _MAX_STALE_DAYS:
                checks.append(("RRG snapshot", "WARN",
                                f"{count} rows, latest {latest} ({stale}d old)"))
            else:
                checks.append(("RRG snapshot", "OK",
                                f"{count} sector-day rows · {quad_check} quadrants · latest {latest}"))
    except Exception as e:
        checks.append(("RRG snapshot", "FAIL", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 2. SECTOR ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────
def _check_sector_analysis():
    checks = []

    # 2a. Sector snapshot table freshness
    try:
        con = _db()
        row = con.execute(
            "SELECT COUNT(*), MAX(date) FROM daily_sector_snapshot"
        ).fetchone()
        con.close()
        count, latest = row
        if not count:
            checks.append(("Sector snapshot table", "FAIL", "daily_sector_snapshot is empty"))
        else:
            stale = _stale(latest)
            if stale > _MAX_STALE_DAYS:
                checks.append(("Sector snapshot table", "WARN",
                                f"Latest data: {latest} ({stale}d old)"))
            else:
                checks.append(("Sector snapshot table", "OK",
                                f"{count} rows · latest {latest}"))
    except Exception as e:
        checks.append(("Sector snapshot table", "FAIL", str(e)))

    # 2b. fetch_all_sector_prices — call and validate shape
    try:
        from backend.data_ingestion.yfinance_fetcher import fetch_all_sector_prices
        prices = fetch_all_sector_prices()
        if not prices:
            checks.append(("fetch_all_sector_prices", "FAIL", "returned empty dict"))
        else:
            empty = [s for s, df in prices.items() if df is None or df.empty]
            ok_count = len(prices) - len(empty)
            if ok_count == 0:
                checks.append(("fetch_all_sector_prices", "FAIL",
                                "all sector DataFrames are empty"))
            elif empty:
                checks.append(("fetch_all_sector_prices", "WARN",
                                f"{ok_count}/{len(prices)} sectors loaded · missing: {', '.join(empty[:3])}"))
            else:
                checks.append(("fetch_all_sector_prices", "OK",
                                f"{ok_count} sectors loaded with price history"))
    except Exception as e:
        checks.append(("fetch_all_sector_prices", "FAIL", str(e)))

    # 2c. compute_pct_returns on one sector
    try:
        from backend.data_ingestion.yfinance_fetcher import (
            fetch_all_sector_prices, compute_pct_returns,
        )
        prices = fetch_all_sector_prices()
        first_df = next((df for df in prices.values() if df is not None and not df.empty), None)
        if first_df is None:
            checks.append(("compute_pct_returns", "WARN", "no sector data to test against"))
        else:
            rets = compute_pct_returns(first_df)
            missing = [k for k in ("pct_1w", "pct_1m", "pct_3m") if rets.get(k) is None]
            if missing:
                checks.append(("compute_pct_returns", "WARN",
                                f"None values for: {', '.join(missing)}"))
            else:
                checks.append(("compute_pct_returns", "OK",
                                f"1W={rets.get('pct_1w',0):.1f}% 1M={rets.get('pct_1m',0):.1f}% 3M={rets.get('pct_3m',0):.1f}%"))
    except Exception as e:
        checks.append(("compute_pct_returns", "FAIL", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 3. INDEX STOCKS
# ─────────────────────────────────────────────────────────────────────────────
def _check_index_stocks():
    checks = []

    # 3a. sector_intelligence table
    try:
        con = _db()
        count = con.execute("SELECT COUNT(*) FROM sector_intelligence").fetchone()[0]
        sectors = con.execute(
            "SELECT COUNT(DISTINCT sector) FROM sector_intelligence"
        ).fetchone()[0]
        con.close()
        if count < 10:
            checks.append(("sector_intelligence table", "FAIL",
                            f"Only {count} rows — Index Stocks will show empty"))
        else:
            checks.append(("sector_intelligence table", "OK",
                            f"{count} stocks across {sectors} sectors"))
    except Exception as e:
        checks.append(("sector_intelligence table", "FAIL", str(e)))

    # 3b. weightage data not all NULL
    try:
        con = _db()
        null_wt = con.execute(
            "SELECT COUNT(*) FROM sector_intelligence WHERE weightage_pct IS NULL"
        ).fetchone()[0]
        total = con.execute("SELECT COUNT(*) FROM sector_intelligence").fetchone()[0]
        con.close()
        if total and null_wt / total > 0.5:
            checks.append(("Weightage data", "WARN",
                            f"{null_wt}/{total} stocks have NULL weightage_pct"))
        elif total:
            checks.append(("Weightage data", "OK",
                            f"{total - null_wt}/{total} stocks have weightage data"))
    except Exception as e:
        checks.append(("Weightage data", "WARN", str(e)))

    # 3c. FNO symbols for filtering
    try:
        con = _db()
        fno = con.execute("SELECT COUNT(*) FROM fno_symbols").fetchone()[0]
        con.close()
        if fno < 50:
            checks.append(("FNO symbols", "WARN", f"Only {fno} F&O symbols (expected 150+)"))
        else:
            checks.append(("FNO symbols", "OK", f"{fno} F&O symbols loaded"))
    except Exception as e:
        checks.append(("FNO symbols", "FAIL", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 4. FII DII FLOW
# ─────────────────────────────────────────────────────────────────────────────
def _check_fii_dii_flow():
    checks = []

    # 4a. fii_dii_daily table
    try:
        con = _db()
        row = con.execute(
            "SELECT COUNT(*), MAX(date), MIN(date) FROM fii_dii_daily"
        ).fetchone()
        con.close()
        count, latest, oldest = row
        if not count:
            checks.append(("FII/DII daily table", "FAIL", "fii_dii_daily is empty"))
        else:
            stale = _stale(latest)
            if stale > _MAX_STALE_DAYS:
                checks.append(("FII/DII daily table", "WARN",
                                f"{count} rows · latest {latest} ({stale}d old)"))
            elif count < 20:
                checks.append(("FII/DII daily table", "WARN",
                                f"Only {count} days of data (charts need 30+)"))
            else:
                checks.append(("FII/DII daily table", "OK",
                                f"{count} days · {oldest} to {latest}"))
    except Exception as e:
        checks.append(("FII/DII daily table", "FAIL", str(e)))

    # 4b. FII/DII columns not all NULL
    try:
        con = _db()
        cols = [r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='fii_dii_daily'"
        ).fetchall()]
        con.close()
        fii_col = next((c for c in cols if "fii" in c.lower()), None)
        dii_col = next((c for c in cols if "dii" in c.lower()), None)
        if fii_col and dii_col:
            con = _db()
            null_fii = con.execute(
                f"SELECT COUNT(*) FROM fii_dii_daily WHERE {fii_col} IS NULL"
            ).fetchone()[0]
            con.close()
            if null_fii > 0:
                checks.append(("FII/DII values", "WARN",
                                f"{null_fii} rows with NULL {fii_col}"))
            else:
                checks.append(("FII/DII values", "OK",
                                f"Columns {fii_col}/{dii_col} fully populated"))
        else:
            checks.append(("FII/DII values", "WARN", f"Columns found: {cols}"))
    except Exception as e:
        checks.append(("FII/DII values", "WARN", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 5 & 6. FII SECTORS / FPI SECTORS
# ─────────────────────────────────────────────────────────────────────────────
def _check_fii_fpi_sectors():
    checks = []

    # 5a. nsdl_fii_sector table
    try:
        con = _db()
        row = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT sector) FROM nsdl_fii_sector"
        ).fetchone()
        con.close()
        count, sectors = row
        if count < 10:
            checks.append(("NSDL sector table", "FAIL",
                            f"Only {count} rows — FII/FPI Sectors will be empty"))
        else:
            checks.append(("NSDL sector table", "OK",
                            f"{count} rows · {sectors} sectors"))
    except Exception as e:
        checks.append(("NSDL sector table", "FAIL", str(e)))

    # 5b. Call fetch_nsdl_fii_sectors and validate output
    try:
        from backend.data_ingestion.nsdl_fetcher import fetch_nsdl_fii_sectors
        result = fetch_nsdl_fii_sectors()
        if not result:
            checks.append(("fetch_nsdl_fii_sectors", "FAIL", "returned empty — no NSDL data"))
        else:
            dates = sorted(result.keys(), reverse=True)
            latest_df = result[dates[0]]
            if latest_df is None or latest_df.empty:
                checks.append(("fetch_nsdl_fii_sectors", "WARN",
                                f"{len(dates)} date keys but latest DataFrame is empty"))
            else:
                checks.append(("fetch_nsdl_fii_sectors", "OK",
                                f"{len(dates)} periods · latest {dates[0]} · {len(latest_df)} sectors"))
    except Exception as e:
        checks.append(("fetch_nsdl_fii_sectors", "FAIL", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 7. STOCK PICKER
# ─────────────────────────────────────────────────────────────────────────────
def _check_stock_picker():
    checks = []

    # 7a. sector_intelligence has stocks to pick from
    try:
        con = _db()
        sectors = [r[0] for r in con.execute(
            "SELECT DISTINCT sector FROM sector_intelligence LIMIT 5"
        ).fetchall()]
        con.close()
        if not sectors:
            checks.append(("Available sectors", "FAIL",
                            "sector_intelligence empty — Stock Picker has no sectors"))
        else:
            checks.append(("Available sectors", "OK", f"{len(sectors)}+ sectors available"))
    except Exception as e:
        checks.append(("Available sectors", "FAIL", str(e)))

    # 7b. fetch_sector_stocks for one sector
    try:
        from backend.data_ingestion.yfinance_fetcher import fetch_sector_stocks
        con = _db()
        sector = con.execute(
            "SELECT sector FROM sector_intelligence GROUP BY sector ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        con.close()
        if not sector:
            checks.append(("fetch_sector_stocks", "WARN", "No sector found in DB to test"))
        else:
            stocks = fetch_sector_stocks(sector[0])
            if not stocks:
                checks.append(("fetch_sector_stocks", "FAIL",
                                f"fetch_sector_stocks('{sector[0]}') returned empty"))
            else:
                loaded = {s: df for s, df in stocks.items() if df is not None and not df.empty}
                checks.append(("fetch_sector_stocks", "OK",
                                f"'{sector[0]}': {len(loaded)}/{len(stocks)} stocks loaded"))
    except Exception as e:
        checks.append(("fetch_sector_stocks", "FAIL", str(e)))

    # 7c. compute_all_indicators on one stock
    try:
        from backend.calculations.indicators import compute_all_indicators
        from backend.data_ingestion.yfinance_fetcher import fetch_sector_stocks
        con = _db()
        sector = con.execute(
            "SELECT sector FROM sector_intelligence GROUP BY sector ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        con.close()
        if sector:
            stocks = fetch_sector_stocks(sector[0])
            # compute_all_indicators expects the full OHLCV DataFrame
            first_df = next((df for df in stocks.values() if df is not None and not df.empty), None)
            if first_df is not None and len(first_df) > 30:
                indic = compute_all_indicators(first_df)
                rsi = indic.get("rsi_14") or indic.get("rsi")
                if rsi is None:
                    checks.append(("compute_all_indicators", "WARN", "RSI returned None"))
                else:
                    checks.append(("compute_all_indicators", "OK",
                                    f"RSI={float(rsi):.1f}, EMA={indic.get('ema_signal','?')}"))
            else:
                checks.append(("compute_all_indicators", "WARN", "No stock data to test"))
    except Exception as e:
        checks.append(("compute_all_indicators", "FAIL", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 8. SMART MONEY
# ─────────────────────────────────────────────────────────────────────────────
def _check_smart_money():
    checks = []

    # 8a. daily_stock_snapshot freshness
    try:
        con = _db()
        row = con.execute(
            "SELECT COUNT(*), MAX(date), COUNT(DISTINCT symbol) FROM daily_stock_snapshot"
        ).fetchone()
        con.close()
        count, latest, symbols = row
        if not count:
            checks.append(("Stock snapshot table", "FAIL", "daily_stock_snapshot is empty"))
        else:
            stale = _stale(latest)
            if stale > _MAX_STALE_DAYS:
                checks.append(("Stock snapshot table", "WARN",
                                f"{symbols} stocks · latest {latest} ({stale}d old)"))
            else:
                checks.append(("Stock snapshot table", "OK",
                                f"{symbols} stocks · {count} rows · latest {latest}"))
    except Exception as e:
        checks.append(("Stock snapshot table", "FAIL", str(e)))

    # 8b. smart_money_history signal quality
    try:
        con = _db()
        row = con.execute(
            "SELECT COUNT(*), MAX(trade_date), COUNT(DISTINCT symbol) FROM smart_money_history"
        ).fetchone()
        con.close()
        count, latest, symbols = row
        if not count:
            checks.append(("Smart money history", "FAIL", "smart_money_history is empty"))
        else:
            stale = _stale(latest)
            if stale > _MAX_STALE_DAYS:
                checks.append(("Smart money history", "WARN",
                                f"{symbols} stocks · latest {latest} ({stale}d old)"))
            else:
                checks.append(("Smart money history", "OK",
                                f"{symbols} stocks · {count:,} rows · latest {latest}"))
    except Exception as e:
        checks.append(("Smart money history", "FAIL", str(e)))

    # 8c. sector_intelligence for sector mapping
    try:
        con = _db()
        count = con.execute("SELECT COUNT(*) FROM sector_intelligence").fetchone()[0]
        con.close()
        if count < 10:
            checks.append(("Sector map (for grouping)", "FAIL",
                            "sector_intelligence empty — Smart Money sector grouping will break"))
        else:
            checks.append(("Sector map (for grouping)", "OK", f"{count} stock-sector mappings"))
    except Exception as e:
        checks.append(("Sector map (for grouping)", "FAIL", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 9. FII ACCUMULATION
# ─────────────────────────────────────────────────────────────────────────────
def _check_fii_accumulation():
    checks = []

    # 9a. shareholding_pattern coverage
    try:
        con = _db()
        row = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT symbol), COUNT(DISTINCT quarter) "
            "FROM shareholding_pattern"
        ).fetchone()
        con.close()
        count, symbols, quarters = row
        if count < 100:
            checks.append(("Shareholding pattern", "FAIL",
                            f"Only {count} rows — FII Accumulation will be mostly empty"))
        else:
            checks.append(("Shareholding pattern", "OK",
                            f"{symbols} stocks · {quarters} quarters · {count:,} rows"))
    except Exception as e:
        checks.append(("Shareholding pattern", "FAIL", str(e)))

    # 9b. FII column not all NULL
    try:
        con = _db()
        cols = [r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='shareholding_pattern'"
        ).fetchall()]
        fii_col = next((c for c in cols if "fii" in c.lower()), None)
        if fii_col:
            null_fii = con.execute(
                f"SELECT COUNT(*) FROM shareholding_pattern WHERE {fii_col} IS NULL"
            ).fetchone()[0]
            total = con.execute("SELECT COUNT(*) FROM shareholding_pattern").fetchone()[0]
            con.close()
            if total and null_fii / total > 0.3:
                checks.append(("FII holding values", "WARN",
                                f"{null_fii}/{total} rows have NULL FII holding %"))
            else:
                checks.append(("FII holding values", "OK",
                                f"{total - null_fii}/{total} rows have FII % data"))
        else:
            checks.append(("FII holding values", "WARN", f"No FII column found: {cols}"))
            con.close()
    except Exception as e:
        checks.append(("FII holding values", "WARN", str(e)))

    # 9c. refresh meta
    try:
        con = _db()
        meta = con.execute(
            "SELECT value FROM shareholding_refresh_meta WHERE key='last_full_refresh'"
        ).fetchone()
        con.close()
        if not meta:
            checks.append(("Refresh metadata", "WARN",
                            "No last_full_refresh record — refresh may never have run"))
        else:
            checks.append(("Refresh metadata", "OK", f"Last refresh: {meta[0][:10]}"))
    except Exception as e:
        checks.append(("Refresh metadata", "WARN", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 10. ALERTS
# ─────────────────────────────────────────────────────────────────────────────
def _check_alerts():
    checks = []

    # 10a. sector data available for scanner
    try:
        con = _db()
        row = con.execute(
            "SELECT COUNT(*), MAX(date) FROM daily_sector_snapshot"
        ).fetchone()
        con.close()
        count, latest = row
        if not count:
            checks.append(("Sector data for scanner", "FAIL",
                            "daily_sector_snapshot empty — Alerts scanner has no data"))
        else:
            stale = _stale(latest)
            if stale > _MAX_STALE_DAYS:
                checks.append(("Sector data for scanner", "WARN",
                                f"Latest sector data: {latest} ({stale}d old)"))
            else:
                checks.append(("Sector data for scanner", "OK",
                                f"{count} rows · latest {latest}"))
    except Exception as e:
        checks.append(("Sector data for scanner", "FAIL", str(e)))

    # 10b. compute_all_indicators import and run
    try:
        from backend.calculations.indicators import compute_all_indicators
        checks.append(("indicators module", "OK", "import OK"))
    except Exception as e:
        checks.append(("indicators module", "FAIL", f"import error: {e}"))

    # 10c. smart_money_history for H-M scanner
    try:
        con = _db()
        row = con.execute(
            "SELECT COUNT(DISTINCT symbol), MAX(trade_date) FROM smart_money_history"
        ).fetchone()
        con.close()
        symbols, latest = row
        if not symbols:
            checks.append(("H-M scanner data", "FAIL",
                            "smart_money_history empty — H-M scanner will return no stocks"))
        else:
            stale = _stale(latest) if latest else 999
            if stale > _MAX_STALE_DAYS:
                checks.append(("H-M scanner data", "WARN",
                                f"{symbols} stocks · latest {latest} ({stale}d old)"))
            else:
                checks.append(("H-M scanner data", "OK",
                                f"{symbols} stocks available for H-M scanner"))
    except Exception as e:
        checks.append(("H-M scanner data", "FAIL", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 11. EXPORT
# ─────────────────────────────────────────────────────────────────────────────
def _check_export():
    checks = []

    # 11a. All major source tables
    table_checks = [
        ("daily_sector_snapshot", "date",       "Sector snapshot",        10),
        ("fii_dii_daily",         "date",        "FII/DII flow",           20),
        ("smart_money_history",   "trade_date",  "Smart money history",   100),
        ("shareholding_pattern",  None,          "Shareholding pattern",  100),
    ]
    for tbl, dcol, label, min_rows in table_checks:
        try:
            con = _db()
            count = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            latest = None
            if dcol:
                latest = con.execute(f"SELECT MAX({dcol}) FROM {tbl}").fetchone()[0]
            con.close()
            if count < min_rows:
                checks.append((f"Export: {label}", "WARN",
                                f"{tbl}: {count} rows (need {min_rows}+ for useful export)"))
            else:
                detail = f"{count:,} rows"
                if latest:
                    detail += f" · latest {str(latest)[:10]}"
                checks.append((f"Export: {label}", "OK", detail))
        except Exception as e:
            checks.append((f"Export: {label}", "FAIL", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 11. AI FORECAST
# ─────────────────────────────────────────────────────────────────────────────
def _check_ai_forecast():
    checks = []

    # 11a. Prophet import
    try:
        from prophet import Prophet  # noqa: F401
        checks.append(("Prophet library", "OK", "import OK"))
    except Exception as e:
        checks.append(("Prophet library", "FAIL", f"import error: {e}"))

    # 11b. XGBoost import
    try:
        import xgboost  # noqa: F401
        checks.append(("XGBoost library", "OK", f"version {xgboost.__version__}"))
    except Exception as e:
        checks.append(("XGBoost library", "FAIL", f"import error: {e}"))

    # 11c. ai_forecast module import
    try:
        from backend.calculations.ai_forecast import run_prophet_forecast, run_xgb_direction  # noqa: F401
        checks.append(("ai_forecast module", "OK", "run_prophet_forecast + run_xgb_direction imported"))
    except Exception as e:
        checks.append(("ai_forecast module", "FAIL", f"import error: {e}"))

    # 11d. ai_scan_results table + freshness
    try:
        from backend.storage.ai_scan_db import load_latest_scan, scan_age_days
        rows, scan_date = load_latest_scan()
        if not rows:
            checks.append(("AI scan DB", "WARN",
                            "ai_scan_results table empty — scheduler runs at 9 PM IST or trigger via Admin → Row 6"))
        else:
            age = scan_age_days()
            if age is not None and age > 3:
                checks.append(("AI scan DB", "WARN",
                                f"{len(rows)} stocks · last scan {scan_date} ({age}d old) — consider refresh"))
            else:
                checks.append(("AI scan DB", "OK",
                                f"{len(rows)} stocks · last scan {scan_date}"))
    except Exception as e:
        checks.append(("AI scan DB", "FAIL", str(e)))

    # 11e. yfinance reachable (quick smoke test on RELIANCE.NS — 5d only)
    try:
        import yfinance as yf
        d = yf.download("RELIANCE.NS", period="5d", progress=False, auto_adjust=True)
        if d is None or len(d) == 0:
            checks.append(("yfinance smoke test", "WARN",
                            "RELIANCE.NS returned no data — Yahoo Finance may be temporarily down"))
        else:
            checks.append(("yfinance smoke test", "OK",
                            f"RELIANCE.NS · {len(d)} bars fetched"))
    except Exception as e:
        checks.append(("yfinance smoke test", "FAIL", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 12. GANN ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────
def _check_gann():
    checks = []

    # 12a. gann module import
    try:
        from backend.calculations.gann import compute_gann_all  # noqa: F401
        checks.append(("Gann calc module", "OK", "compute_gann_all imported"))
    except Exception as e:
        checks.append(("Gann calc module", "FAIL", f"import error: {e}"))

    # 12b. gann_cache table + symbol coverage + freshness
    try:
        from backend.storage.gann_db import load_all_summary, cache_age_days
        rows = load_all_summary()
        if not rows:
            checks.append(("Gann cache DB", "WARN",
                            "gann_cache table empty — run Gann pipeline via Admin or wait for 9:30 PM IST scheduler"))
        else:
            age = cache_age_days()
            n   = len(rows)
            latest = rows[0]["scan_date"] if rows else "—"
            if n < 45:
                checks.append(("Gann cache DB", "WARN",
                                f"Only {n} stocks cached (expect ≥45) · last run {latest}"))
            elif age is not None and age > 3:
                checks.append(("Gann cache DB", "WARN",
                                f"{n} stocks · last run {latest} ({age}d old) — consider refresh"))
            else:
                checks.append(("Gann cache DB", "OK",
                                f"{n} stocks cached · last run {latest}"))
    except Exception as e:
        checks.append(("Gann cache DB", "FAIL", str(e)))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def _check_hm_scanner():
    checks = []

    try:
        from backend.calculations.hm_indicators import add_indicators, generate_signals
        checks.append(("hm_indicators module", "OK", "add_indicators + generate_signals imported"))
    except Exception as e:
        checks.append(("hm_indicators module", "FAIL", f"import error: {e}"))

    try:
        from backend.calculations.hm_backtest import backtest_signals, summarize_backtests
        checks.append(("hm_backtest module", "OK", "backtest_signals + summarize_backtests imported"))
    except Exception as e:
        checks.append(("hm_backtest module", "FAIL", f"import error: {e}"))

    try:
        import yfinance as yf
        import pandas as pd
        from backend.calculations.hm_indicators import add_indicators, generate_signals
        raw = yf.download("RELIANCE.NS", period="60d", interval="1d",
                          auto_adjust=True, progress=False)
        if raw is None or raw.empty:
            checks.append(("H-M live data smoke test", "WARN",
                            "RELIANCE.NS returned no data — market data source may be down"))
        else:
            df = add_indicators(raw)
            df = generate_signals(df, min_score=70, confirmation_mode="Balanced")
            n_bottom = int(df["BOTTOM_SIGNAL"].sum())
            n_top = int(df["TOP_SIGNAL"].sum())
            rsi_last = round(float(df["RSI"].iloc[-1]), 1)
            checks.append(("H-M live data smoke test", "OK",
                            f"RELIANCE.NS · {len(df)} bars · RSI={rsi_last} · "
                            f"{n_bottom} bottom / {n_top} top signals"))
    except Exception as e:
        checks.append(("H-M live data smoke test", "FAIL", str(e)))

    return checks


_PAGES = [
    ("📡 Market Pulse",     _check_market_pulse),
    ("📈 Sector Analysis",  _check_sector_analysis),
    ("🏛️ Index Stocks",     _check_index_stocks),
    ("🏦 FII DII Flow",     _check_fii_dii_flow),
    ("🏢 FII / 🌏 FPI Sectors", _check_fii_fpi_sectors),
    ("🎯 Stock Picker",     _check_stock_picker),
    ("💰 Smart Money",      _check_smart_money),
    ("📊 FII Accumulation", _check_fii_accumulation),
    ("🔔 Alerts",           _check_alerts),
    ("🔭 H-M Scanner",      _check_hm_scanner),
    ("🤖 AI Forecast",      _check_ai_forecast),
    ("📤 Export",           _check_export),
    ("🔢 Gann Analysis",    _check_gann),
]


def run_health_check() -> list[dict]:
    """
    Run all page health checks (Option C — function-level validation).
    Returns list of dicts ordered by menu:
      {page, status, checks [(label, status, detail)], elapsed}
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    results = []
    for page, fn in _PAGES:
        t0 = time.time()
        try:
            checks = fn()
        except Exception as e:
            checks = [("Unexpected error", "FAIL", traceback.format_exc(limit=3))]
        elapsed = round(time.time() - t0, 2)
        results.append({
            "page":    page,
            "status":  _agg(checks),
            "checks":  checks,
            "elapsed": elapsed,
        })
    return results
