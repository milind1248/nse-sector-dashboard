"""Sidebar logo rendered as inline SVG."""
import streamlit as st

LOGO_SVG = """
<div style="padding: 6px 0 10px 0;">
<svg viewBox="0 0 220 64" xmlns="http://www.w3.org/2000/svg" width="100%">

  <!-- Background pill -->
  <rect x="0" y="0" width="220" height="64" rx="10" fill="#0e1117"/>

  <!-- Chart bars (stylised FII flow) -->
  <rect x="10" y="28" width="8" height="26" rx="2" fill="#2979FF" opacity="0.9"/>
  <rect x="21" y="18" width="8" height="36" rx="2" fill="#2979FF"/>
  <rect x="32" y="34" width="8" height="20" rx="2" fill="#D50000" opacity="0.85"/>
  <rect x="43" y="22" width="8" height="32" rx="2" fill="#00C853"/>
  <rect x="54" y="30" width="8" height="24" rx="2" fill="#00C853" opacity="0.8"/>

  <!-- Trend line over bars -->
  <polyline points="14,32 25,22 36,38 47,26 58,30"
            fill="none" stroke="#FFD600" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round"/>

  <!-- Circle dots on line -->
  <circle cx="14" cy="32" r="2.5" fill="#FFD600"/>
  <circle cx="25" cy="22" r="2.5" fill="#FFD600"/>
  <circle cx="36" cy="38" r="2.5" fill="#FFD600"/>
  <circle cx="47" cy="26" r="2.5" fill="#FFD600"/>
  <circle cx="58" cy="30" r="2.5" fill="#FFD600"/>

  <!-- Vertical divider -->
  <line x1="73" y1="10" x2="73" y2="54" stroke="#2a2d35" stroke-width="1"/>

  <!-- Text: NSE -->
  <text x="80" y="28" font-family="'Segoe UI',sans-serif" font-size="18"
        font-weight="800" fill="#ffffff" letter-spacing="1">NSE</text>

  <!-- Text: Sector -->
  <text x="80" y="44" font-family="'Segoe UI',sans-serif" font-size="11"
        font-weight="600" fill="#2979FF" letter-spacing="2">SECTOR</text>

  <!-- Text: Analysis -->
  <text x="80" y="57" font-family="'Segoe UI',sans-serif" font-size="9"
        font-weight="400" fill="#888888" letter-spacing="1.5">ANALYSIS</text>

  <!-- FII tag pill -->
  <rect x="152" y="20" width="58" height="18" rx="9" fill="#2979FF" opacity="0.15"/>
  <text x="181" y="33" font-family="'Segoe UI',sans-serif" font-size="9"
        font-weight="700" fill="#2979FF" text-anchor="middle" letter-spacing="1">FII FLOW</text>

</svg>
</div>
"""

def show_logo():
    """Render the sidebar logo."""
    st.sidebar.markdown(LOGO_SVG, unsafe_allow_html=True)
