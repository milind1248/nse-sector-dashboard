"""Shared SEBI disclaimer — footer and full-page content."""
import streamlit as st

_SHORT = (
    "This platform is for educational and informational purposes only. "
    "It does not constitute investment advice or recommendations. "
    "Investments in securities are subject to market risks. "
    "Please consult a SEBI-registered investment adviser before making any investment decisions."
)

_FOOTER_HTML = f"""
<div style="
  margin-top:48px;
  border-top:1px solid #1e2130;
  padding:14px 0 6px;
  font-size:10px;
  color:#555;
  line-height:1.7;
">
  <span style="color:#444;font-weight:600;letter-spacing:.5px;">DISCLAIMER</span>
  &nbsp;·&nbsp;
  {_SHORT}
  &nbsp;&nbsp;<a href="/Disclaimer"
    style="color:#3a5a8a;text-decoration:none;font-size:10px;"
    target="_self">Read full disclaimer ↗</a>
</div>
"""


_SEBI_NOTICE_HTML = (
    "<div style='font-size:11px;color:#888;background:#1a1a2e;border-left:3px solid #555;"
    "padding:6px 10px;border-radius:4px;line-height:1.5;margin-bottom:4px'>"
    "⚖️ <b>Regulatory Disclaimer:</b> For educational and informational purposes only. "
    "Not investment advice, a buy/sell recommendation, or a research report under "
    "SEBI (Research Analyst) Regulations, 2014. Consult a <b>SEBI-registered investment adviser</b> "
    "before making any financial decisions. The publisher is <b>not registered</b> with SEBI "
    "as a Research Analyst or Investment Advisor."
    "</div>"
)


def show_sebi_notice() -> None:
    """Render the compact inline SEBI regulatory notice (consistent across all pages)."""
    st.markdown(_SEBI_NOTICE_HTML, unsafe_allow_html=True)


def show_footer() -> None:
    """Render the short disclaimer footer at the bottom of any page."""
    st.markdown(_FOOTER_HTML, unsafe_allow_html=True)


def show_full_disclaimer() -> None:
    """Render the complete SEBI disclosure on the Disclaimer page."""
    st.title("⚖️ Disclaimer")
    st.caption("Last updated: July 2026")

    st.markdown("""
---

### Educational and Informational Purpose

The information, data, charts, analytics, scanners, screeners, dashboards, reports, and market
insights available on this website are provided **solely for educational, research, and
informational purposes**. Nothing contained on this website should be construed as financial,
investment, trading, legal, accounting, or tax advice, nor should it be considered a
recommendation, solicitation, or offer to buy or sell any securities or financial instruments.

---

### No Investment Advisory Services

This platform is **not registered** with the Securities and Exchange Board of India (SEBI) as an
Investment Adviser (IA), Research Analyst (RA), Portfolio Manager, or in any other regulated
capacity, unless expressly stated otherwise.

The content published on this website does not constitute personalized investment advice or
investment recommendations.

---

### Market Risk

Investments in securities markets are subject to market risks. Past performance, historical
returns, technical patterns, FPI/FII or DII activity, sector rotation, momentum indicators,
AI-generated insights, scanner signals, backtesting results, or historical trends **do not
guarantee future performance or returns**.

Any trading or investment decisions made based on information available on this website are
solely at the user's own discretion and risk.

---

### Data Accuracy

The platform may use data obtained from stock exchanges, public sources, third-party data
providers, APIs, or other publicly available information.

While reasonable efforts are made to ensure accuracy, completeness, and timeliness, we do not
guarantee that any information, prices, charts, corporate actions, index constituents, financial
data, or analytics are free from errors, omissions, delays, or inaccuracies.

**Users are advised to independently verify all information before making any financial decisions.**

---

### AI-Generated Insights

This platform may use Artificial Intelligence (AI), Machine Learning (ML), Large Language Models
(LLMs), statistical models, and quantitative algorithms to generate analytics, summaries,
predictions, classifications, and insights.

These outputs are generated automatically and may contain inaccuracies or incomplete information.
AI-generated content should not be treated as investment advice or as the sole basis for making
investment decisions.

---

### Third-Party Links and Content

This website may contain links to third-party websites, including stock exchanges, regulators,
financial institutions, and market data providers. Such links are provided solely for user
convenience.

We do not endorse, control, or accept responsibility for the accuracy, availability, or content
of any third-party website.

---

### Limitation of Liability

The owners, developers, contributors, and operators of this website shall not be liable for any
direct, indirect, incidental, consequential, or special loss or damage arising from the use of,
or reliance upon, any information, tools, reports, scanners, AI outputs, or services available
on this platform.

**Users assume full responsibility for their investment and trading decisions.**

---

### Professional Advice

Before making any investment, trading, or financial decision, users should consult a qualified
**SEBI-registered Investment Adviser, Research Analyst, Chartered Accountant**, tax professional,
or other licensed financial professional, as appropriate.

---

### Privacy Policy

Creating an account (via Google or email/password) is entirely **optional** — every page and
feature on this site is fully usable without signing in, and nothing is currently gated behind
login.

If you do sign in, we store the following in our own database: your email address, display name,
your Google profile photo (only when you use Google sign-in — not collected for email sign-up),
which method you signed in with, and timestamps for account creation and last login. We also
reserve a subscription-tier field for a possible future feature; no such feature exists yet, no
billing occurs today, and this field currently sits at its default, unused value.

This information is used only to personalize your experience on this site and, potentially, for
that future feature — **it is never sold**, and never shared with anyone beyond the processors
below.

Authentication itself — password storage, the Google OAuth token exchange, and issuing your
sign-in session — is handled entirely by **Supabase**, our backend infrastructure provider; our
own systems never see or store your password or Google access tokens. Your sign-in session lives
only in your current browser tab and is **not saved in a cookie** — closing or refreshing the tab
signs you out.

If you sign in with Google, Google's own consent screen discloses to you, before you authorize,
what it shares with this site. Please also refer to **Google's own Privacy Policy** for how Google
itself handles your data.

To request deletion of your account or data, or for any privacy question, please reach out via the
[Contact page](/Contact).

---

### Terms of Service

By creating an account or using this website, you agree to use it only for the educational and
informational purpose described above, and not to misuse it — including attempting to disrupt the
service, scrape it at abusive volumes, or interfere with other users' access.

Accounts are a convenience feature for a personal-project dashboard, not a paid or guaranteed
service. **We do not warrant uninterrupted availability**, and features — including sign-in itself
— may be modified, suspended, or discontinued at any time without notice.

You are responsible for keeping your own account credentials secure and for all activity under
your account.

These Terms, together with the rest of this Disclaimer, are governed by the same **"use entirely
at your own risk, no warranties"** principle stated above under Limitation of Liability.

---

### Acceptance

By accessing or using this website, you acknowledge that you have read, understood, and agreed
to this Disclaimer and that you use the platform **entirely at your own risk**.

---
""")

    st.info(
        "🔗 **SEBI Investor Resources:** "
        "SEBI Complaints — scores.sebi.gov.in · "
        "NSE India — nseindia.com · "
        "BSE India — bseindia.com",
        icon="ℹ️",
    )
