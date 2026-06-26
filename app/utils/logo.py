"""Sidebar logo — st.logo() + aggressive CSS to override Streamlit's fixed size cap."""
import streamlit as st
from pathlib import Path

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"

_LOGO_CSS = """
<style>
/* Expand the sidebar header section that holds the logo */
[data-testid="stSidebarHeader"] {
    height: 130px !important;
    min-height: 130px !important;
    padding: 12px 12px 8px 12px !important;
    display: flex !important;
    align-items: center !important;
}
/* Force the logo element itself to fill that space */
[data-testid="stLogo"] {
    width: 100% !important;
    height: 106px !important;
    max-height: none !important;
}
[data-testid="stLogo"] img {
    width: 100% !important;
    height: 106px !important;
    max-height: none !important;
    object-fit: contain !important;
    object-position: left center !important;
}
</style>
"""

def show_logo():
    if _LOGO_PATH.exists():
        st.logo(str(_LOGO_PATH), size="large")
        st.markdown(_LOGO_CSS, unsafe_allow_html=True)
