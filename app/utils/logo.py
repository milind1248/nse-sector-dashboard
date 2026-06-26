"""Sidebar logo using st.logo() — no CSS height hacks."""
import streamlit as st
from pathlib import Path

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"


def show_logo():
    if _LOGO_PATH.exists():
        st.logo(str(_LOGO_PATH), size="large")
