"""
Bulk & Block Deals — daily NSE archive CSVs (large institutional/promoter
trades). Static-archive host, no session/cookie warm-up needed — same
no-warm-up pattern already proven for Bhavcopy/EQUITY_L.csv in
sector_sync.py / nse_fetcher.py.

NSE publishes:
  - bulk.csv:  trades where quantity >= 0.5% of listed shares
  - block.csv: trades of >= 5 lakh shares (or >= Rs 5 crore) executed via
    the block deal window
Both only ever contain TODAY's deals — there's no historical archive URL
for older dates via this same static path, so this pipeline is inherently
"today only" and accumulates history in Postgres via daily idempotent upserts.
"""
import logging
from datetime import datetime, date

import pandas as pd
import requests

from backend.storage.db import get_conn

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_BULK_URL = "https://archives.nseindia.com/content/equities/bulk.csv"
_BLOCK_URL = "https://archives.nseindia.com/content/equities/block.csv"


def _fetch_csv(url: str) -> pd.DataFrame:
    r = requests.get(url, headers=_HEADERS, timeout=20)
    r.raise_for_status()
    lines = r.text.strip().splitlines()
    if len(lines) < 2 or "NO RECORDS" in lines[1]:
        return pd.DataFrame()
    from io import StringIO
    df = pd.read_csv(StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    return df


def fetch_bulk_deals() -> pd.DataFrame:
    return _fetch_csv(_BULK_URL)


def fetch_block_deals() -> pd.DataFrame:
    return _fetch_csv(_BLOCK_URL)


def _save_deals(df: pd.DataFrame, table: str) -> int:
    if df.empty:
        return 0
    conn = get_conn()
    saved = 0
    for _, row in df.iterrows():
        try:
            trade_date = datetime.strptime(str(row["Date"]).strip(), "%d-%b-%Y").date()
        except (ValueError, KeyError):
            continue
        symbol = str(row.get("Symbol", "")).strip()
        if not symbol:
            continue
        security_name = str(row.get("Security Name", "")).strip() or None
        client_name = str(row.get("Client Name", "")).strip() or None
        deal_type = str(row.get("Buy/Sell", "")).strip().upper() or None
        try:
            quantity = int(float(str(row.get("Quantity Traded", 0)).replace(",", "")))
        except ValueError:
            quantity = None
        price_col = "Trade Price / Wght. Avg. Price"
        try:
            price = float(str(row.get(price_col, 0)).replace(",", ""))
        except ValueError:
            price = None

        conn.execute(
            f"""
            INSERT INTO {table}
                (trade_date, symbol, security_name, client_name, deal_type, quantity, price, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trade_date, symbol, client_name, deal_type, quantity, price) DO NOTHING
            """,
            (trade_date, symbol, security_name, client_name, deal_type, quantity, price,
             datetime.utcnow().isoformat()),
        )
        saved += 1
    conn.commit()
    conn.close()
    return saved


def run_bulk_deals_pipeline() -> dict:
    bulk_df = fetch_bulk_deals()
    block_df = fetch_block_deals()

    bulk_saved = _save_deals(bulk_df, "bulk_deals")
    block_saved = _save_deals(block_df, "block_deals")

    logger.info(f"Bulk deals: {len(bulk_df)} rows fetched, {bulk_saved} upserted. "
                f"Block deals: {len(block_df)} rows fetched, {block_saved} upserted.")
    return {"bulk_fetched": len(bulk_df), "bulk_saved": bulk_saved,
            "block_fetched": len(block_df), "block_saved": block_saved}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_bulk_deals_pipeline())
