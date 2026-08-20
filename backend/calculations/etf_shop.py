"""
"ETF Shop 2025" strategy — Mahesh Chandra Kaushik (SEBI RA), YouTube video.
Powers app/pages/16_🛒_ETF_Shop_1.py. Streamlit-free (matches every other
backend/calculations module) — caching/DB persistence is the caller's job.

Ported from scripts/etf_shop_backtest.py (see that file's own docstring for
the full rule extraction from the transcript and its LIMITATIONS section —
kept as a genuinely independent standalone script by this codebase's own
convention, not a shared import, so this module is its own copy of the
same logic, not a wrapper around it).

Rules, in one line: rank 65 curated equity ETFs by "% above their own
52-week low" every day; buy at most one per day, walking rank 1->10 and
skipping anything already held; if all of rank 1-10 are already held,
average into whichever held ETF has fallen >=3.14% since its last buy;
sell an ETF's entire position when it closes >= avg_price * (1 + target%).
Live book uses 6.28% (2xPi) — the presenter's own stated preference and
the backtest's best net-return variant.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

PI_TARGETS = {"3.14% (1xPi)": 3.14, "4.71% (1.5xPi)": 4.71, "6.28% (2xPi)": 6.28}
LIVE_TARGET_PCT = 6.28
AVERAGE_DROP_PCT = 3.14
CAPITAL_PARTS = 40          # video's own literal rule — used by run_backtest() for honest historical testing
RANK_DEPTH = 10
LOOKBACK_52W = 252

# Live-book-only guardrails (NOT part of the video's original rules — added
# after this session's own backtest showed the literal 40-part rule
# overruns its own budget by 1.4-1.9x, and that restricting to liquid names
# costs ~2 points of return for a meaningful drop in stuck-open-position and
# capital-overrun risk). See backend/data_ingestion/etf_shop_pipeline.py for
# where these are actually applied to the daily live decision.
LIQUIDITY_RANK_MAX = 25     # only rank-1-10 candidates within the top 25 most liquid ETFs are eligible
CAPITAL_DEPLOY_CAP_PCT = 80.0   # stop taking new signals once this % of total capital is deployed
LIVE_TOTAL_CAPITAL_RS = 200_000.0
LIVE_CAPITAL_PARTS = 30     # vs the video's 40 — bigger per-trade size, fewer simultaneous positions

ETF_UNIVERSE = [
    "MOM30IETF", "NIFTYQLITY", "VAL30IETF", "ABSLPSE", "UTISXN50", "CPSEETF",
    "GOLDBEES", "HNGSNGBEES", "MAHKTECH", "HDFCGROWTH", "LOWVOLIETF", "HDFCQUAL",
    "BSE500IETF", "COMMOIETF", "FINIETF", "INFRAIETF", "MNC", "ALPHAETF",
    "MIDSMALL", "SMALLCAP", "MONIFTY500", "MOREALTY", "MOSMALL250", "MOVALUE",
    "MONQ50", "MON100", "TOP100CASE", "NIFTYBEES", "MOMENTUM50", "ALPHA",
    "ALPL30IETF", "AUTOIETF", "BANKBEES", "DIVOPPBEES", "EVINDIA", "BFSI",
    "FMCGIETF", "HEALTHY", "MOHEALTH", "CONSUMBEES", "MODEFENCE", "TNIDETF",
    "MAKEINDIA", "ITBEES", "METALIETF", "MOM100", "MIDCAPETF", "MIDQ50ADD",
    "MIDCAP", "NEXT50IETF", "OILIETF", "PHARMABEES", "PVTBANIETF", "PSUBNKBEES",
    "TOP10ADD", "ESG", "NV20IETF", "MULTICAP", "EMULTIMQ", "MAFANG",
    "MASPTOP50", "ICICIB22", "MIDSELIETF", "SILVERBEES", "SENSEXIETF", "SHARIABEES",
]

# Underlying asset / index each ETF tracks — verbatim from the user's curated
# Google Sheet export (column C), used for display only (not part of the
# ranking/entry/exit logic itself).
ETF_UNDERLYING_ASSET = {
    "MOM30IETF": "ICICI Prudential Nifty 200 Momentum 30 ETF",
    "NIFTYQLITY": "Aditya Birla Sun Life Nifty 200 Quality 30 ETF",
    "VAL30IETF": "Nifty200 Value 30 Index",
    "ABSLPSE": "Aditya Birla Sun Life Nifty PSE ETF",
    "UTISXN50": "BSE Sensex Next 50",
    "CPSEETF": "CPSE ETF",
    "GOLDBEES": "Gold",
    "HNGSNGBEES": "Hang Seng Index",
    "MAHKTECH": "Hang Seng TECH Total Return Index",
    "HDFCGROWTH": "HDFC NIFTY Growth Sectors 15 ETF",
    "LOWVOLIETF": "Nifty 100 Low Volatility 30 Index",
    "HDFCQUAL": "HDFC NIFTY100 Quality 30 ETF",
    "BSE500IETF": "S&P BSE 500 index",
    "COMMOIETF": "ICICI Prudential Nifty Commodities ETF",
    "FINIETF": "ICICI Prudential Nifty Financial Services Ex-Bank ETF",
    "INFRAIETF": "ICICI Prudential Nifty Infrastructure ETF",
    "MNC": "Kotak Nifty MNC ETF",
    "ALPHAETF": "Mirae Asset Nifty 200 Alpha 30 ETF",
    "MIDSMALL": "Mirae Asset Nifty MidSmallcap400 Momentum Quality 100 ETF",
    "SMALLCAP": "Mirae Asset Nifty Smallcap 250 Momentum Quality 100 ETF",
    "MONIFTY500": "Motilal Oswal Nifty 500 ETF",
    "MOREALTY": "Motilal Oswal Nifty Realty ETF",
    "MOSMALL250": "Motilal Oswal Nifty Smallcap 250 ETF",
    "MOVALUE": "Motilal Oswal S&P BSE Enhanced Value ETF",
    "MONQ50": "Nasdaq Q-50 Total Return Index",
    "MON100": "Nasdaq100",
    "TOP100CASE": "Zerodha Nifty 100 ETF",
    "NIFTYBEES": "Nifty 50",
    "MOMENTUM50": "Nifty 500 Momentum 50 Total Return Index",
    "ALPHA": "NIFTY Alpha 50 Index",
    "ALPL30IETF": "Nifty Alpha Low-Volatility 30 Index",
    "AUTOIETF": "Nifty Auto Index",
    "BANKBEES": "Nifty Bank",
    "DIVOPPBEES": "Nifty Dividend Opportunities 50 TRI",
    "EVINDIA": "Nifty EV and New Age Automotive Total Return Index",
    "BFSI": "Nifty Financial Services Index",
    "FMCGIETF": "Nifty FMCG Index",
    "HEALTHY": "Nifty Healthcare TRI",
    "MOHEALTH": "Motilal Oswal S&P BSE Healthcare ETF",
    "CONSUMBEES": "Nifty India Consumption TRI",
    "MODEFENCE": "Nifty India Defence Total Return Index",
    "TNIDETF": "Nifty India Digital Index",
    "MAKEINDIA": "Nifty India Manufacturing Total Return Index",
    "ITBEES": "Nifty IT TRI",
    "METALIETF": "Nifty Metal Index",
    "MOM100": "Nifty Midcap 100",
    "MIDCAPETF": "Mirae Asset Nifty Midcap 150 ETF",
    "MIDQ50ADD": "Nifty Midcap 150 Quality 50 Index",
    "MIDCAP": "Nifty Midcap 50 Index",
    "NEXT50IETF": "Nifty Next 50",
    "OILIETF": "Nifty Oil & Gas Index",
    "PHARMABEES": "Nifty Pharma TRI",
    "PVTBANIETF": "Nifty Private Bank Index",
    "PSUBNKBEES": "Nifty PSU Bank",
    "TOP10ADD": "Nifty Top 10 Equal Weight Index",
    "ESG": "NIFTY100 ESG SECTOR LEADERS",
    "NV20IETF": "Nifty50 Value 20",
    "MULTICAP": "Nifty500 Multicap 50:25:25 Index",
    "EMULTIMQ": "Nifty500 Multicap Momentum Quality 50 Total Return Index",
    "MAFANG": "NYSE FANG+ Total Return Index",
    "MASPTOP50": "S&P 500 Top 50 Total Return Index",
    "ICICIB22": "S&P BSE BHARAT 22 index",
    "MIDSELIETF": "S&P BSE Midcap Select Index",
    "SILVERBEES": "Silver (LBMA daily spot fixing price)",
    "SENSEXIETF": "SENSEX",
    "SHARIABEES": "Shariah",
}


def fetch_symbol(symbol: str, period: str) -> pd.DataFrame:
    df = yf.download(symbol + ".NS", period=period, interval="1d", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def _rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """Standard Wilder-smoothed RSI — same convention used elsewhere in this
    codebase (backend/calculations/hm_indicators.py::rsi_tv)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def fetch_universe(years: float = 5.0) -> dict[str, pd.DataFrame]:
    period = f"{max(1, round(years)) + 1}y"
    data = {}
    for code in ETF_UNIVERSE:
        try:
            df = fetch_symbol(code, period)
            if len(df) > LOOKBACK_52W + 30:
                df["PCT_ABOVE_52W_LOW"] = (df["Close"] - df["Low"].rolling(LOOKBACK_52W).min()) / \
                                           df["Low"].rolling(LOOKBACK_52W).min() * 100
                df["SMA20"] = df["Close"].rolling(20).mean()
                df["SMA50"] = df["Close"].rolling(50).mean()
                df["SMA200"] = df["Close"].rolling(200).mean()
                df["RSI14"] = _rsi_wilder(df["Close"], 14)
                data[code] = df
        except Exception:
            continue
    return data


def report_liquidity(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for code, df in data.items():
        avg_vol = float(df["Volume"].tail(60).mean())
        avg_close = float(df["Close"].tail(60).mean())
        rows.append({"symbol": code, "avg_volume_60d": int(avg_vol), "avg_price": round(avg_close, 2),
                      "avg_traded_value_cr_60d": round(avg_vol * avg_close / 1e7, 2)})
    out = pd.DataFrame(rows).sort_values("avg_traded_value_cr_60d", ascending=False).reset_index(drop=True)
    out["liquidity_rank"] = out.index + 1
    return out


def compute_liquidity_ranks(data: dict[str, pd.DataFrame]) -> dict[str, int]:
    """symbol -> liquidity rank across the FULL universe (1 = most liquid,
    by 60-day avg traded value), not just among the top-10-by-52w-low
    subset — a stock's liquidity standing should reflect all 65 ETFs."""
    liq = report_liquidity(data)
    return dict(zip(liq["symbol"], liq["liquidity_rank"]))


def rank_today(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Today's live rank table — closest to 52-week low = rank 1. Includes
    SMA20/50/200, RSI(14), and liquidity rank (across the FULL 65-ETF
    universe, not just this table's rows) for each qualifying ETF."""
    liquidity_ranks = compute_liquidity_ranks(data)
    rows = []
    for code, df in data.items():
        if df.empty or len(df) < 2:
            continue
        last = df.iloc[-1]
        prev = df.iloc[-2]
        pct = last["PCT_ABOVE_52W_LOW"]
        if pd.isna(pct) or pct < 0:
            continue
        low_52w = float(df["Low"].tail(LOOKBACK_52W).min())
        day_chg_pct = (float(last["Close"]) / float(prev["Close"]) - 1) * 100 if float(prev["Close"]) else None

        def _fnum(v):
            return round(float(v), 2) if pd.notna(v) else None

        rows.append({
            "symbol": code, "underlying_asset": ETF_UNDERLYING_ASSET.get(code, code),
            "close": round(float(last["Close"]), 2), "low_52w": round(low_52w, 2),
            "pct_above_52w_low": round(float(pct), 2),
            "volume": int(last["Volume"]) if pd.notna(last["Volume"]) else None,
            "day_change_pct": round(day_chg_pct, 2) if day_chg_pct is not None else None,
            "sma20": _fnum(last.get("SMA20")), "sma50": _fnum(last.get("SMA50")),
            "sma200": _fnum(last.get("SMA200")), "rsi14": _fnum(last.get("RSI14")),
            "liquidity_rank": liquidity_ranks.get(code),
        })
    out = pd.DataFrame(rows).sort_values("pct_above_52w_low").reset_index(drop=True)
    out["rank"] = out.index + 1
    return out


def decide_todays_action(
    data: dict[str, pd.DataFrame],
    open_positions: list[dict],
    total_capital: float | None = None,
    deployed_capital: float | None = None,
    liquidity_rank_max: int | None = LIQUIDITY_RANK_MAX,
    capital_deploy_cap_pct: float = CAPITAL_DEPLOY_CAP_PCT,
) -> dict | None:
    """
    Same rank-1-to-10 / skip-already-held / averaging-on-3.14%-drop logic as
    the backtest's entry step, applied to TODAY's live rank against the
    CURRENT persisted open-position set. Two live-only guardrails layer on
    top (both no-ops if their inputs aren't supplied, so callers that just
    want the raw video rule — e.g. anything testing against the pure
    backtest logic — are unaffected):

      1. CAPITAL CAP: if deployed_capital/total_capital are both given and
         deployed_capital already exceeds capital_deploy_cap_pct% of
         total_capital, skip immediately — no rank/averaging logic runs at
         all, since there's no real capital left to safely deploy.
      2. LIQUIDITY FILTER: if liquidity_rank_max is given, any rank-1-10
         candidate whose liquidity_rank is worse (a bigger number) than
         liquidity_rank_max is skipped over for BOTH new-entry and
         averaging — a low-volume ETF hitting its "target" on paper doesn't
         mean it can actually be exited there without slippage.

    Returns {"action": "NEW_ENTRY"|"AVERAGE"|"SKIP", "symbol": str|None, "reason": str}.
    """
    if total_capital is not None and deployed_capital is not None:
        deployed_pct = (deployed_capital / total_capital * 100) if total_capital else 0
        if deployed_pct >= capital_deploy_cap_pct:
            return {"action": "SKIP", "symbol": None,
                    "reason": f"Capital cap reached: Rs {deployed_capital:,.0f} of Rs {total_capital:,.0f} "
                              f"already deployed ({deployed_pct:.1f}% >= {capital_deploy_cap_pct:.0f}% cap) — "
                              f"no new purchase today regardless of signal."}

    ranked = rank_today(data)
    held_symbols = {p["symbol"] for p in open_positions}
    top_ranks = ranked.head(RANK_DEPTH)

    def _liquid_enough(row) -> bool:
        if liquidity_rank_max is None:
            return True
        lr = row.get("liquidity_rank")
        return pd.notna(lr) and lr <= liquidity_rank_max

    skipped_illiquid = []
    for _, row in top_ranks.iterrows():
        if row["symbol"] not in held_symbols:
            if not _liquid_enough(row):
                skipped_illiquid.append(row["symbol"])
                continue
            return {"action": "NEW_ENTRY", "symbol": row["symbol"],
                     "reason": f"Rank {int(row['rank'])}, {row['pct_above_52w_low']:.2f}% above 52w low, "
                               f"liquidity rank {int(row['liquidity_rank'])} — not currently held."}

    candidates = []
    for _, row in top_ranks.iterrows():
        code = row["symbol"]
        held = next((p for p in open_positions if p["symbol"] == code), None)
        if held is None:
            continue
        if not _liquid_enough(row):
            skipped_illiquid.append(code)
            continue
        df = data.get(code)
        if df is None or df.empty:
            continue
        cur_close = float(df.iloc[-1]["Close"])
        last_buy = held["last_buy_price"]
        drop_pct = (last_buy - cur_close) / last_buy * 100 if last_buy else 0
        if drop_pct >= AVERAGE_DROP_PCT:
            candidates.append((code, drop_pct))

    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        code, drop = candidates[0]
        return {"action": "AVERAGE", "symbol": code,
                "reason": f"All liquid rank 1-{RANK_DEPTH} already held; {code} has fallen {drop:.2f}% "
                          f"since last buy (>= {AVERAGE_DROP_PCT}% threshold) — averaging in."}

    illiquid_note = (f" ({len(set(skipped_illiquid))} candidate(s) skipped for being outside the top "
                      f"{liquidity_rank_max} most liquid ETFs)" if skipped_illiquid else "")
    return {"action": "SKIP", "symbol": None,
            "reason": f"All rank 1-{RANK_DEPTH} already held or too illiquid, none eligible has fallen "
                      f"{AVERAGE_DROP_PCT}%+ since last buy — no purchase today{illiquid_note}."}


def check_exits(data: dict[str, pd.DataFrame], open_positions: list[dict],
                 target_pct: float = LIVE_TARGET_PCT) -> list[dict]:
    """Which open positions touched their profit target TODAY (High-based
    limit-fill check, same convention as backend/calculations/hm_backtest.py)."""
    exits = []
    for pos in open_positions:
        df = data.get(pos["symbol"])
        if df is None or df.empty:
            continue
        bar = df.iloc[-1]
        target_price = pos["avg_price"] * (1 + target_pct / 100)
        if float(bar["High"]) >= target_price:
            units = pos["units"]
            pnl_pct = (target_price / pos["avg_price"] - 1) * 100
            pnl_rs = units * (target_price - pos["avg_price"])
            exits.append({
                "symbol": pos["symbol"], "exit_price": round(target_price, 2),
                "units": units, "avg_entry_price": pos["avg_price"],
                "pnl_pct": round(pnl_pct, 2), "pnl_rs": round(pnl_rs, 2),
                "n_buys": pos.get("n_buys", 1), "first_buy_date": pos.get("first_buy_date"),
            })
    return exits


def run_backtest(data: dict[str, pd.DataFrame], target_pct: float, capital: float,
                  capital_parts: int = CAPITAL_PARTS) -> dict:
    """Full walk-forward backtest — identical logic to scripts/etf_shop_backtest.py's
    run_backtest(), reproduced here so the page's Backtest Results tab doesn't
    depend on importing a standalone script."""
    all_dates = sorted(set().union(*[set(df.index) for df in data.values()]))
    calendar = pd.DatetimeIndex(all_dates)
    part_size = capital / capital_parts

    holdings: dict[str, dict] = {}
    trades = []
    peak_capital_deployed = 0.0
    skip_days = 0

    for t_idx in range(LOOKBACK_52W, len(calendar) - 1):
        today = calendar[t_idx]

        for code in list(holdings.keys()):
            df = data.get(code)
            if df is None or today not in df.index:
                continue
            bar = df.loc[today]
            avg_price = holdings[code]["avg_price"]
            target_price = avg_price * (1 + target_pct / 100)
            if float(bar["High"]) >= target_price:
                units = holdings[code]["units"]
                proceeds = units * target_price
                cost = units * avg_price
                trades.append({
                    "symbol": code, "entry_dates": holdings[code]["buy_dates"],
                    "exit_date": today.date(), "units": units,
                    "avg_entry_price": round(avg_price, 2), "exit_price": round(target_price, 2),
                    "pnl_pct": round((target_price / avg_price - 1) * 100, 2),
                    "pnl_rs": round(proceeds - cost, 2),
                    "hold_days": (today - holdings[code]["buy_dates"][0]).days,
                    "n_buys": len(holdings[code]["buy_dates"]),
                })
                del holdings[code]

        next_day = calendar[t_idx + 1]
        ranked = []
        for code, df in data.items():
            if today not in df.index:
                continue
            pct = df.loc[today, "PCT_ABOVE_52W_LOW"]
            if pd.isna(pct) or pct < 0:
                continue
            ranked.append((code, float(pct)))
        ranked.sort(key=lambda x: x[1])
        top_ranks = ranked[:RANK_DEPTH]

        buy_code = None
        for code, _ in top_ranks:
            if code not in holdings:
                buy_code = code
                break

        if buy_code is None:
            candidates = []
            for code, _ in top_ranks:
                if code not in holdings:
                    continue
                df = data.get(code)
                if df is None or today not in df.index:
                    continue
                cur_close = float(df.loc[today, "Close"])
                last_buy = holdings[code]["last_buy_price"]
                drop_pct = (last_buy - cur_close) / last_buy * 100
                if drop_pct >= AVERAGE_DROP_PCT:
                    candidates.append((code, drop_pct))
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                buy_code = candidates[0][0]

        if buy_code is not None:
            df = data[buy_code]
            if next_day in df.index:
                entry_price = float(df.loc[next_day, "Open"])
                if entry_price > 0:
                    units = part_size / entry_price
                    if buy_code in holdings:
                        h = holdings[buy_code]
                        total_units = h["units"] + units
                        h["avg_price"] = (h["avg_price"] * h["units"] + entry_price * units) / total_units
                        h["units"] = total_units
                        h["last_buy_price"] = entry_price
                        h["buy_dates"].append(next_day)
                    else:
                        holdings[buy_code] = {"units": units, "avg_price": entry_price,
                                               "last_buy_price": entry_price, "buy_dates": [next_day]}
        else:
            skip_days += 1

        deployed = sum(h["units"] * h["avg_price"] for h in holdings.values())
        peak_capital_deployed = max(peak_capital_deployed, deployed)

    trades_df = pd.DataFrame(trades)
    open_positions = [{"symbol": c, "units": round(h["units"], 2), "avg_price": round(h["avg_price"], 2),
                        "n_buys": len(h["buy_dates"]), "first_buy": h["buy_dates"][0].date()}
                       for c, h in holdings.items()]
    return {
        "trades": trades_df, "open_positions": open_positions,
        "peak_capital_deployed": peak_capital_deployed, "skip_days": skip_days,
        "capital_parts_used_at_peak": peak_capital_deployed / part_size if part_size else 0,
    }
