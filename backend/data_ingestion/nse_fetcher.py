"""Fetches FII/DII and market breadth data from NSE India / nsepython."""
import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _try_nsepython_fii() -> Optional[pd.DataFrame]:
    try:
        from nsepython import fii_dii_data
        df = fii_dii_data()
        return df
    except Exception as e:
        logger.warning(f"nsepython fii_dii_data failed: {e}")
    return None


def _try_nse_web_fii() -> Optional[pd.DataFrame]:
    """Fallback: scrape NSE FII/DII page."""
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
        if resp.status_code == 200:
            data = resp.json()
            rows = []
            for item in data:
                try:
                    rows.append({
                        "date":     pd.to_datetime(item.get("date", "")).date(),
                        "fii_buy":  float(str(item.get("fiiBuyValue", "0")).replace(",", "") or 0),
                        "fii_sell": float(str(item.get("fiiSellValue", "0")).replace(",", "") or 0),
                        "fii_net":  float(str(item.get("fiiNetValue", "0")).replace(",", "") or 0),
                        "dii_buy":  float(str(item.get("diiBuyValue", "0")).replace(",", "") or 0),
                        "dii_sell": float(str(item.get("diiSellValue", "0")).replace(",", "") or 0),
                        "dii_net":  float(str(item.get("diiNetValue", "0")).replace(",", "") or 0),
                    })
                except Exception:
                    continue
            if rows:
                return pd.DataFrame(rows)
    except Exception as e:
        logger.warning(f"NSE web FII fetch failed: {e}")
    return None


def fetch_fii_dii(days: int = 90) -> pd.DataFrame:
    """Returns DataFrame with columns: date, fii_buy, fii_sell, fii_net, dii_buy, dii_sell, dii_net."""
    df = _try_nsepython_fii()
    if df is None or df.empty:
        df = _try_nse_web_fii()
    if df is None or df.empty:
        logger.error("All FII/DII sources failed — returning empty")
        return pd.DataFrame(columns=["date", "fii_buy", "fii_sell", "fii_net",
                                     "dii_buy", "dii_sell", "dii_net"])

    # Normalise column names (nsepython returns varying names)
    df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]
    col_map = {}
    for col in df.columns:
        if "fii" in col and "buy" in col:   col_map[col] = "fii_buy"
        if "fii" in col and "sell" in col:  col_map[col] = "fii_sell"
        if "fii" in col and "net" in col:   col_map[col] = "fii_net"
        if "dii" in col and "buy" in col:   col_map[col] = "dii_buy"
        if "dii" in col and "sell" in col:  col_map[col] = "dii_sell"
        if "dii" in col and "net" in col:   col_map[col] = "dii_net"
        if "date" in col:                   col_map[col] = "date"
    df = df.rename(columns=col_map)

    # Keep only needed columns
    needed = ["date", "fii_buy", "fii_sell", "fii_net", "dii_buy", "dii_sell", "dii_net"]
    df = df[[c for c in needed if c in df.columns]]

    # Parse date
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        df = df.dropna(subset=["date"])

    # Numeric cast
    for col in ["fii_buy", "fii_sell", "fii_net", "dii_buy", "dii_sell", "dii_net"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", "").str.replace("(", "-").str.replace(")", ""),
                errors="coerce"
            )

    cutoff = date.today() - timedelta(days=days)
    if "date" in df.columns:
        df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


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
