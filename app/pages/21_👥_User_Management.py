"""User, group & subscription management — payment tracking for monetization. Admin login required."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import date, datetime, timezone, timedelta
import calendar

import pandas as pd
import streamlit as st

st.set_page_config(page_title="User Management | Market Sector Analysis", layout="wide")
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.auth import require_admin, logout, session_remaining_minutes
require_admin()

from app.utils.access_control import GOVERNED_PAGES
from backend.storage import subscription_db as sdb

_IST = timezone(timedelta(hours=5, minutes=30))


def _to_ist(ts) -> str:
    if not ts:
        return "—"
    try:
        dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_IST).strftime("%d %b %Y %H:%M IST")
    except Exception:
        return str(ts)[:16] if ts else "—"


def _fmt_date(d) -> str:
    if not d:
        return "—"
    return d.strftime("%d %b %Y") if isinstance(d, date) else str(d)[:10]


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


# ── Header ────────────────────────────────────────────────────────────────────
h1, h2 = st.columns([5, 1])
with h1:
    st.title("👥 User Management")
with h2:
    st.write("")
    if st.button("🚪 Logout", width='stretch'):
        logout()
        st.rerun()

st.caption(
    f"Logged in · Session expires in **{session_remaining_minutes()} min** · "
    "Manage user groups, subscriptions, and payment history here. "
    "Data-pipeline operations stay on the Admin page."
)
st.markdown("---")

tab_users, tab_groups, tab_grant, tab_pending, tab_planreq, tab_payments = st.tabs([
    "👤 Users", "🏷️ Groups & Access", "💳 Grant Subscription",
    "📸 Pending Payments", "🔄 Plan Change Requests", "🧾 Payment History",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — USERS
# ══════════════════════════════════════════════════════════════════════════════
with tab_users:
    st.subheader("All Users")
    search = st.text_input("Search by email or name", key="user_search", placeholder="e.g. gmail.com")
    users = sdb.list_users(search or None)

    if not users:
        st.info("No users found.")
    else:
        groups = sdb.list_groups()
        group_names = [g["name"] for g in groups]

        rows = []
        for u in users:
            rows.append({
                "Email": u["email"],
                "Name": u["full_name"] or "—",
                "Group": u["subscription_tier"],
                "Status": u["subscription_status"],
                "Subscription Ends": _fmt_date(u["current_period_end"]),
                "Last Login": _to_ist(u["last_login_at"]),
                "Signed Up": _to_ist(u["created_at"]),
            })
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

        st.markdown("---")
        st.subheader("Manage a User")
        emails = {u["email"]: u for u in users}
        sel_email = st.selectbox("Select user", list(emails.keys()), key="mgmt_user_sel")
        sel = emails[sel_email]

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Current Group", sel["subscription_tier"])
        with c2:
            st.metric("Status", sel["subscription_status"])
        with c3:
            st.metric("Subscription Ends", _fmt_date(sel["current_period_end"]))

        ac1, ac2, ac3 = st.columns(3)
        with ac1:
            if sel["subscription_status"] == "suspended":
                if st.button("✅ Activate User", key="activate_btn", width='stretch'):
                    sdb.activate_user(sel["id"])
                    st.success(f"Activated {sel_email}.")
                    st.rerun()
            else:
                if st.button("🚫 Suspend User", key="suspend_btn", width='stretch'):
                    sdb.suspend_user(sel["id"])
                    st.warning(f"Suspended {sel_email}.")
                    st.rerun()
        with ac2:
            new_group = st.selectbox("Change group to", group_names,
                                     index=group_names.index(sel["subscription_tier"])
                                     if sel["subscription_tier"] in group_names else 0,
                                     key="override_group_sel")
        with ac3:
            st.write("")
            if st.button("Apply Group Override", key="override_btn", width='stretch'):
                sdb.set_user_group_override(sel["id"], new_group)
                st.cache_data.clear()
                st.success(f"{sel_email} moved to {new_group} (direct override, no subscription record).")
                st.rerun()

        with st.expander(f"Subscription history — {sel_email}"):
            subs = sdb.list_subscriptions(sel["id"])
            if subs:
                st.dataframe(pd.DataFrame([{
                    "Group": s["group_name"], "Start": _fmt_date(s["period_start"]),
                    "End": _fmt_date(s["period_end"]), "Status": s["status"],
                    "Created By": s["created_by"] or "—", "Notes": s["notes"] or "—",
                } for s in subs]), width='stretch', hide_index=True)
            else:
                st.caption("No subscription records yet.")

        with st.expander(f"Payment history — {sel_email}"):
            pays = sdb.list_payments(sel["id"])
            if pays:
                st.dataframe(pd.DataFrame([{
                    "Date": _fmt_date(p["payment_date"]), "Amount (₹)": p["amount_inr"],
                    "Reference": p["payment_ref"] or "—", "Verified By": p["verified_by"] or "—",
                    "Notes": p["notes"] or "—",
                } for p in pays]), width='stretch', hide_index=True)
            else:
                st.caption("No payment records yet.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — GROUPS & ACCESS
# ══════════════════════════════════════════════════════════════════════════════
with tab_groups:
    st.subheader("Groups & Page Access")
    st.caption("Control which pages each group can see. Home, Contact, and Disclaimer are always public.")

    all_page_names = [p["name"] for p in GOVERNED_PAGES]

    for g in sdb.list_groups():
        default_badge = " (default)" if g["is_default"] else ""
        with st.expander(f"{g['display_name']}{default_badge} — ₹{g['price_inr'] or 0}/month", expanded=False):
            current_pages = sdb.get_group_pages(g["name"])
            new_pages = st.multiselect(
                "Pages accessible to this group",
                options=all_page_names,
                default=[p for p in current_pages if p in all_page_names],
                key=f"pages_{g['name']}",
            )
            gc1, gc2 = st.columns([1, 1])
            with gc1:
                new_price = st.number_input("Monthly price (₹)", min_value=0.0,
                                            value=float(g["price_inr"] or 0), step=50.0,
                                            key=f"price_{g['name']}")
            with gc2:
                st.write("")
                if st.button("💾 Save Changes", key=f"save_{g['name']}", width='stretch'):
                    sdb.set_group_pages(g["name"], new_pages)
                    sdb.upsert_group(g["name"], g["display_name"], new_price,
                                     g["is_default"], g["sort_order"])
                    st.success(f"Saved {g['display_name']}.")
                    st.cache_data.clear()
                    st.rerun()

    st.markdown("---")
    st.subheader("Add a New Group")
    with st.form("new_group_form"):
        ngc1, ngc2, ngc3 = st.columns(3)
        with ngc1:
            new_name = st.text_input("Group key (lowercase, no spaces)", placeholder="e.g. diamond")
        with ngc2:
            new_display = st.text_input("Display name", placeholder="e.g. Diamond")
        with ngc3:
            new_price_val = st.number_input("Monthly price (₹)", min_value=0.0, step=50.0)
        submitted = st.form_submit_button("➕ Create Group", type="primary")
        if submitted:
            if not new_name.strip() or not new_display.strip():
                st.error("Group key and display name are required.")
            else:
                sdb.upsert_group(new_name.strip().lower(), new_display.strip(), new_price_val,
                                 is_default=False, sort_order=99)
                st.success(f"Created group '{new_display}'.")
                st.rerun()

    st.markdown("---")
    st.subheader("💳 UPI QR Code")
    st.caption("Shown to users on the Pricing page. Upload once, update anytime.")
    qc1, qc2 = st.columns([1, 2])
    with qc1:
        existing_qr = sdb.get_qr_code()
        if existing_qr:
            st.image(existing_qr[0], caption="Current QR code", width=200)
        else:
            st.info("No QR code uploaded yet.")
    with qc2:
        new_qr = st.file_uploader("Upload QR code image", type=["png", "jpg", "jpeg"], key="qr_upload")
        if st.button("💾 Save QR Code", key="save_qr_btn", disabled=new_qr is None):
            sdb.set_qr_code(new_qr.getvalue(), new_qr.type)
            st.success("QR code saved.")
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — GRANT SUBSCRIPTION (QR payment workflow)
# ══════════════════════════════════════════════════════════════════════════════
with tab_grant:
    st.subheader("Grant Subscription & Record Payment")
    st.caption(
        "Use this after verifying a QR-code payment: pick the user, the group, the coverage "
        "period, and the amount received — this grants access and logs the payment together."
    )

    _grant_flash = st.session_state.pop("_grant_flash", None)
    if _grant_flash:
        st.success(_grant_flash)

    all_users = sdb.list_users()
    if not all_users:
        st.info("No users have signed up yet.")
    else:
        user_emails = {u["email"]: u for u in all_users}
        group_names = [g["name"] for g in sdb.list_groups()]
        today = date.today()

        with st.form("grant_sub_form"):
            gsel_email = st.selectbox("User", list(user_emails.keys()), key="grant_user_sel")
            gsel_group = st.selectbox("Group", group_names, key="grant_group_sel")

            pc1, pc2 = st.columns(2)
            with pc1:
                st.markdown("**Coverage start**")
                sm1, sm2 = st.columns(2)
                start_month = sm1.selectbox("Month", list(range(1, 13)), index=today.month - 1,
                                            format_func=lambda m: calendar.month_abbr[m], key="start_month")
                start_year = sm2.number_input("Year", min_value=2024, max_value=2100,
                                              value=today.year, key="start_year")
            with pc2:
                st.markdown("**Coverage end**")
                em1, em2 = st.columns(2)
                end_month = em1.selectbox("Month", list(range(1, 13)), index=today.month - 1,
                                          format_func=lambda m: calendar.month_abbr[m], key="end_month")
                end_year = em2.number_input("Year", min_value=2024, max_value=2100,
                                            value=today.year, key="end_year")

            ac1, ac2 = st.columns(2)
            with ac1:
                amount = st.number_input("Amount received (₹)", min_value=0.0, step=50.0, key="grant_amount")
            with ac2:
                payment_date = st.date_input("Payment date", value=today, key="grant_pay_date")

            payment_ref = st.text_input("Payment reference (UPI txn ID, screenshot note, etc.)",
                                        key="grant_ref")
            notes = st.text_area("Notes (optional)", key="grant_notes", height=68)

            submitted = st.form_submit_button("✅ Grant Access & Record Payment", type="primary",
                                              width='stretch')

        if submitted:
            period_start = date(int(start_year), start_month, 1)
            period_end = _month_end(int(end_year), end_month)
            if period_end < period_start:
                st.error("Coverage end must be on or after coverage start.")
            else:
                user = user_emails[gsel_email]
                sub_id = sdb.create_subscription(
                    user["id"], gsel_group, period_start, period_end,
                    created_by="admin", notes=notes or None,
                )
                sdb.record_payment(
                    user["id"], sub_id, amount, payment_date,
                    payment_ref=payment_ref or None, verified_by="admin", notes=notes or None,
                )
                st.cache_data.clear()
                st.session_state["_grant_flash"] = (
                    f"Granted {gsel_group} to {gsel_email} for "
                    f"{_fmt_date(period_start)} → {_fmt_date(period_end)}, "
                    f"₹{amount:,.0f} recorded."
                )
                st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — PENDING PAYMENTS (screenshots submitted from the Pricing page)
# ══════════════════════════════════════════════════════════════════════════════
with tab_pending:
    st.subheader("Pending Payments")
    st.caption(
        "Users submit a plan + payment screenshot from the Pricing page. "
        "Review the screenshot and email, then Approve (grants the subscription) or Reject."
    )

    pending_flash = st.session_state.pop("_pending_flash", None)
    if pending_flash:
        st.success(pending_flash)

    pending_claims = sdb.list_pending_payments()
    if not pending_claims:
        st.info("No pending payment claims.")
    else:
        today = date.today()
        for claim in pending_claims:
            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                with c1:
                    shot = sdb.get_payment_screenshot(claim["id"])
                    if shot:
                        st.image(shot[0], caption="Payment screenshot", width=220)
                    else:
                        st.caption("No screenshot attached.")
                with c2:
                    st.markdown(f"**{claim['email']}**")
                    st.caption(
                        f"Requested: **{claim['requested_group'].title()}** · "
                        f"₹{claim['amount_inr']:,.0f} · Paid {_fmt_date(claim['payment_date'])} · "
                        f"Submitted {_to_ist(claim['created_at'])}"
                    )
                    if claim["payment_ref"]:
                        st.caption(f"Reference: {claim['payment_ref']}")
                    if claim["notes"]:
                        st.caption(f"Notes: {claim['notes']}")

                    pm1, pm2 = st.columns(2)
                    start_m = pm1.selectbox("Start month", list(range(1, 13)),
                                            index=today.month - 1,
                                            format_func=lambda m: calendar.month_abbr[m],
                                            key=f"pend_start_m_{claim['id']}")
                    start_y = pm2.number_input("Start year", min_value=2024, max_value=2100,
                                               value=today.year, key=f"pend_start_y_{claim['id']}")
                    em1, em2 = st.columns(2)
                    end_m = em1.selectbox("End month", list(range(1, 13)),
                                          index=today.month - 1,
                                          format_func=lambda m: calendar.month_abbr[m],
                                          key=f"pend_end_m_{claim['id']}")
                    end_y = em2.number_input("End year", min_value=2024, max_value=2100,
                                             value=today.year, key=f"pend_end_y_{claim['id']}")

                    ac1, ac2 = st.columns(2)
                    with ac1:
                        if st.button("✅ Approve", key=f"approve_{claim['id']}", width='stretch'):
                            p_start = date(int(start_y), start_m, 1)
                            p_end = _month_end(int(end_y), end_m)
                            if p_end < p_start:
                                st.error("End period must be on or after start period.")
                            else:
                                sdb.approve_payment(claim["id"], p_start, p_end, verified_by="admin")
                                st.cache_data.clear()
                                st.session_state["_pending_flash"] = (
                                    f"Approved {claim['requested_group']} for {claim['email']}."
                                )
                                st.rerun()
                    with ac2:
                        if st.button("🚫 Reject", key=f"reject_{claim['id']}", width='stretch'):
                            sdb.reject_payment(claim["id"], verified_by="admin",
                                               notes="Rejected from Pending Payments")
                            st.session_state["_pending_flash"] = f"Rejected claim from {claim['email']}."
                            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — PLAN CHANGE REQUESTS (self-service upgrade/downgrade from My Profile)
# ══════════════════════════════════════════════════════════════════════════════
with tab_planreq:
    st.subheader("Plan Change Requests")
    st.caption(
        "Users request an upgrade or downgrade from their My Profile page. "
        "Approve to grant the new plan for a period, or reject."
    )

    planreq_flash = st.session_state.pop("_planreq_flash", None)
    if planreq_flash:
        st.success(planreq_flash)

    plan_requests = sdb.list_pending_plan_requests()
    if not plan_requests:
        st.info("No pending plan change requests.")
    else:
        today = date.today()
        for req in plan_requests:
            with st.container(border=True):
                badge = "⬆️ Upgrade" if req["request_type"] == "upgrade" else "⬇️ Downgrade"
                st.markdown(f"**{req['email']}** · {badge}")
                st.caption(
                    f"{req['current_group'].title()} → **{req['requested_group'].title()}** · "
                    f"Requested {_to_ist(req['created_at'])}"
                )
                if req["notes"]:
                    st.caption(f"Notes: {req['notes']}")

                pm1, pm2 = st.columns(2)
                start_m = pm1.selectbox("Start month", list(range(1, 13)),
                                        index=today.month - 1,
                                        format_func=lambda m: calendar.month_abbr[m],
                                        key=f"preq_start_m_{req['id']}")
                start_y = pm2.number_input("Start year", min_value=2024, max_value=2100,
                                           value=today.year, key=f"preq_start_y_{req['id']}")
                em1, em2 = st.columns(2)
                end_m = em1.selectbox("End month", list(range(1, 13)),
                                      index=today.month - 1,
                                      format_func=lambda m: calendar.month_abbr[m],
                                      key=f"preq_end_m_{req['id']}")
                end_y = em2.number_input("End year", min_value=2024, max_value=2100,
                                         value=today.year, key=f"preq_end_y_{req['id']}")

                ac1, ac2 = st.columns(2)
                with ac1:
                    if st.button("✅ Approve", key=f"preq_approve_{req['id']}", width='stretch'):
                        p_start = date(int(start_y), start_m, 1)
                        p_end = _month_end(int(end_y), end_m)
                        if p_end < p_start:
                            st.error("End period must be on or after start period.")
                        else:
                            sdb.approve_plan_request(req["id"], p_start, p_end, verified_by="admin")
                            st.cache_data.clear()
                            st.session_state["_planreq_flash"] = (
                                f"Approved {req['requested_group']} for {req['email']}."
                            )
                            st.rerun()
                with ac2:
                    if st.button("🚫 Reject", key=f"preq_reject_{req['id']}", width='stretch'):
                        sdb.reject_plan_request(req["id"], verified_by="admin")
                        st.session_state["_planreq_flash"] = f"Rejected request from {req['email']}."
                        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — PAYMENT HISTORY
# ══════════════════════════════════════════════════════════════════════════════
with tab_payments:
    st.subheader("Payment History")
    all_payments = sdb.list_payments()

    if not all_payments:
        st.info("No payments recorded yet.")
    else:
        total = sum(p["amount_inr"] for p in all_payments)
        m1, m2 = st.columns(2)
        m1.metric("Total Payments", len(all_payments))
        m2.metric("Total Collected", f"₹{total:,.0f}")

        st.markdown("---")
        pf1, pf2 = st.columns(2)
        with pf1:
            filter_email = st.text_input("Filter by email", key="pay_filter_email")
        with pf2:
            filter_date_range = st.date_input(
                "Filter by date range", value=(), key="pay_filter_dates"
            )

        rows = all_payments
        if filter_email:
            rows = [p for p in rows if filter_email.lower() in p["email"].lower()]
        if isinstance(filter_date_range, tuple) and len(filter_date_range) == 2:
            d0, d1 = filter_date_range
            rows = [p for p in rows if d0 <= p["payment_date"] <= d1]

        st.dataframe(pd.DataFrame([{
            "Date": _fmt_date(p["payment_date"]), "Email": p["email"],
            "Amount (₹)": p["amount_inr"], "Status": p["status"],
            "Reference": p["payment_ref"] or "—",
            "Verified By": p["verified_by"] or "—", "Notes": p["notes"] or "—",
            "Recorded": _to_ist(p["created_at"]),
        } for p in rows]), width='stretch', hide_index=True)
