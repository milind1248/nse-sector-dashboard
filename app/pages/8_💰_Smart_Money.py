"""Smart Money Tracker — FII/DII position detection via Delivery % + Futures OI."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sqlite3
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(
    page_title="Smart Money Tracker | FII/DII OI + Delivery | Market Sector Analysis",
    layout="wide",
)

from app.utils.seo import inject_seo
inject_seo("Smart_Money")

from app.utils.logo import show_logo
show_logo()

# ── DB helpers ────────────────────────────────────────────────────────────────
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nse_dashboard.db"

def _db():
    return sqlite3.connect(_DB_PATH)

def _init_tables():
    con = _db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS smart_money_history (
            symbol        TEXT NOT NULL,
            trade_date    TEXT NOT NULL,
            close_price   REAL,
            pct_price_chg REAL,
            trade_qty     REAL,
            tot_trade     REAL,
            action        REAL,
            dlv_pct       REAL,
            futures_oi    REAL,
            oi_change     REAL,
            pct_oi_chg    REAL,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS fno_symbols (
            symbol      TEXT PRIMARY KEY,
            updated_at  TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS shareholding_pattern (
            symbol           TEXT NOT NULL,
            quarter          TEXT NOT NULL,
            promoter         REAL,
            fii              REAL,
            dii              REAL,
            government       REAL,
            public_retail    REAL,
            fetched_at       TEXT NOT NULL,
            PRIMARY KEY (symbol, quarter)
        )
    """)
    con.commit()
    con.close()

_init_tables()


def _last_trading_date() -> date:
    """
    Return most recent date for which NSE bhav copy is available.
    Bhav copy publishes after ~6 PM IST, so during market hours (before 18:00 IST)
    today's data doesn't exist yet — return the previous trading day instead.
    """
    from datetime import datetime
    import pytz
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist)
    today = now_ist.date()
    wd = today.weekday()

    # Weekend — use Friday
    if wd == 5:
        return today - timedelta(days=1)
    if wd == 6:
        return today - timedelta(days=2)

    # Weekday but before 6 PM IST — today's bhav copy not yet published
    if now_ist.hour < 18:
        prev = today - timedelta(days=1)
        # Skip back over weekend
        if prev.weekday() == 5:   # Saturday
            prev -= timedelta(days=1)
        if prev.weekday() == 6:   # Sunday
            prev -= timedelta(days=2)
        return prev

    return today


def _trading_dates_for_90d() -> list[date]:
    """Return up to 130 calendar days back, excluding weekends, capped at 90 trading days."""
    end = _last_trading_date()
    result = []
    for i in range(200):
        d = end - timedelta(days=i)
        if d.weekday() < 5:
            result.append(d)
        if len(result) == 90:
            break
    return result


def _stored_dates(symbol: str) -> set[str]:
    con = _db()
    rows = con.execute(
        "SELECT trade_date FROM smart_money_history WHERE symbol=?", (symbol,)
    ).fetchall()
    con.close()
    return {r[0] for r in rows}


def _purge_old(symbol: str):
    """Keep only last 90 trading days; delete older rows."""
    cutoff = _trading_dates_for_90d()[-1].isoformat()
    con = _db()
    con.execute(
        "DELETE FROM smart_money_history WHERE symbol=? AND trade_date < ?",
        (symbol, cutoff),
    )
    con.commit()
    con.close()


def _save_rows(rows: list[dict]):
    if not rows:
        return
    con = _db()
    con.executemany("""
        INSERT OR REPLACE INTO smart_money_history
        (symbol,trade_date,close_price,pct_price_chg,trade_qty,tot_trade,
         action,dlv_pct,futures_oi,oi_change,pct_oi_chg)
        VALUES (:symbol,:trade_date,:close_price,:pct_price_chg,:trade_qty,:tot_trade,
                :action,:dlv_pct,:futures_oi,:oi_change,:pct_oi_chg)
    """, rows)
    con.commit()
    con.close()


def _load_from_db(symbol: str) -> pd.DataFrame:
    con = _db()
    df = pd.read_sql_query(
        "SELECT * FROM smart_money_history WHERE symbol=? ORDER BY trade_date DESC",
        con, params=(symbol,),
    )
    con.close()
    return df


# ── NSE archive fetchers (called per day, used in parallel) ───────────────────
_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _fetch_one_day(symbol: str, dt: date) -> dict | None:
    """Download CM + MTO + FO for a single date and extract symbol's metrics."""
    import requests, zipfile, io as _io

    row = {"symbol": symbol, "trade_date": dt.isoformat(),
           "close_price": None, "pct_price_chg": None,
           "trade_qty": None, "tot_trade": None, "action": None,
           "dlv_pct": None, "futures_oi": None, "oi_change": None, "pct_oi_chg": None}

    ds = dt.strftime("%Y%m%d")
    got_any = False

    # ── CM Bhav Copy ──────────────────────────────────────────────────────────
    try:
        url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ds}_F_0000.csv.zip"
        r = requests.get(url, headers=_HDR, timeout=20)
        if r.status_code == 200:
            z = zipfile.ZipFile(_io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            s = df[(df["TckrSymb"] == symbol) & (df["SctySrs"].isin({"EQ","BE","BZ","SM","ST"}))]
            if not s.empty:
                close = pd.to_numeric(s["ClsPric"].iloc[0], errors="coerce")
                prev  = pd.to_numeric(s["PrvsClsgPric"].iloc[0], errors="coerce")
                tqty  = pd.to_numeric(s["TtlTradgVol"].iloc[0], errors="coerce")
                ttrd  = pd.to_numeric(s["TtlNbOfTxsExctd"].iloc[0], errors="coerce")
                row["close_price"]   = float(close) if pd.notna(close) else None
                row["trade_qty"]     = float(tqty)  if pd.notna(tqty)  else None
                row["tot_trade"]     = float(ttrd)  if pd.notna(ttrd)  else None
                if pd.notna(close) and pd.notna(prev) and prev > 0:
                    row["pct_price_chg"] = round((close - prev) / prev * 100, 2)
                if pd.notna(tqty) and pd.notna(ttrd) and ttrd > 0:
                    row["action"] = round(tqty / ttrd, 1)
                got_any = True
    except Exception:
        pass

    # ── MTO Delivery ──────────────────────────────────────────────────────────
    try:
        url = f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{dt.strftime('%d%m%Y')}.DAT"
        r = requests.get(url, headers=_HDR, timeout=15)
        if r.status_code == 200:
            lines = [l for l in r.text.splitlines() if l.startswith("20,")]
            mdf = pd.read_csv(_io.StringIO("\n".join(lines)), header=None,
                              names=["rec","sr","sym","series","qty_traded","dlv_qty","dlv_pct"])
            m = mdf[(mdf["sym"] == symbol) & (mdf["series"] == "EQ")]
            if not m.empty:
                row["dlv_pct"] = float(pd.to_numeric(m["dlv_pct"].iloc[0], errors="coerce"))
                got_any = True
    except Exception:
        pass

    # ── FO Bhav Copy (nearest expiry) ─────────────────────────────────────────
    try:
        url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ds}_F_0000.csv.zip"
        r = requests.get(url, headers=_HDR, timeout=20)
        if r.status_code == 200:
            z = zipfile.ZipFile(_io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            stf = df[(df["FinInstrmTp"] == "STF") & (df["TckrSymb"] == symbol)].copy()
            if not stf.empty:
                stf["XpryDt"] = pd.to_datetime(stf["XpryDt"], errors="coerce")
                nearest = stf.loc[stf["XpryDt"].idxmin()]
                oi     = pd.to_numeric(nearest["OpnIntrst"],     errors="coerce")
                oichg  = pd.to_numeric(nearest["ChngInOpnIntrst"], errors="coerce")
                if pd.notna(oi):
                    row["futures_oi"] = float(oi)
                    row["oi_change"]  = float(oichg) if pd.notna(oichg) else None
                    prev_oi = oi - (oichg if pd.notna(oichg) else 0)
                    if prev_oi != 0:
                        row["pct_oi_chg"] = round((oichg / prev_oi) * 100, 2)
                got_any = True
    except Exception:
        pass

    return row if got_any else None


def _fetch_missing_days(symbol: str, missing_dates: list[date],
                        progress_cb=None) -> list[dict]:
    """Parallel fetch of all missing dates (max 15 threads)."""
    results = []
    total = len(missing_dates)
    done  = 0
    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = {ex.submit(_fetch_one_day, symbol, d): d for d in missing_dates}
        for f in as_completed(futures):
            done += 1
            try:
                row = f.result()
                if row:
                    results.append(row)
            except Exception:
                pass
            if progress_cb:
                progress_cb(done, total)
    return results


# ── FNO symbol list — DB-backed, only refreshed on explicit Refresh click ────
def _fno_list_from_db() -> list[str]:
    con = _db()
    rows = con.execute("SELECT symbol FROM fno_symbols ORDER BY symbol").fetchall()
    con.close()
    return [r[0] for r in rows]


def _refresh_fno_list_from_nse() -> list[str]:
    """Download FO Bhav Copy, extract STF symbols, save to DB. Called only on Refresh."""
    import requests, zipfile, io as _io
    from datetime import datetime
    for offset in range(7):
        dt = _last_trading_date() - timedelta(days=offset)
        if dt.weekday() >= 5:
            continue
        url = (f"https://nsearchives.nseindia.com/content/fo/"
               f"BhavCopy_NSE_FO_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip")
        try:
            r = requests.get(url, headers=_HDR, timeout=15)
            if r.status_code != 200:
                continue
            z = zipfile.ZipFile(_io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            syms = sorted(df[df["FinInstrmTp"] == "STF"]["TckrSymb"].unique().tolist())
            if not syms:
                continue
            now = datetime.utcnow().isoformat()
            con = _db()
            con.execute("DELETE FROM fno_symbols")
            con.executemany(
                "INSERT INTO fno_symbols (symbol, updated_at) VALUES (?, ?)",
                [(s, now) for s in syms],
            )
            con.commit()
            con.close()
            return syms
        except Exception:
            continue
    return []


def _get_fno_list() -> list[str]:
    """Return FNO symbols from DB; fetch from NSE only if DB is empty."""
    syms = _fno_list_from_db()
    if not syms:
        syms = _refresh_fno_list_from_nse()
    return syms


# ── Shareholding Pattern (screener.in) ───────────────────────────────────────

def _fetch_shareholding_screener(symbol: str) -> list[dict]:
    """
    Fetch 6 quarters of shareholding pattern from screener.in.
    Categories: Promoters, FIIs, DIIs, Government, Public (sum ≈ 100%).
    Returns list of row dicts ordered newest-first.
    """
    import requests
    from bs4 import BeautifulSoup
    from datetime import datetime

    # Try consolidated first, then standalone
    for suffix in ["/consolidated/", "/"]:
        url = f"https://www.screener.in/company/{symbol}{suffix}"
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            sh_section = soup.find("section", {"id": "shareholding"})
            if not sh_section:
                continue
            table = sh_section.find("table")
            if not table:
                continue

            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # First row = header with quarter labels
            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
            quarters = headers[1:]   # skip the first label column

            # Parse each category row
            data: dict[str, list] = {}
            cat_map = {
                "Promoters": "promoter",
                "FIIs":      "fii",
                "DIIs":      "dii",
                "Government":"government",
                "Public":    "public_retail",
            }
            for row in rows[1:]:
                cells = row.find_all(["th", "td"])
                if not cells:
                    continue
                label = cells[0].get_text(strip=True).replace("+", "").strip()
                key = cat_map.get(label)
                if not key:
                    continue
                vals = []
                for c in cells[1:]:
                    txt = c.get_text(strip=True).replace("%", "").replace(",", "").strip()
                    try:
                        vals.append(float(txt))
                    except ValueError:
                        vals.append(None)
                data[key] = vals

            if not data:
                continue

            # Build row dicts — last 6 quarters only, newest first
            num_q = len(quarters)
            start  = max(0, num_q - 12)
            now_ts = datetime.utcnow().isoformat()
            result = []
            for i in range(num_q - 1, start - 1, -1):
                if i >= len(quarters):
                    continue
                q = quarters[i]
                result.append({
                    "symbol":        symbol,
                    "quarter":       q,
                    "promoter":      data.get("promoter",      [None] * num_q)[i],
                    "fii":           data.get("fii",           [None] * num_q)[i],
                    "dii":           data.get("dii",           [None] * num_q)[i],
                    "government":    data.get("government",    [None] * num_q)[i],
                    "public_retail": data.get("public_retail", [None] * num_q)[i],
                    "fetched_at":    now_ts,
                })
            return result
        except Exception:
            continue
    return []


def _save_shareholding(rows: list[dict]):
    if not rows:
        return
    con = _db()
    con.executemany("""
        INSERT OR REPLACE INTO shareholding_pattern
        (symbol, quarter, promoter, fii, dii, government, public_retail, fetched_at)
        VALUES (:symbol, :quarter, :promoter, :fii, :dii, :government, :public_retail, :fetched_at)
    """, rows)
    con.commit()
    con.close()


def _load_shareholding(symbol: str) -> pd.DataFrame:
    con = _db()
    df = pd.read_sql_query(
        """SELECT quarter, promoter, fii, dii, government, public_retail, fetched_at
           FROM shareholding_pattern WHERE symbol=?""",
        con, params=(symbol,),
    )
    con.close()
    if df.empty:
        return df
    # Parse "Jun 2025" → sortable date, then sort newest first
    df["_sort"] = pd.to_datetime(df["quarter"], format="%b %Y", errors="coerce")
    df = df.sort_values("_sort", ascending=False).drop(columns=["_sort"]).reset_index(drop=True)
    return df


def _get_shareholding(symbol: str) -> pd.DataFrame:
    """Load from DB; fetch from screener.in if missing or older than 7 days."""
    from datetime import datetime, timedelta
    df = _load_shareholding(symbol)
    needs_refresh = df.empty
    if not needs_refresh and not df.empty:
        try:
            fetched = datetime.fromisoformat(df["fetched_at"].iloc[0])
            needs_refresh = (datetime.utcnow() - fetched) > timedelta(days=7)
        except Exception:
            needs_refresh = True
    if needs_refresh:
        rows = _fetch_shareholding_screener(symbol)
        _save_shareholding(rows)
        df = _load_shareholding(symbol)
    return df.drop(columns=["fetched_at"], errors="ignore")


# ── Bulk date-centric fetch (downloads each bhav copy once for ALL symbols) ───

def _null_row(symbol: str, dt: date) -> dict:
    return {"symbol": symbol, "trade_date": dt.isoformat(),
            "close_price": None, "pct_price_chg": None,
            "trade_qty": None, "tot_trade": None, "action": None,
            "dlv_pct": None, "futures_oi": None, "oi_change": None, "pct_oi_chg": None}


def _fetch_date_all_symbols(dt: date, symbols_set: set[str]) -> list[dict]:
    """
    Download CM + MTO + FO bhav copies for `dt` exactly ONCE,
    extract metrics for every symbol in symbols_set.
    Returns a list of row dicts (one per symbol that had data).
    Empty list if the date is not available on NSE archives.
    """
    import requests, zipfile, io as _io

    ds  = dt.strftime("%Y%m%d")
    dmd = dt.strftime("%d%m%Y")

    # ── 1. CM Bhav Copy ───────────────────────────────────────────────────────
    cm_data: dict[str, dict] = {}
    try:
        r = requests.get(
            f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ds}_F_0000.csv.zip",
            headers=_HDR, timeout=20,
        )
        if r.status_code == 200:
            z = zipfile.ZipFile(_io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            eq = df[
                df["SctySrs"].isin({"EQ", "BE", "BZ", "SM", "ST"}) &
                df["TckrSymb"].isin(symbols_set)
            ].copy()
            for c in ["ClsPric", "PrvsClsgPric", "TtlTradgVol", "TtlNbOfTxsExctd"]:
                eq[c] = pd.to_numeric(eq[c], errors="coerce")
            for _, row in eq.iterrows():
                sym   = row["TckrSymb"]
                close = row["ClsPric"]
                prev  = row["PrvsClsgPric"]
                tqty  = row["TtlTradgVol"]
                ttrd  = row["TtlNbOfTxsExctd"]
                cm_data[sym] = {
                    "close_price":   float(close) if pd.notna(close) else None,
                    "trade_qty":     float(tqty)  if pd.notna(tqty)  else None,
                    "tot_trade":     float(ttrd)  if pd.notna(ttrd)  else None,
                    "pct_price_chg": round((close - prev) / prev * 100, 2)
                                   if pd.notna(close) and pd.notna(prev) and prev > 0 else None,
                    "action":        round(tqty / ttrd, 1)
                                   if pd.notna(tqty) and pd.notna(ttrd) and ttrd > 0 else None,
                }
    except Exception:
        pass

    if not cm_data:
        return []   # date not available — caller saves null skeletons

    # ── 2. MTO Delivery ───────────────────────────────────────────────────────
    dlv_data: dict[str, float] = {}
    try:
        r = requests.get(
            f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{dmd}.DAT",
            headers=_HDR, timeout=15,
        )
        if r.status_code == 200:
            lines = [l for l in r.text.splitlines() if l.startswith("20,")]
            mdf = pd.read_csv(
                _io.StringIO("\n".join(lines)), header=None,
                names=["rec", "sr", "sym", "series", "qty_traded", "dlv_qty", "dlv_pct"],
            )
            mdf = mdf[mdf["series"] == "EQ"]
            mdf["dlv_pct"] = pd.to_numeric(mdf["dlv_pct"], errors="coerce")
            for _, row in mdf[mdf["sym"].isin(symbols_set)].iterrows():
                if pd.notna(row["dlv_pct"]):
                    dlv_data[row["sym"]] = float(row["dlv_pct"])
    except Exception:
        pass

    # ── 3. FO Bhav Copy (nearest expiry per symbol) ───────────────────────────
    fo_data: dict[str, dict] = {}
    try:
        r = requests.get(
            f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ds}_F_0000.csv.zip",
            headers=_HDR, timeout=20,
        )
        if r.status_code == 200:
            z = zipfile.ZipFile(_io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            stf = df[
                (df["FinInstrmTp"] == "STF") & df["TckrSymb"].isin(symbols_set)
            ].copy()
            stf["XpryDt"] = pd.to_datetime(stf["XpryDt"], errors="coerce")
            for c in ["OpnIntrst", "ChngInOpnIntrst"]:
                stf[c] = pd.to_numeric(stf[c], errors="coerce")
            # Nearest expiry per symbol
            idx = stf.groupby("TckrSymb")["XpryDt"].idxmin()
            nearest = stf.loc[idx]
            for _, row in nearest.iterrows():
                oi    = row["OpnIntrst"]
                oichg = row["ChngInOpnIntrst"]
                if pd.notna(oi):
                    prev_oi = oi - (oichg if pd.notna(oichg) else 0)
                    fo_data[row["TckrSymb"]] = {
                        "futures_oi": float(oi),
                        "oi_change":  float(oichg) if pd.notna(oichg) else None,
                        "pct_oi_chg": round((oichg / prev_oi) * 100, 2)
                                     if pd.notna(oichg) and prev_oi != 0 else None,
                    }
    except Exception:
        pass

    # ── 4. Merge and build rows ───────────────────────────────────────────────
    rows = []
    for sym in cm_data:
        row = {"symbol": sym, "trade_date": dt.isoformat()}
        row.update(cm_data[sym])
        row["dlv_pct"] = dlv_data.get(sym)
        row.update(fo_data.get(sym, {"futures_oi": None, "oi_change": None, "pct_oi_chg": None}))
        rows.append(row)
    return rows


def _bulk_refresh_history(symbols: list[str], progress_cb=None):
    """
    For each of the 90 trading dates, download bhav copies ONCE and save data
    for all symbols that are missing that date. 90 dates × 3 files = 270 HTTP requests total.
    """
    all_90d      = _trading_dates_for_90d()
    symbols_set  = set(symbols)
    total        = len(all_90d)

    for i, dt in enumerate(all_90d):
        # Which symbols already have this date in DB?
        con = _db()
        stored_for_date = {r[0] for r in con.execute(
            "SELECT symbol FROM smart_money_history WHERE trade_date=?",
            (dt.isoformat(),),
        ).fetchall()}
        con.close()

        missing_syms = symbols_set - stored_for_date
        if missing_syms:
            fetched_rows = _fetch_date_all_symbols(dt, missing_syms)
            _save_rows(fetched_rows)

            # Null skeletons for symbols where bhav copy had no data (old dates / non-FNO)
            fetched_syms = {r["symbol"] for r in fetched_rows}
            null_rows = [_null_row(s, dt) for s in missing_syms if s not in fetched_syms]
            _save_rows(null_rows)

        if progress_cb:
            progress_cb(i + 1, total)

    # Global purge — remove any rows older than the 90-day window
    cutoff = all_90d[-1].isoformat()
    con = _db()
    con.execute("DELETE FROM smart_money_history WHERE trade_date < ?", (cutoff,))
    con.commit()
    con.close()


# ── Page header ───────────────────────────────────────────────────────────────
col_h, col_ref = st.columns([6, 1])
col_h.title("💰 Smart Money Tracker")
col_h.caption("Institutional activity detection via NSE Cash Delivery %, Action ratio & Futures OI — For educational purposes only. Not SEBI-registered investment advice.")
if col_ref.button("🔄 Refresh", use_container_width=True):
    with st.status("🔄 Refreshing Smart Money data…", expanded=True) as _ref_sts:
        st.write("**Step 1 / 2** — Updating FNO symbol list from NSE archives…")
        new_syms = _refresh_fno_list_from_nse()
        if new_syms:
            st.write(f"✅ {len(new_syms)} FNO symbols loaded.")
        else:
            st.write("⚠️ Could not fetch symbol list — NSE may be unavailable.")
            new_syms = _fno_list_from_db()   # fall back to existing DB list

        st.write(f"**Step 2 / 3** — Fetching 90-day history for all {len(new_syms)} FNO stocks…")
        st.caption("Downloads each date's bhav copy once for all symbols (270 requests, ~60–90 sec).")
        _ref_prog = st.progress(0)
        _ref_txt  = st.empty()

        def _ref_cb(done, total):
            _ref_prog.progress(int(done / total * 100))
            _ref_txt.text(f"Processing date {done} / {total}…")

        _bulk_refresh_history(new_syms, progress_cb=_ref_cb)
        _ref_prog.empty()
        _ref_txt.empty()

        # Step 3 — Shareholding pattern for all FNO symbols
        st.write(f"**Step 3 / 3** — Fetching shareholding pattern for all {len(new_syms)} FNO stocks…")
        st.caption("Parallel fetch from screener.in · skips symbols refreshed within last 7 days.")

        from datetime import datetime as _dt
        _sh_prog = st.progress(0)
        _sh_txt  = st.empty()

        # Find which symbols need a refresh (missing or older than 7 days)
        con = _db()
        existing = {
            r[0]: r[1] for r in con.execute(
                "SELECT symbol, MAX(fetched_at) FROM shareholding_pattern GROUP BY symbol"
            ).fetchall()
        }
        con.close()

        cutoff_ts = (_dt.utcnow() - __import__("datetime").timedelta(days=7)).isoformat()
        syms_to_fetch = [
            s for s in new_syms
            if s not in existing or (existing[s] or "") < cutoff_ts
        ]
        _sh_txt.text(f"0 / {len(syms_to_fetch)} symbols to fetch ({len(new_syms) - len(syms_to_fetch)} already up-to-date)…")

        _sh_done = {"n": 0}
        def _fetch_and_save_sh(sym):
            rows = _fetch_shareholding_screener(sym)
            _save_shareholding(rows)
            _sh_done["n"] += 1

        with ThreadPoolExecutor(max_workers=8) as _sh_ex:
            _sh_futures = {_sh_ex.submit(_fetch_and_save_sh, s): s for s in syms_to_fetch}
            for _f in as_completed(_sh_futures):
                pct = int(_sh_done["n"] / max(len(syms_to_fetch), 1) * 100)
                _sh_prog.progress(pct)
                _sh_txt.text(f"{_sh_done['n']} / {len(syms_to_fetch)} shareholding patterns fetched…")

        _sh_prog.empty()
        _sh_txt.empty()
        _ref_sts.update(label="✅ Refresh complete — all FNO stocks updated!", state="complete")
    st.rerun()

# ── Disclaimer (SEBI) ────────────────────────────────────────────────────────
st.markdown(
    "<div style='font-size:11px;color:#888;background:#1a1a2e;border-left:3px solid #555;"
    "padding:6px 10px;border-radius:4px;line-height:1.5;margin-bottom:4px'>"
    "⚖️ <b>Regulatory Disclaimer:</b> This tool is for educational and informational purposes only. "
    "It does not constitute investment advice, a recommendation to buy/sell securities, or a research report "
    "under SEBI (Research Analyst) Regulations, 2014. Signals are derived from publicly available NSE data "
    "using mathematical formulas. Past patterns do not guarantee future performance. Consult a SEBI-registered "
    "investment advisor before making investment decisions. The publisher is <b>not registered</b> with SEBI "
    "as a Research Analyst or Investment Advisor."
    "</div>",
    unsafe_allow_html=True,
)

# ── Legend ────────────────────────────────────────────────────────────────────
with st.expander("📖 How to read Smart Money signals", expanded=False):
    st.markdown("""
**Smart Money = "Buying"** when — for that specific date — both conditions are true:
- **Delivery %** > 90-day average delivery % for the stock
- **Action** (TradeQty ÷ TotTrade) > 90-day average Action for the stock

High delivery = institutions taking physical delivery (not intraday). High Action = larger average trade size = possible block/institutional orders.

| OI Signal | Price | OI | Trend Interpretation |
|-----------|-------|----|----------------------|
| **Long Buildup** | ↑ | ↑ | 🟢 Bullish — fresh longs being added |
| **Short Covering** | ↑ | ↓ | 🟢 Bullish — shorts being squared off |
| **Long Unwinding** | ↓ | ↓ | 🔴 Bearish — longs exiting |
| **Short Buildup** | ↓ | ↑ | 🔴 Bearish — fresh shorts being added |

> **Note:** OI signals are derived from NSE F&O bhav copy data. Signals are indicative only and must be validated with fundamental analysis. Do not trade solely based on this data.
""")

# ── Load FNO symbol list (DB-first, no HTTP unless DB is empty) ───────────────
fno_symbols = _get_fno_list()

if not fno_symbols:
    st.error("Could not load FNO stock list. NSE archives publish data after ~6 PM IST.")
    st.stop()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_stock, tab_screener = st.tabs(["🔍 Stock Analysis (90-Day)", "📊 Smart Money Screener"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — 90-Day Stock Deep Dive with DB cache
# ══════════════════════════════════════════════════════════════════════════════
with tab_stock:
    symbol = st.selectbox("Search stock symbol (type to filter)", fno_symbols, index=0)

    if symbol:
        all_90d = _trading_dates_for_90d()           # list of 90 trading dates
        stored  = _stored_dates(symbol)               # dates already in DB
        missing = [d for d in all_90d if d.isoformat() not in stored]

        if missing:
            prog_bar  = st.progress(0)
            prog_text = st.empty()
            prog_text.text(f"Fetching {len(missing)} new trading day(s) for {symbol}…")

            _prog = {"done": 0}
            def _cb(done, total):
                pct = int(done / total * 100)
                prog_bar.progress(pct)
                prog_text.text(f"Fetching {symbol} history: {done} / {total} days…")

            new_rows = _fetch_missing_days(symbol, missing, progress_cb=_cb)

            # Save fetched rows
            _save_rows(new_rows)

            # Mark dates that returned no data as attempted (null skeleton)
            # so they are never retried on future page loads
            fetched_dates = {r["trade_date"] for r in new_rows}
            null_rows = [
                {"symbol": symbol, "trade_date": d.isoformat(),
                 "close_price": None, "pct_price_chg": None,
                 "trade_qty": None, "tot_trade": None, "action": None,
                 "dlv_pct": None, "futures_oi": None, "oi_change": None,
                 "pct_oi_chg": None}
                for d in missing if d.isoformat() not in fetched_dates
            ]
            if null_rows:
                _save_rows(null_rows)

            _purge_old(symbol)
            prog_bar.empty()
            prog_text.empty()

        hist = _load_from_db(symbol)

        # Drop null skeleton rows (dates attempted but not available on NSE archives)
        hist = hist.dropna(subset=["close_price"])

        if hist.empty:
            st.warning("No data available for this symbol. It may not be in F&O segment or NSE archives.")
        else:
            hist["trade_date"] = pd.to_datetime(hist["trade_date"]).dt.date
            hist = hist.sort_values("trade_date", ascending=False).reset_index(drop=True)

            # ── Compute 90-day averages ────────────────────────────────────────
            avg_dlv = hist["dlv_pct"].mean()
            avg_act = hist["action"].mean()

            # ── Smart Money column ─────────────────────────────────────────────
            def _sm_label(row):
                d, a = row["dlv_pct"], row["action"]
                if pd.notna(d) and pd.notna(a) and pd.notna(avg_dlv) and pd.notna(avg_act):
                    if d > avg_dlv and a > avg_act:
                        return "Buying"
                return "–"

            hist["smart_money"] = hist.apply(_sm_label, axis=1)

            # ── OI signal ─────────────────────────────────────────────────────
            def _oi_sig(row):
                p, o = row["pct_price_chg"], row["pct_oi_chg"]
                if pd.isna(p) or pd.isna(o): return "Neutral"
                if p > 0 and o > 0: return "Long Buildup"
                if p > 0 and o < 0: return "Short Covering"
                if p < 0 and o < 0: return "Long Unwinding"
                if p < 0 and o > 0: return "Short Buildup"
                return "Neutral"

            hist["oi_signal"] = hist.apply(_oi_sig, axis=1)

            # ── 90-day average banner ─────────────────────────────────────────
            buying_days = (hist["smart_money"] == "Buying").sum()
            latest = hist.iloc[0]

            st.markdown(
                f"<div style='background:#1a1f2e;border-radius:8px;padding:14px 20px;"
                f"display:flex;gap:32px;flex-wrap:wrap;margin-bottom:12px'>"
                f"<div><div style='color:#aaa;font-size:11px'>90-Day Avg Delivery %</div>"
                f"<div style='color:#FFD600;font-size:22px;font-weight:700'>"
                f"{avg_dlv:.1f}%</div></div>"
                f"<div><div style='color:#aaa;font-size:11px'>90-Day Avg Action</div>"
                f"<div style='color:#FFD600;font-size:22px;font-weight:700'>"
                f"{avg_act:.1f}</div></div>"
                f"<div><div style='color:#aaa;font-size:11px'>Smart Money Buying Days</div>"
                f"<div style='color:#00C853;font-size:22px;font-weight:700'>"
                f"{buying_days} / {len(hist)}</div></div>"
                f"<div><div style='color:#aaa;font-size:11px'>Latest Close</div>"
                f"<div style='color:#fff;font-size:22px;font-weight:700'>"
                f"₹{latest['close_price']:,.2f}</div></div>"
                f"<div><div style='color:#aaa;font-size:11px'>Latest OI Signal</div>"
                f"<div style='font-size:18px;font-weight:700;color:"
                f"{'#00C853' if latest['oi_signal'] in ('Long Buildup','Short Covering') else '#FF5252' if latest['oi_signal'] != 'Neutral' else '#888'}'>"
                f"{latest['oi_signal']}</div></div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            # ── Charts ────────────────────────────────────────────────────────
            col_ch1, col_ch2 = st.columns(2)
            with col_ch1:
                ch = hist.sort_values("trade_date")
                sm_dates = hist[hist["smart_money"] == "Buying"]["trade_date"].tolist()
                buy_df = ch[ch["smart_money"] == "Buying"]
                fig = go.Figure()
                # Price line
                fig.add_trace(go.Scatter(
                    x=ch["trade_date"].astype(str), y=ch["close_price"],
                    name="Close", mode="lines", line=dict(color="#2979FF", width=2),
                ))
                # Green circles at Buying signal days
                fig.add_trace(go.Scatter(
                    x=buy_df["trade_date"].astype(str), y=buy_df["close_price"],
                    mode="markers", name="Smart Money Buying",
                    marker=dict(color="#00C853", size=10, symbol="circle",
                                line=dict(color="#fff", width=1.5)),
                    hovertemplate="<b>%{x}</b><br>Close: ₹%{y:,.2f}<br>Smart Money: Buying<extra></extra>",
                ))
                # Subtle vertical lines
                for sd in sm_dates:
                    fig.add_vline(x=str(sd), line_width=1,
                                  line_color="#00C853", opacity=0.2)
                fig.update_layout(
                    template="plotly_dark", height=280,
                    title=f"{symbol} — Close Price (🟢 = Smart Money Buying)",
                    margin=dict(t=40, b=20),
                )
                st.plotly_chart(fig, use_container_width=True)

            with col_ch2:
                ch2 = hist.sort_values("trade_date")
                dlv_clean = ch2["dlv_pct"].ffill()
                fig2 = go.Figure()
                fig2.add_trace(go.Bar(
                    x=ch2["trade_date"].astype(str), y=ch2["dlv_pct"],
                    marker_color=["#00C853" if v and v > avg_dlv else "#555"
                                  for v in ch2["dlv_pct"]],
                    name="Delivery %",
                ))
                if pd.notna(avg_dlv):
                    fig2.add_hline(y=avg_dlv, line_dash="dash",
                                   line_color="#FFD600",
                                   annotation_text=f"Avg {avg_dlv:.1f}%")
                fig2.update_layout(
                    template="plotly_dark", height=280,
                    title=f"{symbol} — Delivery % (yellow = 90d avg)",
                    margin=dict(t=40, b=20),
                )
                st.plotly_chart(fig2, use_container_width=True)

            # ── 90-day table ─────────────────────────────────────────────────
            st.subheader(f"📅 {len(hist)} Trading Days — {symbol}")

            display = pd.DataFrame({
                "Date":          hist["trade_date"].astype(str),
                "Close (₹)":     hist["close_price"],
                "% Price CHG":   hist["pct_price_chg"],
                "Delivery %":    hist["dlv_pct"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "–"),
                "Action":        hist["action"],
                "Futures OI":    hist["futures_oi"].apply(lambda x: int(x) if pd.notna(x) else None),
                "OI Change":     hist["oi_change"].apply(lambda x: int(x) if pd.notna(x) else None),
                "% OI Change":   hist["pct_oi_chg"],
                "OI Signal":     hist["oi_signal"],
                "Smart Money":   hist["smart_money"],
            })

            OI_COLORS = {
                "Long Buildup":   "color:#00C853;font-weight:600",
                "Short Covering": "color:#64DD17;font-weight:600",
                "Long Unwinding": "color:#FF5252;font-weight:600",
                "Short Buildup":  "color:#D50000;font-weight:600",
                "Neutral":        "color:#666",
            }

            def _cn(v):
                if not isinstance(v, (int, float)): return ""
                return "color:#00C853" if v > 0 else "color:#D50000" if v < 0 else ""

            def _csm(v):
                return "color:#00C853;font-weight:700" if v == "Buying" else "color:#555"

            def _coi(v):
                return OI_COLORS.get(v, "")

            st.dataframe(
                display.style
                    .map(_cn,  subset=["% Price CHG", "OI Change", "% OI Change"])
                    .map(_coi, subset=["OI Signal"])
                    .map(_csm, subset=["Smart Money"])
                    .format({
                        "Close (₹)":   "₹{:,.2f}",
                        "% Price CHG": "{:+.2f}%",
                        "% OI Change": "{:+.2f}%",
                        "OI Change":   "{:+,}",
                        "Futures OI":  "{:,}",
                        "Action":      "{:.1f}",
                    }, na_rep="–"),
                use_container_width=True, hide_index=True, height=550,
            )

            # ── Shareholding Pattern (6 quarters) ────────────────────────────
            st.markdown("---")
            st.subheader(f"🏦 Shareholding Pattern — {symbol} (Last 12 Quarters)")
            st.caption("Source: screener.in · Refreshed weekly · DII = Mutual Funds + Other Domestic Institutions")

            sh_df = _get_shareholding(symbol)

            if sh_df.empty:
                st.info("Shareholding data not available for this symbol on screener.in.")
            else:
                # Both chart and table: newest first (Mar 2026 → Jun 2023)
                sh_chart = sh_df.head(12).reset_index(drop=True)   # newest first
                sh_table = sh_df.head(12).reset_index(drop=True)   # newest first
                quarters  = sh_chart["quarter"].tolist()

                # ── Stacked bar chart ─────────────────────────────────────────
                CAT_COLORS = {
                    "Promoter":   "#2979FF",
                    "FII":        "#00C853",
                    "DII":        "#FFD600",
                    "Government": "#FF6D00",
                    "Public":     "#AA00FF",
                }
                fig_sh = go.Figure()
                cat_cols = [
                    ("Promoter",   "promoter"),
                    ("FII",        "fii"),
                    ("DII",        "dii"),
                    ("Government", "government"),
                    ("Public",     "public_retail"),
                ]
                for label, col in cat_cols:
                    vals = sh_chart[col].tolist()
                    fig_sh.add_trace(go.Bar(
                        name=label,
                        x=quarters,
                        y=vals,
                        marker_color=CAT_COLORS[label],
                        text=[f"{v:.1f}%" if v is not None else "" for v in vals],
                        textposition="inside",
                    ))
                fig_sh.update_layout(
                    barmode="stack",
                    template="plotly_dark",
                    height=340,
                    title=f"{symbol} — Shareholding Pattern (%) — Last 12 Quarters",
                    yaxis=dict(title="%", range=[0, 100]),
                    legend=dict(orientation="h", y=-0.2),
                    margin=dict(t=50, b=60),
                )
                st.plotly_chart(fig_sh, use_container_width=True)

                # ── Table (latest quarter on top) ─────────────────────────────
                sh_display = sh_table[["quarter","promoter","fii","dii","government","public_retail"]].copy()
                sh_display.columns = ["Quarter", "Promoter %", "FII %", "DII %", "Govt %", "Public %"]

                # Compute total to verify ≈ 100%
                sh_display["Total %"] = (
                    sh_table[["promoter","fii","dii","government","public_retail"]].sum(axis=1)
                )

                def _sh_color(col_name, lo, hi, rgb):
                    def _fn(v):
                        if not isinstance(v, (int, float)): return ""
                        intensity = max(0.0, min(1.0, (v - lo) / max(hi - lo, 1)))
                        r, g, b = [int(c + (255 - c) * (1 - intensity)) for c in rgb]
                        fg = "#fff" if intensity > 0.5 else "#ccc"
                        return f"background-color:rgb({r},{g},{b});color:{fg}"
                    return _fn

                st.dataframe(
                    sh_display.style
                        .format({c: "{:.2f}%" for c in sh_display.columns if "%" in c},
                                na_rep="–")
                        .map(_sh_color("Promoter %", 0, 80, (25, 118, 210)),  subset=["Promoter %"])
                        .map(_sh_color("FII %",      0, 30, (27, 94,  32)),   subset=["FII %"])
                        .map(_sh_color("DII %",      0, 30, (230, 81, 0)),    subset=["DII %"]),
                    use_container_width=True, hide_index=True,
                )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Smart Money Screener (DB-based, last business day, 90d avg filter)
# ══════════════════════════════════════════════════════════════════════════════
with tab_screener:
    last_bd = _last_trading_date().isoformat()

    # Pull all symbols that have data in DB
    con = _db()
    all_syms_in_db = [r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM smart_money_history"
    ).fetchall()]
    con.close()

    if not all_syms_in_db:
        st.info(
            "No data in screener yet. Go to **Stock Analysis** tab and search for stocks — "
            "their 90-day history will be saved automatically and appear here."
        )
    else:
        # For each symbol: load all rows, compute 90d avg, check last business day signal
        screener_rows = []
        for sym in all_syms_in_db:
            hist_s = _load_from_db(sym).dropna(subset=["close_price"])
            if hist_s.empty:
                continue

            # Require at least 60 trading days of data for a meaningful average
            if len(hist_s) < 60:
                continue

            avg_dlv_s = hist_s["dlv_pct"].mean()
            avg_act_s = hist_s["action"].mean()

            # Get last business day row
            last_row = hist_s[hist_s["trade_date"] == last_bd]
            if last_row.empty:
                # Try the most recent available date
                last_row = hist_s.sort_values("trade_date", ascending=False).head(1)

            r = last_row.iloc[0]
            d = r["dlv_pct"]
            a = r["action"]

            # Smart Money = Buying only if BOTH above their 90d average
            if not (pd.notna(d) and pd.notna(a) and
                    pd.notna(avg_dlv_s) and pd.notna(avg_act_s) and
                    d > avg_dlv_s and a > avg_act_s):
                continue

            # OI signal
            pp = r["pct_price_chg"]
            po = r["pct_oi_chg"]
            if pd.notna(pp) and pd.notna(po):
                if pp > 0 and po > 0:   oi_sig = "Long Buildup"
                elif pp > 0 and po < 0: oi_sig = "Short Covering"
                elif pp < 0 and po < 0: oi_sig = "Long Unwinding"
                elif pp < 0 and po > 0: oi_sig = "Short Buildup"
                else:                   oi_sig = "Neutral"
            else:
                oi_sig = "Neutral"

            screener_rows.append({
                "Symbol":            sym,
                "Date":              r["trade_date"],
                "Close (₹)":        r["close_price"],
                "% Price CHG":       r["pct_price_chg"],
                "Delivery %":        d,
                "90d Avg Delivery%": avg_dlv_s,
                "Action":            a,
                "90d Avg Action":    avg_act_s,
                "Futures OI":        r["futures_oi"],
                "OI Change":         r["oi_change"],
                "% OI Change":       r["pct_oi_chg"],
                "OI Signal":         oi_sig,
                "Smart Money":       "Buying",
                "_days":             len(hist_s),
            })

        total_tracked = len(all_syms_in_db)

        if not screener_rows:
            st.subheader("📊 Smart Money Screener")
            st.info(
                f"No stocks show a Smart Money **Buying** signal on the last business day "
                f"({last_bd}) among the **{total_tracked}** stock(s) tracked in the database.\n\n"
                "Add more stocks via **Stock Analysis** tab to broaden the scan."
            )
        else:
            scr_df = pd.DataFrame(screener_rows)

            st.subheader(
                f"📊 Smart Money Screener — {last_bd}  ·  "
                f"{len(scr_df)} Buying signal(s) from {total_tracked} tracked stocks"
            )
            st.caption(
                "Only stocks with ≥60 days of DB history are scanned. "
                "Smart Money = Buying when last business day Delivery % > 90d avg "
                "AND Action > 90d avg. Add more stocks in Stock Analysis tab."
            )

            # Sort controls
            sc1, sc2 = st.columns([3, 2])
            with sc1:
                sort_col2 = st.selectbox(
                    "Sort by",
                    ["Delivery %", "Action", "90d Avg Delivery%", "90d Avg Action",
                     "% OI Change", "% Price CHG", "Symbol"],
                    index=0, key="scr_sort",
                )
            with sc2:
                sort_asc2 = st.radio("Order", ["Descending", "Ascending"],
                                     horizontal=True, index=0, key="scr_asc")

            sort_map2 = {
                "Delivery %":          "Delivery %",
                "Action":              "Action",
                "90d Avg Delivery%":   "90d Avg Delivery%",
                "90d Avg Action":      "90d Avg Action",
                "% OI Change":         "% OI Change",
                "% Price CHG":         "% Price CHG",
                "Symbol":              "Symbol",
            }
            scr_df = scr_df.sort_values(
                sort_map2[sort_col2], ascending=(sort_asc2 == "Ascending")
            ).reset_index(drop=True)

            # Build display DataFrame — short column names to avoid horizontal scroll
            display2 = pd.DataFrame({
                "Symbol":      scr_df["Symbol"],
                "Close ₹":     scr_df["Close (₹)"],
                "Chg%":        scr_df["% Price CHG"],
                "Dlv%":        scr_df["Delivery %"],
                "Avg Dlv%":    scr_df["90d Avg Delivery%"],
                "Action":      scr_df["Action"],
                "Avg Act":     scr_df["90d Avg Action"],
                "FUT OI":      scr_df["Futures OI"].apply(lambda x: int(x) if pd.notna(x) else None),
                "OI Chg%":     scr_df["% OI Change"],
                "OI Signal":   scr_df["OI Signal"],
                "Signal":      scr_df["Smart Money"],
            })

            OI_C2 = {
                "Long Buildup":   "color:#00C853;font-weight:600",
                "Short Covering": "color:#64DD17;font-weight:600",
                "Long Unwinding": "color:#FF5252;font-weight:600",
                "Short Buildup":  "color:#D50000;font-weight:600",
                "Neutral":        "color:#666",
            }

            def _cn2(v):
                if not isinstance(v, (int, float)): return ""
                return "color:#00C853" if v > 0 else "color:#D50000" if v < 0 else ""

            def _csm2(v):
                return "color:#00C853;font-weight:700" if v == "Buying" else "color:#555"

            def _cavg(v):
                return "color:#FFD600" if isinstance(v, float) else ""

            st.dataframe(
                display2.style
                    .map(_cn2,  subset=["Chg%", "OI Chg%"])
                    .map(_cavg, subset=["Avg Dlv%", "Avg Act"])
                    .map(lambda v: OI_C2.get(v, ""), subset=["OI Signal"])
                    .map(_csm2, subset=["Signal"])
                    .format({
                        "Close ₹":  "₹{:,.0f}",
                        "Chg%":     "{:+.1f}%",
                        "Dlv%":     "{:.1f}%",
                        "Avg Dlv%": "{:.1f}%",
                        "Action":   "{:.1f}",
                        "Avg Act":  "{:.1f}",
                        "OI Chg%":  "{:+.1f}%",
                        "FUT OI":   "{:,}",
                    }, na_rep="–"),
                use_container_width=True, hide_index=True, height=600,
            )

from app.utils.disclaimer import show_footer
show_footer()
