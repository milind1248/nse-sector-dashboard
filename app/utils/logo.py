"""Sidebar logo — st.logo() at top + CSS to increase its height."""
import streamlit as st
from pathlib import Path

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"


def show_logo():
    if _LOGO_PATH.exists():
        st.logo(str(_LOGO_PATH), size="large")
        # Override Streamlit's hard-coded logo height cap
        st.markdown(
            """<style>
            [data-testid="stLogo"] {
                height: 72px !important;
                max-height: 72px !important;
                width: auto !important;
            }
            [data-testid="stLogo"] img {
                height: 72px !important;
                max-height: 72px !important;
                width: auto !important;
                object-fit: contain;
            }
            </style>""",
            unsafe_allow_html=True,
        )
