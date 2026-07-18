"""
Group-based page access control, layered on top of Supabase Auth
(app/utils/user_session.py) and the monetization tables in
scripts/supabase_schema.sql (auth_groups, group_page_access,
user_subscriptions, payment_history).

profiles.subscription_tier is the user's current group name;
profiles.subscription_status doubles as the suspend/activate flag.

Home, Contact, Disclaimer, and Pricing stay always-public by design — they're
not in GOVERNED_PAGES and never call require_page_access(). Pricing needs to
be visible to logged-out visitors so they can compare plans before signing up.
My Profile is also excluded — it's for any signed-in user regardless of tier,
gated by its own is_logged_in() check rather than a group page-list check.
"""
import streamlit as st

from backend.page_tester import PAGE_REGISTRY
from app.utils.gated_overlay import render_gated_overlay

_UNGOVERNED = {"Home", "Contact", "Disclaimer", "Pricing", "My Profile"}

GOVERNED_PAGES: list[dict] = [p for p in PAGE_REGISTRY if p["name"] not in _UNGOVERNED]

# Static blurred-preview screenshots for the paywall overlay. Only pages with
# an entry here get the StockEdge-style overlay; every other governed page
# keeps the plain st.info/st.warning block below. Images captured manually
# (see app/assets/page_previews/) and never regenerated live.
_PAGE_PREVIEWS: dict[str, str] = {
    "Market Pulse": "app/assets/page_previews/market_pulse.png",
    "Sector Analysis": "app/assets/page_previews/sector_analysis.png",
    "Index Stocks": "app/assets/page_previews/index_stocks.png",
    "FII DII Flow": "app/assets/page_previews/fii_dii_flow.png",
    "FII Sectors": "app/assets/page_previews/fii_sectors.png",
    "FPI Sectors": "app/assets/page_previews/fpi_sectors.png",
    "Stock Picker": "app/assets/page_previews/stock_picker.png",
    "Smart Money": "app/assets/page_previews/smart_money.png",
    "FII Accumulation": "app/assets/page_previews/fii_accumulation.png",
    "Bulk Deals": "app/assets/page_previews/bulk_deals.png",
    "Alerts": "app/assets/page_previews/alerts.png",
    "HM Scanner": "app/assets/page_previews/hm_scanner.png",
    "AI Forecast": "app/assets/page_previews/ai_forecast.png",
    "Gann Analysis": "app/assets/page_previews/gann_analysis.png",
    "Export": "app/assets/page_previews/export.png",
    "Paper Trading": "app/assets/page_previews/paper_trading.png",
}

# Pages using the CSS Ken-Burns pan/zoom + shimmer overlay (see
# gated_overlay.py's `animated` param) instead of a static image. Trialled
# on Market Pulse first and approved — now on every page with a preview.
_ANIMATED_PAGES = set(_PAGE_PREVIEWS.keys())


@st.cache_data(ttl=300, show_spinner=False)
def _cached_group_pages(group_name: str) -> list[str]:
    from backend.storage.subscription_db import get_group_pages
    return get_group_pages(group_name)


def require_page_access(page_key: str) -> None:
    """Call right after render_auth_sidebar() on any page listed in GOVERNED_PAGES."""
    from app.utils.user_session import is_logged_in, current_user

    if not is_logged_in():
        preview = _PAGE_PREVIEWS.get(page_key)
        if preview:
            def _open_signin():
                st.session_state["_show_auth_dialog"] = True
                st.rerun()
            render_gated_overlay(
                preview,
                f"Sign in to view {page_key}",
                "Create a free account or sign in to access this page.",
                "🔓 Sign In",
                f"_ov_signin_{page_key}",
                _open_signin,
                animated=page_key in _ANIMATED_PAGES,
            )
        else:
            st.info("🔒 Please sign in to view this page.")
            if st.button("🔓 Sign In", key=f"_access_signin_{page_key}"):
                st.session_state["_show_auth_dialog"] = True
                st.rerun()
        st.stop()

    from backend.storage.profiles_db import get_profile
    profile = get_profile(current_user()["id"])
    if profile is None:
        st.warning("Your profile could not be loaded. Please sign out and sign in again.")
        st.stop()

    if profile["subscription_status"] == "suspended":
        st.error("🚫 Your account access has been suspended. Contact the site admin for help.")
        st.stop()

    # Lazy self-heal: revert any user whose active subscription already lapsed,
    # in case the daily scheduler sweep hasn't run recently (Cloud sleeps idle apps).
    from backend.storage.subscription_db import expire_subscriptions
    try:
        expire_subscriptions()
    except Exception:
        pass
    profile = get_profile(current_user()["id"])

    group = profile["subscription_tier"]
    allowed = _cached_group_pages(group)
    if page_key not in allowed:
        preview = _PAGE_PREVIEWS.get(page_key)
        if preview:
            def _go_pricing():
                st.switch_page("pages/22_💎_Pricing.py")
            render_gated_overlay(
                preview,
                f"Upgrade to unlock {page_key}",
                f"This page isn't included in your {group.title()} plan — upgrade to access it.",
                "💎 View Plans",
                f"_ov_upgrade_{page_key}",
                _go_pricing,
                animated=page_key in _ANIMATED_PAGES,
            )
        else:
            st.warning(
                f"🔒 This page isn't included in your **{group.title()}** plan. "
                "Upgrade your subscription to unlock it, or contact the site admin."
            )
        st.stop()
