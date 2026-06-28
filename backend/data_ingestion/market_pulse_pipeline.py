"""
Market Pulse Pipeline — runs once after market close (8 PM IST, Mon–Fri).
Fetches Bhavcopy, sector returns, and RRG; stores results in SQLite so the
Market Pulse page never makes a live HTTP call on page load.

Tables created/updated:
  market_breadth  — advance/decline/unchanged per trade date
  sector_heatmap  — sector % returns per trade date
  rrg_snapshot    — RRG coordinates + trail per trade date
"""
import sqlite3
import json
import logging
import zipfile
import io
import requests
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
import numpy as np

from config import SECTOR_STOCKS, NIFTY_SYMBOL
from backend.data_ingestion.yfinance_fetcher import (
    fetch_all_sector_prices, compute_pct_returns, _get_close,
)
from backend.calculations.relative_strength import compute_rrg_coordinates

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nse_dashboard.db"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db():
    return sqlite3.connect(_DB_PATH)


def _ensure_tables():
    con = _db()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS market_breadth (
            trade_date  TEXT PRIMARY KEY,
            advance     INTEGER,
            decline     INTEGER,
            unchanged   INTEGER,
            ad_ratio    REAL,
            updated_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS sector_heatmap (
            trade_date  TEXT,
            sector      TEXT,
            ret_1w      REAL,
            ret_2w      REAL,
            ret_1m      REAL,
            ret_3m      REAL,
            ret_6m      REAL,
            ret_1y      REAL,
            updated_at  TEXT,
            PRIMARY KEY (trade_date, sector)
        );

        CREATE TABLE IF NOT EXISTS rrg_snapshot (
            trade_date  TEXT,
            sector      TEXT,
            rs_ratio    REAL,
            rs_momentum REAL,
            quadrant    TEXT,
            trail_json  TEXT,
            updated_at  TEXT,
            PRIMARY KEY (trade_date, sector)
        );
    """)
    con.commit()
    con.close()


_ensure_tables()


# ── Step 1: NSE Bhavcopy → breadth ───────────────────────────────────────────

def _fetch_breadth(trade_date: date) -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for offset in range(7):
        dt = trade_date - timedelta(days=offset)
        url = (
            f"https://nsearchives.nseindia.com/content/cm/"
            f"BhavCopy_NSE_CM_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip"
        )
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code != 200:
                continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            eq = df[~df["SctySrs"].isin({"GS", "GB", "TB", "IV"})].copy()
            eq["ClsPric"]      = pd.to_numeric(eq["ClsPric"],      errors="coerce")
            eq["PrvsClsgPric"] = pd.to_numeric(eq["PrvsClsgPric"], errors="coerce")
            eq = eq.dropna(subset=["ClsPric", "PrvsClsgPric"])
            eq = eq[eq["PrvsClsgPric"] > 0]
            adv = int((eq["ClsPric"] > eq["PrvsClsgPric"]).sum())
            dec = int((eq["ClsPric"] < eq["PrvsClsgPric"]).sum())
            unc = int((eq["ClsPric"] == eq["PrvsClsgPric"]).sum())
            if adv + dec > 0:
                logger.info(f"Bhavcopy fetched for {dt}: A={adv} D={dec}")
                return {"trade_date": dt.isoformat(), "advance": adv,
                        "decline": dec, "unchanged": unc,
                        "ad_ratio": round(adv / dec, 3) if dec else None}
        except Exception as e:
            logger.warning(f"Bhavcopy {dt} failed: {e}")
    return {}


# ── Step 2: Sector returns (heatmap) ─────────────────────────────────────────

def _fetch_sector_returns(trade_date: date) -> list[dict]:
    sector_prices = fetch_all_sector_prices()
    rows = []
    for sector, df in sector_prices.items():
        if df is None or df.empty:
            continue
        try:
            rets = compute_pct_returns(df)
            rows.append({
                "trade_date": trade_date.isoformat(),
                "sector":     sector,
                "ret_1w":     rets.get("pct_1w"),
                "ret_2w":     rets.get("pct_2w"),
                "ret_1m":     rets.get("pct_1m"),
                "ret_3m":     rets.get("pct_3m"),
                "ret_6m":     rets.get("pct_6m"),
                "ret_1y":     rets.get("pct_1y"),
            })
        except Exception as e:
            logger.warning(f"Sector returns {sector}: {e}")
    return rows


# ── Step 3: RRG coordinates ───────────────────────────────────────────────────

def _fetch_rrg(trade_date: date) -> list[dict]:
    sector_prices = fetch_all_sector_prices()
    nifty_raw = yf.download(NIFTY_SYMBOL, period="1y", interval="1d",
                             progress=False, auto_adjust=True)
    if nifty_raw is None or nifty_raw.empty:
        return []
    nifty_raw.index = pd.to_datetime(nifty_raw.index).date
    rrg = compute_rrg_coordinates(sector_prices, nifty_raw)
    rows = []
    for item in (rrg or []):
        rows.append({
            "trade_date":  trade_date.isoformat(),
            "sector":      item["sector"],
            "rs_ratio":    item.get("rs_ratio"),
            "rs_momentum": item.get("rs_momentum"),
            "quadrant":    item.get("quadrant"),
            "trail_json":  json.dumps(item.get("trail", [])),
        })
    return rows


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_market_pulse_pipeline(triggered_by: str = "scheduler") -> dict:
    """
    Full Market Pulse data cook. Writes to SQLite.
    Returns summary dict with counts for job logging.
    """
    _ensure_tables()
    today      = date.today()
    now_utc    = pd.Timestamp.utcnow().isoformat()
    summary    = {}

    # ── Breadth ───────────────────────────────────────────────────────────────
    logger.info("Market Pulse pipeline: fetching Bhavcopy breadth...")
    breadth = _fetch_breadth(today)
    if breadth:
        con = _db()
        con.execute("""
            INSERT OR REPLACE INTO market_breadth
            (trade_date, advance, decline, unchanged, ad_ratio, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (breadth["trade_date"], breadth["advance"], breadth["decline"],
              breadth["unchanged"], breadth["ad_ratio"], now_utc))
        con.commit(); con.close()
        summary["breadth_date"] = breadth["trade_date"]
        logger.info(f"Breadth stored for {breadth['trade_date']}")
    else:
        logger.warning("Bhavcopy breadth fetch failed — skipping")

    # ── Sector heatmap ────────────────────────────────────────────────────────
    logger.info("Market Pulse pipeline: computing sector returns...")
    heatmap_rows = _fetch_sector_returns(today)
    if heatmap_rows:
        con = _db()
        con.executemany("""
            INSERT OR REPLACE INTO sector_heatmap
            (trade_date, sector, ret_1w, ret_2w, ret_1m, ret_3m, ret_6m, ret_1y, updated_at)
            VALUES (:trade_date, :sector, :ret_1w, :ret_2w, :ret_1m,
                    :ret_3m, :ret_6m, :ret_1y, '""" + now_utc + """')
        """, heatmap_rows)
        con.commit(); con.close()
        summary["heatmap_sectors"] = len(heatmap_rows)
        logger.info(f"Heatmap stored: {len(heatmap_rows)} sectors")

    # ── RRG ───────────────────────────────────────────────────────────────────
    logger.info("Market Pulse pipeline: computing RRG...")
    rrg_rows = _fetch_rrg(today)
    if rrg_rows:
        con = _db()
        con.executemany("""
            INSERT OR REPLACE INTO rrg_snapshot
            (trade_date, sector, rs_ratio, rs_momentum, quadrant, trail_json, updated_at)
            VALUES (:trade_date, :sector, :rs_ratio, :rs_momentum,
                    :quadrant, :trail_json, '""" + now_utc + """')
        """, rrg_rows)
        con.commit(); con.close()
        summary["rrg_sectors"] = len(rrg_rows)
        logger.info(f"RRG stored: {len(rrg_rows)} sectors")

    # ── Purge data older than 90 days ────────────────────────────────────────
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    con = _db()
    for tbl in ("market_breadth", "sector_heatmap", "rrg_snapshot"):
        cur = con.execute(f"DELETE FROM {tbl} WHERE trade_date < ?", (cutoff,))
        if cur.rowcount:
            logger.info(f"Purged {cur.rowcount} rows from {tbl} older than {cutoff}")
    con.commit()
    con.close()

    logger.info(f"Market Pulse pipeline complete: {summary}")
    return summary
