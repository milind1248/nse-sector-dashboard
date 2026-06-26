"""
Contact page — Web3Forms submitted client-side via browser fetch() (free plan compatible).
Access key is a routing key, not a security credential.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Contact | NSE Sector Analysis", page_icon="📧", layout="wide")

from app.utils.seo import inject_seo
inject_seo("Contact")

from app.utils.logo import show_logo
show_logo()

# Access key — not a password, just a routing token (safe to embed in browser HTML)
try:
    _KEY = st.secrets["contact"]["web3forms_key"]
except Exception:
    _KEY = "6be66989-c986-4010-b28a-0a277fe52ba5"

# ── Page header ───────────────────────────────────────────────────────────────
st.title("📧 Contact Us")
st.markdown("Have feedback, a data issue, or a feature request? Fill in the form and we'll get back to you.")
st.markdown("---")

col_form, col_info = st.columns([3, 2], gap="large")

with col_form:
    st.subheader("Send a Message")

    FORM_HTML = f"""
<style>
  body {{ margin:0; padding:0; background:transparent; font-family:'Source Sans Pro',sans-serif; color:#fafafa; }}
  .cf-wrap {{ max-width:560px; }}
  .cf-wrap label {{ display:block; font-size:13px; color:#aaa; margin:14px 0 4px; }}
  .cf-wrap input, .cf-wrap select, .cf-wrap textarea {{
    width:100%; box-sizing:border-box;
    background:#1e2130; border:1px solid #3a3d4a; border-radius:6px;
    color:#fafafa; font-size:14px; padding:9px 12px;
    outline:none; transition:border .2s;
  }}
  .cf-wrap input:focus, .cf-wrap select:focus, .cf-wrap textarea:focus {{
    border-color:#2979ff;
  }}
  .cf-wrap select option {{ background:#1e2130; }}
  .cf-wrap textarea {{ resize:vertical; min-height:130px; }}
  .cf-btn {{
    margin-top:18px; width:100%; padding:11px;
    background:#2979ff; color:#fff; border:none; border-radius:6px;
    font-size:15px; font-weight:600; cursor:pointer; transition:background .2s;
  }}
  .cf-btn:hover {{ background:#1565c0; }}
  .cf-btn:disabled {{ background:#444; cursor:not-allowed; }}
  #cf-msg {{ margin-top:14px; padding:12px 16px; border-radius:6px; font-size:14px; display:none; }}
  .cf-ok  {{ background:#0a3320; border:1px solid #00C853; color:#00e676; }}
  .cf-err {{ background:#3e0808; border:1px solid #D50000; color:#ff5252; }}
</style>

<div class="cf-wrap">
  <form id="cf" onsubmit="sendForm(event)">
    <input type="hidden" name="access_key" value="{_KEY}">
    <input type="hidden" name="subject"    value="[NSE Dashboard] Contact Form Message">
    <input type="hidden" name="from_name"  value="NSE Sector Analysis">
    <input type="hidden" name="botcheck"   value="">

    <label>Your Name *</label>
    <input type="text" name="name" placeholder="e.g. Rahul Sharma" required maxlength="80">

    <label>Your Email *</label>
    <input type="email" name="email" placeholder="you@example.com" required maxlength="120">

    <label>Topic *</label>
    <select name="topic">
      <option>General Feedback</option>
      <option>Data Issue / Incorrect Data</option>
      <option>Feature Request</option>
      <option>Bug Report</option>
      <option>Question about FII / FPI Data</option>
      <option>Other</option>
    </select>

    <label>Message *</label>
    <textarea name="message" placeholder="Describe your question or feedback..." required minlength="10" maxlength="2000"></textarea>

    <button class="cf-btn" type="submit" id="cf-btn">📨 Send Message</button>
    <div id="cf-msg"></div>
  </form>
</div>

<script>
async function sendForm(e) {{
  e.preventDefault();
  const btn = document.getElementById('cf-btn');
  const msg = document.getElementById('cf-msg');
  btn.disabled = true;
  btn.textContent = 'Sending…';
  msg.style.display = 'none';

  const data = Object.fromEntries(new FormData(e.target));

  try {{
    const res  = await fetch('https://api.web3forms.com/submit', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json', 'Accept': 'application/json'}},
      body: JSON.stringify(data),
    }});
    const json = await res.json();
    if (json.success) {{
      msg.className = 'cf-ok';
      msg.textContent = '✅ Message sent! We will reply to ' + data.email + ' soon.';
      e.target.reset();
    }} else {{
      throw new Error(json.message || 'Submission failed');
    }}
  }} catch(err) {{
    msg.className = 'cf-err';
    msg.textContent = '❌ ' + err.message;
    btn.disabled = false;
    btn.textContent = '📨 Send Message';
  }}
  msg.style.display = 'block';
  btn.disabled = false;
  if (msg.className === 'cf-ok') btn.textContent = '✅ Sent';
}}
</script>
"""
    components.html(FORM_HTML, height=540, scrolling=False)

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
