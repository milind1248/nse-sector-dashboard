"""
Sector Index Stock — data sync engine.

Sources per sync:
  1. NiftyIndices factsheet PDF  — constituent list + official weightage %
  2. NSE EQUITY_L.csv            — company → symbol lookup (master list)
  3. NSE archives CSV (optional) — richer metadata (ISIN, industry, series)
  4. Yahoo Finance                — market cap per stock

Weightage always sourced from NiftyIndices official PDFs.
"""
from __future__ import annotations
import io, re, time, difflib
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from backend.storage.db import get_conn

_REQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}
_NSE_HEADERS = {**_REQ_HEADERS, "Referer": "https://www.nseindia.com/"}
_PDF_HEADERS = {**_REQ_HEADERS, "Referer": "https://www.niftyindices.com/"}
_NSE_CSV_BASE = "https://archives.nseindia.com/content/indices/"

# ── Full index catalogue (34 indices) ────────────────────────────────────────
# nse_csv: optional NSE archives CSV for extra metadata (symbol, ISIN, industry)
# pdf_url: authoritative NiftyIndices factsheet for constituent list + weightage
NSE_INDEX_SOURCES: dict[str, dict] = {
    "NIFTY_AUTO": {
        "sector": "Auto", "display": "Nifty Auto",
        "nse_csv": "ind_niftyautolist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_auto.pdf",
    },
    "BANKNIFTY": {
        "sector": "Bank", "display": "Nifty Bank",
        "nse_csv": "ind_niftybanklist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_bank.pdf",
    },
    "NIFTY_CAPITAL_GOODS": {
        "sector": "Capital Goods", "display": "Nifty Capital Goods",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Capital_Goods.pdf",
    },
    "NIFTY_CEMENT": {
        "sector": "Cement", "display": "Nifty Cement",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Cement.pdf",
    },
    "NIFTY_CHEMICALS": {
        "sector": "Chemicals", "display": "Nifty Chemicals",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Chemicals.pdf",
    },
    "NIFTY_COMM_TRANSPORT": {
        "sector": "Transport", "display": "Nifty Commercial & Transport",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Commercial_and_Transport_Services.pdf",
    },
    "NIFTY_CONSTRUCTION": {
        "sector": "Construction", "display": "Nifty Construction",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Construction.pdf",
    },
    "NCONSDUR": {
        "sector": "Consumer Durables", "display": "Nifty Consumer Durables",
        "nse_csv": "ind_niftyconsumerdurableslist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_nifty_consumer_durables.pdf",
    },
    "NIFTY_CONSUMER_SERVICES": {
        "sector": "Consumer Services", "display": "Nifty Consumer Services",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Consumer_Services.pdf",
    },
    "NIFTY_FIN_SERVICES": {
        "sector": "Financial Services", "display": "Nifty Financial Services",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_Nifty_Financial_Services.pdf",
    },
    "NIFTY_FIN_SERVICES_2550": {
        "sector": "Financial Services", "display": "Nifty Financial Services 25/50",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_financial_services_25_50.pdf",
    },
    "NIFTY_FIN_SERVICES_EXBNK": {
        "sector": "Financial Services", "display": "Nifty Financial Services Ex-Bank",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_financial_services_ex_bank.pdf",
    },
    "NIFTY_FMCG": {
        "sector": "FMCG", "display": "Nifty FMCG",
        "nse_csv": "ind_niftyfmcglist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_FMCG.pdf",
    },
    "NIFTY_HEALTHCARE": {
        "sector": "Healthcare", "display": "Nifty Healthcare",
        "nse_csv": "ind_niftyhealthcarelist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_healthcare.pdf",
    },
    "NIFTY_HOSPITALS": {
        "sector": "Healthcare", "display": "Nifty Hospitals",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Hospitals.pdf",
    },
    "NIFTY_HOUSING_FINANCE": {
        "sector": "Financial Services", "display": "Nifty Housing Finance",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Housing_Finance.pdf",
    },
    "NIFTY_INSURANCE": {
        "sector": "Financial Services", "display": "Nifty Insurance",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Insurance.pdf",
    },
    "NIFTY_IT": {
        "sector": "IT", "display": "Nifty IT",
        "nse_csv": "ind_niftyitlist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_it.pdf",
    },
    "NIFTY_MEDIA": {
        "sector": "Media", "display": "Nifty Media",
        "nse_csv": "ind_niftymedialist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_media.pdf",
    },
    "NIFTY_METAL": {
        "sector": "Metal", "display": "Nifty Metal",
        "nse_csv": "ind_niftymetallist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_metal.pdf",
    },
    "NIFTY_NBFC": {
        "sector": "Financial Services", "display": "Nifty NBFC",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_NBFC.pdf",
    },
    "NIFTY_OIL_AND_GAS": {
        "sector": "Oil & Gas", "display": "Nifty Oil & Gas",
        "nse_csv": "ind_niftyoilgaslist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_oil_and_gas.pdf",
    },
    "NIFTY_PHARMA": {
        "sector": "Pharma", "display": "Nifty Pharma",
        "nse_csv": "ind_niftypharmalist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_pharma.pdf",
    },
    "NIFTY_POWER": {
        "sector": "Power", "display": "Nifty Power",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Power.pdf",
    },
    "NIFTY_PRIVATE_BANK": {
        "sector": "Private Bank", "display": "Nifty Private Bank",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_private_bank.pdf",
    },
    "NIFTY_BANK": {
        "sector": "PSU Bank", "display": "Nifty PSU Bank",
        "nse_csv": "ind_niftypsubanklist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_psu_bank.pdf",
    },
    "NIFTY_REALTY": {
        "sector": "Real Estate", "display": "Nifty Realty",
        "nse_csv": "ind_niftyrealtylist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_realty.pdf",
    },
    "NIFTY_REITS_REALTY": {
        "sector": "Real Estate", "display": "Nifty REITs & Realty",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_REITs_and_Realty.pdf",
    },
    "NIFTY_RETAIL": {
        "sector": "Retail", "display": "Nifty Retail",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Retail.pdf",
    },
    "NIFTY_TELECOM": {
        "sector": "Telecom", "display": "Nifty Telecom",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Telecommunications.pdf",
    },
    "NIFTY500_HEALTHCARE": {
        "sector": "Healthcare", "display": "Nifty500 Healthcare",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty500Healthcare.pdf",
    },
    "NIFTY_MIDSMALL_FIN": {
        "sector": "Financial Services", "display": "Nifty MidSmall Financial Services",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_NiftyMidSmallFinancialSevices.pdf",
    },
    "NIFTY_MIDSMALL_HEALTH": {
        "sector": "Healthcare", "display": "Nifty MidSmall Healthcare",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_NiftyMidSmallHealthCare.pdf",
    },
    "NIFTY_MIDSMALL_IT": {
        "sector": "IT", "display": "Nifty MidSmall IT & Telecom",
        "nse_csv": None,
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_NiftyMidSmallITAndTelecom.pdf",
    },
}

# ── NSE master company→symbol lookup ─────────────────────────────────────────
_nse_master_cache: pd.DataFrame | None = None

def _get_nse_master() -> pd.DataFrame:
    """Download NSE EQUITY_L.csv — all listed companies with symbols."""
    global _nse_master_cache
    if _nse_master_cache is not None:
        return _nse_master_cache
    try:
        r = requests.get(
            "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
            headers=_NSE_HEADERS, timeout=20,
        )
        if r.status_code == 200:
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = [c.strip() for c in df.columns]
            # Columns: NAME OF COMPANY, SYMBOL, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
            df = df.rename(columns={
                "NAME OF COMPANY": "company_name",
                "SYMBOL":          "symbol",
                "SERIES":          "series",
                "ISIN NUMBER":     "isin",
            })
            _nse_master_cache = df[["company_name", "symbol", "series", "isin"]].dropna(subset=["symbol"])
            return _nse_master_cache
    except Exception:
        pass
    return pd.DataFrame(columns=["company_name", "symbol", "series", "isin"])


# ── Helpers ───────────────────────────────────────────────────────────────────
def _normalize(name: str) -> str:
    n = name.lower()
    for s in [" limited", " ltd.", " ltd", " l.t.d", " inc", " corp", " company", " co."]:
        n = n.replace(s, "")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", n).split())


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# Keywords that indicate a stats/metadata row — not a company name
_NON_COMPANY = re.compile(
    r"^(base value|no\. of|launch date|base date|calculation|rebalancing|"
    r"std\. deviation|beta|correlation|p/e|p/b|dividend|price return|"
    r"total return|qtd|ytd|since inception|methodology|index return|"
    r"statistics|inception)", re.I
)

def _looks_like_company(name: str) -> bool:
    """Return True if the string looks like a company name."""
    if _NON_COMPANY.match(name.strip()):
        return False
    # Must contain at least one word with 2+ letters (not just numbers/symbols)
    if not re.search(r"[A-Za-z]{2,}", name):
        return False
    return True


def _parse_pdf(pdf_bytes: bytes) -> list[dict]:
    """
    Parse NiftyIndices factsheet PDF.
    Returns [{company_name, weightage_pct}] from the constituent weight table.
    Filters out stats rows (Beta, Std Dev, Returns etc.).
    """
    try:
        import pdfplumber
    except ImportError:
        return []

    rows: list[dict] = []
    seen: set[str] = set()

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table[0]) < 2:
                        continue
                    # Must have ≥2 numeric rows in col[1]
                    numeric_count = sum(
                        1 for row in table
                        if row[1] and all(
                            _is_float(x) for x in str(row[1]).split("\n") if x.strip()
                        )
                    )
                    if numeric_count < 2:
                        continue

                    for row in table:
                        if not row[0] or not row[1]:
                            continue
                        names   = [n.strip() for n in str(row[0]).split("\n") if n.strip()]
                        wt_strs = [w.strip() for w in str(row[1]).split("\n") if w.strip()]
                        for name, wt_s in zip(names, wt_strs):
                            if not _is_float(wt_s):
                                continue
                            if not _looks_like_company(name):
                                continue
                            wt = float(wt_s)
                            if 0 < wt <= 100 and name not in seen:
                                rows.append({"company_name": name, "weightage_pct": wt})
                                seen.add(name)
    except Exception:
        pass
    return rows


def _fetch_pdf_bytes(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=_PDF_HEADERS, timeout=30)
        if r.status_code == 200 and b"%PDF" in r.content[:10]:
            return r.content
    except Exception:
        pass
    return None


def _fetch_nse_csv(csv_filename: str) -> pd.DataFrame | None:
    try:
        r = requests.get(_NSE_CSV_BASE + csv_filename, headers=_NSE_HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        return df.rename(columns={
            "Company Name": "company_name", "Industry": "industry",
            "Symbol": "symbol", "Series": "series", "ISIN Code": "isin",
        })
    except Exception:
        return None


def _lookup_symbol(company_name: str, master: pd.DataFrame) -> dict:
    """Fuzzy-match company name to NSE master list. Returns {symbol, series, isin}."""
    if master.empty:
        return {}
    key = _normalize(company_name)
    master_keys = master["company_name"].apply(_normalize)
    # Exact match first
    exact = master[master_keys == key]
    if not exact.empty:
        row = exact.iloc[0]
        return {"symbol": row["symbol"], "series": row.get("series"), "isin": row.get("isin")}
    # Fuzzy match
    matches = difflib.get_close_matches(key, master_keys.tolist(), n=1, cutoff=0.75)
    if matches:
        idx = master_keys[master_keys == matches[0]].index[0]
        row = master.iloc[idx]
        return {"symbol": row["symbol"], "series": row.get("series"), "isin": row.get("isin")}
    return {}


def _fetch_market_caps(symbols: list[str]) -> dict[str, float]:
    try:
        import yfinance as yf
    except ImportError:
        return {}
    caps: dict[str, float] = {}
    try:
        tickers = yf.Tickers(" ".join(s + ".NS" for s in symbols))
        for sym in symbols:
            try:
                mc = getattr(tickers.tickers[sym + ".NS"].fast_info, "market_cap", None)
                if mc and mc > 0:
                    caps[sym] = round(mc / 1e7, 2)
            except Exception:
                pass
    except Exception:
        pass
    return caps


def _extract_factsheet_date(pdf_bytes: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = pdf.pages[0].extract_text() or ""
        m = re.search(
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+\d{1,2},\s+\d{4}", text
        )
        return m.group(0) if m else ""
    except Exception:
        return ""


# ── Public API ────────────────────────────────────────────────────────────────
def sync_all(db_path: str | Path | None = None, progress_cb=None) -> dict:
    """
    Sync all indices.  For each index:
      1. Download NiftyIndices PDF → constituent names + official weights
      2. Enrich with NSE CSV (symbol/ISIN/industry) if available,
         else look up symbol from NSE master EQUITY_L.csv via fuzzy match
      3. Fetch market cap from Yahoo Finance
      4. Write to sector_intelligence table

    `db_path` is accepted for backward compatibility with existing callers
    but ignored — the connection now always goes through backend.storage.db.
    """
    def _prog(msg: str, pct: float):
        if progress_cb:
            try:
                progress_cb(msg, pct)
            except Exception:
                pass

    con = get_conn()

    total = len(NSE_INDEX_SOURCES)
    all_rows: list[dict] = []
    indices_ok: list[str] = []
    indices_failed: list[str] = []
    factsheet_dates: set[str] = set()
    errors: list[str] = []

    # Pre-load NSE master once
    _prog("Downloading NSE master company list…", 0.02)
    nse_master = _get_nse_master()

    for i, (index_name, meta) in enumerate(NSE_INDEX_SOURCES.items()):
        base_pct = 0.05 + (i / total) * 0.85

        # ── 1. PDF: constituent list + official weights ────────────────────────
        _prog(f"[{i+1}/{total}] PDF: {meta['display']}", base_pct)
        pdf_bytes = _fetch_pdf_bytes(meta["pdf_url"])
        if not pdf_bytes:
            indices_failed.append(index_name)
            errors.append(f"{index_name}: PDF download failed")
            continue

        pdf_rows = _parse_pdf(pdf_bytes)
        if not pdf_rows:
            indices_failed.append(index_name)
            errors.append(f"{index_name}: No constituent data found in PDF")
            continue

        fdate = _extract_factsheet_date(pdf_bytes)
        if fdate:
            factsheet_dates.add(fdate)

        # ── 2a. NSE CSV enrichment (if available) ─────────────────────────────
        csv_df: pd.DataFrame | None = None
        if meta.get("nse_csv"):
            csv_df = _fetch_nse_csv(meta["nse_csv"])

        # Build {norm_company_name: {symbol, isin, industry, series}} from CSV
        csv_lookup: dict[str, dict] = {}
        if csv_df is not None and not csv_df.empty:
            for _, row in csv_df.iterrows():
                k = _normalize(str(row.get("company_name", "")))
                csv_lookup[k] = {
                    "symbol":   row.get("symbol"),
                    "isin":     row.get("isin"),
                    "industry": row.get("industry"),
                    "series":   row.get("series"),
                }

        # ── 2b. Enrich each PDF row with symbol/metadata ───────────────────────
        rows: list[dict] = []
        for pdf_row in pdf_rows:
            cname = pdf_row["company_name"]
            norm  = _normalize(cname)

            # Try CSV lookup first (exact + fuzzy)
            meta_info = csv_lookup.get(norm)
            if not meta_info:
                fuzzy = difflib.get_close_matches(norm, list(csv_lookup.keys()), n=1, cutoff=0.75)
                if fuzzy:
                    meta_info = csv_lookup[fuzzy[0]]

            # Fall back to NSE master
            if not meta_info or not meta_info.get("symbol"):
                meta_info = _lookup_symbol(cname, nse_master)

            rows.append({
                "company_name":  cname,
                "symbol":        meta_info.get("symbol") if meta_info else None,
                "industry":      meta_info.get("industry") if meta_info else None,
                "series":        meta_info.get("series")   if meta_info else None,
                "isin":          meta_info.get("isin")     if meta_info else None,
                "sector":        meta["sector"],
                "index_name":    index_name,
                "index_display": meta["display"],
                "weightage_pct": pdf_row["weightage_pct"],
                "weight_source": "PDF",
                "market_cap_cr": None,
            })

        # ── 3. Yahoo Finance market caps ──────────────────────────────────────
        symbols = [r["symbol"] for r in rows if r.get("symbol")]
        if symbols:
            _prog(f"[{i+1}/{total}] Market caps: {meta['display']}", base_pct + 0.04 / total)
            caps = _fetch_market_caps(symbols)
            time.sleep(0.3)
            for r in rows:
                if r.get("symbol") and r["symbol"] in caps:
                    r["market_cap_cr"] = caps[r["symbol"]]

        all_rows.extend(rows)
        indices_ok.append(index_name)

    if not all_rows:
        con.close()
        return {"indices_ok": 0, "indices_failed": indices_failed,
                "stocks_total": 0, "stocks_added": 0, "stocks_updated": 0,
                "stocks_removed": 0, "errors": errors}

    _prog("Comparing with existing data…", 0.92)
    try:
        old_df = pd.read_sql("SELECT * FROM sector_intelligence", con)
    except Exception:
        old_df = pd.DataFrame()

    new_df = pd.DataFrame(all_rows)
    old_syms = set(old_df["symbol"].dropna()) if not old_df.empty else set()
    new_syms = set(new_df["symbol"].dropna())
    added   = len(new_syms - old_syms)
    removed = len(old_syms - new_syms)
    updated = 0
    if not old_df.empty:
        for sym in (new_syms & old_syms):
            try:
                o = float(old_df.loc[old_df["symbol"] == sym, "weightage_pct"].iloc[0])
                n = float(new_df.loc[new_df["symbol"] == sym, "weightage_pct"].iloc[0])
                if abs(o - n) > 0.01:
                    updated += 1
            except Exception:
                pass

    _prog("Writing to database…", 0.96)
    keep = ["company_name", "symbol", "industry", "series", "isin",
            "sector", "index_name", "index_display",
            "market_cap_cr", "weightage_pct", "weight_source"]
    write_df = new_df[[c for c in keep if c in new_df.columns]]

    # Delete only the indices we successfully synced, then insert fresh rows.
    # This preserves existing data for indices that failed (e.g. PDF blocked on Cloud).
    synced_index_names = list(write_df["index_name"].unique()) if "index_name" in write_df.columns else []
    if synced_index_names:
        placeholders = ",".join(["%s"] * len(synced_index_names))
        con.execute(f"DELETE FROM sector_intelligence WHERE index_name IN ({placeholders})",
                    synced_index_names)
    for _, row in write_df.iterrows():
        con.execute(
            "INSERT INTO sector_intelligence "
            "(company_name, symbol, industry, series, isin, sector, index_name, index_display, "
            " market_cap_cr, weightage_pct, weight_source) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (row.get("company_name"), row.get("symbol"), row.get("industry"),
             row.get("series"), row.get("isin"), row.get("sector"),
             row.get("index_name"), row.get("index_display"),
             row.get("market_cap_cr"), row.get("weightage_pct"), row.get("weight_source")),
        )
    con.execute("CREATE INDEX IF NOT EXISTS idx_si_sector ON sector_intelligence(sector)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_si_index  ON sector_intelligence(index_name)")

    fdate_str = ", ".join(sorted(factsheet_dates)) or "N/A"
    changes   = f"+{added} added, ~{updated} updated, -{removed} removed"
    con.execute(
        "INSERT INTO sector_sync_log "
        "(synced_at, source, indices_synced, stocks_total, changes, factsheet_date) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (datetime.now(),
         "NiftyIndices PDFs + NSE archives CSV + NSE EQUITY_L master + Yahoo Finance",
         len(indices_ok), len(write_df), changes, fdate_str),
    )
    con.commit()
    con.close()

    _prog("Sync complete!", 1.0)
    return {
        "indices_ok":     len(indices_ok),
        "indices_failed": indices_failed,
        "stocks_total":   len(write_df),
        "stocks_added":   added,
        "stocks_updated": updated,
        "stocks_removed": removed,
        "factsheet_date": fdate_str,
        "errors":         errors,
    }


def get_last_sync(db_path: str | Path | None = None) -> dict | None:
    """`db_path` accepted for backward compatibility with existing callers but ignored."""
    try:
        con = get_conn()
        row = con.execute(
            "SELECT synced_at, source, indices_synced, stocks_total, changes, factsheet_date "
            "FROM sector_sync_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        con.close()
        if row:
            return {"synced_at": str(row[0]), "source": row[1], "indices_synced": row[2],
                    "stocks_total": row[3], "changes": row[4], "factsheet_date": row[5] or "N/A"}
    except Exception:
        pass
    return None
