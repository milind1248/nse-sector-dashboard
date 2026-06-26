"""
Sector Index Stock — data sync engine.

Sources (per sync):
  1. NSE India archives (public CSV) — constituent list: symbol, industry, ISIN
  2. NiftyIndices factsheet PDF      — official weightage % per constituent
  3. Yahoo Finance (yfinance)        — market cap & last price per stock

Weightage source priority: PDF factsheet > calculated from market cap
"""
from __future__ import annotations
import io, re, sqlite3, time, difflib
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

# ── HTTP session ──────────────────────────────────────────────────────────────
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "text/html,application/xhtml+xml,*/*;q=0.8",
})

# ── Index config ──────────────────────────────────────────────────────────────
NSE_INDEX_SOURCES: dict[str, dict] = {
    "BANKNIFTY": {
        "sector": "Bank", "display": "Bank Nifty",
        "nse_csv": "ind_niftybanklist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_bank.pdf",
    },
    "NIFTY_AUTO": {
        "sector": "Auto", "display": "Nifty Auto",
        "nse_csv": "ind_niftyautolist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_auto.pdf",
    },
    "NCONSDUR": {
        "sector": "Consumer Durables", "display": "Nifty Consumer Durables",
        "nse_csv": "ind_niftyconsumerdurableslist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_nifty_consumer_durables.pdf",
    },
    "NIFTY_FMCG": {
        "sector": "FMCG", "display": "Nifty FMCG",
        "nse_csv": "ind_niftyfmcglist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_FMCG.pdf",
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
    "NIFTY_OIL_AND_GAS": {
        "sector": "OIL & GAS", "display": "Nifty Oil & Gas",
        "nse_csv": "ind_niftyoilgaslist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_nifty_oil_and_gas.pdf",
    },
    "NIFTY_PHARMA": {
        "sector": "PHARMA", "display": "Nifty Pharma",
        "nse_csv": "ind_niftypharmalist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_pharma.pdf",
    },
    "NIFTY_BANK": {
        "sector": "PSU Bank", "display": "Nifty PSU Bank",
        "nse_csv": "ind_niftypsubanklist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_psu_bank.pdf",
    },
    "NIFTY_REALTY": {
        "sector": "REALTY", "display": "Nifty Realty",
        "nse_csv": "ind_niftyrealtylist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/ind_nifty_realty.pdf",
    },
    "NIFTY_HEALTHCARE": {
        "sector": "Healthcare", "display": "Nifty Healthcare",
        "nse_csv": "ind_niftyhealthcarelist.csv",
        "pdf_url": "https://www.niftyindices.com/Factsheet/Factsheet_Nifty_Healthcare_Index.pdf",
    },
}

_NSE_CSV_BASE = "https://archives.nseindia.com/content/indices/"
_NSE_HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://www.nseindia.com/",
}

# ── Step 1: NSE CSV — constituent list ───────────────────────────────────────
def _fetch_nse_csv(csv_filename: str) -> pd.DataFrame | None:
    url = _NSE_CSV_BASE + csv_filename
    try:
        r = requests.get(url, headers=_NSE_HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        col_map = {
            "Company Name": "company_name",
            "Industry":     "industry",
            "Symbol":       "symbol",
            "Series":       "series",
            "ISIN Code":    "isin",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df
    except Exception:
        return None


# ── Step 2: NiftyIndices PDF — official weightages ────────────────────────────
def _normalize_name(name: str) -> str:
    """Lowercase, remove punctuation and common suffixes for fuzzy matching."""
    n = name.lower()
    for suffix in [" limited", " ltd.", " ltd", " l.t.d.", " inc", " corp"]:
        n = n.replace(suffix, "")
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return " ".join(n.split())


def _parse_weights_from_pdf(pdf_bytes: bytes) -> dict[str, float]:
    """
    Extract {normalized_company_name: weight_pct} from niftyindices factsheet PDF.
    Looks for a 2-column table on page 1 where col[1] are float-like strings.
    """
    try:
        import pdfplumber
    except ImportError:
        return {}

    weights: dict[str, float] = {}
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            # Page 1 has the constituent table
            page = pdf.pages[0]
            tables = page.extract_tables()

            for table in tables:
                if not table or len(table[0]) < 2:
                    continue
                # Identify the constituent weight table:
                # col[1] cells must be float-like (possibly newline-separated)
                col1_vals = [str(row[1] or "").strip() for row in table if row[1]]
                numeric_count = sum(
                    1 for v in col1_vals
                    if all(_is_float(x) for x in v.split("\n") if x.strip())
                )
                if numeric_count < 2:
                    continue

                # Parse name→weight pairs
                for row in table:
                    if not row[0] or not row[1]:
                        continue
                    names   = [n.strip() for n in str(row[0]).split("\n") if n.strip()]
                    wt_strs = [w.strip() for w in str(row[1]).split("\n") if w.strip()]

                    for name, wt_str in zip(names, wt_strs):
                        try:
                            wt = float(wt_str)
                            if 0 < wt <= 100:
                                weights[_normalize_name(name)] = wt
                        except ValueError:
                            pass

        return weights
    except Exception:
        return {}


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _match_weight(company_name: str, pdf_weights: dict[str, float]) -> float | None:
    """Fuzzy-match company_name to pdf_weights keys. Returns weight or None."""
    if not pdf_weights:
        return None
    key = _normalize_name(company_name)
    if key in pdf_weights:
        return pdf_weights[key]
    # Try difflib closest match
    matches = difflib.get_close_matches(key, pdf_weights.keys(), n=1, cutoff=0.72)
    if matches:
        return pdf_weights[matches[0]]
    return None


# ── Step 3: Yahoo Finance — market cap ───────────────────────────────────────
def _fetch_market_caps(symbols: list[str]) -> dict[str, float]:
    try:
        import yfinance as yf
    except ImportError:
        return {}
    caps: dict[str, float] = {}
    yf_syms = [s + ".NS" for s in symbols]
    try:
        tickers = yf.Tickers(" ".join(yf_syms))
        for sym in symbols:
            try:
                info = tickers.tickers[sym + ".NS"].fast_info
                mc = getattr(info, "market_cap", None)
                if mc and mc > 0:
                    caps[sym] = round(mc / 1e7, 2)   # rupees → crores
            except Exception:
                pass
    except Exception:
        pass
    return caps


# ── Main sync ─────────────────────────────────────────────────────────────────
def _ensure_tables(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS sector_sync_log ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  synced_at TEXT NOT NULL,"
        "  source TEXT,"
        "  indices_synced INTEGER,"
        "  stocks_total INTEGER,"
        "  changes TEXT,"
        "  factsheet_date TEXT"
        ")"
    )
    con.commit()


def sync_all(
    db_path: str | Path,
    progress_cb=None,
) -> dict:
    """
    Full sync: NSE CSV (constituents) + NiftyIndices PDF (weightages) + yfinance (mkt cap).

    progress_cb(message: str, pct: float) is called throughout.
    Returns summary dict.
    """
    def _prog(msg: str, pct: float):
        if progress_cb:
            try:
                progress_cb(msg, pct)
            except Exception:
                pass

    con = sqlite3.connect(str(db_path), timeout=10)
    _ensure_tables(con)

    total = len(NSE_INDEX_SOURCES)
    all_rows: list[dict] = []
    indices_ok: list[str] = []
    indices_failed: list[str] = []
    pdf_dates: list[str] = []
    errors: list[str] = []

    for i, (index_name, meta) in enumerate(NSE_INDEX_SOURCES.items()):
        base_pct = i / total

        # ── 1. NSE CSV ────────────────────────────────────────────────────────
        _prog(f"NSE CSV: {meta['display']} ({i+1}/{total})", base_pct * 0.55)
        csv_df = _fetch_nse_csv(meta["nse_csv"])
        if csv_df is None or csv_df.empty:
            indices_failed.append(index_name)
            errors.append(f"{index_name}: NSE CSV download failed")
            continue

        csv_df["index_name"]    = index_name
        csv_df["index_display"] = meta["display"]
        csv_df["sector"]        = meta["sector"]
        for col in ["company_name", "industry", "symbol", "series", "isin"]:
            if col not in csv_df.columns:
                csv_df[col] = None

        # ── 2. NiftyIndices PDF ───────────────────────────────────────────────
        _prog(f"PDF factsheet: {meta['display']}", base_pct * 0.55 + 0.2 / total)
        pdf_weights: dict[str, float] = {}
        factsheet_date = ""
        try:
            pdf_r = requests.get(
                meta["pdf_url"],
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.niftyindices.com/"},
                timeout=30,
            )
            if pdf_r.status_code == 200 and b"%PDF" in pdf_r.content[:10]:
                pdf_weights = _parse_weights_from_pdf(pdf_r.content)
                # Extract date from first line of page 1 text
                try:
                    import pdfplumber
                    with pdfplumber.open(io.BytesIO(pdf_r.content)) as pdf:
                        first_text = pdf.pages[0].extract_text() or ""
                        date_match = re.search(
                            r"(January|February|March|April|May|June|July|August|"
                            r"September|October|November|December)\s+\d{1,2},\s+\d{4}",
                            first_text,
                        )
                        if date_match:
                            factsheet_date = date_match.group(0)
                            if factsheet_date not in pdf_dates:
                                pdf_dates.append(factsheet_date)
                except Exception:
                    pass
        except Exception as e:
            errors.append(f"{index_name}: PDF failed ({e})")

        # ── 3. Assign weightages ──────────────────────────────────────────────
        if pdf_weights:
            csv_df["weightage_pct"] = csv_df["company_name"].apply(
                lambda n: _match_weight(str(n), pdf_weights) if pd.notna(n) else None
            )
            source_tag = "PDF"
        else:
            csv_df["weightage_pct"] = None
            source_tag = "none"

        # ── 4. Yahoo Finance — market cap ─────────────────────────────────────
        _prog(f"Market caps: {meta['display']}", base_pct * 0.55 + 0.35 / total)
        symbols = csv_df["symbol"].dropna().tolist()
        caps = _fetch_market_caps(symbols)
        time.sleep(0.4)
        csv_df["market_cap_cr"] = csv_df["symbol"].map(caps)

        # If no PDF weights, fall back to mkt-cap calculated weights
        if source_tag == "none":
            total_cap = csv_df["market_cap_cr"].sum()
            if total_cap and total_cap > 0:
                csv_df["weightage_pct"] = (csv_df["market_cap_cr"] / total_cap * 100).round(4)

        csv_df["weight_source"] = source_tag
        csv_df = csv_df.sort_values("weightage_pct", ascending=False, na_position="last")
        all_rows.extend(csv_df.to_dict("records"))
        indices_ok.append(index_name)

    if not all_rows:
        con.close()
        return {
            "indices_ok": 0, "indices_failed": indices_failed,
            "stocks_total": 0, "stocks_added": 0, "stocks_updated": 0,
            "stocks_removed": 0, "errors": errors,
        }

    _prog("Comparing with existing data…", 0.90)

    # Diff vs existing
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
        for sym in new_syms & old_syms:
            try:
                o = old_df.loc[old_df["symbol"] == sym, "weightage_pct"].iloc[0]
                n = new_df.loc[new_df["symbol"] == sym, "weightage_pct"].iloc[0]
                if pd.notna(o) and pd.notna(n) and abs(float(o) - float(n)) > 0.01:
                    updated += 1
            except Exception:
                pass

    _prog("Writing to database…", 0.95)

    keep = ["company_name", "symbol", "industry", "series", "isin",
            "sector", "index_name", "index_display",
            "market_cap_cr", "weightage_pct", "weight_source"]
    write_df = new_df[[c for c in keep if c in new_df.columns]]
    write_df.to_sql("sector_intelligence", con, if_exists="replace", index=False)
    con.execute("CREATE INDEX IF NOT EXISTS idx_si_sector ON sector_intelligence(sector)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_si_index  ON sector_intelligence(index_name)")

    factsheet_date_str = ", ".join(set(pdf_dates)) if pdf_dates else "N/A"
    changes = f"+{added} added, ~{updated} updated, -{removed} removed"
    con.execute(
        "INSERT INTO sector_sync_log "
        "(synced_at, source, indices_synced, stocks_total, changes, factsheet_date) "
        "VALUES (?,?,?,?,?,?)",
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "NSE India archives (CSV) + NiftyIndices factsheet (PDF) + Yahoo Finance (mkt cap)",
            len(indices_ok), len(write_df), changes, factsheet_date_str,
        ),
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
        "factsheet_date": factsheet_date_str,
        "errors":         errors,
    }


def get_last_sync(db_path: str | Path) -> dict | None:
    try:
        con = sqlite3.connect(str(db_path), timeout=5)
        _ensure_tables(con)
        row = con.execute(
            "SELECT synced_at, source, indices_synced, stocks_total, changes, factsheet_date "
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
                "factsheet_date": row[5] or "N/A",
            }
    except Exception:
        pass
    return None
