"""
PEAD Scanner — LLM synthesis step.

Deliberately NOT a tool-calling agent (confirmed with you before building):
every score/check below is computed directly in Python first (PEAD score,
technical confirmation, fraud flags, fair value) — this module's only job
is to read that already-computed, already-auditable bundle and write a
short ACCEPT/REJECT verdict in plain English, exactly the kind of
synthesis-only task a cheap/fast model is well suited for. Only ever
called on the already-shortlisted (PEAD score >= threshold) candidates,
never the full universe — bounds API cost by design.

Secrets pattern matches backend/storage/db.py::_connection_string() —
works both inside a running Streamlit page (st.secrets) and in standalone
scripts (falls back to reading the TOML file directly).
"""
from __future__ import annotations

import json
from pathlib import Path

_SECRETS_PATH = Path(__file__).resolve().parent.parent.parent / ".streamlit" / "secrets.toml"

_MODEL = "claude-haiku-4-5-20251001"  # cheap/fast — this is a synthesis task, not creative generation

_SYSTEM_PROMPT = """You are a disciplined equity research assistant helping screen post-earnings \
candidates for a PEAD (Post-Earnings-Announcement-Drift) trading strategy. You will be given \
structured, already-computed data about one company's latest quarterly result, its technical \
price action, any fraud/regulatory red flags found in recent news, and its valuation. Your job \
is ONLY to synthesize this into a verdict — do not invent numbers, do not second-guess the \
computed data, and treat any fraud flag as a likely hard reject regardless of how good the \
numbers look. Respond with strict JSON only: {"verdict": "ACCEPT" or "REJECT", "reasoning": \
"2-4 sentences explaining why, referencing the specific numbers given"}. This is educational/ \
research tooling, not investment advice — do not include disclaimers in your reasoning, the \
page already shows one."""


def _get_api_key() -> str | None:
    try:
        import streamlit as st
        return st.secrets["llm"]["anthropic_api_key"]
    except Exception:
        pass
    try:
        import toml
        secrets = toml.load(_SECRETS_PATH)
        return secrets["llm"]["anthropic_api_key"]
    except Exception:
        return None


def get_verdict(company_data: dict) -> dict:
    """company_data should include: symbol, company_name, pead_score,
    yoy_sales_growth, yoy_profit_growth, qoq_profit_growth,
    trailing_avg_profit_growth, technical (dict from breakout_detector's
    technical_confirmation), fraud (dict from fraud_checker's
    check_fraud_flags, as a plain dict), fair_value (dict from
    fair_value.compute_fair_value(), or None if unavailable).

    Returns {"verdict": "ACCEPT"|"REJECT"|"ERROR", "reasoning": str}.
    Never raises — an LLM/API failure returns a clearly-marked ERROR verdict
    rather than crashing the page, same defensive pattern as
    news_sentiment.py::fetch_headlines()."""
    api_key = _get_api_key()
    if not api_key:
        return {"verdict": "ERROR", "reasoning": "No Anthropic API key configured in secrets.toml [llm] section."}

    try:
        import anthropic
    except ImportError:
        return {"verdict": "ERROR", "reasoning": "anthropic package not installed."}

    try:
        client = anthropic.Anthropic(api_key=api_key)
        user_content = json.dumps(company_data, default=str, indent=2)
        response = client.messages.create(
            model=_MODEL,
            max_tokens=400,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Here is the data for this candidate:\n{user_content}"}],
        )
        raw_text = response.content[0].text.strip()
        # Models sometimes wrap JSON in a code fence despite instructions — strip it defensively.
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`").lstrip("json").strip()
        parsed = json.loads(raw_text)
        verdict = parsed.get("verdict", "ERROR").upper()
        if verdict not in ("ACCEPT", "REJECT"):
            verdict = "ERROR"
        return {"verdict": verdict, "reasoning": parsed.get("reasoning", "")}
    except Exception as e:
        return {"verdict": "ERROR", "reasoning": f"LLM call failed: {e}"}
