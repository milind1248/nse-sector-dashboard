"""
Group-based page access control, layered on top of Supabase Auth
(app/utils/user_session.py) and the monetization tables in
scripts/supabase_schema.sql (auth_groups, group_page_access,
user_subscriptions, payment_history).

profiles.subscription_tier is the user's current group name;
profiles.subscription_status doubles as the suspend/activate flag.

Home, Contact, and Disclaimer stay always-public by design — they're not in
GOVERNED_PAGES and never call require_page_access().
"""
import streamlit as st

from backend.page_tester import PAGE_REGISTRY

_UNGOVERNED = {"Home", "Contact", "Disclaimer"}

GOVERNED_PAGES: list[dict] = [p for p in PAGE_REGISTRY if p["name"] not in _UNGOVERNED]


@st.cache_data(ttl=300, show_spinner=False)
def _cached_group_pages(group_name: str) -> list[str]:
    from backend.storage.subscription_db import get_group_pages
    return get_group_pages(group_name)


def require_page_access(page_key: str) -> None:
    """Call right after render_auth_sidebar() on any page listed in GOVERNED_PAGES."""
    from app.utils.user_session import is_logged_in, current_user

    if not is_logged_in():
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
        st.warning(
            f"🔒 This page isn't included in your **{group.title()}** plan. "
            "Upgrade your subscription to unlock it, or contact the site admin."
        )
        st.stop()
