"""User Guide — business meaning and how-to for every page of the dashboard."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

st.set_page_config(page_title="User Guide | Market Sector Analysis", layout="wide")
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()
from app.utils.seo import inject_seo
inject_seo("User_Guide")
from app.utils.logo import show_logo
show_logo()

# ── Guide content — add a new page by appending one dict to this list ─────────
GUIDE = [
    {
        "emoji": "🏠",
        "name": "FII Sector Watch (Home)",
        "business": "Your daily snapshot of where foreign money is flowing across Indian sectors.",
        "how": "Check the live ticker — green = FII buying, red = selling. Top-ranked sectors indicate current institutional interest for the latest fortnight.",
        "tabs": [],
    },
    {
        "emoji": "📡",
        "name": "Market Pulse",
        "business": "Measures overall market health — is the current rally broad-based or narrow?",
        "how": "Advance-decline breadth >70% signals a healthy rally. Check the RRG chart to see which sectors are gaining momentum vs rotating out. Updated nightly after market close.",
        "tabs": [
            ("🌡️ Market Breadth", "Advancing vs declining NSE stocks today — broad breadth confirms a rally is not just index-driven."),
            ("🔄 Relative Rotation (RRG)", "Sectors moving into the Leading quadrant (top-right) are outperforming. Track week-over-week rotation to spot emerging leaders."),
            ("📊 Sector Returns", "Daily and weekly % returns for all 18+ sector indices side by side — spot laggards and outperformers instantly."),
        ],
    },
    {
        "emoji": "📈",
        "name": "Sector Analysis",
        "business": "Compare sector price trends against FII activity to spot institutional-driven moves.",
        "how": "Select a sector and time period. Look for FII buying spikes that precede price breakouts — institutional flow often leads price by 1–2 weeks. Use this as Step 2 after identifying a hot sector on the Home page.",
        "tabs": [
            ("📊 Price Chart", "Sector index price history with selectable timeframes — identify trend structure."),
            ("💹 FII vs Price", "FII net flow bars overlaid on price — look for flow spikes preceding price moves."),
            ("📉 RSI / Momentum", "Overbought/oversold readings to time entries within an FII-driven trend."),
            ("🏆 Sector Ranking", "All sectors ranked by return for the selected period — spot outperformers in one view."),
        ],
    },
    {
        "emoji": "🏛️",
        "name": "Index Stocks",
        "business": "See which stocks make up each Nifty index, their weightage, and current technical status.",
        "how": "Pick an index (e.g. Nifty Bank) to see all constituents with weightage, RSI, and EMA position. Heavyweights drive index movement most — prioritise stocks with high weightage when analysing index direction.",
        "tabs": [
            ("📋 Constituents", "Full list of index stocks with live weightage and technical indicators."),
            ("📊 Sector Weight", "Pie/bar chart of each stock's contribution to the index — see concentration risk."),
            ("🔍 Stock Detail", "Drill into any constituent for price chart and indicator history."),
        ],
    },
    {
        "emoji": "🏦",
        "name": "FII DII Flow",
        "business": "Track what domestic and foreign institutions bought or sold each day in cash markets.",
        "how": "Days where both FII and DII buy simultaneously are the strongest accumulation signals. Switch to the Cumulative Chart to see sustained buying phases — a rising cumulative line = net institutional demand building over weeks.",
        "tabs": [
            ("📅 Daily Flow", "Day-by-day FII and DII net buy/sell in ₹ crore — spot single-day institutional activity."),
            ("📊 Fortnightly Sector Breakdown", "NSDL fortnightly sector split — see exactly which sectors received the most FII money this fortnight."),
        ],
    },
    {
        "emoji": "🏢",
        "name": "FII Sectors",
        "business": "Discover which sectors foreign institutions have been buying or avoiding across 5+ years of history.",
        "how": "The heatmap is your primary tool — dark green = heavy buying, dark red = sustained selling. Filter by year to identify seasonal FII patterns. Use the FII → Price → Stock tab to drill from a sector signal all the way down to individual stock confirmation.",
        "tabs": [
            ("📊 Sector × Fortnight Matrix", "Year × Sector grid of FII net investment — color intensity shows magnitude of institutional activity."),
            ("🔬 FII → Price → Stock Analysis", "Drill from sector FII flow into price confirmation and individual stock-level signals."),
        ],
    },
    {
        "emoji": "🌏",
        "name": "FPI Sectors",
        "business": "Fortnightly NSDL data showing Foreign Portfolio Investor flows split by first-half and second-half of each month.",
        "how": "Compare H1 vs H2 of the same month — FPI buying that accelerates in H2 often signals month-end fund deployment by large institutions. The cumulative view shows the overall trend direction across months.",
        "tabs": [
            ("Overview", "Summary of total FPI flow for the selected period with sector ranking."),
            ("Sector Trend", "Sector FPI flow plotted over time — identify reversal points and trend changes."),
            ("Cumulative Flow", "Running cumulative FPI flow since selected start date — rising = sustained foreign demand."),
            ("Heat Map", "Sector × Date intensity heatmap of FPI flow — spot seasonality and concentration."),
            ("H1 / H2 Breakdown", "First-half (1–15) vs second-half (16–EOM) FPI net flow per sector."),
            ("Raw Data", "Filterable table of all NSDL fortnightly entries — useful for custom offline analysis."),
        ],
    },
    {
        "emoji": "🎯",
        "name": "Stock Picker",
        "business": "Screen stocks within FII-active sectors using technical and momentum filters.",
        "how": "Use this as Step 3 in the FII → Sector → Stock flow. Start on the Home or FII Sectors page to identify a sector with fresh FII buying, then come here to filter its stocks by RSI, EMA position, and volume surge. Stocks in uptrends with volume confirm the institutional thesis.",
        "tabs": [
            ("🔍 Screener", "Filter stocks by RSI range, EMA position, volume surge, and % price change."),
            ("📊 Comparison", "Side-by-side price chart of multiple selected stocks — compare relative strength."),
        ],
    },
    {
        "emoji": "💰",
        "name": "Smart Money",
        "business": "Follow institutional footprints through Futures Open Interest changes and cash delivery percentage.",
        "how": "Long Buildup (price up + OI up) = institutions adding long futures positions. High delivery % (>50%) in cash market = genuine buying, not just intraday speculation. The highest-conviction setups show both signals together.",
        "tabs": [
            ("📊 OI Analysis", "FII/DII futures open interest change — identify Long Buildup, Short Buildup, Short Covering, and Long Unwinding patterns."),
            ("📦 Delivery %", "Cash market delivery percentage per stock — high % signals institutional accumulation vs speculative trading."),
            ("🔍 Combined View", "Stocks showing both OI buildup and high delivery simultaneously — the strongest smart-money signals."),
        ],
    },
    {
        "emoji": "📊",
        "name": "FII Accumulation",
        "business": "Identify stocks where FII holding percentage has increased across consecutive quarters in regulatory filings.",
        "how": "Sort by '3-Quarter Change' to find stocks with sustained FII buying. Consecutive quarterly increases are more significant than a single spike. Cross-reference with the Smart Money page for near-term confirmation before drawing any conclusions.",
        "tabs": [],
    },
    {
        "emoji": "🔔",
        "name": "Alerts & Scanners",
        "business": "Find stocks hitting key technical levels — breakouts, pullbacks, and momentum reversals — across all 185 NSE stocks.",
        "how": "Run the scanner for today's setups. Breakout Alert = price crossing above resistance with volume confirmation. 20 EMA Pullback = uptrending stock retracing to its 20-day moving average — a classic trend-continuation entry. H-M Scanner = RSI momentum turning from overbought/oversold extremes.",
        "tabs": [
            ("📡 Breakout Alerts", "Stocks breaking out of consolidation ranges with volume confirmation across all sectors."),
            ("📈 20 EMA Pullback Scanner", "Uptrending stocks pulling back to their 20-day EMA — potential re-entry points in established uptrends."),
            ("🎯 H-M Scanner", "RSI(9) momentum reversal setups — stocks turning from oversold or overbought extremes."),
            ("📊 FRVP Signal", "Fixed Range Volume Profile — select any stock to see the Developing POC level. Price above POC = BUY bias, price below = SELL bias. The POC is computed over the range from the last swing-pivot candle that touched it, mirroring the 3-step TradingView FRVP method."),
        ],
    },
    {
        "emoji": "🤖",
        "name": "AI Forecast",
        "business": "AI models predict the 5-day directional probability and 30-day price trend for any NSE stock.",
        "how": "Select a stock and click ▶ Run Forecast. XGBoost Upward Probability >60% = stronger directional signal. Check Backtest Accuracy first — this shows real out-of-sample model accuracy for this specific stock. The Prophet chart shows the projected 30-day price path with confidence bands.",
        "tabs": [],
    },
    {
        "emoji": "🔢",
        "name": "Gann Analysis",
        "business": "Apply W.D. Gann's mathematical price-time methods to identify natural support, resistance, and turning-point levels.",
        "how": "Enter a stock with its recent swing high and low. Square of Nine levels show price points where natural energy clusters. Price-Time squaring highlights dates when the time elapsed equals the price movement — historically significant turning zones in Gann theory. For educational use only.",
        "tabs": [],
    },
    {
        "emoji": "📤",
        "name": "Export",
        "business": "Download the full dashboard dataset as a multi-sheet Excel file for offline analysis.",
        "how": "Click Generate Report. The Excel file contains 13 sheets covering sector FII history, stock snapshots, market breadth, Smart Money OI data, AI forecast signals, and Gann levels — ready to use in your own Excel models or Python notebooks.",
        "tabs": [],
    },
    {
        "emoji": "📧",
        "name": "Contact",
        "business": "Send feedback, report data discrepancies, or request new features for the dashboard.",
        "how": "Fill in your name, email, and message. When reporting a data issue, include the stock symbol and the date in question — this helps resolve problems much faster.",
        "tabs": [],
    },
]

# ── Page layout ───────────────────────────────────────────────────────────────
st.title("📖 User Guide")
st.caption("Business meaning and step-by-step how-to for every page of the Market Sector Analysis dashboard.")
from app.utils.disclaimer import show_sebi_notice, show_footer
show_sebi_notice()

st.markdown("""
<style>
/* Slightly enlarge expander header font */
[data-testid="stExpander"] summary p {
    font-size: 15px !important;
    font-weight: 600 !important;
}
.guide-divider {
    border: none;
    border-top: 1px solid #1e2130;
    margin: 10px 0 8px 0;
}
.guide-tab-item {
    padding: 5px 0;
    border-bottom: 1px solid #1a1f2e;
    font-size: 14px;
}
.guide-tab-item:last-child {
    border-bottom: none;
}
</style>
""", unsafe_allow_html=True)

st.markdown("---")

for page in GUIDE:
    label = f"{page['emoji']}  {page['name']}"
    with st.expander(label, expanded=False):
        col_what, col_how = st.columns(2, gap="large")

        with col_what:
            st.markdown(
                "<div style='background:#0d1f0d;border-left:4px solid #4ade80;"
                "border-radius:6px;padding:12px 14px;margin-bottom:4px'>"
                "<div style='color:#4ade80;font-size:12px;font-weight:700;"
                "letter-spacing:.5px;margin-bottom:4px'>📌 WHAT IT DOES</div>"
                f"<div style='color:#d0d0d0;font-size:14px'>{page['business']}</div>"
                "</div>",
                unsafe_allow_html=True,
            )

        with col_how:
            st.markdown(
                "<div style='background:#0d1829;border-left:4px solid #4a9eff;"
                "border-radius:6px;padding:12px 14px;margin-bottom:4px'>"
                "<div style='color:#4a9eff;font-size:12px;font-weight:700;"
                "letter-spacing:.5px;margin-bottom:4px'>🧭 HOW TO USE IT</div>"
                f"<div style='color:#d0d0d0;font-size:14px'>{page['how']}</div>"
                "</div>",
                unsafe_allow_html=True,
            )

        if page["tabs"]:
            st.markdown("<hr class='guide-divider'>", unsafe_allow_html=True)
            st.markdown(
                "<div style='color:#8899bb;font-size:12px;font-weight:700;"
                "letter-spacing:.5px;margin-bottom:6px'>TABS ON THIS PAGE</div>",
                unsafe_allow_html=True,
            )
            rows_html = ""
            for tab_name, tab_desc in page["tabs"]:
                rows_html += (
                    f"<div class='guide-tab-item'>"
                    f"<span style='color:#4a9eff;font-weight:600'>{tab_name}</span>"
                    f"<span style='color:#888'> — </span>"
                    f"<span style='color:#c0c0c0'>{tab_desc}</span>"
                    f"</div>"
                )
            st.markdown(
                f"<div style='background:#0e1117;border-radius:6px;padding:8px 12px'>"
                f"{rows_html}</div>",
                unsafe_allow_html=True,
            )

show_footer()
