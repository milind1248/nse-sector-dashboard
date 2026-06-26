"""Visitor counter — increments once per session, stored in SQLite site_stats table."""
import streamlit as st
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def increment_and_get() -> int:
    try:
        from backend.storage.database import get_engine
        import sqlalchemy as sa

        engine = get_engine()

        with engine.begin() as conn:   # engine.begin() = auto-commit transaction
            conn.execute(sa.text(
                "CREATE TABLE IF NOT EXISTS site_stats "
                "(key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0)"
            ))
            row = conn.execute(
                sa.text("SELECT value FROM site_stats WHERE key='visitor_count'")
            ).fetchone()
            if row is None:
                conn.execute(sa.text(
                    "INSERT INTO site_stats (key, value) VALUES ('visitor_count', 1)"
                ))
                return 1
            else:
                count = row[0] + 1
                conn.execute(sa.text(
                    "UPDATE site_stats SET value=:v WHERE key='visitor_count'"
                ), {"v": count})
                return count
    except Exception as e:
        print(f"[visitor] DB error: {e}")   # logs only, never shown on page
        return 0


def get_visitor_count() -> int:
    if "visited" not in st.session_state:
        st.session_state["visited"] = True
        st.session_state["visitor_count"] = increment_and_get()
    return st.session_state.get("visitor_count", 0)


def render_visitor_counter():
    """Call this inside a `with st.sidebar:` block."""
    count = get_visitor_count()
    display = f"{count:04d}" if count > 0 else "----"
    st.markdown(
        f"<div style='text-align:center; padding:6px 0 10px; border-top:1px solid #1e2130; margin-top:4px;'>"
        f"<span style='color:#555; font-size:11px; letter-spacing:1.5px;'>👥 VISITORS</span><br>"
        f"<span style='color:#2979ff; font-weight:800; font-size:22px; letter-spacing:2px;'>"
        f"{display}</span></div>",
        unsafe_allow_html=True,
    )
