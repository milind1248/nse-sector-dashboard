"""StockEdge-style paywall overlay: a blurred static screenshot of a page's
real content, with a centered sign-in/upgrade card on top. Used by
app/utils/access_control.py::require_page_access() in place of a plain
st.info/st.warning line, when a static preview image exists for that page.

The image is a one-time-captured static asset (app/assets/page_previews/),
never generated live — this overlay never triggers a DB or Yahoo Finance
call, satisfying the "don't populate the page for a blocked visitor"
requirement.
"""
import base64
from pathlib import Path

import streamlit as st


def render_gated_overlay(
    image_path: str,
    title: str,
    message: str,
    cta_label: str,
    cta_key: str,
    on_cta,
) -> bool:
    """Render the blurred-background paywall card. Returns True if an image
    was found and the overlay was rendered; False if the caller should fall
    back to a plain st.info/st.warning block instead.
    """
    path = Path(image_path)
    if not path.exists():
        return False

    b64 = base64.b64encode(path.read_bytes()).decode()

    with st.container(key=f"gated_overlay_{cta_key}"):
        st.markdown(
            f"""
            <style>
            div.st-key-gated_overlay_{cta_key} {{
                position: relative;
                min-height: 420px;
                border-radius: 12px;
                overflow: hidden;
                margin-bottom: 1rem;
            }}
            div.st-key-gated_overlay_{cta_key} img.gated-bg-img {{
                position: absolute;
                inset: 0;
                width: 100%;
                height: 100%;
                object-fit: cover;
                object-position: top;
                filter: blur(8px) brightness(0.55);
                z-index: 0;
            }}
            div.st-key-gated_overlay_{cta_key} .gated-card {{
                position: relative;
                z-index: 1;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                height: 380px;
                text-align: center;
                padding: 24px;
            }}
            div.st-key-gated_overlay_{cta_key} .gated-lock {{
                font-size: 40px;
                margin-bottom: 8px;
            }}
            div.st-key-gated_overlay_{cta_key} .gated-title {{
                color: #fff;
                font-size: 22px;
                font-weight: 700;
                margin-bottom: 6px;
                text-shadow: 0 1px 4px rgba(0,0,0,0.6);
            }}
            div.st-key-gated_overlay_{cta_key} .gated-message {{
                color: #eee;
                font-size: 14px;
                max-width: 420px;
                margin-bottom: 18px;
                text-shadow: 0 1px 4px rgba(0,0,0,0.6);
            }}
            div.st-key-gated_overlay_{cta_key} div[data-testid="stHorizontalBlock"] {{
                position: relative;
                z-index: 2;
                margin-top: -64px;
            }}
            </style>
            <img class="gated-bg-img" src="data:image/png;base64,{b64}" />
            <div class="gated-card">
                <div class="gated-lock">🔒</div>
                <div class="gated-title">{title}</div>
                <div class="gated-message">{message}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _, mid, _ = st.columns([1, 1, 1])
        with mid:
            if st.button(cta_label, key=cta_key, width="stretch", type="primary"):
                on_cta()

    return True
