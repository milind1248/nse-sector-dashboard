"""
Weekly Supabase Postgres backup — dumps the public schema to a local file
via pg_dump, so a copy of all data survives even if Supabase itself is
lost. Restore with scripts/restore_local.py.

Uses the exact same connection string backend/storage/db.py already reads
(secrets.toml[supabase].db_connection_string) — no separate credential
config to keep in sync.

Requires PostgreSQL client tools (pg_dump) — see _pg_tools.find_pg_tool().
"""
import subprocess
import sys
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.storage.db import _connection_string
from scripts._pg_tools import find_pg_tool

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
RETENTION_COUNT = 8  # keep the last N dumps (weekly cadence -> ~2 months)


def run_backup() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = BACKUP_DIR / f"supabase_{stamp}.dump"

    dsn = _connection_string()
    cmd = [
        find_pg_tool("pg_dump"), dsn,
        "--schema=public",
        "--no-owner",
        "--no-privileges",
        "--format=custom",
        "-f", str(out_path),
    ]
    logger.info("Starting pg_dump -> %s", out_path)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

    if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        if out_path.exists():
            out_path.unlink()
        raise RuntimeError(f"pg_dump failed (exit {result.returncode}): {result.stderr}")

    logger.info("Backup complete: %s (%.1f MB)", out_path, out_path.stat().st_size / 1e6)
    _apply_retention()
    return out_path


def _apply_retention() -> None:
    dumps = sorted(BACKUP_DIR.glob("supabase_*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in dumps[RETENTION_COUNT:]:
        logger.info("Retention: deleting old backup %s", old.name)
        old.unlink()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    path = run_backup()
    print(f"Backup written to {path}")
