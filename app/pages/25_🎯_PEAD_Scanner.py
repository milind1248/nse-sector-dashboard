from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

st.set_page_config(page_title="PEAD Scanner | NSE Market Sector", layout="wide")

from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.seo import inject_seo
inject_seo("PEADScanner")
from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("PEAD Scanner")

import pandas as pd
import yfinance as yf

from backend.calculations.universe import load_symbols
from backend.data_ingestion.quarterly_results_pipeline import run_quarterly_results_pipeline
from backend.calculations.pead_score import scan_universe, PEADParams, load_quarterly_history, compute_pead_score
from backend.calculations.breakout_detector import technical_confirmation
from backend.calculations.fraud_checker import check_fraud_flags
from backend.calculations.fair_value import compute_fair_value
from backend.calculations.pead_llm_verdict import get_verdict


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_price_history(symbol: str) -> pd.DataFrame:
    raw = yf.download(symbol, period="1y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]
    return raw.dropna(how="all")


def _run_deep_dive(symbol: str, company_name: str) -> dict:
    hist = load_quarterly_history(symbol)
    pead = compute_pead_score(hist)

    price_df = _fetch_price_history(symbol)
    technical = technical_confirmation(price_df) if not price_df.empty else {"technically_confirmed": None}

    fraud = check_fraud_flags(company_name, days_back=365)

    try:
        fv = compute_fair_value(symbol)
    except Exception:
        fv = None

    company_data = {
        "symbol": symbol,
        "company_name": company_name,
        "pead_score": pead.get("pead_score"),
        "yoy_sales_growth": pead.get("yoy_sales_growth"),
        "yoy_profit_growth": pead.get("yoy_profit_growth"),
        "qoq_profit_growth": pead.get("qoq_profit_growth"),
        "trailing_avg_profit_growth": pead.get("trailing_avg_profit_growth"),
        "technical": technical,
        "fraud": {"flagged": fraud.flagged, "reason": fraud.reason, "matched_terms": fraud.matched_terms},
        "fair_value": {
            "average": fv.get("average"), "upside_pct": fv.get("upside_pct"), "uncertainty": fv.get("uncertainty"),
        } if fv and not fv.get("error") else None,
    }

    verdict = get_verdict(company_data)

    return {"pead": pead, "technical": technical, "fraud": fraud, "fair_value": fv, "verdict": verdict}


# ─── Page title & disclaimer ─────────────────────────────────────────────────
st.title("🎯 PEAD Scanner")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption(
    "Post-Earnings-Announcement-Drift screener: quarterly results scored for self-referential growth "
    "surprise (how much a company accelerates above its own historical growth pace, since no paid "
    "analyst-consensus feed is used), then narrowed by technical confirmation, a fraud/regulatory "
    "check, and fair-value context — finishing with a single AI-synthesized ACCEPT/REJECT read per "
    "candidate. Educational research tool, not a recommendation to buy or sell."
)

tab_shortlist, tab_deep_dive = st.tabs(["📋 PEAD Shortlist", "🔍 Deep Dive"])

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — PEAD SHORTLIST
# ═════════════════════════════════════════════════════════════════════════════
with tab_shortlist:
    c1, c2 = st.columns([2, 1])
    universe_choice = c1.selectbox("Universe", ["Nifty 50", "Nifty 500"], key="pead_univ")
    min_score = c2.slider("Minimum PEAD Score", 0, 100, 40, key="pead_min_score")

    refresh = st.button("🔄 Refresh Results (scrapes latest quarterly numbers)", key="pead_refresh_btn")
    if refresh:
        syms = load_symbols(universe_choice)
        with st.spinner(f"Fetching quarterly results for {len(syms)} symbols… this can take a few minutes."):
            result = run_quarterly_results_pipeline(syms, triggered_by="admin_manual")
        st.session_state["pead_refresh_result"] = result
        st.success(f"Fetched {result['success']}/{result['total']} symbols "
                   f"({result['failed']} failed/skipped).")

    run_scan = st.button("▶ Run PEAD Shortlist", type="primary", key="pead_scan_btn")
    if run_scan:
        syms = load_symbols(universe_choice)
        with st.spinner("Scoring quarterly results…"):
            df_scan = scan_universe(syms, PEADParams(min_score_shortlist=min_score))
        st.session_state["pead_scan_df"] = df_scan

    df_scan = st.session_state.get("pead_scan_df")
    if df_scan is not None and not df_scan.empty:
        show_df = df_scan[df_scan["pead_score"] >= min_score].copy()
        st.metric("Shortlisted Companies", len(show_df))
        display_cols = ["symbol", "pead_score", "latest_quarter", "yoy_sales_growth",
                        "yoy_profit_growth", "qoq_profit_growth", "trailing_avg_profit_growth"]
        display_cols = [c for c in display_cols if c in show_df.columns]
        st.dataframe(
            show_df[display_cols].rename(columns={
                "symbol": "Symbol", "pead_score": "PEAD Score", "latest_quarter": "Latest Qtr",
                "yoy_sales_growth": "YoY Sales %", "yoy_profit_growth": "YoY Profit %",
                "qoq_profit_growth": "QoQ Profit %", "trailing_avg_profit_growth": "Trailing Avg Profit %",
            }),
            width='stretch', hide_index=True,
        )
    elif run_scan:
        st.info("No companies matched this PEAD score threshold. Try refreshing results first, "
                "or lower the minimum score.")
    else:
        st.info("Click 'Refresh Results' first (if you haven't fetched quarterly data yet), "
                "then 'Run PEAD Shortlist'.")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — DEEP DIVE
# ═════════════════════════════════════════════════════════════════════════════
with tab_deep_dive:
    st.caption(
        "Runs technical confirmation + fraud/regulatory check + fair-value context + an AI-synthesized "
        "verdict for one company. Best used on a symbol already found in the PEAD Shortlist tab."
    )
    dc1, dc2 = st.columns([2, 2])
    symbol_input = dc1.text_input("Symbol (.NS)", value="RELIANCE.NS", key="pead_dd_symbol").strip().upper()
    company_name_input = dc2.text_input(
        "Company display name (for news search — e.g. 'Reliance Industries')",
        value="", key="pead_dd_name",
        help="Google News matches company names far better than ticker symbols. "
             "Leave blank to fall back to the raw symbol.",
    )

    run_dd = st.button("▶ Run Deep Dive", type="primary", key="pead_dd_btn")
    if run_dd:
        if not symbol_input.endswith(".NS"):
            symbol_input += ".NS"
        company_name = company_name_input.strip() or symbol_input.replace(".NS", "")
        with st.spinner(f"Analysing {symbol_input}… (results, technical, fraud check, valuation, AI verdict)"):
            dd_result = _run_deep_dive(symbol_input, company_name)
        st.session_state["pead_dd_result"] = dd_result
        st.session_state["pead_dd_sym"] = symbol_input

    dd_result = st.session_state.get("pead_dd_result")
    dd_sym = st.session_state.get("pead_dd_sym", symbol_input)

    if dd_result:
        verdict = dd_result["verdict"]
        pead = dd_result["pead"]
        technical = dd_result["technical"]
        fraud = dd_result["fraud"]
        fv = dd_result["fair_value"]

        if verdict["verdict"] == "ACCEPT":
            st.success(f"✅ **ACCEPT** — {dd_sym}")
        elif verdict["verdict"] == "REJECT":
            st.error(f"❌ **REJECT** — {dd_sym}")
        else:
            st.warning(f"⚠️ **VERDICT UNAVAILABLE** — {verdict.get('reasoning', 'Unknown error')}")
        if verdict.get("reasoning") and verdict["verdict"] in ("ACCEPT", "REJECT"):
            st.markdown(f"*{verdict['reasoning']}*")

        st.markdown("---")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("PEAD Score", pead.get("pead_score", "—"))
        m2.metric("YoY Profit Growth", f"{pead.get('yoy_profit_growth', '—')}%" if pead.get("yoy_profit_growth") is not None else "—")
        m3.metric("Above 200 EMA", "✅ Yes" if technical.get("above_200ema") else ("❌ No" if technical.get("above_200ema") is False else "—"))
        m4.metric("Breakout Confirmed", "✅ Yes" if technical.get("technically_confirmed") else "❌ No")

        st.markdown("##### 📊 Result Details")
        st.write(pead.get("reason", "—"))

        st.markdown("##### 📈 Technical Confirmation")
        tc1, tc2, tc3 = st.columns(3)
        tc1.write(f"Resistance level: ₹{technical.get('resistance_level', '—')}")
        tc2.write(f"Last close: ₹{technical.get('last_close', '—')}")
        tc3.write(f"Volume ratio: {technical.get('volume_ratio', '—')}×")

        st.markdown("##### 🚨 Fraud / Regulatory Check")
        if fraud.flagged:
            st.error(fraud.reason)
            for h in fraud.headlines[:5]:
                st.caption(f"- {h['headline']} ({h.get('source', '—')})")
        else:
            st.success(fraud.reason)

        st.markdown("##### 💰 Fair Value")
        if fv and not fv.get("error"):
            fc1, fc2, fc3 = st.columns(3)
            fc1.metric("Average Fair Value", f"₹{fv['average']:,.0f}")
            fc2.metric("Upside vs CMP", f"{fv['upside_pct']:+.1f}%")
            fc3.metric("Uncertainty", fv["uncertainty"])
        else:
            st.caption("Fair value unavailable for this stock.")
