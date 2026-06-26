"""Sidebar logo — placed above navigation using st.logo()."""
import streamlit as st
from pathlib import Path

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"


def show_logo():
    """Place logo at the very top of sidebar, above page navigation."""
    if _LOGO_PATH.exists():
        st.logo(str(_LOGO_PATH), size="large")
