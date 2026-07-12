"""
Smart Money pipeline — fetches CM Bhav Copy + MTO Delivery + FO OI for all F&O
symbols and stores to smart_money_history (90 trading days rolling window).

Called by Admin "▶ Run" button or scheduler.
"""
import logging
import zipfile
import io as _io
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd
import requests

from backend.storage.db import get_conn

logger = logging.getLogger(__name__)

_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db():
    return get_conn()


# ── Date helpers ──────────────────────────────────────────────────────────────

def _last_trading_date() -> date:
    from datetime import datetime
    import pytz
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist)
    today = now_ist.date()
    wd = today.weekday()
    if wd == 5:
        return today - timedelta(days=1)
    if wd == 6:
        return today - timedelta(days=2)
    if now_ist.hour < 18:
        prev = today - timedelta(days=1)
        if prev.weekday() == 5:
            prev -= timedelta(days=1)
        if prev.weekday() == 6:
            prev -= timedelta(days=2)
        return prev
    return today


def _trading_dates_for_90d() -> list[date]:
    end = _last_trading_date()
    result = []
    for i in range(200):
        d = end - timedelta(days=i)
        if d.weekday() < 5:
            result.append(d)
        if len(result) == 90:
            break
    return result


# ── NSE archive fetchers ──────────────────────────────────────────────────────

def _fetch_one_day(symbol: str, dt: date) -> dict | None:
    row = {
        "symbol": symbol, "trade_date": dt.isoformat(),
        "close_price": None, "pct_price_chg": None,
        "trade_qty": None, "tot_trade": None, "action": None,
        "dlv_pct": None, "futures_oi": None, "oi_change": None, "pct_oi_chg": None,
    }
    ds = dt.strftime("%Y%m%d")
    got_any = False

    # CM Bhav Copy
    try:
        url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ds}_F_0000.csv.zip"
        r = requests.get(url, headers=_HDR, timeout=20)
        if r.status_code == 200:
            z = zipfile.ZipFile(_io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            s = df[(df["TckrSymb"] == symbol) & (df["SctySrs"].isin({"EQ", "BE", "BZ", "SM", "ST"}))]
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

    # MTO Delivery
    try:
        url = f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{dt.strftime('%d%m%Y')}.DAT"
        r = requests.get(url, headers=_HDR, timeout=15)
        if r.status_code == 200:
            lines = [l for l in r.text.splitlines() if l.startswith("20,")]
            mdf = pd.read_csv(_io.StringIO("\n".join(lines)), header=None,
                              names=["rec", "sr", "sym", "series", "qty_traded", "dlv_qty", "dlv_pct"])
            m = mdf[(mdf["sym"] == symbol) & (mdf["series"] == "EQ")]
            if not m.empty:
                qty = pd.to_numeric(m["qty_traded"].iloc[0], errors="coerce")
                dlv = pd.to_numeric(m["dlv_qty"].iloc[0],   errors="coerce")
                if pd.notna(qty) and pd.notna(dlv) and qty > 0:
                    row["dlv_pct"] = round(dlv / qty * 100, 2)
                got_any = True
    except Exception:
        pass

    # FO Bhav Copy
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
                oi    = pd.to_numeric(nearest["OpnIntrst"],       errors="coerce")
                oichg = pd.to_numeric(nearest["ChngInOpnIntrst"], errors="coerce")
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


def _stored_dates(symbol: str) -> set[str]:
    con = _db()
    rows = con.execute(
        "SELECT trade_date FROM smart_money_history WHERE symbol=%s", (symbol,)
    ).fetchall()
    con.close()
    return {str(r[0]) for r in rows}


def _save_rows(rows: list[dict]):
    if not rows:
        return
    con = _db()
    con.executemany("""
        INSERT INTO smart_money_history
        (symbol,trade_date,close_price,pct_price_chg,trade_qty,tot_trade,
         action,dlv_pct,futures_oi,oi_change,pct_oi_chg)
        VALUES (%(symbol)s,%(trade_date)s,%(close_price)s,%(pct_price_chg)s,%(trade_qty)s,%(tot_trade)s,
                %(action)s,%(dlv_pct)s,%(futures_oi)s,%(oi_change)s,%(pct_oi_chg)s)
        ON CONFLICT (symbol, trade_date) DO UPDATE SET
            close_price=EXCLUDED.close_price, pct_price_chg=EXCLUDED.pct_price_chg,
            trade_qty=EXCLUDED.trade_qty, tot_trade=EXCLUDED.tot_trade, action=EXCLUDED.action,
            dlv_pct=EXCLUDED.dlv_pct, futures_oi=EXCLUDED.futures_oi,
            oi_change=EXCLUDED.oi_change, pct_oi_chg=EXCLUDED.pct_oi_chg
    """, rows)
    con.commit()
    con.close()


def _purge_old(symbol: str, trading_dates: list[date]):
    if not trading_dates:
        return
    cutoff = trading_dates[-1].isoformat()
    con = _db()
    con.execute(
        "DELETE FROM smart_money_history WHERE symbol=%s AND trade_date < %s",
        (symbol, cutoff),
    )
    con.commit()
    con.close()


def _fno_symbols() -> list[str]:
    con = _db()
    rows = con.execute("SELECT symbol FROM fno_symbols ORDER BY symbol").fetchall()
    con.close()
    return [r[0] for r in rows]


def _refresh_fno_list() -> list[str]:
    """Download latest FO Bhav Copy, extract STF symbols, save to DB."""
    from datetime import datetime
    today = _last_trading_date()
    ds = today.strftime("%Y%m%d")
    try:
        url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ds}_F_0000.csv.zip"
        r = requests.get(url, headers=_HDR, timeout=25)
        if r.status_code != 200:
            return _fno_symbols()
        z = zipfile.ZipFile(_io.BytesIO(r.content))
        df = pd.read_csv(z.open(z.namelist()[0]))
        symbols = sorted(df[df["FinInstrmTp"] == "STF"]["TckrSymb"].dropna().unique().tolist())
        now_ts = datetime.utcnow().isoformat()
        con = _db()
        con.execute("DELETE FROM fno_symbols")
        con.executemany(
            "INSERT INTO fno_symbols (symbol, updated_at) VALUES (%s, %s) "
            "ON CONFLICT (symbol) DO UPDATE SET updated_at=EXCLUDED.updated_at",
            [(s, now_ts) for s in symbols],
        )
        con.commit()
        con.close()
        logger.info(f"FNO symbol list refreshed — {len(symbols)} symbols")
        return symbols
    except Exception as e:
        logger.warning(f"FNO list refresh failed: {e} — using cached list")
        return _fno_symbols()


def _process_symbol(symbol: str, trading_dates: list[date]) -> int:
    """Fetch missing days for one symbol, save to DB. Returns rows saved."""
    stored = _stored_dates(symbol)
    missing = [d for d in trading_dates if d.isoformat() not in stored]
    if not missing:
        return 0
    rows = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_one_day, symbol, d): d for d in missing}
        for f in as_completed(futures):
            try:
                row = f.result()
                if row:
                    rows.append(row)
            except Exception:
                pass
    _save_rows(rows)
    _purge_old(symbol, trading_dates)
    return len(rows)


# ── Public entry point ────────────────────────────────────────────────────────

def run_smart_money_pipeline(triggered_by: str = "admin",
                             progress_callback=None) -> dict:
    """
    Refresh smart_money_history for all F&O symbols.
    Fetches only missing dates (incremental) — idempotent.

    progress_callback(done, total, symbol) — optional live update hook.
    Returns summary dict: {total, rows_added, elapsed_sec}
    """
    import time
    t0 = time.time()

    logger.info(f"Smart Money pipeline started (triggered_by={triggered_by})")

    # Always refresh FNO list first to catch new additions
    symbols = _refresh_fno_list()
    if not symbols:
        return {"total": 0, "rows_added": 0, "elapsed_sec": 0,
                "error": "No F&O symbols found"}

    trading_dates = _trading_dates_for_90d()
    total     = len(symbols)
    rows_added = 0
    done      = 0

    # Process symbols in parallel batches (4 workers — each symbol uses 10 threads internally)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_process_symbol, sym, trading_dates): sym for sym in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            done += 1
            try:
                n = fut.result()
                rows_added += n
            except Exception as e:
                logger.warning(f"Failed for {sym}: {e}")
            if progress_callback:
                try:
                    progress_callback(done, total, sym)
                except Exception:
                    pass

    elapsed = round(time.time() - t0, 1)
    logger.info(
        f"Smart Money pipeline done — {total} symbols · {rows_added} rows added · {elapsed}s"
    )
    return {"total": total, "rows_added": rows_added, "elapsed_sec": elapsed}
