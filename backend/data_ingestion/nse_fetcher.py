"""Fetches FII/DII and market breadth data from NSE India / nsepython."""
import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nse_dashboard.db"


def _upsert_fii_rows(rows: list[dict]) -> None:
    """Persist FII/DII rows to SQLite, overwriting zeros with real values."""
    if not rows:
        return
    try:
        conn = sqlite3.connect(_DB_PATH)
        for r in rows:
            conn.execute(
                """INSERT INTO fii_dii_daily (date, fii_buy, fii_sell, fii_net, dii_buy, dii_sell, dii_net, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(date) DO UPDATE SET
                       fii_buy  = CASE WHEN excluded.fii_buy  != 0 THEN excluded.fii_buy  ELSE fii_buy  END,
                       fii_sell = CASE WHEN excluded.fii_sell != 0 THEN excluded.fii_sell ELSE fii_sell END,
                       fii_net  = CASE WHEN excluded.fii_net  != 0 THEN excluded.fii_net  ELSE fii_net  END,
                       dii_buy  = CASE WHEN excluded.dii_buy  != 0 THEN excluded.dii_buy  ELSE dii_buy  END,
                       dii_sell = CASE WHEN excluded.dii_sell != 0 THEN excluded.dii_sell ELSE dii_sell END,
                       dii_net  = CASE WHEN excluded.dii_net  != 0 THEN excluded.dii_net  ELSE dii_net  END,
                       created_at = datetime('now')""",
                (str(r["date"]), r["fii_buy"], r["fii_sell"], r["fii_net"],
                 r["dii_buy"], r["dii_sell"], r["dii_net"]),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"DB upsert failed: {e}")


def _load_fii_from_db(days: int) -> pd.DataFrame:
    """Return last `days` rows from SQLite fii_dii_daily table."""
    try:
        cutoff = str(date.today() - timedelta(days=days))
        conn = sqlite3.connect(_DB_PATH)
        df = pd.read_sql_query(
            "SELECT date, fii_buy, fii_sell, fii_net, dii_buy, dii_sell, dii_net "
            "FROM fii_dii_daily WHERE date >= ? ORDER BY date",
            conn, params=(cutoff,)
        )
        conn.close()
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df
    except Exception as e:
        logger.warning(f"DB load failed: {e}")
        return pd.DataFrame()


def _try_nsepython_fii() -> Optional[pd.DataFrame]:
    try:
        from nsepython import fii_dii_data
        df = fii_dii_data()
        return df
    except Exception as e:
        logger.warning(f"nsepython fii_dii_data failed: {e}")
    return None


def _try_nse_web_fii() -> Optional[pd.DataFrame]:
    """Fetch FII/DII daily flow from NSE India API.

    API returns category-wise rows: each date has one row for 'FII/FPI' and
    one for 'DII', each with buyValue / sellValue / netValue fields.
    We pivot these into one row per date.
    """
    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.nseindia.com",
        }
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        resp = session.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()

        def _f(val):
            return float(str(val).replace(",", "").strip() or 0)

        by_date: dict = {}
        for item in data:
            try:
                raw_date = item.get("date", "")
                dt = pd.to_datetime(raw_date, dayfirst=True, errors="coerce")
                if pd.isna(dt):
                    continue
                key = dt.date()
                cat = str(item.get("category", "")).upper()
                buy  = _f(item.get("buyValue",  0))
                sell = _f(item.get("sellValue", 0))
                net  = _f(item.get("netValue",  0))

                if key not in by_date:
                    by_date[key] = {"date": key,
                                    "fii_buy": 0, "fii_sell": 0, "fii_net": 0,
                                    "dii_buy": 0, "dii_sell": 0, "dii_net": 0}
                if "FII" in cat:
                    by_date[key].update({"fii_buy": buy, "fii_sell": sell, "fii_net": net})
                elif "DII" in cat:
                    by_date[key].update({"dii_buy": buy, "dii_sell": sell, "dii_net": net})
            except Exception:
                continue

        if by_date:
            return pd.DataFrame(list(by_date.values()))
    except Exception as e:
        logger.warning(f"NSE web FII fetch failed: {e}")
    return None


def fetch_fii_dii(days: int = 90) -> pd.DataFrame:
    """Returns DataFrame with FII/DII daily flow.

    Strategy:
    1. Fetch today's data from NSE (returns only the current day).
    2. Upsert into SQLite so history accumulates over time.
    3. Return full history from SQLite for the requested period.
    """
    # Step 1: fetch today's live data and persist
    live_df = _try_nse_web_fii()
    if live_df is not None and not live_df.empty:
        _upsert_fii_rows(live_df.to_dict("records"))

    # Step 2: return history from DB (accumulates daily)
    db_df = _load_fii_from_db(days)
    if not db_df.empty:
        return db_df.sort_values("date").reset_index(drop=True)

    # Fallback: return whatever live fetch returned (single day)
    if live_df is not None and not live_df.empty:
        return live_df.sort_values("date").reset_index(drop=True)

    logger.error("All FII/DII sources failed — returning empty")
    return pd.DataFrame(columns=["date", "fii_buy", "fii_sell", "fii_net",
                                  "dii_buy", "dii_sell", "dii_net"])


def fetch_market_breadth() -> dict:
    """Returns today's advance/decline counts from NSE."""
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com"}
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
        resp = session.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            adv = data.get("advance", {})
            return {
                "advance":   int(adv.get("advances", 0) or 0),
                "decline":   int(adv.get("declines", 0) or 0),
                "unchanged": int(adv.get("unchanged", 0) or 0),
            }
    except Exception as e:
        logger.warning(f"Breadth fetch failed: {e}")
    return {"advance": 0, "decline": 0, "unchanged": 0}
