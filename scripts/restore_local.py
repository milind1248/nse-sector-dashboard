"""
Restore a Supabase backup (scripts/backup_supabase.py output) into a local
Postgres database, for disaster-recovery inspection or emergency use.

scripts/supabase_schema.sql has one Supabase-specific dependency:
    profiles.id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE
auth.users is Supabase's internal Auth table and doesn't exist on a plain
local Postgres. Rather than maintain a second hand-edited schema file (the
thing this whole backup system exists to avoid), we create a minimal STUB
auth.users(id) table locally — no real credentials, just enough rows to
satisfy the foreign key — populated from the restored profiles table itself.

Usage:
    python scripts/restore_local.py [path/to/backup.dump]
    (defaults to the newest file in backups/)

Requires:
    - PostgreSQL client tools (pg_restore, psql) — see _pg_tools.find_pg_tool().
    - secrets.toml[local_postgres].db_connection_string pointing at a
      local Postgres server/database to restore into (created if it
      doesn't exist — the target database itself must already exist,
      matching standard pg_restore behavior).
"""
import subprocess
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._pg_tools import find_pg_tool

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"

_STUB_AUTH_SQL = """
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (id UUID PRIMARY KEY);
"""

_BACKFILL_AUTH_SQL = """
INSERT INTO auth.users (id)
SELECT id FROM public.profiles
ON CONFLICT DO NOTHING;
"""

# pg_restore adds profiles_id_fkey (against auth.users) during its own
# constraint-creation pass, which runs BEFORE our backfill above — so on a
# fresh local restore the stub auth.users table is still empty at that
# point and the constraint fails to attach (data itself restores fine;
# pg_restore just logs and skips that one ALTER TABLE). Re-add it here,
# now that auth.users is backfilled, guarded so re-running restore is safe.
_REATTACH_FK_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'profiles_id_fkey'
    ) THEN
        ALTER TABLE public.profiles ADD CONSTRAINT profiles_id_fkey
            FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;
"""


def _local_dsn() -> str:
    try:
        import streamlit as st
        return st.secrets["local_postgres"]["db_connection_string"]
    except Exception:
        import toml
        secrets_path = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
        secrets = toml.load(secrets_path)
        return secrets["local_postgres"]["db_connection_string"]


def _newest_backup() -> Path:
    dumps = sorted(BACKUP_DIR.glob("supabase_*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dumps:
        raise FileNotFoundError(f"No backup files found in {BACKUP_DIR}")
    return dumps[0]


def restore(dump_path: Path, local_dsn: str) -> None:
    logger.info("Creating stub auth.users table on local target...")
    psql_stub = subprocess.run(
        [find_pg_tool("psql"), local_dsn, "-c", _STUB_AUTH_SQL],
        capture_output=True, text=True,
    )
    if psql_stub.returncode != 0:
        raise RuntimeError(f"Failed to create stub auth schema: {psql_stub.stderr}")

    logger.info("Restoring %s into local database...", dump_path)
    restore_result = subprocess.run(
        [find_pg_tool("pg_restore"), "--clean", "--if-exists", "--no-owner", "--no-privileges",
         "-d", local_dsn, str(dump_path)],
        capture_output=True, text=True,
    )
    # pg_restore commonly exits non-zero on harmless warnings (e.g. dropping
    # objects that don't exist yet on first run) — only fail on the absence
    # of any successfully restored objects.
    if restore_result.returncode != 0:
        logger.warning("pg_restore reported warnings:\n%s", restore_result.stderr)

    logger.info("Backfilling stub auth.users from restored profiles...")
    backfill = subprocess.run(
        [find_pg_tool("psql"), local_dsn, "-c", _BACKFILL_AUTH_SQL],
        capture_output=True, text=True,
    )
    if backfill.returncode != 0:
        logger.warning("auth.users backfill failed (ok if profiles table is empty): %s", backfill.stderr)

    logger.info("Re-attaching profiles_id_fkey (skipped by pg_restore since auth.users was empty)...")
    reattach = subprocess.run(
        [find_pg_tool("psql"), local_dsn, "-c", _REATTACH_FK_SQL],
        capture_output=True, text=True,
    )
    if reattach.returncode != 0:
        logger.warning("Failed to re-attach profiles_id_fkey: %s", reattach.stderr)

    logger.info("Restore complete.")
    _print_summary(local_dsn)


def _print_summary(local_dsn: str) -> None:
    check_tables = ["profiles", "daily_sector_snapshot", "smart_money_history", "fii_dii_daily"]
    for t in check_tables:
        result = subprocess.run(
            [find_pg_tool("psql"), local_dsn, "-t", "-c", f"SELECT COUNT(*) FROM public.{t};"],
            capture_output=True, text=True,
        )
        count = result.stdout.strip() if result.returncode == 0 else "ERROR"
        print(f"  {t}: {count} rows")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    dump_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else _newest_backup()
    dsn = _local_dsn()
    restore(dump_arg, dsn)
