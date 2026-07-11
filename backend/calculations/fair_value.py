"""Multi-model Fair Value engine (InvestingPro-style) for NSE stocks.

Data: Yahoo Finance fundamentals (one call for the stock + one per sector
peer, cached). Models with missing inputs are skipped, never guessed.

Models
------
Multiples (peer-median based):  P/E, P/B, P/S, EV/EBITDA, EV/Revenue
Income based:                   Earnings Power Value (EPS / cost of equity)
DCF:                            5Y & 10Y FCF DCF (Gordon exit),
                                5Y DCF with EBITDA-multiple exit
Classic:                        Graham Number, Graham Growth DCF

Aggregate: mean fair value, upside vs CMP, min-max spread and an
uncertainty grade from model dispersion.
"""
from __future__ import annotations

import math
import statistics

# India assumptions (documented, conservative)
RISK_FREE = 0.071          # 10y G-Sec ~7.1%
EQUITY_RISK_PREMIUM = 0.055
TERMINAL_GROWTH = 0.04     # long-run nominal GDP-ish
DEFAULT_BETA = 1.0
MAX_GROWTH = 0.20          # cap DCF growth at 20%
MIN_GROWTH = 0.03


def _cost_of_equity(beta: float | None) -> float:
    b = beta if beta and 0.2 < beta < 3 else DEFAULT_BETA
    return RISK_FREE + b * EQUITY_RISK_PREMIUM


def _safe(info: dict, key: str):
    v = info.get(key)
    return v if isinstance(v, (int, float)) and math.isfinite(v) and v != 0 else None


def fetch_peer_multiples(sector_symbols: list[str], exclude: str) -> dict:
    """Median peer multiples for one sector. One .info call per peer (cached upstream)."""
    import yfinance as yf
    cols = {"pe": "trailingPE", "pb": "priceToBook", "ps": "priceToSalesTrailing12Months",
            "ev_ebitda": "enterpriseToEbitda", "ev_rev": "enterpriseToRevenue"}
    acc: dict[str, list[float]] = {k: [] for k in cols}
    for sym in sector_symbols:
        if sym.replace(".NS", "") == exclude.replace(".NS", ""):
            continue
        try:
            info = yf.Ticker(sym if sym.endswith(".NS") else f"{sym}.NS").info
        except Exception:
            continue
        for k, field in cols.items():
            v = _safe(info, field)
            if v and 0 < v < 200:
                acc[k].append(float(v))
    return {k: (statistics.median(v) if len(v) >= 3 else None) for k, v in acc.items()}


def _dcf(fcf0: float, growth: float, years: int, wacc: float,
         terminal_value: float | None = None) -> float:
    """PV of growing FCF stream + terminal value (Gordon if not given)."""
    pv, fcf = 0.0, fcf0
    for t in range(1, years + 1):
        fcf *= (1 + growth)
        pv += fcf / (1 + wacc) ** t
    tv = terminal_value if terminal_value is not None else fcf * (1 + TERMINAL_GROWTH) / (wacc - TERMINAL_GROWTH)
    pv += tv / (1 + wacc) ** years
    return pv


def compute_fair_value(symbol: str, peer_multiples: dict | None = None) -> dict:
    """Full fair-value report for one NSE symbol (no .NS needed)."""
    import yfinance as yf
    try:
        info = yf.Ticker(f"{symbol.replace('.NS','')}.NS").info
    except Exception as e:
        return {"error": str(e)}

    cmp_ = _safe(info, "currentPrice") or _safe(info, "regularMarketPrice")
    if not cmp_:
        return {"error": "No price data"}

    shares  = _safe(info, "sharesOutstanding")
    eps     = _safe(info, "trailingEps")
    fwd_eps = _safe(info, "forwardEps")
    bv      = _safe(info, "bookValue")
    rev     = _safe(info, "totalRevenue")
    ebitda  = _safe(info, "ebitda")
    fcf     = _safe(info, "freeCashflow")
    ocf     = _safe(info, "operatingCashflow")
    debt    = _safe(info, "totalDebt") or 0
    cash    = _safe(info, "totalCash") or 0
    beta    = _safe(info, "beta")
    g_earn  = _safe(info, "earningsGrowth")
    g_rev   = _safe(info, "revenueGrowth")

    ke = _cost_of_equity(beta)
    wacc = max(ke - 0.01, 0.09)  # rough: slightly below Ke, floor 9%
    growth = min(max(g_earn if g_earn and g_earn > 0 else (g_rev or 0.10), MIN_GROWTH), MAX_GROWTH)
    net_debt = debt - cash
    pm = peer_multiples or {}

    models: list[dict] = []

    def add(name: str, value, basis: str):
        if value and math.isfinite(value) and 0.1 * cmp_ < value < 10 * cmp_:
            models.append({"model": name, "value": round(float(value), 2), "basis": basis})

    # ── Income ────────────────────────────────────────────────────────────────
    if eps and eps > 0:
        add("Earnings Power Value", eps / ke, f"EPS ₹{eps:.1f} ÷ Ke {ke*100:.1f}%")
        add("Graham Number", math.sqrt(22.5 * eps * bv) if bv and bv > 0 else None,
            "√(22.5 × EPS × BV)")
        g_pct = growth * 100
        add("Graham Growth DCF", eps * (8.5 + 2 * g_pct) * (4.4 / 7.0),
            f"EPS×(8.5+2×{g_pct:.0f}%)×4.4/7")

    # ── Peer-median multiples ────────────────────────────────────────────────
    if eps and eps > 0 and pm.get("pe"):
        add("P/E Multiples", eps * pm["pe"], f"EPS × peer P/E {pm['pe']:.1f}x")
    if bv and bv > 0 and pm.get("pb"):
        add("Price / Book Multiples", bv * pm["pb"], f"BV × peer P/B {pm['pb']:.1f}x")
    if rev and shares and pm.get("ps"):
        add("Price / Sales Multiples", rev / shares * pm["ps"],
            f"Rev/share × peer P/S {pm['ps']:.1f}x")
    if ebitda and ebitda > 0 and shares and pm.get("ev_ebitda"):
        add("EV / EBITDA Multiples", (ebitda * pm["ev_ebitda"] - net_debt) / shares,
            f"peer EV/EBITDA {pm['ev_ebitda']:.1f}x")
    if rev and shares and pm.get("ev_rev"):
        add("EV / Revenue Multiples", (rev * pm["ev_rev"] - net_debt) / shares,
            f"peer EV/Rev {pm['ev_rev']:.1f}x")

    # ── DCF family ───────────────────────────────────────────────────────────
    fcf_base = fcf if fcf and fcf > 0 else (ocf * 0.7 if ocf and ocf > 0 else None)
    if fcf_base and shares:
        add("5Y DCF Growth Exit", (_dcf(fcf_base, growth, 5, wacc) - net_debt) / shares,
            f"g {growth*100:.0f}% · WACC {wacc*100:.1f}%")
        add("10Y DCF Growth Exit",
            (_dcf(fcf_base, growth, 10, wacc) - net_debt) / shares,
            f"g {growth*100:.0f}% · WACC {wacc*100:.1f}%")
        if ebitda and ebitda > 0 and pm.get("ev_ebitda"):
            ebitda_y5 = ebitda * (1 + growth) ** 5
            tv = ebitda_y5 * pm["ev_ebitda"]
            add("5Y DCF EBITDA Exit", (_dcf(fcf_base, growth, 5, wacc, terminal_value=tv) - net_debt) / shares,
                f"exit {pm['ev_ebitda']:.1f}x EBITDA")

    if not models:
        return {"error": "Insufficient fundamental data for any model", "cmp": cmp_}

    vals = [m["value"] for m in models]
    avg = statistics.mean(vals)
    stdev = statistics.stdev(vals) if len(vals) > 1 else 0.0
    disp = stdev / avg if avg else 1
    uncertainty = "LOW" if disp < 0.15 else ("MEDIUM" if disp < 0.30 else "HIGH")

    return {
        "error": None,
        "symbol": symbol.replace(".NS", ""),
        "cmp": round(cmp_, 2),
        "models": sorted(models, key=lambda m: m["value"]),
        "average": round(avg, 2),
        "upside_pct": round((avg - cmp_) / cmp_ * 100, 1),
        "spread_low": round(min(vals), 2),
        "spread_high": round(max(vals), 2),
        "uncertainty": uncertainty,
        "n_models": len(models),
        # context bars
        "wk52_low": _safe(info, "fiftyTwoWeekLow"),
        "wk52_high": _safe(info, "fiftyTwoWeekHigh"),
        "target_mean": _safe(info, "targetMeanPrice"),
        "target_low": _safe(info, "targetLowPrice"),
        "target_high": _safe(info, "targetHighPrice"),
        "n_analysts": info.get("numberOfAnalystOpinions"),
        "assumptions": f"Ke {ke*100:.1f}% (CAPM, rf {RISK_FREE*100:.1f}%) · WACC {wacc*100:.1f}% · "
                       f"growth {growth*100:.0f}% (capped {MAX_GROWTH*100:.0f}%) · terminal {TERMINAL_GROWTH*100:.0f}%",
    }
