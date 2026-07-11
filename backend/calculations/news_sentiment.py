"""News sentiment scoring for NSE stocks.

Headlines come from Google News RSS (India edition) — no API key needed.
Scoring: FinBERT (ProsusAI/finbert) when torch+transformers are available,
otherwise VADER with a finance-lexicon boost. Both return scores in [-1, 1].
"""
from __future__ import annotations

import datetime as _dt
import re

import pandas as pd

_FINBERT = None          # lazy singleton (model ~440 MB, loaded once)
_FINBERT_FAILED = False
_VADER = None

# Finance-specific words VADER doesn't know (score boost, applied pre-VADER)
_FIN_POS = ["upgrade", "beats", "beat estimates", "order win", "bags order", "record profit",
            "surges", "rally", "bonus", "buyback", "dividend", "stake buy", "expansion",
            "all-time high", "outperform", "target raised", "strong results", "profit jumps"]
_FIN_NEG = ["downgrade", "misses", "fraud", "probe", "default", "pledge", "resigns",
            "plunges", "crash", "sell-off", "penalty", "fine", "lawsuit", "weak results",
            "target cut", "underperform", "loss widens", "profit falls", "debt concerns"]


def fetch_headlines(query: str, max_items: int = 25, days_back: int = 10) -> pd.DataFrame:
    """Fetch recent news headlines for a stock from Google News RSS (India)."""
    import feedparser
    from urllib.parse import quote

    url = (f"https://news.google.com/rss/search?q={quote(query)}"
           f"+when:{days_back}d&hl=en-IN&gl=IN&ceid=IN:en")
    feed = feedparser.parse(url)
    rows = []
    for e in feed.entries[:max_items]:
        try:
            pub = _dt.datetime(*e.published_parsed[:6]) if getattr(e, "published_parsed", None) else None
        except Exception:
            pub = None
        title = re.sub(r"\s+-\s+[^-]+$", "", e.title)  # strip trailing "- Source"
        source = getattr(getattr(e, "source", None), "title", "") or ""
        rows.append({"published": pub, "headline": title, "source": source,
                     "link": getattr(e, "link", "")})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("published", ascending=False, na_position="last").reset_index(drop=True)
    return df


def _load_finbert():
    global _FINBERT, _FINBERT_FAILED
    if _FINBERT is not None or _FINBERT_FAILED:
        return _FINBERT
    # find_spec probes without executing module code — a broken/partial
    # torch install would segfault the process on import, so never import
    # unless both packages are actually present.
    import importlib.util
    if (importlib.util.find_spec("torch") is None
            or importlib.util.find_spec("transformers") is None):
        _FINBERT_FAILED = True
        return None
    try:
        from transformers import pipeline
        _FINBERT = pipeline("sentiment-analysis", model="ProsusAI/finbert",
                            truncation=True, max_length=128)
    except Exception:
        _FINBERT_FAILED = True
    return _FINBERT


def _load_vader():
    global _VADER
    if _VADER is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _VADER = SentimentIntensityAnalyzer()
    return _VADER


def _score_vader(text: str) -> float:
    v = _load_vader()
    s = v.polarity_scores(text)["compound"]
    low = text.lower()
    boost = sum(0.3 for w in _FIN_POS if w in low) - sum(0.3 for w in _FIN_NEG if w in low)
    return max(-1.0, min(1.0, s + boost))


def score_headlines(df: pd.DataFrame, use_finbert: bool = True) -> tuple[pd.DataFrame, str]:
    """Add sentiment/label columns. Returns (df, engine_name)."""
    if df.empty:
        return df, "none"

    texts = df["headline"].tolist()
    engine = "VADER + finance lexicon"
    scores: list[float] = []

    fb = _load_finbert() if use_finbert else None
    if fb is not None:
        engine = "FinBERT"
        try:
            for r in fb(texts, batch_size=8):
                sign = {"positive": 1, "negative": -1, "neutral": 0}[r["label"].lower()]
                scores.append(sign * float(r["score"]))
        except Exception:
            scores = []
    if not scores:
        engine = "VADER + finance lexicon"
        scores = [_score_vader(t) for t in texts]

    out = df.copy()
    out["score"] = [round(s, 3) for s in scores]
    out["sentiment"] = out["score"].map(
        lambda s: "🟢 Positive" if s > 0.15 else ("🔴 Negative" if s < -0.15 else "⚪ Neutral"))
    return out, engine


def aggregate_sentiment(scored: pd.DataFrame) -> dict:
    """Recency-weighted aggregate score + label. Newest headline weighs ~3x oldest."""
    if scored.empty:
        return {"score": 0.0, "label": "No news", "n": 0, "pos": 0, "neg": 0, "neu": 0}
    n = len(scored)
    weights = pd.Series(range(n, 0, -1), index=scored.index) ** 0.7
    agg = float((scored["score"] * weights).sum() / weights.sum())
    label = ("Bullish" if agg > 0.15 else "Bearish" if agg < -0.15 else "Neutral")
    return {
        "score": round(agg, 3), "label": label, "n": n,
        "pos": int((scored["score"] > 0.15).sum()),
        "neg": int((scored["score"] < -0.15).sum()),
        "neu": int(((scored["score"] >= -0.15) & (scored["score"] <= 0.15)).sum()),
    }


def analyze_stock_news(ticker_name: str, use_finbert: bool = True) -> dict:
    """Full pipeline: fetch -> score -> aggregate. Returns dict for the page."""
    query = f'"{ticker_name}" NSE stock'
    df = fetch_headlines(query)
    if df.empty:  # broader fallback query
        df = fetch_headlines(f"{ticker_name} share price")
    scored, engine = score_headlines(df, use_finbert=use_finbert)
    summary = aggregate_sentiment(scored)
    summary["engine"] = engine
    return {"headlines": scored, "summary": summary}
