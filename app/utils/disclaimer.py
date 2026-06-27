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
    st.caption("Last updated: June 2026")

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
