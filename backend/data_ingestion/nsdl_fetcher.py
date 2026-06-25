"""
NSDL Fortnightly Sector-wise FPI data — DB-backed fetcher.

Flow:
  1. Scrape https://www.fpi.nsdl.co.in/web/Reports/FPI_Fortnightly_Selection.aspx
     to discover ALL available report dates from the NSDL dropdown.
  2. For each date not yet in the DB, fetch the HTML report and parse it.
  3. Store every row in the `nsdl_fii_sector` table (one row per date+sector).
  4. All reads (pages, analysis) load from DB — no re-fetching old data.

Table structure (98 cols total): 2 fixed + 4 periods × 24 cols
Each period = 12 INR + 12 USD cols.
Equity INR column offsets (0-based):
  period-prev AUC = 2   net-prev = 26   net-curr = 50   AUC-curr = 74
"""
import logging
import re
from datetime import date, datetime
from typing import Optional
import pandas as pd
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL   = "https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/"
SELECT_URL = "https://www.fpi.nsdl.co.in/web/Reports/FPI_Fortnightly_Selection.aspx"

# New format (98 cols): 2 fixed + 4 periods × 24 cols (12 INR + 12 USD each)
COL_NEW_AUC_PREV = 2
COL_NEW_NET_PREV = 26
COL_NEW_NET_CURR = 50
COL_NEW_AUC_CURR = 74

# Old format (42 cols): 2 fixed + 4 periods × 10 cols (5 INR + 5 USD each)
# Periods: AUC-prev | net-prev-fortnight | net-curr-fortnight | AUC-curr
COL_OLD_AUC_PREV = 2
COL_OLD_NET_PREV = 12
COL_OLD_NET_CURR = 22
COL_OLD_AUC_CURR = 32

# NSDL sector name → internal sector name
NSDL_TO_INTERNAL = {
    "Automobile and Auto Components":      "Auto",
    "Capital Goods":                        "Capital Goods",
    "Chemicals":                            "Chemicals",
    "Construction":                         "Infrastructure",
    "Construction Materials":               "Infrastructure",
    "Consumer Durables":                    "Consumer Durables",
    "Consumer Services":                    "Services",
    "Fast Moving Consumer Goods":           "FMCG",
    "Financial Services":                   "Financial Services",
    "Forest Materials":                     "Others",
    "Healthcare":                           "Healthcare",
    "Information Technology":               "IT",
    "Media, Entertainment & Publication":   "Media",
    "Metals & Mining":                      "Metal",
    "Oil, Gas & Consumable Fuels":          "Oil & Gas",
    "Power":                                "Power",
    "Realty":                               "Real Estate",
    "Services":                             "Services",
    "Telecommunication":                    "Telecom",
    "Textiles":                             "Textile",
    "Utilities":                            "Energy",
    "Diversified":                          "Others",
    "Sovereign":                            "Others",
    "Others":                               "Others",
}

# Month name → number mapping for parsing NSDL date strings like "JUNE 15, 2026"
_MONTHS = {m: i+1 for i, m in enumerate([
    "JANUARY","FEBRUARY","MARCH","APRIL","MAY","JUNE",
    "JULY","AUGUST","SEPTEMBER","OCTOBER","NOVEMBER","DECEMBER"
])}


# ── HTTP helper ───────────────────────────────────────────────────────────────
def _get(url: str, timeout: int = 25) -> Optional[str]:
    """Fetch URL using curl_cffi to bypass NSDL's bot blocking."""
    try:
        from curl_cffi import requests as cf
        r = cf.get(url, timeout=timeout, impersonate="chrome110")
        if r.status_code == 200:
            return r.text
        logger.warning("HTTP %s for %s", r.status_code, url)
    except Exception as e:
        logger.warning("Fetch error %s: %s", url, e)
    return None


# ── Discover all report URLs from the NSDL selection page ────────────────────
def discover_reports() -> dict[date, str]:
    """
    Scrape the NSDL selection page for all option values.
    Each option value is the exact static HTML URL for that report.
    Returns dict{report_date: full_url}, sorted newest → oldest.

    The selection page renders the full dropdown server-side (ASP.NET WebForms),
    so a single curl_cffi GET returns all options.  Only the JavaScript-triggered
    UpdatePanel re-render (when the user changes the dropdown) requires JS;
    the initial page load gives us everything we need.
    """
    BASE = "https://www.fpi.nsdl.co.in/web"
    html = _get(SELECT_URL)
    if not html:
        logger.warning("Cannot reach NSDL selection page")
        return {}

    soup    = BeautifulSoup(html, "html.parser")
    select  = soup.find("select", id="ddlfortnighly")
    if not select:
        logger.warning("ddlfortnighly select not found on NSDL page")
        return {}

    result = {}
    for opt in select.find_all("option"):
        txt   = opt.get_text(strip=True).upper()        # e.g. "APR 30, 2026"
        value = (opt.get("value") or "").strip()        # e.g. "~/StaticReports/...html"
        if not value or not txt:
            continue
        # Parse date from text: "APR 30, 2026" or "APRIL 30, 2026"
        m = re.match(r"([A-Z]+)\s+(\d{1,2}),?\s+(\d{4})", txt)
        if not m:
            continue
        mon_str, day, yr = m.group(1), int(m.group(2)), int(m.group(3))
        mon_num = _MONTHS.get(mon_str) or _MONTHS.get(_MONTH_ABBR.get(mon_str, ""))
        if not mon_num:
            continue
        try:
            d = date(yr, mon_num, day)
        except ValueError:
            continue
        # Build absolute URL from the ~/ relative path
        url = BASE + value.lstrip("~")
        result[d] = url

    logger.info("NSDL selection page: found %d reports (%s … %s)",
                len(result), max(result) if result else "?", min(result) if result else "?")
    return result


# Month abbreviation → full key in _MONTHS
_MONTH_ABBR = {
    "JAN": "JANUARY",  "FEB": "FEBRUARY", "MAR": "MARCH",
    "APR": "APRIL",    "MAY": "MAY",       "JUN": "JUNE",
    "JUL": "JULY",     "AUG": "AUGUST",    "SEP": "SEPTEMBER",
    "OCT": "OCTOBER",  "NOV": "NOVEMBER",  "DEC": "DECEMBER",
}

# Keep backward-compat alias
def discover_available_dates() -> list[date]:
    return sorted(discover_reports().keys(), reverse=True)


# ── Build report URL from a date ──────────────────────────────────────────────
def _build_url(d: date) -> str:
    month = d.strftime("%B")           # "June"
    return f"{BASE_URL}FIIInvestSector_{month}{d.day}{d.year}.html"


# ── Parse NSDL HTML report → DataFrame ───────────────────────────────────────
def _clean(val: str) -> Optional[float]:
    if not val or val.strip() in ("-", "–", "N/A", ""):
        return None
    try:
        return float(val.replace(",", "").strip())
    except ValueError:
        return None


def _detect_format(rows: list) -> tuple[int, int, int, int, int]:
    """
    Returns (data_start_row, auc_prev_col, net_prev_col, net_curr_col, auc_curr_col).
    Detects whether this is the new 98-col format or old 42-col format.
    """
    for i, row in enumerate(rows):
        cells = row.find_all(["td","th"])
        n = len(cells)
        if n >= 90:    # new format: ~98 cols per data row
            return i, COL_NEW_AUC_PREV, COL_NEW_NET_PREV, COL_NEW_NET_CURR, COL_NEW_AUC_CURR
        if 38 <= n <= 45:  # old format: ~42 cols per data row
            return i, COL_OLD_AUC_PREV, COL_OLD_NET_PREV, COL_OLD_NET_CURR, COL_OLD_AUC_CURR
    return 4, COL_NEW_AUC_PREV, COL_NEW_NET_PREV, COL_NEW_NET_CURR, COL_NEW_AUC_CURR


def _parse_html(html: str) -> Optional[pd.DataFrame]:
    soup   = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return None
    rows = tables[0].find_all("tr")
    if len(rows) < 4:
        return None

    data_start, c_auc_prev, c_net_prev, c_net_curr, c_auc_curr = _detect_format(rows)

    records = []
    for row in rows[data_start:]:
        cells = [td.get_text(strip=True) for td in row.find_all(["td","th"])]
        min_cols = 35 if c_net_curr == COL_OLD_NET_CURR else 75
        if len(cells) < min_cols:
            continue
        sector_name = cells[1].strip()
        if not sector_name or sector_name.lower() in ("total","grand total","","sectors"):
            continue
        if any(kw in sector_name.lower() for kw in ("note","sr.","source")):
            continue
        # Skip pure-numeric first cell rows that are actually header continuation
        if cells[0].isdigit() is False and cells[1].lower() in ("sectors","sector","sl. no."):
            continue

        def g(idx):
            return _clean(cells[idx]) if idx < len(cells) else None

        auc_prev = g(c_auc_prev)
        net_prev = g(c_net_prev)
        net_curr = g(c_net_curr)
        auc_curr = g(c_auc_curr)

        auc_change     = (auc_curr - auc_prev) if auc_curr is not None and auc_prev is not None else None
        auc_pct_change = round(auc_change / auc_prev * 100, 2) if auc_change is not None and auc_prev else None
        net_flow_chg   = (net_curr - net_prev) if net_curr is not None and net_prev is not None else None

        def signal(n):
            if n is None:   return "neutral"
            if n > 1000:    return "buying"
            if n > 0:       return "light_buy"
            if n > -1000:   return "light_sell"
            return "selling"

        records.append({
            "nsdl_sector":    sector_name,
            "sector":         NSDL_TO_INTERNAL.get(sector_name, sector_name),
            "auc_prev_eq":    auc_prev,
            "net_prev_eq":    net_prev,
            "net_curr_eq":    net_curr,
            "auc_curr_eq":    auc_curr,
            "auc_change":     auc_change,
            "auc_pct_change": auc_pct_change,
            "net_flow_change":net_flow_chg,
            "signal":         signal(net_curr),
        })

    if not records:
        return None
    df = pd.DataFrame(records)
    return df.sort_values("net_curr_eq", ascending=False).reset_index(drop=True)


# ── Database read/write ───────────────────────────────────────────────────────
def _dates_in_db() -> set[date]:
    """Return set of report_dates already stored in DB."""
    try:
        from backend.storage.database import db_session
        from backend.storage.models import NsdlFiiSector
        with db_session() as s:
            rows = s.query(NsdlFiiSector.report_date).distinct().all()
            return {r[0] for r in rows}
    except Exception as e:
        logger.warning("DB read error: %s", e)
        return set()


def _save_to_db(report_date: date, df: pd.DataFrame) -> None:
    """Upsert all sector rows for a given report_date."""
    try:
        from backend.storage.database import db_session, get_engine
        from backend.storage.models import NsdlFiiSector, Base
        # Ensure table exists
        engine = get_engine()
        Base.metadata.create_all(engine)

        with db_session() as s:
            # Delete existing rows for this date (full replace)
            s.query(NsdlFiiSector).filter(NsdlFiiSector.report_date == report_date).delete()
            for _, row in df.iterrows():
                s.add(NsdlFiiSector(
                    report_date      = report_date,
                    nsdl_sector      = row["nsdl_sector"],
                    sector           = row["sector"],
                    auc_prev_eq      = row.get("auc_prev_eq"),
                    net_prev_eq      = row.get("net_prev_eq"),
                    net_curr_eq      = row.get("net_curr_eq"),
                    auc_curr_eq      = row.get("auc_curr_eq"),
                    auc_change       = row.get("auc_change"),
                    auc_pct_change   = row.get("auc_pct_change"),
                    net_flow_change  = row.get("net_flow_change"),
                    signal           = row.get("signal"),
                ))
        logger.info("Saved %d sectors for %s to DB", len(df), report_date)
    except Exception as e:
        logger.error("DB save error for %s: %s", report_date, e)


def _load_all_from_db() -> dict[date, pd.DataFrame]:
    """Load all stored reports from DB → dict{date: DataFrame}."""
    try:
        from backend.storage.database import db_session, get_engine
        from backend.storage.models import NsdlFiiSector, Base
        get_engine()   # ensure tables exist
        with db_session() as s:
            rows = s.query(NsdlFiiSector).order_by(
                NsdlFiiSector.report_date, NsdlFiiSector.nsdl_sector
            ).all()
        if not rows:
            return {}

        records = [{
            "report_date":    r.report_date,
            "nsdl_sector":    r.nsdl_sector,
            "sector":         r.sector,
            "auc_prev_eq":    r.auc_prev_eq,
            "net_prev_eq":    r.net_prev_eq,
            "net_curr_eq":    r.net_curr_eq,
            "auc_curr_eq":    r.auc_curr_eq,
            "auc_change":     r.auc_change,
            "auc_pct_change": r.auc_pct_change,
            "net_flow_change":r.net_flow_change,
            "signal":         r.signal,
        } for r in rows]

        df_all = pd.DataFrame(records)
        result = {}
        for d, grp in df_all.groupby("report_date"):
            result[d] = grp.drop(columns=["report_date"]).sort_values(
                "net_curr_eq", ascending=False
            ).reset_index(drop=True)
        return result
    except Exception as e:
        logger.error("DB load error: %s", e)
        return {}


# ── Main public API ───────────────────────────────────────────────────────────
def sync_nsdl_to_db(force_refresh_latest: bool = False) -> dict[date, pd.DataFrame]:
    """
    1. Scrape selection page for all report dates + their exact URLs.
    2. Fetch & store only dates missing from DB (+ re-fetch latest if forced).
    3. Return full dict{date: DataFrame} from DB.
    """
    reports   = discover_reports()           # {date: url}
    in_db     = _dates_in_db()
    to_fetch  = {d: url for d, url in reports.items() if d not in in_db}

    if force_refresh_latest and reports:
        latest = max(reports)
        to_fetch[latest] = reports[latest]   # always re-fetch latest

    if to_fetch:
        ordered = sorted(to_fetch.keys(), reverse=True)
        logger.info("Fetching %d NSDL reports: %s …", len(ordered),
                    [str(d) for d in ordered[:5]])
        for d in ordered:
            url  = to_fetch[d]
            html = _get(url)
            if not html:
                logger.warning("No HTML for %s (%s)", d, url)
                continue
            if "Request Rejected" in html or len(html) < 500:
                logger.warning("Blocked/empty response for %s", d)
                continue
            df = _parse_html(html)
            if df is not None and not df.empty:
                _save_to_db(d, df)
                logger.info("Stored %s (%d sectors)", d, len(df))
            else:
                logger.warning("Parsed empty for %s", d)
    else:
        logger.info("DB is up to date — %d reports stored", len(in_db))

    return _load_all_from_db()


def fetch_nsdl_fii_sectors(periods: int = 30) -> dict[date, pd.DataFrame]:
    """
    Public entry point used by all pages.
    Loads from DB; fetches missing dates automatically.
    `periods` is kept for API compatibility but all available data is returned.
    """
    return sync_nsdl_to_db(force_refresh_latest=False)


def get_latest_nsdl(periods: int = 2):
    """Returns (curr_df, prev_df, curr_date, prev_date) from DB."""
    data = fetch_nsdl_fii_sectors()
    if not data:
        return None, None, None, None
    sorted_dates = sorted(data.keys(), reverse=True)
    cd  = sorted_dates[0]
    pd_ = sorted_dates[1] if len(sorted_dates) > 1 else None
    return data[cd], data.get(pd_), cd, pd_
