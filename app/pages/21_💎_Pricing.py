"""Pricing page — plan comparison + UPI QR payment claim submission. Publicly viewable."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from datetime import date

import streamlit as st

st.set_page_config(page_title="Pricing | Market Sector Analysis", page_icon="💎", layout="wide")
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.seo import inject_seo
inject_seo("Pricing")

from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.user_session import is_logged_in, current_user
from backend.storage import subscription_db as sdb

st.title("💎 Pricing")
st.caption("Compare plans and the pages each one unlocks. Pay via UPI, then share your payment "
           "screenshot below — we'll review it and activate your plan.")

_flash = st.session_state.pop("_pricing_flash", None)
if _flash:
    st.success(_flash)

groups = sdb.list_groups()

# ── Current plan badge (logged-in visitors only) ───────────────────────────────
current_group = None
if is_logged_in():
    from backend.storage.profiles_db import get_profile
    profile = get_profile(current_user()["id"])
    if profile:
        current_group = profile["subscription_tier"]
        st.info(f"👤 Your current plan: **{current_group.title()}**")

st.markdown("---")

# ── Plan comparison ──────────────────────────────────────────────────────────
cols = st.columns(len(groups))
for col, g in zip(cols, groups):
    with col:
        is_current = current_group == g["name"]
        badge = " ✅ (Current)" if is_current else ""
        st.subheader(f"{g['display_name']}{badge}")
        price = g["price_inr"] or 0
        st.markdown(f"### ₹{price:,.0f}/month" if price else "### Free")
        pages = sdb.get_group_pages(g["name"])
        if pages:
            for p in pages:
                st.markdown(f"✅ {p}")
        else:
            st.caption("No pages configured yet.")

st.markdown("---")

# ── Payment section ──────────────────────────────────────────────────────────
st.subheader("Subscribe")

if not is_logged_in():
    st.info("🔒 Please sign in to subscribe to a plan.")
    if st.button("🔓 Sign In", key="_pricing_signin"):
        st.session_state["_show_auth_dialog"] = True
        st.rerun()
    st.stop()

pending = sdb.get_pending_claim(current_user()["id"])
if pending:
    st.warning(
        f"Your **{pending['requested_group'].title()}** request submitted on "
        f"{pending['payment_date'].strftime('%d %b %Y')} is awaiting review. "
        "You'll see your plan update here once it's approved."
    )
else:
    qr = sdb.get_qr_code()
    qc1, qc2 = st.columns([1, 2])
    with qc1:
        if qr:
            if st.session_state.get("_qr_revealed"):
                st.image(qr[0], caption="Scan to pay via UPI", width=240)
            else:
                import base64
                b64 = base64.b64encode(qr[0]).decode()
                st.markdown(
                    f'<img src="data:{qr[1]};base64,{b64}" width="240" '
                    f'style="filter: blur(10px); border-radius: 8px;" />',
                    unsafe_allow_html=True,
                )
                st.caption("QR code hidden — tap to reveal")
                if st.button("👁 Show QR Code", key="_qr_reveal_btn", type="primary", width='stretch'):
                    st.session_state["_qr_revealed"] = True
                    st.rerun()
        else:
            st.info("QR code not yet configured — contact the site admin for payment details.")
    with qc2:
        st.markdown(
            "**How to subscribe:**\n"
            "1. Scan the QR code and pay via any UPI app.\n"
            "2. Take a screenshot of the successful payment.\n"
            "3. Fill in the form and upload the screenshot below.\n"
            "4. We'll verify it and activate your plan — usually within a day."
        )

    other_groups = [g["name"] for g in groups if g["name"] != current_group]
    if not other_groups:
        st.info("You're already on the top plan.")
    else:
        with st.form("pricing_claim_form"):
            plan = st.selectbox("Plan", other_groups, key="pricing_plan_sel")
            amount = st.number_input("Amount paid (₹)", min_value=0.0, step=50.0, key="pricing_amount")
            pay_date = st.date_input("Payment date", value=date.today(), key="pricing_pay_date")
            payment_ref = st.text_input("Payment reference (UPI txn ID, optional)", key="pricing_ref")
            screenshot = st.file_uploader("Payment screenshot", type=["png", "jpg", "jpeg"],
                                          key="pricing_screenshot")
            notes = st.text_area("Notes (optional)", key="pricing_notes", height=68)
            submitted = st.form_submit_button("✅ Submit Payment Claim", type="primary", width='stretch')

        if submitted:
            if screenshot is None:
                st.error("Please upload a payment screenshot.")
            else:
                sdb.submit_payment_claim(
                    current_user()["id"], plan, amount, pay_date,
                    payment_ref or None, screenshot.getvalue(), screenshot.type,
                    notes=notes or None,
                )
                st.session_state["_pricing_flash"] = (
                    "Submitted — the admin will review your payment and activate your plan shortly."
                )
                st.rerun()

st.markdown("---")
from app.utils.disclaimer import show_footer
show_footer()
