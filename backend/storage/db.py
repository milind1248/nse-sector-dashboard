"""
Shared Postgres (Supabase) connection helper.

Every storage/pipeline module that used to do `sqlite3.connect(DB_PATH)` now
does `from backend.storage.db import get_conn` instead. `PGConnection` mimics
just enough of sqlite3.Connection's API (`.execute()` returns a cursor,
`.commit()`, `.close()`) that most call sites only need two changes:
  1. the import/connect swap this module provides
  2. `?` placeholders -> `%s` in their SQL strings

Rows come back as plain tuples (psycopg2's default cursor), matching
sqlite3's default row behavior exactly — existing code that does `row[0]`,
tuple-unpacks a row, or does `dict(zip(cols, row))` keeps working unchanged.
Do NOT switch to RealDictCursor here: a dict-returning row breaks every one
of those positional-access patterns across the codebase.

Credentials come from `.streamlit/secrets.toml` under `[supabase]`. Works
both inside a running Streamlit page (via `st.secrets`) and in standalone
scripts like `run.py schedule` / `scripts/*.py` that never import streamlit
(falls back to reading the TOML file directly).
"""
from pathlib import Path

import psycopg2

_SECRETS_PATH = Path(__file__).resolve().parent.parent.parent / ".streamlit" / "secrets.toml"


def _connection_string() -> str:
    try:
        import streamlit as st
        return st.secrets["supabase"]["db_connection_string"]
    except Exception:
        import toml
        secrets = toml.load(_SECRETS_PATH)
        return secrets["supabase"]["db_connection_string"]


class PGConnection:
    """sqlite3.Connection-compatible wrapper around a psycopg2 connection."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql: str, params=()):
        cur = self._raw.cursor()
        cur.execute(sql, params)
        return cur

    def executemany(self, sql: str, seq_of_params):
        cur = self._raw.cursor()
        cur.executemany(sql, seq_of_params)
        return cur

    def cursor(self):
        """Passthrough so pandas' read_sql_query/to_sql (which need a real DBAPI2
        connection, not just an object with .execute()) work unchanged."""
        return self._raw.cursor()

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def get_conn() -> PGConnection:
    """Open a fresh connection to the Supabase Postgres database."""
    return PGConnection(psycopg2.connect(_connection_string()))
