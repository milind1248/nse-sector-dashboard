"""
Fraud / corporate-governance red-flag check for the PEAD Scanner — matches
the "Kavach"-penalty example from the source video (Aman Industries had a
good result but a ₹25 lakh SEBI penalty and a trading restriction on
management, which should hard-reject it regardless of how good the
numbers look).

Reuses backend/calculations/news_sentiment.py::fetch_headlines() (an
arbitrary free-text Google News RSS query, already used elsewhere on the
site) with targeted regulatory/fraud queries, over a much longer lookback
than the standard 10-day sentiment window (a penalty from 6 months ago
still matters). Deliberately a transparent KEYWORD-MATCH gate, not an LLM
call — a fraud/governance check should be a hard, auditable filter you can
verify by reading the actual headline, not a probabilistic judgment call.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.calculations.news_sentiment import fetch_headlines

# Deliberately explicit and India-market-specific — matches real regulatory
# vocabulary (SEBI orders, NSE/BSE circulars) rather than generic finance
# negative words already covered by news_sentiment.py's _FIN_NEG list.
_RED_FLAG_TERMS = [
    "sebi penalty", "sebi order", "sebi probe", "sebi action", "sebi ban",
    "trading restriction", "trading ban", "regulatory action",
    "fraud", "forensic audit", "accounting fraud", "financial irregularit",
    "auditor resign", "resignation of auditor", "qualified audit",
    "related party transaction", "corporate governance",
    "insider trading", "market manipulation", "show cause notice",
    "penalty imposed", "fine imposed", "non-compliance", "non compliance",
    "kavach", "default on loan", "npa classification",
]

_FRAUD_QUERY_TEMPLATES = [
    # BUGFIX: without parentheses around the OR terms, Google News RSS's
    # query parser doesn't reliably bind the company name to every OR
    # branch — confirmed directly: a Reliance Industries query returned
    # headlines about a completely different company ("Rajesh Exports")
    # because the unparenthesized "OR" effectively broadened the whole
    # search instead of staying scoped to the quoted company name.
    '"{name}" (SEBI penalty OR SEBI order OR SEBI probe)',
    '"{name}" (fraud OR forensic audit OR financial irregularities)',
    '"{name}" (trading restriction OR regulatory action)',
]


@dataclass
class FraudCheckResult:
    flagged: bool
    matched_terms: list
    headlines: list  # list of {headline, source, link, published}
    reason: str


def _company_name_in_headline(company_name: str, headline: str) -> bool:
    """BUGFIX: Google News RSS does not reliably enforce quoted-phrase or
    parenthesized-OR-group matching — confirmed directly: a query quoting
    "Reliance Industries" still returned headlines entirely about other
    companies (e.g. "Rajesh Exports"). Since there's no paid search API
    with real boolean matching here, this is enforced in Python instead:
    a headline only counts as a red flag if the company name (or its
    first significant word, e.g. "Reliance" out of "Reliance Industries")
    actually appears in the headline text."""
    name_lower = company_name.lower()
    headline_lower = headline.lower()
    if name_lower in headline_lower:
        return True
    first_word = name_lower.split()[0] if name_lower.split() else ""
    return len(first_word) >= 4 and first_word in headline_lower


def check_fraud_flags(company_name: str, days_back: int = 365, max_items_per_query: int = 15) -> FraudCheckResult:
    """company_name should be the display/search name (e.g. "Reliance
    Industries"), not the ticker symbol — Google News matches company
    names far better than tickers. Searches a full year back by default,
    since a governance red flag from months ago still matters for a
    PEAD trade held over weeks."""
    all_headlines: list[dict] = []
    matched_terms: set[str] = set()

    for template in _FRAUD_QUERY_TEMPLATES:
        query = template.format(name=company_name)
        df = fetch_headlines(query, max_items=max_items_per_query, days_back=days_back)
        if df.empty:
            continue
        for _, row in df.iterrows():
            headline_text = str(row.get("headline", ""))
            if not _company_name_in_headline(company_name, headline_text):
                continue
            headline_lower = headline_text.lower()
            hits = [term for term in _RED_FLAG_TERMS if term in headline_lower]
            if hits:
                matched_terms.update(hits)
                all_headlines.append({
                    "headline": row.get("headline"),
                    "source": row.get("source"),
                    "link": row.get("link"),
                    "published": str(row.get("published")) if pd.notna(row.get("published")) else None,
                })

    # De-dupe by headline text (same story often appears across queries)
    seen = set()
    deduped = []
    for h in all_headlines:
        if h["headline"] not in seen:
            seen.add(h["headline"])
            deduped.append(h)

    flagged = len(deduped) > 0
    reason = (
        f"{len(deduped)} headline(s) matched red-flag terms: {', '.join(sorted(matched_terms))}"
        if flagged else "No regulatory/fraud red flags found in the last year of news."
    )
    return FraudCheckResult(flagged=flagged, matched_terms=sorted(matched_terms), headlines=deduped, reason=reason)
