"""
"5 Agent Tools" cross-validation panel for the PEAD Scanner Deep Dive tab —
matches the video's demo UI (Forensic / Fundamental / Technical / News &
Sentiment / Peer Comparison, each showing Clean/Flag + a one-line finding,
then a combined ACCEPT/REJECT card with confidence, target, stop-loss).

Deliberately built entirely from data this codebase already computes
elsewhere (fraud_checker, pead_score, breakout_detector + indicators.py,
news_sentiment, fair_value's peer-multiple fetch) — no new data source,
no new LLM call. The only new logic here is packaging those 5 existing
results into the tool-card shape and picking a sector peer list for the
5th tool.
"""
from __future__ import annotations

import statistics

import pandas as pd

import config
from backend.calculations.fraud_checker import check_fraud_flags
from backend.calculations.breakout_detector import technical_confirmation
from backend.calculations.indicators import compute_all_indicators
from backend.calculations.news_sentiment import analyze_stock_news
from backend.calculations.fair_value import fetch_peer_multiples, _safe


def _find_sector(symbol: str) -> str | None:
    """Which config.SECTOR_STOCKS bucket this symbol belongs to (for peer
    comparison) — a stock can appear in more than one sector list (e.g.
    BEL is both Capital Goods and Defence); the first match is used."""
    bare = symbol.replace(".NS", "").upper()
    for sector, syms in config.SECTOR_STOCKS.items():
        if any(s.replace(".NS", "").upper() == bare for s in syms):
            return sector
    return None


def _forensic_tool(company_name: str) -> dict:
    fraud = check_fraud_flags(company_name, days_back=365)
    if fraud.flagged:
        return {
            "name": "Forensic & Governance Checker", "icon": "🛡️", "status": "FLAG",
            "gate": True,  # matches the video: forensic is a hard gate, one flag = reject
            "summary": fraud.reason,
            "detail": fraud,
        }
    return {
        "name": "Forensic & Governance Checker", "icon": "🛡️", "status": "CLEAN",
        "gate": True,
        "summary": "No SEBI flags or regulatory/fraud red flags found in the last year.",
        "detail": fraud,
    }


def _fundamental_tool(pead: dict) -> dict:
    red_flags = pead.get("red_flags") or []
    yoy_sales = pead.get("yoy_sales_growth")
    yoy_profit = pead.get("yoy_profit_growth")
    growth_bit = (
        f"Revenue {yoy_sales:+.0f}%, Net Profit {yoy_profit:+.0f}% YoY"
        if yoy_sales is not None and yoy_profit is not None else "Insufficient quarterly history"
    )
    if red_flags:
        return {
            "name": "Fundamental Analyzer", "icon": "📊", "status": "FLAG", "gate": False,
            "summary": f"{growth_bit}. {red_flags[0]}",
            "detail": pead,
        }
    return {
        "name": "Fundamental Analyzer", "icon": "📊", "status": "CLEAN", "gate": False,
        "summary": f"{growth_bit}. No earnings-quality red flags.",
        "detail": pead,
    }


def _technical_tool(price_df: pd.DataFrame) -> dict:
    if price_df is None or price_df.empty:
        return {"name": "Technical Analyzer", "icon": "📈", "status": "FLAG", "gate": False,
                "summary": "No price history available.", "detail": {}}
    ind = compute_all_indicators(price_df)
    tech = technical_confirmation(price_df)
    # BUGFIX: compute_all_indicators() keys its RSI as "rsi_14", not "rsi" —
    # the old `ind.get("rsi")` silently returned None every time, masked
    # because the FLAG branch below had a safe `if rsi else` fallback; it
    # only surfaced as a crash once a real breakout hit the CLEAN branch's
    # unguarded f"{rsi:.0f}" (confirmed directly against MANAPPURAM.NS,
    # the first real technically-confirmed stock this tool encountered).
    rsi = ind.get("rsi_14")
    macd, macd_signal = ind.get("macd"), ind.get("macd_signal")
    macd_bull = macd is not None and macd_signal is not None and macd > macd_signal
    breakout_ok = bool(tech.get("technically_confirmed"))
    detail = {**ind, **tech}
    rsi_str = f"{rsi:.0f}" if rsi is not None else "—"
    if breakout_ok:
        summary = (
            f"RSI {rsi_str}{' (neutral)' if rsi is not None and 40 <= rsi <= 60 else ''}, "
            f"MACD {'bullish crossover' if macd_bull else 'no crossover'}, "
            f"price broke {tech.get('resistance_level', '—')} with "
            f"{tech.get('volume_ratio', '—')}x volume."
        )
        return {"name": "Technical Analyzer", "icon": "📈", "status": "CLEAN", "gate": False,
                "summary": summary, "detail": detail}
    # "No breakout = no play" — matches the video's own framing directly.
    return {"name": "Technical Analyzer", "icon": "📈", "status": "FLAG", "gate": False,
            "summary": f"No confirmed breakout yet (RSI {rsi_str})." if rsi is not None else "No confirmed breakout yet.",
            "detail": detail}


def _news_tool(company_name: str) -> dict:
    res = analyze_stock_news(company_name)
    label = res.get("label", "Neutral")
    n = res.get("n", 0)
    if label == "Bearish":
        return {"name": "News & Sentiment Agent", "icon": "📰", "status": "FLAG", "gate": False,
                "summary": f"Bearish tone across {n} recent headlines.", "detail": res}
    return {"name": "News & Sentiment Agent", "icon": "📰", "status": "CLEAN", "gate": False,
            "summary": f"{label} sentiment across {n} recent headlines." if n else "No recent headlines found.",
            "detail": res}


def _peer_tool(symbol: str) -> dict:
    sector = _find_sector(symbol)
    if not sector:
        return {"name": "Peer Comparison", "icon": "⚖️", "status": "CLEAN", "gate": False,
                "summary": "No sector peer group configured for this stock.", "detail": {}}
    peers = config.SECTOR_STOCKS[sector]
    pm = fetch_peer_multiples(peers, exclude=symbol)
    peer_pe = pm.get("pe")

    import yfinance as yf
    try:
        info = yf.Ticker(symbol if symbol.endswith(".NS") else f"{symbol}.NS").info
        own_pe = _safe(info, "trailingPE")
    except Exception:
        own_pe = None

    if own_pe is None or peer_pe is None:
        return {"name": "Peer Comparison", "icon": "⚖️", "status": "CLEAN", "gate": False,
                "summary": f"Sector: {sector}. Peer P/E data unavailable.",
                "detail": {"sector": sector, "peer_pe": peer_pe, "own_pe": own_pe}}

    rel = "discount to" if own_pe < peer_pe else ("premium to" if own_pe > peer_pe else "in line with")
    summary = f"P/E {own_pe:.1f} vs sector median {peer_pe:.1f} — trading at a {rel} {sector} peers."
    return {"name": "Peer Comparison", "icon": "⚖️", "status": "CLEAN", "gate": False,
            "summary": summary, "detail": {"sector": sector, "peer_pe": peer_pe, "own_pe": own_pe}}


def _safe_tool(fn, fallback_name: str, fallback_icon: str, *args) -> dict:
    """Every other batch operation in this codebase (shareholding_pipeline,
    quarterly_results_pipeline) isolates each item with try/except so one
    bad symbol can't take down the whole run — this tool panel had no such
    isolation, and a live scan across hundreds of real, messy stocks (data
    gaps, corporate actions, delisted tickers) surfaced exactly that gap.
    Any unexpected exception here degrades to an honest "data unavailable"
    FLAG instead of crashing the whole scan/page."""
    try:
        return fn(*args)
    except Exception as e:
        return {"name": fallback_name, "icon": fallback_icon, "status": "FLAG", "gate": False,
                "summary": f"Tool error — data unavailable ({type(e).__name__}: {e}).", "detail": {}}


def run_agent_analysis(symbol: str, company_name: str, pead: dict, price_df: pd.DataFrame) -> dict:
    """Runs all 5 tools and derives a combined verdict + confidence — a
    pure, deterministic function of the 5 tools' own outputs (not a 6th
    LLM call), matching the "cross-validating findings" framing while
    staying fully auditable."""
    tools = [
        _safe_tool(_forensic_tool, "Forensic & Governance Checker", "🛡️", company_name),
        _safe_tool(_fundamental_tool, "Fundamental Analyzer", "📊", pead),
        _safe_tool(_technical_tool, "Technical Analyzer", "📈", price_df),
        _safe_tool(_news_tool, "News & Sentiment Agent", "📰", company_name),
        _safe_tool(_peer_tool, "Peer Comparison", "⚖️", symbol),
    ]

    forensic_flag = tools[0]["status"] == "FLAG"       # hard gate
    technical_flag = tools[2]["status"] == "FLAG"       # "no breakout = no play"
    flag_count = sum(1 for t in tools if t["status"] == "FLAG")

    if forensic_flag:
        verdict, reason = "REJECTED", f"Forensic gate failed: {tools[0]['summary']}"
    elif technical_flag:
        verdict, reason = "REJECTED", f"No technical confirmation: {tools[2]['summary']}"
    elif flag_count >= 2:
        verdict, reason = "REJECTED", f"{flag_count} of 5 tools flagged concerns — not enough conviction."
    else:
        verdict = "ACCEPTED"
        reason = "; ".join(t["summary"] for t in tools if t["status"] == "CLEAN")

    # Confidence: deterministic, not a made-up LLM number — starts at a
    # base and is docked per flag (forensic/technical docked harder,
    # matching their gate status above).
    confidence = 90
    if forensic_flag:
        confidence -= 40
    if technical_flag:
        confidence -= 25
    confidence -= 10 * max(0, flag_count - (1 if forensic_flag else 0) - (1 if technical_flag else 0))
    confidence = max(5, min(95, confidence))

    return {
        "symbol": symbol, "tools": tools, "verdict": verdict,
        "confidence": confidence, "reason": reason, "flag_count": flag_count,
    }
