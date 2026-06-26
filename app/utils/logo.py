"""Sidebar logo — placed above navigation using st.logo() + CSS override for size."""
import streamlit as st
from pathlib import Path

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"

_LOGO_CSS = """
<style>
/* Force logo container to use full sidebar width */
[data-testid="stLogo"] {
    width: 100% !important;
    max-width: 100% !important;
    padding: 0 0 8px 0 !important;
}
[data-testid="stLogo"] img {
    width: 100% !important;
    height: auto !important;
    max-height: none !important;
    object-fit: contain !important;
}
</style>
"""

def show_logo():
    """Place logo at top of sidebar, full width."""
    if _LOGO_PATH.exists():
        st.logo(str(_LOGO_PATH), size="large")
        st.markdown(_LOGO_CSS, unsafe_allow_html=True)
