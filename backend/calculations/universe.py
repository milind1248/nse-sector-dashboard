"""Nifty 50 / Nifty 500 universe loading — shared across scanner pages.

Promoted from app/pages/12_🔭_HM_Scanner.py::_load_symbols() and
backend/calculations/hm_expansion_universe.py::load_symbols() (near-verbatim
duplicates of each other) into one shared module, per the standing follow-up
noted in hm_expansion_universe.py's own docstring.
"""
from __future__ import annotations

import pandas as pd

FALLBACK_NIFTY50 = [
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "AXISBANK.NS",
    "BAJAJ-AUTO.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "BEL.NS", "BHARTIARTL.NS",
    "CIPLA.NS", "COALINDIA.NS", "DRREDDY.NS", "EICHERMOT.NS", "ETERNAL.NS",
    "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS", "HEROMOTOCO.NS",
    "HINDALCO.NS", "HINDUNILVR.NS", "ICICIBANK.NS", "ITC.NS", "INDUSINDBK.NS",
    "INFY.NS", "JSWSTEEL.NS", "JIOFIN.NS", "KOTAKBANK.NS", "LT.NS",
    "M&M.NS", "MARUTI.NS", "NTPC.NS", "NESTLEIND.NS", "ONGC.NS",
    "POWERGRID.NS", "RELIANCE.NS", "SBILIFE.NS", "SHRIRAMFIN.NS", "SBIN.NS",
    "SUNPHARMA.NS", "TCS.NS", "TATACONSUM.NS", "TATAMOTORS.NS", "TATASTEEL.NS",
    "TECHM.NS", "TITAN.NS", "TRENT.NS", "ULTRACEMCO.NS", "WIPRO.NS",
]


def load_symbols(universe: str = "Nifty 500") -> list[str]:
    """Real Nifty 500 constituent list from NSE indices, with a hardcoded
    Nifty 50 fallback if the network call fails or "Nifty 50" is requested
    directly."""
    if universe == "Nifty 50":
        return FALLBACK_NIFTY50
    try:
        from io import StringIO
        import requests
        url = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*",
                   "Referer": "https://www.niftyindices.com/"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        col = "Symbol" if "Symbol" in df.columns else df.columns[0]
        syms = [str(s).strip().upper() + ".NS" for s in df[col].dropna().tolist()]
        if len(syms) >= 400:
            return syms
    except Exception:
        pass
    return FALLBACK_NIFTY50
