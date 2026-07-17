"""Locate PostgreSQL client binaries (pg_dump/pg_restore/psql), used by
backup_supabase.py and restore_local.py. Checks PATH first, then falls back
to the standard Windows install directory — a freshly installed PostgreSQL
isn't on PATH until the shell/service restarts."""
import shutil
from pathlib import Path


def find_pg_tool(name: str) -> str:
    on_path = shutil.which(name)
    if on_path:
        return on_path
    for bin_dir in sorted(Path("C:/Program Files/PostgreSQL").glob("*/bin"), reverse=True):
        candidate = bin_dir / f"{name}.exe"
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        f"{name} not found on PATH or under C:/Program Files/PostgreSQL/*/bin. "
        "Install PostgreSQL client tools first."
    )
