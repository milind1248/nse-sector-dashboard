"""
SEO utility for Streamlit pages.
Injects meta tags (description, keywords, Open Graph, Twitter Card)
into document <head> via a one-time JS snippet.
Call inject_seo() at the top of every page after set_page_config().
"""
import streamlit as st

_SITE_NAME  = "Market Sector Analysis"
_SITE_URL   = "https://nse-sector-dashboard-milind.streamlit.app"
_SITE_IMAGE = f"{_SITE_URL}/favicon.ico"

# Per-page SEO config  ─ key = page filename stem (without number/emoji prefix)
PAGE_SEO = {
    "Home": {
        "title":       "Market Sector Analysis | FII Fortnightly Sector Flow Dashboard",
        "description": "Track where Foreign Institutional Investors (FII/FPI) are investing in Indian stock markets. "
                       "Fortnightly NSDL sector-wise data, heatmaps, top buyer/seller sectors. "
                       "For informational and research purposes only. Not investment advice.",
        "keywords":    "FII sector flow India, FPI investment sectors NSE, NSDL fortnightly data, "
                       "Indian stock market FII tracker, sector wise FII data, market sector analysis dashboard",
    },
    "FPI_Sectors": {
        "title":       "FPI Sector Investment Tracker | First Half Second Half Analysis | Market Sector Analysis",
        "description": "Deep-dive into FPI (Foreign Portfolio Investment) flows by sector. "
                       "Filter by first half (1–15) or second half (16–EOM) of each month. "
                       "Cumulative flow tracker, top buyer and seller sectors, heat maps and trend charts.",
        "keywords":    "FPI sector tracker India, foreign portfolio investment sectors, FII first half second half, "
                       "NSDL sector report, cumulative FPI flow, sector heat map NSE",
    },
    "FII_Invest_Sector": {
        "title":       "FII Historical Sector Investment | 5-Year Heatmap | Market Sector Analysis",
        "description": "Explore 5+ years of FII fortnightly sector investment history. "
                       "Interactive heatmap showing every sector's net FII equity flow since 2020. "
                       "Identify long-term FII favourites and sectors under sustained selling pressure.",
        "keywords":    "FII historical sector data India, FII investment heatmap NSE, "
                       "sector wise FII history 2020 2021 2022 2023 2024 2025, NSDL FII data download",
    },
    "Sector_Analysis": {
        "title":       "Sector Price Analysis | FII Flow vs Price Data | Market Sector Analysis",
        "description": "Compare sector index prices against FII flow data. "
                       "Analyse Nifty Bank, Nifty IT, Nifty Auto, Nifty Pharma and 20+ sector indices "
                       "alongside institutional flow data for research purposes. Not investment advice.",
        "keywords":    "NSE sector index analysis, Nifty sector performance, FII flow price data, "
                       "sector index chart India, Nifty Bank Nifty IT Nifty Auto research",
    },
    "Smart_Money": {
        "title":       "Smart Money Tracker | FII/DII OI + Delivery Analysis | Market Sector Analysis",
        "description": "Track FII/DII (smart money) positions using Futures Open Interest and Cash Delivery % data. "
                       "Identify Long Buildup, Short Buildup, Short Covering and Long Unwinding signals across all FNO stocks. "
                       "For informational and research purposes only. Not investment advice.",
        "keywords":    "smart money tracker NSE, FII DII open interest India, futures OI change NSE, "
                       "delivery percentage NSE, long buildup short buildup, institutional activity NSE stocks",
    },
    "Stock_Picker": {
        "title":       "Stock Screener | FII Sector-Based Stock Analysis | Market Sector Analysis",
        "description": "Analyse stocks within FII-active sectors. "
                       "Filter by momentum, volume, RSI and FII flow data for research and screening purposes. "
                       "For informational purposes only — not investment advice or recommendations.",
        "keywords":    "stock screener NSE, FII sector stocks India, momentum analysis India, "
                       "NSE equity screener, sector stock analysis, institutional flow stocks",
    },
    "FII_DII_Flow": {
        "title":       "FII DII Daily Flow | Institutional Buy Sell Activity | Market Sector Analysis",
        "description": "Monitor daily FII and DII (Domestic Institutional Investor) buy/sell activity "
                       "in Indian equity markets. Weekly, fortnightly, monthly and quarterly views "
                       "with cumulative flow charts to spot institutional accumulation trends.",
        "keywords":    "FII DII daily flow India, institutional buying NSE, DII buying data, "
                       "FII net purchase India, daily FII data NSE, institutional flow dashboard",
    },
    "Market_Pulse": {
        "title":       "Market Pulse | Nifty Breadth & Relative Rotation | Market Sector Analysis",
        "description": "View overall Indian stock market breadth data. "
                       "Advance-decline breadth, Relative Rotation Graph (RRG), VIX trends and "
                       "market-wide FII flow data for research and analysis. For informational purposes only.",
        "keywords":    "Nifty market breadth, advance decline ratio NSE, RRG relative rotation graph India, "
                       "India VIX chart, market health indicator NSE, Nifty 50 analysis",
    },
    "Alerts": {
        "title":       "Technical Alerts | Sector Breakout & Reversal Patterns | Market Sector Analysis",
        "description": "Monitor stocks crossing key technical levels across all sectors. "
                       "View breakout and reversal patterns from historical data for research reference. "
                       "For informational purposes only — not investment advice.",
        "keywords":    "sector breakout monitor NSE, FII flow data India, technical pattern analysis, "
                       "NSE stock technical levels, sector momentum analysis",
    },
    "Contact": {
        "title":       "Contact Us | Feedback & Support | Market Sector Analysis",
        "description": "Send feedback, report data issues or request new features for the Market Sector Analysis FII dashboard.",
        "keywords":    "contact NSE dashboard, FII data feedback, Indian stock market tool support",
    },
    "Export": {
        "title":       "Export FII Sector Data | Download NSDL Data CSV | Market Sector Analysis",
        "description": "Download historical FII/FPI sector-wise investment data as CSV or Excel. "
                       "Full NSDL fortnightly history from 2020 to present. "
                       "Use offline in your own analysis tools, Excel models or Python notebooks.",
        "keywords":    "download FII data India, NSDL sector data CSV, FPI data export, "
                       "FII investment data Excel, historical FII data download NSE",
    },
}


def inject_seo(page_key: str) -> None:
    """
    Inject SEO meta tags for the given page key (matches PAGE_SEO dict).
    Call once per page, right after st.set_page_config().
    """
    cfg = PAGE_SEO.get(page_key, PAGE_SEO["Home"])
    title       = cfg["title"].replace("'", "\\'")
    description = cfg["description"].replace("'", "\\'")
    keywords    = cfg["keywords"].replace("'", "\\'")
    site_name   = _SITE_NAME.replace("'", "\\'")
    url         = _SITE_URL
    image       = _SITE_IMAGE

    st.markdown(f"""
<script>
(function() {{
    function setMeta(name, content, isProp) {{
        var attr  = isProp ? 'property' : 'name';
        var sel   = 'meta[' + attr + '="' + name + '"]';
        var el    = document.querySelector(sel);
        if (!el) {{
            el = document.createElement('meta');
            el.setAttribute(attr, name);
            document.head.appendChild(el);
        }}
        el.setAttribute('content', content);
    }}

    // Basic SEO
    document.title = '{title}';
    setMeta('description', '{description}');
    setMeta('keywords',    '{keywords}');
    setMeta('robots',      'index, follow');
    setMeta('author',      'Market Sector Analysis');

    // Open Graph (Facebook / LinkedIn / WhatsApp preview)
    setMeta('og:type',        'website',       true);
    setMeta('og:site_name',   '{site_name}',   true);
    setMeta('og:title',       '{title}',       true);
    setMeta('og:description', '{description}', true);
    setMeta('og:url',         '{url}',         true);
    setMeta('og:image',       '{image}',       true);

    // Twitter Card
    setMeta('twitter:card',        'summary');
    setMeta('twitter:title',       '{title}');
    setMeta('twitter:description', '{description}');
    setMeta('twitter:image',       '{image}');

    // Canonical link
    var link = document.querySelector('link[rel="canonical"]');
    if (!link) {{
        link = document.createElement('link');
        link.rel = 'canonical';
        document.head.appendChild(link);
    }}
    link.href = '{url}';
}})();
</script>
""", unsafe_allow_html=True)
