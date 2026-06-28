import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

st.set_page_config(
    page_title="Disclaimer | Market Sector Analysis",
    page_icon="⚖️", layout="wide",
)
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.logo import show_logo
show_logo()

from app.utils.disclaimer import show_full_disclaimer
show_full_disclaimer()
from app.utils.disclaimer import show_footer
show_footer()
