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
        from backend.storage.models import Base, SiteStats
        from sqlalchemy.orm import Session

        engine = get_engine()
        Base.metadata.create_all(engine)

        with Session(engine) as s:
            row = s.get(SiteStats, "visitor_count")
            if row is None:
                row = SiteStats(key="visitor_count", value=1)
                s.add(row)
            else:
                row.value += 1
            s.commit()
            s.refresh(row)
            return row.value
    except Exception as e:
        return 0


def get_visitor_count() -> int:
    """Get current count without incrementing."""
    if "visited" not in st.session_state:
        st.session_state["visited"] = True
        count = increment_and_get()
        st.session_state["visitor_count"] = count
    return st.session_state.get("visitor_count", 0)


def render_visitor_counter():
    """Call this INSIDE a `with st.sidebar:` block."""
    count = get_visitor_count()
    if count > 0:
        st.markdown(
            f"<div style='text-align:center; padding:6px 0 10px; border-top:1px solid #1e2130; margin-top:4px;'>"
            f"<span style='color:#555; font-size:11px; letter-spacing:1.5px;'>👥 VISITORS</span><br>"
            f"<span style='color:#2979ff; font-weight:800; font-size:22px; letter-spacing:2px;'>"
            f"{count:04d}</span></div>",
            unsafe_allow_html=True,
        )
