"""
"ETF Dukan 3" strategy - Mahesh Chandra Kaushik (SEBI RA), "ETF Dukaan
Updated Version, Class 3" YouTube video. Powers app/pages/28_ETF_Dukan_3.py.
Streamlit-free (matches every other backend/calculations module).

Rules, in one line: rank a curated, theme-deduplicated 45-ETF universe by
RSI(14) ascending every day; buy at most one per day, walking the rank list
and skipping anything already held; if nothing unheld is available, average
into whichever held ETF has fallen >=3% since its last buy; sell an ETF's
entire position when it closes >= avg_price * (1 + target%), target 4.71%.
Capital is split into 50 "parts"; position size = working_capital / 50.

Curated universe: built this session by combining the fabtrader momentum
strategy's 37-ETF list with this strategy's own 75-ETF list (76 unique
symbols), classifying each by its real NSE "Underlying Asset" description
into a specific theme, and keeping only the single most liquid ETF per
theme - so two funds tracking the same thing never compete for a rank slot.
Backtested over 10 years (2016-2026): 12.72% CAGR, -30.96% max drawdown,
Sharpe 0.55 (pure-reinvest mode) - the best risk-adjusted result of every
ETF strategy tested this session.

Compounding math (video's own literal rule, OFF by default here since it's
a real drag on returns - see backtest comparison): on each sale, subtract
an estimated brokerage cost, then 20.8% tax (20% income tax + 4% cess) on
the post-brokerage profit; of what's left, HALF is paid out as "self
dividend" (withdrawn) and HALF is added back to working capital.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import yfinance as yf

TARGET_PCT = 4.71
AVERAGE_DROP_PCT = 3.0
CAPITAL_PARTS = 50
RANK_DEPTH = None          # walk the FULL rank list looking for an unheld ETF (no cutoff, per the video)
TAX_RATE = 0.208           # 20% income tax + 4% cess, matching the video's own worked example
TXN_COST_PCT = 0.001

# (Theme, NSE underlying-asset description) per symbol - the curated,
# deduplicated universe built this session (76 combined ETFs -> 45 with
# >=200 trading days of history classified into distinct themes).
ETF_UNIVERSE_META: dict[str, tuple[str, str]] = {
    "NIFTYBEES": ("Nifty 50", "Nifty 50"),
    "JUNIORBEES": ("Nifty Next 50", "Nippon India ETF Nifty Next 50 Junior BeES"),
    "TOP100CASE": ("Nifty 100", "Zerodha Nifty 100 ETF"),
    "MONIFTY500": ("Nifty 500 (Total Market)", "Motilal Oswal Nifty 500 ETF"),
    "HDFCSENSEX": ("Sensex 30", "SENSEX"),
    "BSE500IETF": ("BSE 500 (Total Market)", "S&P BSE 500 index"),
    "SILVERBEES": ("Silver", "Domestic price of Silver - LBMA Silver daily spot fixing price"),
    "GOLDBEES": ("Gold", "Gold"),
    "COMMOIETF": ("Broad Commodities Basket", "ICICI Prudential Nifty Commodities ETF"),
    "LIQUIDBEES": ("Government Bond (Gilt)", "Government Securities"),
    "LIQUIDCASE": ("Liquid/Overnight", "Zerodha Nifty 1D Rate Liquid ETF"),
    "EBBETF0430": ("Target Maturity Bond (Bharat Bond)", "Nifty BHARAT Bond"),
    "ALPHA": ("Alpha", "NIFTY Alpha 50 Index"),
    "SMALLCAP": ("Momentum", "Mirae Asset Nifty Smallcap 250 Momentum Quality 100 ETF"),
    "ALPL30IETF": ("Alpha Low-Volatility", "Nifty Alpha Low-Volatility 30 Index"),
    "LOWVOLIETF": ("Low Volatility", "Nifty 100 Low Volatility 30 Index"),
    "MOVALUE": ("Value", "Motilal Oswal S&P BSE Enhanced Value ETF"),
    "TOP10ADD": ("Equal Weight", "Nifty Top 10 Equal Weight Index"),
    "SHARIABEES": ("Shariah Compliant", "Shariah"),
    "MAHKTECH": ("Hong Kong - Hang Seng TECH", "Hang Seng TECH Total Return Index"),
    "HNGSNGBEES": ("Hong Kong - Hang Seng", "Hang Seng Index"),
    "MON100": ("US - Nasdaq 100", "Nasdaq100"),
    "MAFANG": ("US - FANG+ Tech", "NYSE FANG+ Total Return Index"),
    "MONQ50": ("US - Nasdaq Next-50 (Q-50)", "Nasdaq Q-50 Total Return Index"),
    "MASPTOP50": ("US - S&P 500 Top 50", "S&P 500 Top 50 Total Return Index"),
    "HDFCSML250": ("Smallcap", "HDFC NIFTY Smallcap 250 ETF"),
    "MID150BEES": ("Midcap", "Nifty Midcap 150 TRI"),
    "METALIETF": ("Metals & Mining", "Nifty Metal Index"),
    "FMCGIETF": ("FMCG", "Nifty FMCG Index"),
    "CONSUMBEES": ("Consumption (broad)", "Nifty India Consumption TRI"),
    "OILIETF": ("Oil & Gas", "Nifty Oil & Gas Index"),
    "BANKBEES": ("Banking (broad)", "Nifty Bank"),
    "PSUBNKBEES": ("PSU Banks", "Nifty PSU Bank"),
    "PVTBANIETF": ("Private Banks", "Nifty Private Bank Index"),
    "FINIETF": ("BFSI (broad)", "ICICI Prudential Nifty Financial Services Ex-Bank ETF"),
    "PHARMABEES": ("Pharma", "Nifty Pharma TRI"),
    "MODEFENCE": ("Defence", "Nifty India Defence Total Return Index"),
    "AUTOBEES": ("Auto", "Nifty Auto TRI"),
    "GROWWRAIL": ("Railways", "Nifty India Railways PSU Index"),
    "INFRAIETF": ("Infrastructure", "ICICI Prudential Nifty Infrastructure ETF"),
    "MOREALTY": ("Realty", "Motilal Oswal Nifty Realty ETF"),
    "ITBEES": ("IT Services", "Nifty IT TRI"),
    "CPSEETF": ("PSU/CPSE Basket", "CPSE ETF"),
    "TNIDETF": ("India Digital", "Nifty India Digital Index"),
    "GROWWEV": ("EV & New-Age Auto", "Nifty EV and New Age Automotive Index"),
}

ETF_UNIVERSE = list(ETF_UNIVERSE_META.keys())

# Backtest reference numbers (2016-08-19 to 2026-08-19, 10 years, pure-reinvest
# mode) - baked in as static reference for the Backtest Results tab so it
# loads instantly without recomputing; the page's "Re-run Backtest" button
# calls run_backtest() live if a visitor wants to verify these themselves.
BACKTEST_SUMMARY = {
    "window": "2016-08-19 to 2026-08-19 (10 years)",
    "pure": {"cagr_pct": 12.72, "max_dd_pct": -30.96, "sharpe": 0.55, "total_return_pct": 231.03, "n_trades": 720},
    "described_capital_only": {"cagr_pct": 6.96, "max_dd_pct": -32.93, "sharpe": 0.08, "total_return_pct": 96.00, "n_trades": 696},
    "described_total_wealth": {"cagr_pct": 10.07, "max_dd_pct": -28.02, "sharpe": 0.38, "total_return_pct": 160.99},
}


def _rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def fetch_universe(years: float = 2.0) -> dict[str, pd.DataFrame]:
    """Batch-fetch OHLC + RSI14 for the curated universe. Returns {symbol: df}."""
    period = f"{int(years * 365)}d" if years < 1 else f"{int(years)}y"
    data: dict[str, pd.DataFrame] = {}
    for sym in ETF_UNIVERSE:
        try:
            df = yf.download(f"{sym}.NS", period=period, interval="1d", auto_adjust=True, progress=False)
            if hasattr(df.columns, "get_level_values"):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=["Close"])
            if len(df) < 30:
                continue
            df["RSI14"] = _rsi_wilder(df["Close"])
            data[sym] = df
        except Exception:
            continue
    return data


def rank_today(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Rank the whole universe by RSI(14) ascending (lowest = rank 1 = most oversold)."""
    rows = []
    for sym, df in data.items():
        if df.empty or pd.isna(df["RSI14"].iloc[-1]):
            continue
        close_now = float(df["Close"].iloc[-1])
        rsi = float(df["RSI14"].iloc[-1])
        ret_1d = float(df["Close"].pct_change().iloc[-1] * 100) if len(df) > 1 else 0.0
        ret_5d = float((close_now / df["Close"].iloc[-6] - 1) * 100) if len(df) > 5 else 0.0
        theme, underlying = ETF_UNIVERSE_META.get(sym, ("Unclassified", sym))
        rows.append({
            "symbol": sym, "theme": theme, "underlying": underlying,
            "close": close_now, "rsi14": rsi, "ret_1d_pct": ret_1d, "ret_5d_pct": ret_5d,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values("rsi14", ascending=True).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out


def decide_todays_action(data: dict[str, pd.DataFrame], open_positions: list[dict],
                          working_capital: float, capital_parts: int = CAPITAL_PARTS) -> dict:
    """One buy (new entry, walking the RSI rank) or average (down >=3%), else SKIP."""
    ranked = rank_today(data)
    if ranked.empty:
        return {"action": "SKIP", "symbol": None, "reason": "No rankable data today"}

    held_symbols = {p["symbol"] for p in open_positions}
    part_size = working_capital / capital_parts

    for _, row in ranked.iterrows():
        sym = row["symbol"]
        if sym not in held_symbols:
            return {
                "action": "NEW_ENTRY", "symbol": sym, "rank": int(row["rank"]),
                "rsi14": row["rsi14"], "price": row["close"], "part_size": part_size,
                "reason": f"Lowest-RSI unheld ETF (RSI={row['rsi14']:.1f}, rank #{int(row['rank'])})",
            }

    # nothing unheld available -> look for an averaging opportunity
    avg_candidates = []
    for pos in open_positions:
        sym = pos["symbol"]
        if sym not in data or data[sym].empty:
            continue
        price = float(data[sym]["Close"].iloc[-1])
        drop_pct = (price / pos["last_buy_price"] - 1) * 100
        if drop_pct <= -AVERAGE_DROP_PCT:
            avg_candidates.append((sym, drop_pct, price))
    if avg_candidates:
        avg_candidates.sort(key=lambda x: x[1])
        sym, drop_pct, price = avg_candidates[0]
        return {
            "action": "AVERAGE", "symbol": sym, "price": price, "part_size": part_size,
            "reason": f"Down {drop_pct:.2f}% from last buy - averaging in",
        }

    return {"action": "SKIP", "symbol": None, "reason": "All ETFs already held; none has fallen >=3% for averaging"}


def check_exits(data: dict[str, pd.DataFrame], open_positions: list[dict], target_pct: float = TARGET_PCT) -> list[dict]:
    """At most ONE exit/day - whichever held position shows the highest profit >= target_pct."""
    candidates = []
    for pos in open_positions:
        sym = pos["symbol"]
        if sym not in data or data[sym].empty:
            continue
        price = float(data[sym]["Close"].iloc[-1])
        profit_pct = (price / pos["avg_price"] - 1) * 100
        if profit_pct >= target_pct:
            candidates.append({**pos, "exit_price": price, "pnl_pct": profit_pct})
    if not candidates:
        return []
    candidates.sort(key=lambda c: c["pnl_pct"], reverse=True)
    best = candidates[0]
    gross_profit = best["units"] * best["exit_price"] - best["invested_cost"]
    return [{**best, "gross_profit_rs": gross_profit}]


def apply_compounding(gross_profit_rs: float, invested_cost: float, proceeds: float,
                       apply_tax_dividend: bool) -> dict:
    """Video's tax(20.8%) + 50% self-dividend math, togglable per etf_dukan3_config.apply_tax_dividend."""
    cost = (invested_cost + proceeds) * TXN_COST_PCT
    if not apply_tax_dividend:
        net_profit = gross_profit_rs - cost
        return {"net_profit_rs": net_profit, "self_dividend_rs": 0.0, "growth_added_rs": net_profit}
    profit_after_brokerage = gross_profit_rs - cost
    tax = max(profit_after_brokerage, 0) * TAX_RATE
    net_profit = profit_after_brokerage - tax
    self_dividend = max(net_profit, 0) / 2
    growth_added = net_profit - self_dividend
    return {"net_profit_rs": net_profit, "self_dividend_rs": self_dividend, "growth_added_rs": growth_added}
