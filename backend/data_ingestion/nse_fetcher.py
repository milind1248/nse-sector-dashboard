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


def _try_moneycontrol_fii() -> Optional[pd.DataFrame]:
    """Fetch 30 days of FII/DII Cash Market data from MoneyControl page (embedded JSON)."""
    try:
        import requests, re, json as _json
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
            "Referer": "https://www.moneycontrol.com",
        }
        session = requests.Session()
        session.get("https://www.moneycontrol.com", headers=headers, timeout=10)
        r = session.get(
            "https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/index.php",
            headers=headers, timeout=12,
        )
        match = re.search(r'"fiiDiiData":(\[.*?\])', r.text, re.S)
        if not match:
            return None

        raw = _json.loads(match.group(1))
        rows = []
        for item in raw:
            try:
                def _f(v):
                    return float(str(v).replace(",", "").strip()) if v not in ("", None) else 0.0
                fii_net = _f(item.get("fiiCM", 0))
                dii_net = _f(item.get("diiCM", 0))
                rows.append({
                    "date":     pd.to_datetime(item["date"]).date(),
                    "fii_buy":  0.0,
                    "fii_sell": 0.0,
                    "fii_net":  fii_net,
                    "dii_buy":  0.0,
                    "dii_sell": 0.0,
                    "dii_net":  dii_net,
                })
            except Exception:
                continue
        return pd.DataFrame(rows) if rows else None
    except Exception as e:
        logger.warning(f"MoneyControl FII fetch failed: {e}")
    return None


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
    1. MoneyControl — 30 days of Cash Market net FII/DII (most reliable).
    2. NSE live API  — today's data only (buy/sell/net breakdown).
    3. Upsert both into SQLite so history accumulates beyond 30 days.
    4. Return full DB history for the requested period.
    """
    # Step 1: MoneyControl (30 days history)
    mc_df = _try_moneycontrol_fii()
    if mc_df is not None and not mc_df.empty:
        _upsert_fii_rows(mc_df.to_dict("records"))

    # Step 2: NSE live (today's buy/sell detail, overwrites MC's 0 buy/sell)
    nse_df = _try_nse_web_fii()
    if nse_df is not None and not nse_df.empty:
        _upsert_fii_rows(nse_df.to_dict("records"))

    # Step 3: return full history from DB
    db_df = _load_fii_from_db(days)
    if not db_df.empty:
        return db_df.sort_values("date").reset_index(drop=True)

    # Fallback: return whatever we got live
    for df in [mc_df, nse_df]:
        if df is not None and not df.empty:
            return df.sort_values("date").reset_index(drop=True)

    logger.error("All FII/DII sources failed — returning empty")
    return pd.DataFrame(columns=["date", "fii_buy", "fii_sell", "fii_net",
                                  "dii_buy", "dii_sell", "dii_net"])


def _breadth_from_bhavcopy() -> Optional[dict]:
    """Compute advance/decline from NSE daily Bhavcopy CSV (most reliable, no cookies needed).
    Downloads today's or most recent available Bhavcopy and counts advancers/decliners.
    """
    try:
        import requests, zipfile, io
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                   "Referer": "https://www.nseindia.com"}
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=8)

        # Try last 5 trading days (handles weekends/holidays)
        for offset in range(0, 6):
            dt = date.today() - timedelta(days=offset)
            url = (f"https://nsearchives.nseindia.com/content/cm/"
                   f"BhavCopy_NSE_CM_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip")
            try:
                r = session.get(url, headers=headers, timeout=12)
                if r.status_code != 200:
                    continue
                z = zipfile.ZipFile(io.BytesIO(r.content))
                df = pd.read_csv(z.open(z.namelist()[0]))

                # Exclude non-equity: govt bonds (GS/GB), T-bills (TB), InvIT/REIT (IV)
                exclude_series = {'GS', 'GB', 'TB', 'IV'}
                eq = df[~df['SctySrs'].isin(exclude_series)].copy()
                eq['ClsPric']      = pd.to_numeric(eq['ClsPric'], errors='coerce')
                eq['PrvsClsgPric'] = pd.to_numeric(eq['PrvsClsgPric'], errors='coerce')
                eq = eq.dropna(subset=['ClsPric', 'PrvsClsgPric'])
                eq = eq[eq['PrvsClsgPric'] > 0]

                advance  = int((eq['ClsPric'] > eq['PrvsClsgPric']).sum())
                decline  = int((eq['ClsPric'] < eq['PrvsClsgPric']).sum())
                unchanged = int((eq['ClsPric'] == eq['PrvsClsgPric']).sum())

                if advance + decline > 0:
                    logger.info(f"Bhavcopy breadth {dt}: adv={advance} dec={decline} unch={unchanged}")
                    return {"advance": advance, "decline": decline, "unchanged": unchanged}
            except Exception as e:
                logger.warning(f"Bhavcopy {dt} failed: {e}")
                continue
    except Exception as e:
        logger.warning(f"Bhavcopy breadth failed: {e}")
    return None


def _breadth_from_moneycontrol() -> Optional[dict]:
    """Fallback: parse advance/decline for NIFTY 500 from MoneyControl embedded JSON."""
    try:
        import requests, re, json as _json
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}
        session = requests.Session()
        session.get("https://www.moneycontrol.com", headers=headers, timeout=8)
        r = session.get(
            "https://www.moneycontrol.com/stocksmarketsindia/heat-map-advance-decline-ratio-nse-bse",
            headers={**headers, "Referer": "https://www.moneycontrol.com"}, timeout=12,
        )
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if not match:
            return None
        page_data = _json.loads(match.group(1))
        index_list = page_data["props"]["pageProps"]["adRatioData"]["indexList"]
        # Use NIFTY 500 as broadest available index
        for idx in index_list:
            if "500" in idx.get("indexName", ""):
                return {
                    "advance":   int(idx.get("advance", 0) or 0),
                    "decline":   int(idx.get("decline", 0) or 0),
                    "unchanged": 0,
                    "source":    "MC-NIFTY500",
                }
    except Exception as e:
        logger.warning(f"MC breadth fallback failed: {e}")
    return None


def fetch_market_breadth() -> dict:
    """Returns today's advance/decline counts.
    Priority: NSE Bhavcopy (reliable, no cookies) → NSE live API → MoneyControl.
    """
    # 1. Bhavcopy — most reliable, works in any network context
    bhav = _breadth_from_bhavcopy()
    if bhav:
        return bhav

    # 2. NSE live-analysis-advance API
    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
            "Referer": "https://www.nseindia.com/market-data/advance",
            "Accept": "application/json, */*",
        }
        session = requests.Session()
        try:
            session.get("https://www.nseindia.com", headers=headers, timeout=8)
        except Exception:
            pass
        try:
            session.get("https://www.nseindia.com/market-data/advance", headers=headers, timeout=6)
        except Exception:
            pass
        resp = session.get("https://www.nseindia.com/api/live-analysis-advance",
                           headers=headers, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            counts = data.get("advance", {}).get("count", {})
            adv = int(counts.get("Advances", 0) or 0)
            dec = int(counts.get("Declines", 0) or 0)
            if adv > 0 or dec > 0:
                return {"advance": adv, "decline": dec,
                        "unchanged": int(counts.get("Unchange", 0) or 0)}
    except Exception as e:
        logger.warning(f"NSE live breadth failed: {e}")

    # 3. MoneyControl NIFTY 500 fallback
    mc = _breadth_from_moneycontrol()
    if mc:
        return mc

    return {"advance": 0, "decline": 0, "unchanged": 0}
