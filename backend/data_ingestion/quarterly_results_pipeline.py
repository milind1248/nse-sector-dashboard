"""
Quarterly results (Sales/Profit/EBITDA) refresh pipeline — feeds the PEAD
Scanner's results-surprise scoring.

Mirrors backend/data_ingestion/shareholding_pipeline.py's exact shape
(same Screener.in source, same requests+BeautifulSoup scrape, same
ThreadPoolExecutor(max_workers=3) + time.sleep(1.5) rate-limiting, same
per-symbol isolation) — proven pattern, reused rather than reinvented.
Scrapes the page's `section#quarters` table (Sales/Expenses/Operating
Profit/OPM%/Net Profit/EPS), which shareholding_pipeline.py never touches
(it only reads `section#shareholding`).

No fixed quarterly schedule like shareholding_pipeline.py's 27th-of-month
cadence — company results land continuously across a ~4-6 week window each
quarter on no fixed per-company date, so this pipeline is designed to be
run on demand (admin "Refresh Results" button) rather than a single
scheduled date. A real recurring job can be added once this is proven.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from backend.storage.db import get_conn

logger = logging.getLogger(__name__)

_ROW_KEY_MAP = {
    "Sales": "sales",
    "Expenses": "expenses",
    "Operating Profit": "operating_profit",
    "OPM %": "opm_pct",
    "Other Income": "other_income",
    "Profit before tax": "pbt",
    "Net Profit": "net_profit",
    "EPS in Rs": "eps",
}


def _db():
    return get_conn()


def _parse_number(txt: str) -> float | None:
    txt = txt.replace(",", "").replace("%", "").strip()
    if not txt or txt in ("-", "—"):
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _fetch_quarterly_results(symbol: str) -> list[dict]:
    """Fetch up to 8 quarters of Sales/Profit/EBITDA from Screener.in's
    section#quarters table. `symbol` may be given with or without a ".NS"
    suffix (this project's universe.py/yfinance convention uses ".NS") —
    Screener.in's own URLs use the plain NSE symbol only and 404 on a
    ".NS"-suffixed one (confirmed directly), so the suffix is stripped
    just for the URL. Rows are still stored under the symbol AS GIVEN, to
    stay joinable with the rest of this codebase's ".NS"-suffixed tables."""
    import requests
    from bs4 import BeautifulSoup

    screener_symbol = symbol[:-3] if symbol.upper().endswith(".NS") else symbol
    for suffix in ["/consolidated/", "/"]:
        url = f"https://www.screener.in/company/{screener_symbol}{suffix}"
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            section = soup.find("section", {"id": "quarters"})
            if not section:
                continue
            table = section.find("table")
            if not table:
                continue
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
            quarters = headers[1:]

            data: dict[str, list] = {}
            for row in rows[1:]:
                cells = row.find_all(["th", "td"])
                if not cells:
                    continue
                label = cells[0].get_text(strip=True).rstrip("+").strip()
                key = _ROW_KEY_MAP.get(label)
                if not key:
                    continue
                data[key] = [_parse_number(c.get_text(strip=True)) for c in cells[1:]]

            if "sales" not in data:
                continue

            num_q = len(quarters)
            start = max(0, num_q - 8)
            now_ts = datetime.utcnow().isoformat()

            def _get(key: str, i: int):
                vals = data.get(key)
                return vals[i] if vals and i < len(vals) else None

            result = []
            for i in range(num_q - 1, start - 1, -1):
                if i >= len(quarters):
                    continue
                result.append({
                    "symbol": symbol,
                    "quarter": quarters[i],
                    "sales": _get("sales", i),
                    "net_profit": _get("net_profit", i),
                    "operating_profit": _get("operating_profit", i),
                    "opm_pct": _get("opm_pct", i),
                    "other_income": _get("other_income", i),
                    "pbt": _get("pbt", i),
                    "eps": _get("eps", i),
                    "fetched_at": now_ts,
                })
            return result
        except Exception as e:
            logger.debug(f"Fetch failed for {symbol}{suffix}: {e}")
            continue
    return []


def _save(rows: list[dict]) -> None:
    if not rows:
        return
    con = _db()
    con.executemany("""
        INSERT INTO quarterly_results
        (symbol, quarter, sales, net_profit, operating_profit, opm_pct, other_income, pbt, eps, fetched_at)
        VALUES (%(symbol)s, %(quarter)s, %(sales)s, %(net_profit)s, %(operating_profit)s,
                %(opm_pct)s, %(other_income)s, %(pbt)s, %(eps)s, %(fetched_at)s)
        ON CONFLICT (symbol, quarter) DO UPDATE SET
            sales=EXCLUDED.sales, net_profit=EXCLUDED.net_profit,
            operating_profit=EXCLUDED.operating_profit, opm_pct=EXCLUDED.opm_pct,
            other_income=EXCLUDED.other_income, pbt=EXCLUDED.pbt,
            eps=EXCLUDED.eps, fetched_at=EXCLUDED.fetched_at
    """, rows)
    con.commit()
    con.close()


def run_quarterly_results_pipeline(symbols: list[str], triggered_by: str = "manual") -> dict:
    """Fetch quarterly results for the given symbol list and store to DB.
    Called on-demand from the PEAD Scanner page's "Refresh Results" button
    (or manually). Logging (log_start/log_finish) is the caller's
    responsibility — do NOT log internally, matching shareholding_pipeline.py's
    convention."""
    logger.info(f"Quarterly results pipeline started — {len(symbols)} symbols, triggered_by={triggered_by}")

    errors: list[str] = []
    success = 0

    def _fetch_and_save(sym: str) -> str:
        rows = _fetch_quarterly_results(sym)
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
                else:
                    success += 1
            except Exception as e:
                errors.append(sym)
                logger.error(f"Error fetching {sym}: {e}")
            time.sleep(1.5)  # polite rate-limiting — avoid triggering Screener.in rate limits

    logger.info(f"Quarterly results pipeline complete. Success: {success}, Failed: {len(errors)}")
    return {"total": len(symbols), "success": success, "failed": len(errors), "failed_symbols": errors}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    syms = sys.argv[1:] or ["RELIANCE", "TCS", "INFY"]
    print(run_quarterly_results_pipeline(syms))
