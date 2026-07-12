"""
One-time data backfill: copy every row from the local SQLite DB into Supabase.

Run AFTER scripts/supabase_schema.sql has been applied to the Supabase project
and .streamlit/secrets.toml has a real [supabase].db_connection_string.

Usage:
    python scripts/migrate_sqlite_to_supabase.py

Auto-increment `id` columns are NOT copied — Postgres generates fresh ones.
Nothing in this app treats a paper_orders/paper_holdings id (or any other
table's id) as a foreign key elsewhere, so this is safe.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH
from backend.storage.db import get_conn
import psycopg2.extras

# table -> True if it has an auto-increment `id` column to skip on insert
TABLES: dict[str, bool] = {
    "paper_orders": True,
    "paper_holdings": True,
    "ai_forecast_cache": True,
    "ai_scan_results": True,
    "gann_cache": False,
    "market_breadth": False,
    "sector_heatmap": False,
    "rrg_snapshot": False,
    "daily_sector_snapshot": True,
    "daily_stock_snapshot": True,
    "fii_dii_daily": True,
    "market_breadth_daily": True,
    "nsdl_fii_sector": True,
    "site_stats": False,
    "alerts_log": True,
    "sector_intelligence": False,
    "sector_sync_log": True,
    "smart_money_history": False,
    "fno_symbols": False,
    "shareholding_pattern": False,
    "shareholding_refresh_meta": False,
    "job_run_log": True,
    "page_test_log": True,
}


def _sqlite_columns(sq_con: sqlite3.Connection, table: str, skip_id: bool) -> list[str]:
    cols = [row[1] for row in sq_con.execute(f"PRAGMA table_info({table})").fetchall()]
    return [c for c in cols if not (skip_id and c == "id")]


def migrate_table(sq_con: sqlite3.Connection, pg_conn, table: str, skip_id: bool) -> tuple[int, int]:
    cols = _sqlite_columns(sq_con, table, skip_id)
    col_list = ", ".join(cols)
    rows = sq_con.execute(f"SELECT {col_list} FROM {table}").fetchall()

    if rows:
        placeholders = ", ".join(["%s"] * len(cols))
        insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
        cur = pg_conn._raw.cursor()
        psycopg2.extras.execute_batch(cur, insert_sql, rows, page_size=500)
        pg_conn.commit()

    sq_count = sq_con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    pg_count = pg_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return sq_count, pg_count


def main():
    sq_con = sqlite3.connect(DB_PATH)
    pg_conn = get_conn()

    print(f"Source: {DB_PATH}")
    print(f"{'Table':<28} {'SQLite':>8} {'Supabase':>10}  Status")
    print("-" * 62)

    all_ok = True
    for table, skip_id in TABLES.items():
        try:
            sq_count, pg_count = migrate_table(sq_con, pg_conn, table, skip_id)
            ok = sq_count == pg_count
            all_ok &= ok
            status = "OK" if ok else "MISMATCH"
            print(f"{table:<28} {sq_count:>8} {pg_count:>10}  {status}")
        except Exception as e:
            all_ok = False
            print(f"{table:<28} {'ERROR':>8} {'':>10}  {e}")

    sq_con.close()
    pg_conn.close()

    print("-" * 62)
    print("All row counts match." if all_ok else "Some tables did not match — check output above.")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
