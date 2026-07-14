"""My Profile — account, contact details, password, subscription & payment history."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st

st.set_page_config(page_title="My Profile | Market Sector Analysis", page_icon="👤", layout="wide")
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.seo import inject_seo
inject_seo("My Profile")

from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.user_session import (
    is_logged_in, current_user, change_password, change_email, _TIER_ICONS, _TIER_ICON_FALLBACK,
)
from backend.storage.profiles_db import get_profile, update_profile
from backend.storage.subscription_db import list_subscriptions, list_payments

st.title("👤 My Profile")

if not is_logged_in():
    st.info("🔒 Please sign in to view your profile.")
    if st.button("🔓 Sign In", key="_profile_signin"):
        st.session_state["_show_auth_dialog"] = True
        st.rerun()
    st.stop()

_flash = st.session_state.pop("_profile_flash", None)
if _flash:
    kind, msg = _flash
    (st.error if kind == "error" else st.success)(msg)

user_id = current_user()["id"]
profile = get_profile(user_id)
if profile is None:
    st.warning("Your profile could not be loaded. Please sign out and sign in again.")
    st.stop()

tier = profile["subscription_tier"]
icon = _TIER_ICONS.get(tier, _TIER_ICON_FALLBACK)
st.caption(f"{icon} Current plan: **{tier.title()}** · Status: **{profile['subscription_status'].title()}**")
st.markdown("---")

# ── Account ──────────────────────────────────────────────────────────────────
st.subheader("Account")
st.write(f"**Email:** {profile['email']}")

with st.expander("Change email"):
    with st.form("change_email_form"):
        new_email = st.text_input("New email", key="pf_new_email")
        submitted = st.form_submit_button("Update Email", type="primary")
    if submitted:
        if not new_email or "@" not in new_email:
            st.error("Enter a valid email address.")
        else:
            ok, msg = change_email(new_email)
            st.session_state["_profile_flash"] = ("success" if ok else "error", msg)
            st.rerun()

st.markdown("---")

# ── Profile & contact details ───────────────────────────────────────────────
st.subheader("Profile & Contact Details")
with st.form("profile_form"):
    c1, c2 = st.columns(2)
    with c1:
        display_name = st.text_input("Display name", value=profile["full_name"] or "", key="pf_name")
        phone = st.text_input("Phone", value=profile["phone"] or "", key="pf_phone")
    with c2:
        alt_email = st.text_input("Alternate email", value=profile["alt_email"] or "", key="pf_alt_email")
    address = st.text_area("Address", value=profile["address"] or "", key="pf_address", height=80)
    submitted = st.form_submit_button("💾 Save Profile", type="primary")
if submitted:
    update_profile(user_id, display_name or None, phone or None, alt_email or None, address or None)
    st.session_state["_profile_flash"] = ("success", "Profile updated.")
    st.rerun()

if profile["auth_provider"] == "google":
    st.caption(
        "Signed in with Google — if you sign in with Google again, your display name "
        "will sync back to your Google profile name."
    )

st.markdown("---")

# ── Password ─────────────────────────────────────────────────────────────────
st.subheader("Password")
if profile["auth_provider"] == "google":
    st.info("Signed in with Google — manage your password through your Google account.")
else:
    with st.form("change_password_form"):
        pw1 = st.text_input("New password", type="password", key="pf_pw1", help="At least 6 characters.")
        pw2 = st.text_input("Confirm new password", type="password", key="pf_pw2")
        submitted = st.form_submit_button("Change Password", type="primary")
    if submitted:
        if not pw1 or len(pw1) < 6:
            st.error("Password must be at least 6 characters.")
        elif pw1 != pw2:
            st.error("Passwords do not match.")
        else:
            ok, msg = change_password(pw1)
            st.session_state["_profile_flash"] = ("success" if ok else "error", msg)
            st.rerun()

st.markdown("---")

# ── Subscription ─────────────────────────────────────────────────────────────
st.subheader("Subscription")
subs = list_subscriptions(user_id)
if subs:
    st.dataframe(pd.DataFrame([{
        "Group": s["group_name"].title(),
        "Start": s["period_start"].strftime("%d %b %Y") if s["period_start"] else "—",
        "End": s["period_end"].strftime("%d %b %Y") if s["period_end"] else "—",
        "Status": s["status"].title(),
    } for s in subs]), width='stretch', hide_index=True)
else:
    st.caption("No subscription history yet.")

st.markdown("---")

# ── Payment History ──────────────────────────────────────────────────────────
st.subheader("Payment History")
payments = list_payments(user_id)
if payments:
    st.dataframe(pd.DataFrame([{
        "Date": p["payment_date"].strftime("%d %b %Y") if p["payment_date"] else "—",
        "Amount (₹)": p["amount_inr"],
        "Status": p["status"].title(),
        "Reference": p["payment_ref"] or "—",
    } for p in payments]), width='stretch', hide_index=True)
else:
    st.caption("No payments recorded yet.")
