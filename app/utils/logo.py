"""Sidebar logo — uses st.sidebar.image for full-size display."""
import streamlit as st
from pathlib import Path

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"


def show_logo():
    if _LOGO_PATH.exists():
        st.sidebar.image(str(_LOGO_PATH), use_container_width=True)
