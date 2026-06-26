"""
Sector Index Stock — data sync engine.

Sources:
  1. NSE India archives (public CSVs) → constituent list, industry, ISIN
  2. Yahoo Finance (yfinance)          → market cap, last price
  3. Calculated                        → weightage % from free-float mkt cap

Usage:
    from backend.data_ingestion.sector_sync import sync_all
    result = sync_all(db_path, progress_cb=lambda msg, pct: None)
"""
from __future__ import annotations
import sqlite3, time, traceback
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

# ── NSE archive CSV map ───────────────────────────────────────────────────────
_BASE = "https://archives.nseindia.com/content/indices/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://www.nseindia.com/",
    "Accept":     "text/html,application/xhtml+xml,*/*;q=0.8",
}

NSE_INDEX_SOURCES: dict[str, dict] = {
    "BANKNIFTY": {
        "sector": "Bank", "display": "Bank Nifty",
        "csv": "ind_niftybanklist.csv",
    },
    "NIFTY_AUTO": {
        "sector": "Auto", "display": "Nifty Auto",
        "csv": "ind_niftyautolist.csv",
    },
    "NCONSDUR": {
        "sector": "Consumer Durables", "display": "Nifty Consumer Durables",
        "csv": "ind_niftyconsumerdurableslist.csv",
    },
    "NIFTY_FMCG": {
        "sector": "FMCG", "display": "Nifty FMCG",
        "csv": "ind_niftyfmcglist.csv",
    },
    "NIFTY_IT": {
        "sector": "IT", "display": "Nifty IT",
        "csv": "ind_niftyitlist.csv",
    },
    "NIFTY_MEDIA": {
        "sector": "Media", "display": "Nifty Media",
        "csv": "ind_niftymedialist.csv",
    },
    "NIFTY_METAL": {
        "sector": "Metal", "display": "Nifty Metal",
        "csv": "ind_niftymetallist.csv",
    },
    "NIFTY_OIL_AND_GAS": {
        "sector": "OIL & GAS", "display": "Nifty Oil & Gas",
        "csv": "ind_niftyoilgaslist.csv",
    },
    "NIFTY_PHARMA": {
        "sector": "PHARMA", "display": "Nifty Pharma",
        "csv": "ind_niftypharmalist.csv",
    },
    "NIFTY_BANK": {
        "sector": "PSU Bank", "display": "Nifty PSU Bank",
        "csv": "ind_niftypsubanklist.csv",
    },
    "NIFTY_REALTY": {
        "sector": "REALTY", "display": "Nifty Realty",
        "csv": "ind_niftyrealtylist.csv",
    },
    "NIFTY_HEALTHCARE": {
        "sector": "Healthcare", "display": "Nifty Healthcare",
        "csv": "ind_niftyhealthcarelist.csv",
    },
}

# Yahoo Finance suffix for NSE stocks
_YF_SUFFIX = ".NS"


def _fetch_csv(csv_filename: str) -> pd.DataFrame | None:
    url = _BASE + csv_filename
    try:
        r = requests.get(url, headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        df = pd.read_csv(StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        return df
    except Exception:
        return None


def _fetch_market_caps(symbols: list[str]) -> dict[str, float]:
    """Return {symbol: market_cap_cr} from yfinance. Best-effort."""
    try:
        import yfinance as yf
    except ImportError:
        return {}

    yf_syms = [s + _YF_SUFFIX for s in symbols]
    caps: dict[str, float] = {}
    try:
        tickers = yf.Tickers(" ".join(yf_syms))
        for sym in symbols:
            try:
                info = tickers.tickers[sym + _YF_SUFFIX].fast_info
                mc = getattr(info, "market_cap", None)
                if mc and mc > 0:
                    caps[sym] = round(mc / 1e7, 2)   # ₹ Cr
            except Exception:
                pass
        return caps
    except Exception:
        return caps


def _ensure_sync_log(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS sector_sync_log ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  synced_at TEXT NOT NULL,"
        "  source TEXT,"
        "  indices_synced INTEGER,"
        "  stocks_total INTEGER,"
        "  changes TEXT"
        ")"
    )
    con.commit()


def sync_all(
    db_path: str | Path,
    progress_cb=None,
) -> dict:
    """
    Sync all indices from NSE + yfinance into sector_intelligence table.

    progress_cb(message: str, pct: float) called throughout.
    Returns summary dict with keys: indices_ok, indices_failed, stocks_added,
    stocks_updated, stocks_removed, errors.
    """
    def _prog(msg: str, pct: float):
        if progress_cb:
            progress_cb(msg, pct)

    con = sqlite3.connect(str(db_path), timeout=10)
    _ensure_sync_log(con)

    indices_ok, indices_failed = 0, []
    stocks_added, stocks_updated, stocks_removed = 0, 0, 0
    errors: list[str] = []
    all_new_rows: list[dict] = []

    total = len(NSE_INDEX_SOURCES)

    for i, (index_name, meta) in enumerate(NSE_INDEX_SOURCES.items()):
        pct_base = i / total
        _prog(f"⬇️  Fetching {meta['display']} from NSE…", pct_base * 0.6)

        df = _fetch_csv(meta["csv"])
        if df is None or df.empty:
            indices_failed.append(index_name)
            errors.append(f"{index_name}: CSV download failed")
            continue

        # Normalise columns
        col_map = {
            "Company Name": "company_name",
            "Industry":     "industry",
            "Symbol":       "symbol",
            "Series":       "series",
            "ISIN Code":    "isin",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df["index_name"]    = index_name
        df["index_display"] = meta["display"]
        df["sector"]        = meta["sector"]

        for col in ["company_name","industry","symbol","series","isin"]:
            if col not in df.columns:
                df[col] = None

        indices_ok += 1
        symbols = df["symbol"].dropna().tolist()

        # Fetch market caps
        _prog(f"💹 Fetching market caps for {meta['display']} ({len(symbols)} stocks)…",
              pct_base * 0.6 + 0.3 / total)
        caps = _fetch_market_caps(symbols)
        time.sleep(0.5)   # be polite

        df["market_cap_cr"] = df["symbol"].map(caps)

        # Calculate weightage % from market cap
        total_cap = df["market_cap_cr"].sum()
        if total_cap and total_cap > 0:
            df["weightage_pct"] = (df["market_cap_cr"] / total_cap * 100).round(4)
        else:
            df["weightage_pct"] = None

        df = df.sort_values("weightage_pct", ascending=False, na_position="last")
        all_new_rows.extend(df.to_dict("records"))

    if not all_new_rows:
        con.close()
        return {
            "indices_ok": 0, "indices_failed": indices_failed,
            "stocks_added": 0, "stocks_updated": 0, "stocks_removed": 0,
            "errors": errors,
        }

    _prog("🗄️  Comparing with existing data…", 0.85)

    # Load existing
    try:
        old_df = pd.read_sql("SELECT * FROM sector_intelligence", con)
    except Exception:
        old_df = pd.DataFrame()

    new_df = pd.DataFrame(all_new_rows)

    # Diff counts
    old_syms = set(old_df["symbol"].dropna()) if not old_df.empty else set()
    new_syms = set(new_df["symbol"].dropna())
    stocks_added   = len(new_syms - old_syms)
    stocks_removed = len(old_syms - new_syms)
    # Updated = same symbol but changed weightage/mktcap
    if not old_df.empty:
        common = list(new_syms & old_syms)
        old_common = old_df[old_df["symbol"].isin(common)].set_index("symbol")
        new_common = new_df[new_df["symbol"].isin(common)].set_index("symbol")
        for sym in common:
            try:
                o_wt = old_common.loc[sym, "weightage_pct"] if sym in old_common.index else None
                n_wt = new_common.loc[sym, "weightage_pct"] if sym in new_common.index else None
                if o_wt is not None and n_wt is not None and abs(float(o_wt) - float(n_wt)) > 0.01:
                    stocks_updated += 1
            except Exception:
                pass

    _prog("💾 Writing updated data to database…", 0.92)

    # Replace table
    keep_cols = ["company_name","symbol","industry","series","isin",
                 "sector","index_name","index_display","market_cap_cr","weightage_pct"]
    write_df = new_df[[c for c in keep_cols if c in new_df.columns]]
    write_df.to_sql("sector_intelligence", con, if_exists="replace", index=False)
    con.execute("CREATE INDEX IF NOT EXISTS idx_si_sector ON sector_intelligence(sector)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_si_index  ON sector_intelligence(index_name)")

    # Log
    changes = (f"+{stocks_added} added, ~{stocks_updated} updated, "
               f"-{stocks_removed} removed")
    sources = "NSE India archives (constituents) + Yahoo Finance (market cap)"
    con.execute(
        "INSERT INTO sector_sync_log (synced_at, source, indices_synced, stocks_total, changes) "
        "VALUES (?,?,?,?,?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sources,
         indices_ok, len(write_df), changes),
    )
    con.commit()
    con.close()

    _prog("✅ Sync complete!", 1.0)
    return {
        "indices_ok":      indices_ok,
        "indices_failed":  indices_failed,
        "stocks_total":    len(write_df),
        "stocks_added":    stocks_added,
        "stocks_updated":  stocks_updated,
        "stocks_removed":  stocks_removed,
        "errors":          errors,
    }


def get_last_sync(db_path: str | Path) -> dict | None:
    try:
        con = sqlite3.connect(str(db_path), timeout=5)
        _ensure_sync_log(con)
        row = con.execute(
            "SELECT synced_at, source, indices_synced, stocks_total, changes "
            "FROM sector_sync_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        con.close()
        if row:
            return {
                "synced_at":      row[0],
                "source":         row[1],
                "indices_synced": row[2],
                "stocks_total":   row[3],
                "changes":        row[4],
            }
    except Exception:
        pass
    return None
