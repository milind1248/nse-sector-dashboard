"""Contact page — sends email via Gmail SMTP. Recipient is never shown in UI."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

st.set_page_config(page_title="Contact | NSE Sector Analysis", page_icon="📧", layout="wide")

from app.utils.seo import inject_seo
inject_seo("Contact")

from app.utils.logo import show_logo
show_logo()


def _is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[\w\.\+\-]+@[\w\-]+\.[a-z]{2,}$", email.strip(), re.IGNORECASE))


def _send_email(name: str, sender_email: str, topic: str, message: str) -> tuple[bool, str]:
    """Send contact form email via Gmail SMTP. Returns (success, error_msg)."""
    try:
        cfg = st.secrets["contact"]
    except (KeyError, FileNotFoundError):
        return False, "Email service not configured. Please set up Streamlit secrets."

    try:
        subject = f"[NSE Dashboard] {topic} — from {name}"
        body = f"""
New contact form submission from NSE Sector Analysis Dashboard.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Name    : {name}
Email   : {sender_email}
Topic   : {topic}
Time    : {datetime.now().strftime('%d %b %Y %H:%M IST')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Message:
{message}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Reply directly to this email to respond to {name}.
"""
        msg = MIMEMultipart()
        msg["From"]    = cfg["sender_email"]
        msg["To"]      = cfg["recipient"]        # never exposed in UI
        msg["Subject"] = subject
        msg["Reply-To"] = sender_email           # reply goes directly to user
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(cfg["smtp_server"], int(cfg["smtp_port"])) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(cfg["sender_email"], cfg["sender_pass"])
            srv.sendmail(cfg["sender_email"], cfg["recipient"], msg.as_string())

        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP authentication failed. Check sender credentials in secrets."
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"


# ── Page ──────────────────────────────────────────────────────────────────────
st.title("📧 Contact Us")
st.markdown(
    "Have feedback, questions, or found a data issue? We'd love to hear from you. "
    "Fill in the form below and we'll get back to you."
)
st.markdown("---")

col_form, col_info = st.columns([3, 2], gap="large")

with col_form:
    st.subheader("Send a Message")

    with st.form("contact_form", clear_on_submit=True):
        name  = st.text_input("Your Name *", placeholder="e.g. Rahul Sharma", max_chars=80)
        email = st.text_input("Your Email *", placeholder="you@example.com", max_chars=120)
        topic = st.selectbox("Topic *", [
            "General Feedback",
            "Data Issue / Incorrect Data",
            "Feature Request",
            "Bug Report",
            "Question about FII / FPI Data",
            "Other",
        ])
        message = st.text_area(
            "Message *",
            placeholder="Describe your feedback, question or issue in detail...",
            height=180, max_chars=2000,
        )
        submitted = st.form_submit_button("📨 Send Message", type="primary", use_container_width=True)

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
                ok, err = _send_email(name.strip(), email.strip(), topic, message.strip())

            if ok:
                st.success(
                    f"✅ **Message sent successfully!** \n\n"
                    f"Thank you **{name.split()[0]}**, we've received your message and will "
                    f"reply to **{email}** soon."
                )
                st.balloons()
            else:
                st.error(f"❌ Failed to send message. {err}")
                st.info("💡 You can also reach us at the details shown on the right.")

with col_info:
    st.subheader("About This Dashboard")
    st.markdown("""
**NSE Sector Analysis** is a free, open-source tool built for Indian equity investors who follow
FII (Foreign Institutional Investor) flows to make better investment decisions.

---

**📊 What we track**
- Fortnightly FII/FPI sector investment (NSDL data)
- Daily FII + DII buy/sell flow (NSE India)
- Nifty sector index prices (Yahoo Finance)
- 5+ years of historical sector data

---

**🗓️ Data Updates**
NSDL publishes fortnightly data on the **15th** and **last day** of each month.
The dashboard updates automatically on those dates.

---

**🔗 Data Sources**
- [NSDL FPI Data](https://www.fpi.nsdl.co.in)
- [NSE India](https://www.nseindia.com)
- [Yahoo Finance](https://finance.yahoo.com)

---

**⚡ Response Time**
We typically respond within **1–2 business days**.
""")

    # FAQ expander
    with st.expander("❓ Frequently Asked Questions"):
        st.markdown("""
**Q: How often is the data updated?**
A: NSDL sector data is updated on the 15th and last day of each month. Daily FII/DII flow updates every hour during market hours.

**Q: Why is the latest fortnight missing?**
A: NSDL usually publishes data 2–3 days after the period ends. Click **🔄 Refresh** on the Home page on or after the 17th or 3rd of each month.

**Q: Can I download the data?**
A: Yes — use the **📤 Export** page to download CSV files.

**Q: Is this data free to use?**
A: Yes. Source data is from NSDL (public) and NSE India (public). This dashboard is free.
""")
