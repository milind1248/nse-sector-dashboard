"""Small decorative UI effects, shared across pages."""
import random

import streamlit as st


def render_rupee_rain(count: int = 45) -> None:
    """A brief ₹-symbol rain animation, pure CSS/HTML — no JS, no network
    calls, no images. Each span's own CSS animation (animation-fill-mode:
    forwards) ends invisible and off-screen after its duration, so nothing
    needs to be cleaned up. Note: st.markdown(unsafe_allow_html=True) does
    not execute injected <script> tags (only st.components.v1.html's iframe
    does) — don't add a setTimeout-based DOM removal here, it would silently
    never run.
    """
    spans = "".join(
        f'<span style="left:{random.uniform(0,100):.1f}%;'
        f'animation-delay:{random.uniform(0,2.5):.2f}s;'
        f'animation-duration:{random.uniform(5.0,7.0):.2f}s;'
        f'font-size:{random.randint(16,32)}px;">₹</span>'
        for _ in range(count)
    )
    st.markdown(
        f"""
        <style>
        #rupee-rain {{
            position: fixed; inset: 0; pointer-events: none;
            overflow: hidden; z-index: 9999;
        }}
        #rupee-rain span {{
            position: absolute; top: -10%; color: #2ecc71;
            opacity: 0.85; animation-name: rupee-fall;
            animation-timing-function: linear; animation-fill-mode: forwards;
            text-shadow: 0 0 6px rgba(46,204,113,0.6);
        }}
        @keyframes rupee-fall {{
            to {{ top: 110%; opacity: 0; }}
        }}
        </style>
        <div id="rupee-rain">{spans}</div>
        """,
        unsafe_allow_html=True,
    )
