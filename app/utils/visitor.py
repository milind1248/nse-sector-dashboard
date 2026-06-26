"""Visitor counter — increments on every page load, stored in SQLite."""
import streamlit as st
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _get_db():
    from backend.storage.database import get_engine
    from sqlalchemy.orm import Session
    return get_engine(), Session


def increment_and_get() -> int:
    """Increment visitor count and return new value. Creates table row if missing."""
    try:
        from backend.storage.database import get_engine
        from backend.storage.models import Base, SiteStats
        from sqlalchemy.orm import Session

        engine = get_engine()
        Base.metadata.create_all(engine)   # creates site_stats table if not exists

        with Session(engine) as s:
            row = s.get(SiteStats, "visitor_count")
            if row is None:
                row = SiteStats(key="visitor_count", value=1)
                s.add(row)
            else:
                row.value += 1
            s.commit()
            return row.value
    except Exception:
        return 0


def show_visitor_counter():
    """Increment count and display in sidebar."""
    # Only count once per browser session, not on every Streamlit rerun
    if "visited" not in st.session_state:
        st.session_state["visited"] = True
        count = increment_and_get()
        st.session_state["visitor_count"] = count
    else:
        count = st.session_state.get("visitor_count", 0)

    if count > 0:
        st.sidebar.markdown(
            f"<div style='text-align:center; color:#555; font-size:11px; "
            f"padding:4px 0 8px; letter-spacing:1px;'>"
            f"👥 VISITORS &nbsp; "
            f"<span style='color:#2979ff; font-weight:700; font-size:13px;'>"
            f"{count:04d}</span></div>",
            unsafe_allow_html=True,
        )
