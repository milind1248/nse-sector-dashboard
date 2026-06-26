"""
Contact page — sends via Web3Forms API (web3forms.com).
No SMTP credentials needed. Only requires a free Web3Forms access key.
Recipient email is stored in secrets, never shown in UI.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import requests
import re
from datetime import datetime

st.set_page_config(page_title="Contact | NSE Sector Analysis", page_icon="📧", layout="wide")

from app.utils.seo import inject_seo
inject_seo("Contact")

from app.utils.logo import show_logo
show_logo()


def _is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[\w\.\+\-]+@[\w\-]+\.[a-z]{2,}$", email.strip(), re.IGNORECASE))


def _send_via_web3forms(name: str, user_email: str, topic: str, message: str) -> tuple[bool, str]:
    """
    Send via Web3Forms API — no SMTP setup, no password.
    Requires only a free access key from https://web3forms.com
    """
    try:
        key = st.secrets["contact"]["web3forms_key"]
    except (KeyError, FileNotFoundError):
        # Fallback: try smtplib if secrets not set up
        return False, "not_configured"

    payload = {
        "access_key":  key,
        "subject":     f"[NSE Dashboard] {topic} — from {name}",
        "from_name":   "NSE Sector Analysis",
        "name":        name,
        "email":       user_email,
        "message":     f"Topic: {topic}\n\n{message}",
        "botcheck":    "",   # honeypot
    }
    try:
        r = requests.post("https://api.web3forms.com/submit",
                          json=payload, timeout=10)
        data = r.json()
        if data.get("success"):
            return True, ""
        return False, data.get("message", "Web3Forms returned an error.")
    except requests.Timeout:
        return False, "Request timed out. Please try again."
    except Exception as e:
        return False, str(e)


# ── Page ──────────────────────────────────────────────────────────────────────
st.title("📧 Contact Us")
st.markdown(
    "Have feedback, a data issue, or a feature request? Fill in the form and we'll get back to you."
)
st.markdown("---")

col_form, col_info = st.columns([3, 2], gap="large")

with col_form:
    st.subheader("Send a Message")

    with st.form("contact_form", clear_on_submit=True):
        name    = st.text_input("Your Name *",  placeholder="e.g. Rahul Sharma", max_chars=80)
        email   = st.text_input("Your Email *", placeholder="you@example.com", max_chars=120)
        topic   = st.selectbox("Topic *", [
            "General Feedback",
            "Data Issue / Incorrect Data",
            "Feature Request",
            "Bug Report",
            "Question about FII / FPI Data",
            "Other",
        ])
        message = st.text_area(
            "Message *",
            placeholder="Describe your question or feedback in detail...",
            height=180, max_chars=2000,
        )
        submitted = st.form_submit_button(
            "📨 Send Message", type="primary", use_container_width=True
        )

    if submitted:
        errors = []
        if not name.strip():
            errors.append("Name is required.")
        if not email.strip() or not _is_valid_email(email):
            errors.append("A valid email address is required.")
        if not message.strip() or len(message.strip()) < 10:
            errors.append("Message must be at least 10 characters.")

        if errors:
            for e in errors:
                st.error(f"⚠️ {e}")
        else:
            with st.spinner("Sending your message…"):
                ok, err = _send_via_web3forms(
                    name.strip(), email.strip(), topic, message.strip()
                )

            if ok:
                st.success(
                    f"✅ **Message sent!** Thank you **{name.split()[0]}**, "
                    f"we'll reply to **{email}** soon."
                )
                st.balloons()
            elif err == "not_configured":
                st.warning(
                    "⚙️ Contact form is not yet configured on this server. "
                    "The site owner has been notified."
                )
            else:
                st.error(f"❌ Could not send: {err}")

with col_info:
    st.subheader("About This Dashboard")
    st.markdown("""
**NSE Sector Analysis** is a free tool for Indian equity investors
who follow FII (Foreign Institutional Investor) sector flows.

---
**📊 What we track**
- Fortnightly FII/FPI sector investment (NSDL)
- Daily FII + DII buy/sell flow (NSE India)
- Nifty sector index prices (Yahoo Finance)
- 5+ years of historical sector data

---
**🗓️ Data Updates**
NSDL publishes on the **15th** and **last day** of each month.
Dashboard updates automatically on those dates.

---
**🔗 Data Sources**
- [NSDL FPI Data](https://www.fpi.nsdl.co.in)
- [NSE India](https://www.nseindia.com)
- [Yahoo Finance](https://finance.yahoo.com)

---
**⚡ Response Time**
Typically **1–2 business days**.
""")

    with st.expander("❓ Frequently Asked Questions"):
        st.markdown("""
**Q: How often is data updated?**
NSDL sector data updates on the 15th and last day of every month.
Daily FII/DII flow refreshes every hour during market hours.

**Q: Why is the latest fortnight missing?**
NSDL usually publishes 2–3 days after the period ends.
Click **🔄 Refresh** on Home on or after the 17th or 3rd.

**Q: Can I download the data?**
Yes — use the **📤 Export** page to download CSV files.

**Q: Is this free?**
Yes. Source data is from NSDL and NSE India (both public). This dashboard is free.
""")

# ── Setup guide (shown only in local dev when not configured) ─────────────────
with st.expander("⚙️ Admin: How to enable the contact form", expanded=False):
    st.markdown("""
**One-time setup using [Web3Forms](https://web3forms.com) — no credentials needed:**

1. Go to **[web3forms.com](https://web3forms.com)**
2. Enter your email address → click **Create Access Key**
3. Check your inbox and copy the **Access Key**
4. Add to `.streamlit/secrets.toml`:

```toml
[contact]
web3forms_key = "YOUR_ACCESS_KEY_HERE"
```

5. For Streamlit Cloud: **App Settings → Secrets** → paste the same.

That's it. Web3Forms routes form submissions to your email.
No SMTP, no password, no account required.
""")
