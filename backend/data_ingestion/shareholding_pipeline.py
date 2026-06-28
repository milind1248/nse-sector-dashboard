"""
Quarterly shareholding pattern refresh pipeline.

Runs 4 times per year — 27th of January, April, July, October — giving
6 days buffer after the SEBI filing deadline (21 days post quarter-end).

Quarter schedule:
  Q4 (Jan–Mar end)  → filed by 21 Apr  → pulled 27 Apr
  Q1 (Apr–Jun end)  → filed by 21 Jul  → pulled 27 Jul
  Q2 (Jul–Sep end)  → filed by 21 Oct  → pulled 27 Oct
  Q3 (Oct–Dec end)  → filed by 21 Jan  → pulled 27 Jan

Data source: publicly available quarterly company filings (SEBI Regulation 31 LODR).
"""
import logging
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from config import SECTOR_STOCKS

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nse_dashboard.db"


def _db():
    return sqlite3.connect(_DB_PATH)


def _ensure_tables():
    con = _db()
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
    con.execute("""
        CREATE TABLE IF NOT EXISTS shareholding_refresh_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


def _fetch_shareholding(symbol: str) -> list[dict]:
    """Fetch up to 12 quarters from public quarterly company filings."""
    import requests
    from bs4 import BeautifulSoup

    for suffix in ["/consolidated/", "/"]:
        url = f"https://www.screener.in/company/{symbol}{suffix}"
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
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
            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
            quarters = headers[1:]
            cat_map = {
                "Promoters": "promoter",
                "FIIs":      "fii",
                "DIIs":      "dii",
                "Government":"government",
                "Public":    "public_retail",
            }
            data: dict[str, list] = {}
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
            num_q  = len(quarters)
            start  = max(0, num_q - 12)
            now_ts = datetime.utcnow().isoformat()
            result = []
            for i in range(num_q - 1, start - 1, -1):
                if i >= len(quarters):
                    continue
                result.append({
                    "symbol":        symbol,
                    "quarter":       quarters[i],
                    "promoter":      data.get("promoter",      [None] * num_q)[i],
                    "fii":           data.get("fii",           [None] * num_q)[i],
                    "dii":           data.get("dii",           [None] * num_q)[i],
                    "government":    data.get("government",    [None] * num_q)[i],
                    "public_retail": data.get("public_retail", [None] * num_q)[i],
                    "fetched_at":    now_ts,
                })
            return result
        except Exception as e:
            logger.debug(f"Fetch failed for {symbol}{suffix}: {e}")
            continue
    return []


def _save(rows: list[dict]):
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


def _all_symbols() -> list[str]:
    seen = set()
    out = []
    for syms in SECTOR_STOCKS.values():
        for s in syms:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def run_shareholding_pipeline(triggered_by: str = "scheduler"):
    """
    Fetch shareholding pattern for all sector stocks and store to DB.
    Called by the quarterly scheduler (27th Jan/Apr/Jul/Oct) or manually by admin.
    Logging (log_start/log_finish) is the caller's responsibility — do NOT log internally.
    """
    _ensure_tables()
    symbols = _all_symbols()
    logger.info(f"Shareholding pipeline started — {len(symbols)} symbols to fetch.")

    errors  = []
    success = 0

    def _fetch_and_save(sym: str) -> str:
        rows = _fetch_shareholding(sym)
        if rows:
            _save(rows)
            return "ok"
        return "miss"

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(_fetch_and_save, s): s for s in symbols}
        for fut in as_completed(futs):
            sym = futs[fut]
            try:
                status = fut.result()
                if status == "miss":
                    errors.append(sym)
                    logger.warning(f"No data returned for {sym}")
                else:
                    success += 1
                    logger.info(f"[{success}/{len(symbols)}] {sym} — saved")
            except Exception as e:
                errors.append(sym)
                logger.error(f"Error fetching {sym}: {e}")
            time.sleep(0.4)  # polite rate-limiting

    # Record last successful run timestamp
    ts = datetime.utcnow().isoformat()
    con = _db()
    con.execute(
        "INSERT OR REPLACE INTO shareholding_refresh_meta (key, value) VALUES ('last_full_refresh', ?)",
        (ts,)
    )
    con.commit()
    con.close()

    logger.info(f"Shareholding pipeline complete. Success: {success}, Failed: {len(errors)}")
    if errors:
        logger.warning(f"Failed symbols: {errors}")

    if errors:
        raise RuntimeError(f"{len(errors)} symbols failed: {errors[:5]}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_shareholding_pipeline()
