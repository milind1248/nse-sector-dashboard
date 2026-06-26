"""Visitor counter — uses sqlite3 directly (bypasses SQLAlchemy pool read-only issues)."""
import sqlite3
import streamlit as st
from pathlib import Path

_DB = Path(__file__).resolve().parent.parent.parent / "data" / "nse_dashboard.db"


def increment_and_get() -> int:
    try:
        con = sqlite3.connect(str(_DB), timeout=5)
        con.execute(
            "CREATE TABLE IF NOT EXISTS site_stats "
            "(key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0)"
        )
        row = con.execute(
            "SELECT value FROM site_stats WHERE key='visitor_count'"
        ).fetchone()
        if row is None:
            con.execute("INSERT INTO site_stats VALUES ('visitor_count', 1)")
            count = 1
        else:
            count = row[0] + 1
            con.execute(
                "UPDATE site_stats SET value=? WHERE key='visitor_count'", (count,)
            )
        con.commit()
        con.close()
        return count
    except Exception as e:
        print(f"[visitor] {e}")
        return 0


def get_visitor_count() -> int:
    if "visited" not in st.session_state:
        st.session_state["visited"] = True
        st.session_state["visitor_count"] = increment_and_get()
    return st.session_state.get("visitor_count", 0)


def render_visitor_counter():
    """Call inside a `with st.sidebar:` block."""
    count = get_visitor_count()
    display = f"{count:04d}" if count > 0 else "----"
    st.markdown(
        f"<div style='text-align:center;padding:6px 0 10px;border-top:1px solid #1e2130;margin-top:4px;'>"
        f"<span style='color:#555;font-size:11px;letter-spacing:1.5px;'>👥 VISITORS</span><br>"
        f"<span style='color:#2979ff;font-weight:800;font-size:22px;letter-spacing:2px;'>{display}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
