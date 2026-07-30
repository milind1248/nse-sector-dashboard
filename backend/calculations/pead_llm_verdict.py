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

Uses Groq's free API tier (OpenAI-compatible chat completions endpoint,
called via plain `requests` — no extra SDK dependency needed) rather than
a paid provider, since this task's volume (~150 calls/quarter) comfortably
fits Groq's free rate limits.

Secrets pattern matches backend/storage/db.py::_connection_string() —
works both inside a running Streamlit page (st.secrets) and in standalone
scripts (falls back to reading the TOML file directly).
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

_SECRETS_PATH = Path(__file__).resolve().parent.parent.parent / ".streamlit" / "secrets.toml"

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_MODEL = "llama-3.3-70b-versatile"  # strong reasoning, free tier, fast on Groq's LPU inference

_SYSTEM_PROMPT = """You are a disciplined equity research assistant helping screen post-earnings \
candidates for a PEAD (Post-Earnings-Announcement-Drift) trading strategy. You will be given \
structured, already-computed data about one company's latest quarterly result, its technical \
price action, any fraud/regulatory red flags found in recent news, and its valuation. Your job \
is ONLY to synthesize this into a verdict — do not invent numbers, do not second-guess the \
computed data, and treat any fraud flag as a likely hard reject regardless of how good the \
numbers look. Respond with strict JSON only, no markdown fences, no extra text: \
{"verdict": "ACCEPT" or "REJECT", "reasoning": "2-4 sentences explaining why, referencing the \
specific numbers given"}. This is educational/research tooling, not investment advice — do not \
include disclaimers in your reasoning, the page already shows one."""


def _get_api_key() -> str | None:
    try:
        import streamlit as st
        return st.secrets["llm"]["groq_api_key"]
    except Exception:
        pass
    try:
        import toml
        secrets = toml.load(_SECRETS_PATH)
        return secrets["llm"]["groq_api_key"]
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
        return {"verdict": "ERROR", "reasoning": "No Groq API key configured in secrets.toml [llm] section."}

    try:
        user_content = json.dumps(company_data, default=str, indent=2)
        resp = requests.post(
            _GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": _MODEL,
                "max_tokens": 400,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"Here is the data for this candidate:\n{user_content}"},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw_text = resp.json()["choices"][0]["message"]["content"].strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`").lstrip("json").strip()
        parsed = json.loads(raw_text)
        verdict = parsed.get("verdict", "ERROR").upper()
        if verdict not in ("ACCEPT", "REJECT"):
            verdict = "ERROR"
        return {"verdict": verdict, "reasoning": parsed.get("reasoning", "")}
    except Exception as e:
        return {"verdict": "ERROR", "reasoning": f"LLM call failed: {e}"}
