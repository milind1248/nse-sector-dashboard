"""
All-Time-High momentum framework — Rohan Mehta interview (Hindi transcript,
"Conversation with Kushal" podcast). Powers app/pages/15_🚀_Momentum_Scanner.py.

Three-criteria stock-selection rule:
  1. Price at/near all-time high (max available yfinance history).
  2. TTM PAT (profit) at its own all-time high — only checked for stocks
     that already pass criteria 1 and 3 (see run_momentum_scan below), a
     deliberate optimization since ~185 -> ~15 stocks typically qualify,
     cutting the number of slow yfinance quarterly-financials calls by
     ~90% without changing the result for any individual stock.
  3. Trailing 52-week return beats both Nifty 500 and the stock's own
     sector index.

Score 3/3 = BUY, 2/3 = HOLD, <=1/3 = AVOID. Ported from the standalone
research script scripts/momentum_alltimehigh_framework.py (see that file's
docstring for the full rule extraction + LIMITATIONS discussion — the
10-year backtest there showed a real but thin net-of-cost edge, ~76%
monthly turnover eating most of the gross alpha).

No Streamlit imports here (matches every other backend/calculations module)
— caching is the caller's responsibility.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from config import SECTOR_INDICES, SECTOR_STOCKS

BENCHMARK_FALLBACKS = ["^CRSLDX", "^NSEI"]  # Nifty 500 preferred, Nifty 50 fallback
LOOKBACK_DAYS_1Y = 252
DEFAULT_ATH_TOLERANCE_PCT = 2.0
DEFAULT_TOP_N = 15


def stock_to_sector() -> dict[str, str]:
    out: dict[str, str] = {}
    for sector, syms in SECTOR_STOCKS.items():
        for s in syms:
            out.setdefault(s, sector)
    return out


def universe_symbols() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for syms in SECTOR_STOCKS.values():
        for s in syms:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def fetch_history(symbol: str, period: str = "max") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def resolve_benchmark() -> tuple[str, pd.DataFrame]:
    for tkr in BENCHMARK_FALLBACKS:
        try:
            df = fetch_history(tkr, period="2y")
            if len(df) > 200:
                return tkr, df
        except Exception:
            continue
    raise RuntimeError("Could not fetch any benchmark index")


def is_all_time_high(close: pd.Series, tolerance_pct: float = 0.0) -> pd.Series:
    running_max = close.cummax()
    return close >= running_max * (1 - tolerance_pct / 100)


def trailing_return(close: pd.Series, window: int = LOOKBACK_DAYS_1Y) -> pd.Series:
    return close.pct_change(window) * 100


def ttm_pat_at_all_time_high(symbol: str) -> dict:
    """LIVE-ONLY fundamental check (today's snapshot). See module docstring."""
    try:
        tk = yf.Ticker(symbol)
        qf = tk.quarterly_income_stmt
        if qf is None or qf.empty:
            return {"ok": False, "ttm_pat": None, "max_ttm_pat": None, "n_quarters": 0}
        row_name = None
        for cand in ("Net Income", "Net Income Common Stockholders", "NetIncome"):
            if cand in qf.index:
                row_name = cand
                break
        if row_name is None:
            return {"ok": False, "ttm_pat": None, "max_ttm_pat": None, "n_quarters": 0}
        pat = qf.loc[row_name].dropna().sort_index()
        if len(pat) < 4:
            return {"ok": False, "ttm_pat": None, "max_ttm_pat": None, "n_quarters": len(pat)}
        ttm_series = pat.rolling(4).sum().dropna()
        if ttm_series.empty:
            return {"ok": False, "ttm_pat": None, "max_ttm_pat": None, "n_quarters": len(pat)}
        latest_ttm = float(ttm_series.iloc[-1])
        max_ttm = float(ttm_series.max())
        return {
            "ok": latest_ttm >= max_ttm * 0.999,
            "ttm_pat": latest_ttm, "max_ttm_pat": max_ttm, "n_quarters": len(pat),
        }
    except Exception:
        return {"ok": False, "ttm_pat": None, "max_ttm_pat": None, "n_quarters": 0}


def run_momentum_scan(
    symbols: tuple[str, ...],
    ath_tolerance_pct: float = DEFAULT_ATH_TOLERANCE_PCT,
    top_n: int = DEFAULT_TOP_N,
) -> pd.DataFrame:
    """
    Full 3-criteria live scan. Returns a DataFrame with columns:
    symbol, sector, price, ret_1y_pct, sector_ret_1y_pct, bench_ret_1y_pct,
    crit1_price_ath, crit2_profit_ath, crit3_outperform, score, decision,
    below_200ema, em_rank.

    top_n is used only to flag the top-N-by-return rows (decision stays
    BUY/HOLD/AVOID for everyone; top_n narrows what the page highlights as
    the actual portfolio-sized shortlist, matching the backtest's
    holding-count convention).
    """
    sec_map = stock_to_sector()
    bench_ticker, bench_df = resolve_benchmark()
    bench_ret_1y = float(trailing_return(bench_df["Close"]).iloc[-1])

    sector_ret_cache: dict[str, float | None] = {}

    def sector_return(sector: str) -> float | None:
        if sector in sector_ret_cache:
            return sector_ret_cache[sector]
        tkr = SECTOR_INDICES.get(sector)
        val = None
        if tkr:
            try:
                df = fetch_history(tkr, period="2y")
                if len(df) > 100:
                    val = float(trailing_return(df["Close"]).iloc[-1])
            except Exception:
                val = None
        sector_ret_cache[sector] = val
        return val

    # Pass 1 — criteria 1 + 3 only (cheap, no fundamentals fetch).
    prelim_rows = []
    for sym in symbols:
        try:
            df = fetch_history(sym, period="max")
            if len(df) < 260:
                continue
            close = df["Close"]
            price = float(close.iloc[-1])
            crit1 = bool(is_all_time_high(close, tolerance_pct=ath_tolerance_pct).iloc[-1])
            ret_1y = float(trailing_return(close).iloc[-1])
            sector = sec_map.get(sym, "Unknown")
            s_ret = sector_return(sector)
            crit3 = (ret_1y > bench_ret_1y) and (s_ret is None or ret_1y > s_ret)

            close_200ema = close.ewm(span=200, adjust=False, min_periods=200).mean().iloc[-1]
            below_200ema = price < float(close_200ema)

            prelim_rows.append({
                "symbol": sym.replace(".NS", ""), "sector": sector, "price": round(price, 2),
                "ret_1y_pct": round(ret_1y, 2),
                "sector_ret_1y_pct": round(s_ret, 2) if s_ret is not None else None,
                "bench_ret_1y_pct": round(bench_ret_1y, 2),
                "crit1_price_ath": crit1, "crit3_outperform": crit3,
                "below_200ema": below_200ema, "_symbol_ns": sym,
            })
        except Exception:
            continue

    # Pass 2 — criterion 2 (TTM PAT) only for stocks passing 1 AND 3, per
    # the module docstring's optimization.
    for row in prelim_rows:
        if row["crit1_price_ath"] and row["crit3_outperform"]:
            pat_res = ttm_pat_at_all_time_high(row["_symbol_ns"])
            row["crit2_profit_ath"] = pat_res["ok"]
        else:
            row["crit2_profit_ath"] = False
        row.pop("_symbol_ns", None)
        row["score"] = int(row["crit1_price_ath"]) + int(row["crit2_profit_ath"]) + int(row["crit3_outperform"])
        row["decision"] = "BUY" if row["score"] == 3 else ("HOLD" if row["score"] == 2 else "AVOID")

    df_out = pd.DataFrame(prelim_rows).dropna(subset=["ret_1y_pct"])
    if df_out.empty:
        return df_out
    df_out["em_rank"] = df_out["ret_1y_pct"].rank(ascending=False, method="min").astype(int)
    df_out["in_top_n"] = df_out["em_rank"] <= top_n
    return df_out.sort_values("em_rank").reset_index(drop=True)
