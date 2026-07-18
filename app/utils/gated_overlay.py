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
import re
from pathlib import Path

import streamlit as st


def _slug(s: str) -> str:
    """CSS-class-safe token. Container keys/cta_keys may contain spaces
    (e.g. cta_key derived from a page name like "Market Pulse") — Streamlit
    turns those into a literal 'st-key-...' class with a space in it, which
    silently breaks any compound CSS selector built from the raw string."""
    return re.sub(r"[^a-zA-Z0-9_-]", "-", s)


def render_gated_overlay(
    image_path: str,
    title: str,
    message: str,
    cta_label: str,
    cta_key: str,
    on_cta,
    animated: bool = False,
) -> bool:
    """Render the blurred-background paywall card. Returns True if an image
    was found and the overlay was rendered; False if the caller should fall
    back to a plain st.info/st.warning block instead.

    The image renders at its full natural aspect ratio (no cropping, no
    scrollbars) — the card and CTA button are positioned as percentages of
    the container so they stay correctly placed regardless of the image's
    actual rendered height at any viewport width.

    animated=True adds a slow CSS-only "Ken Burns" pan/zoom on the same
    static image plus a subtle diagonal shimmer sweep — no new image
    assets, no JS, no extra network requests, so it can't slow page load
    or add a DB/API call. Pure `transform`/`background-position` CSS
    animations are GPU-composited and supported identically in every
    evergreen browser (Chrome, Firefox, Safari, Edge — desktop and
    mobile) without vendor prefixes at this spec level. Opt-in per call
    site (default False) so it can be trialled on one page first.
    """
    path = Path(image_path)
    if not path.exists():
        return False

    b64 = base64.b64encode(path.read_bytes()).decode()
    slug = _slug(cta_key)

    _anim_css = ""
    _anim_class = ""
    if animated:
        _anim_class = " gated-anim"
        _anim_css = f"""
            div.st-key-gated_overlay_{slug} img.gated-bg-img.gated-anim {{
                animation: gated_kenburns_{slug} 22s ease-in-out infinite;
                will-change: transform;
                transform-origin: center center;
            }}
            @keyframes gated_kenburns_{slug} {{
                0%   {{ transform: scale(1.0); }}
                50%  {{ transform: scale(1.07) translate(-1%, -1%); }}
                100% {{ transform: scale(1.0); }}
            }}
            div.st-key-gated_overlay_{slug} .gated-shimmer {{
                position: absolute;
                inset: 0;
                background: linear-gradient(115deg,
                    transparent 35%, rgba(255,255,255,0.10) 48%,
                    rgba(255,255,255,0.10) 52%, transparent 65%);
                background-size: 250% 250%;
                animation: gated_shimmer_{slug} 7s linear infinite;
                pointer-events: none;
            }}
            @keyframes gated_shimmer_{slug} {{
                0%   {{ background-position: 200% 0%; }}
                100% {{ background-position: -50% 0%; }}
            }}
            /* Respect reduced-motion preference — freeze both animations */
            @media (prefers-reduced-motion: reduce) {{
                div.st-key-gated_overlay_{slug} img.gated-bg-img.gated-anim,
                div.st-key-gated_overlay_{slug} .gated-shimmer {{
                    animation: none;
                }}
            }}
        """

    with st.container(key=f"gated_overlay_{slug}"):
        st.markdown(
            f"""
            <style>
            div.st-key-gated_overlay_{slug} {{
                position: relative;
                border-radius: 12px;
                overflow: hidden;
                margin-bottom: 1rem;
                line-height: 0;
                /* Opt this element out of Chrome Android's "Force Dark" /
                   auto-dark-theme, which can mis-detect our chart screenshot
                   as UI chrome and desaturate/invert it to flat gray on
                   mobile — doesn't affect desktop rendering. */
                color-scheme: light;
            }}
            div.st-key-gated_overlay_{slug} img.gated-bg-img {{
                display: block;
                width: 100%;
                height: auto;
                filter: blur(0px) brightness(0.6) saturate(0.85);
                color-scheme: light;
            }}
            div.st-key-gated_overlay_{slug} .gated-scrim {{
                position: absolute;
                inset: 0;
                background: radial-gradient(ellipse at center, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0.15) 60%);
            }}
            {_anim_css}
            div.st-key-gated_overlay_{slug} .gated-card {{
                position: absolute;
                top: 40%;
                left: 50%;
                transform: translate(-50%, -50%);
                z-index: 1;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                width: 90%;
                text-align: center;
                line-height: normal;
            }}
            div.st-key-gated_overlay_{slug} .gated-lock {{
                font-size: 48px;
                margin-bottom: 10px;
            }}
            div.st-key-gated_overlay_{slug} .gated-title {{
                color: #fff;
                font-size: 22px;
                font-weight: 700;
                margin-bottom: 6px;
                text-shadow: 0 1px 4px rgba(0,0,0,0.8);
            }}
            div.st-key-gated_overlay_{slug} .gated-message {{
                color: #eee;
                font-size: 14px;
                max-width: 420px;
                text-shadow: 0 1px 4px rgba(0,0,0,0.8);
            }}
            div.st-key-gated_overlay_{slug} div[data-testid="stHorizontalBlock"] {{
                position: absolute;
                left: 50%;
                top: 56%;
                transform: translateX(-50%);
                width: 60%;
                min-width: 220px;
                z-index: 2;
            }}
            @media (max-width: 640px) {{
                div.st-key-gated_overlay_{slug} img.gated-bg-img {{
                    filter: blur(0px) brightness(0.8) saturate(0.9);
                }}
                div.st-key-gated_overlay_{slug} .gated-scrim {{
                    background: radial-gradient(ellipse at center, rgba(0,0,0,0.2) 0%, rgba(0,0,0,0.08) 60%);
                }}
                div.st-key-gated_overlay_{slug} .gated-card {{
                    top: 30%;
                    width: 96%;
                }}
                div.st-key-gated_overlay_{slug} .gated-message {{
                    font-size: 12px;
                }}
                div.st-key-gated_overlay_{slug} div[data-testid="stHorizontalBlock"] {{
                    top: 66%;
                    width: 82%;
                }}
            }}
            </style>
            <img class="gated-bg-img{_anim_class}" src="data:image/png;base64,{b64}" />
            {'<div class="gated-shimmer"></div>' if animated else ''}
            <div class="gated-scrim"></div>
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
