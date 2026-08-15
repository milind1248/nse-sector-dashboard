"""
"ETF Shop 2025" strategy — Mahesh Chandra Kaushik (SEBI RA), YouTube video.
Powers app/pages/27_🛒_ETF_Shop.py. Streamlit-free (matches every other
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
CAPITAL_PARTS = 40
RANK_DEPTH = 10
LOOKBACK_52W = 252

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


def fetch_symbol(symbol: str, period: str) -> pd.DataFrame:
    df = yf.download(symbol + ".NS", period=period, interval="1d", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(how="all")


def fetch_universe(years: float = 5.0) -> dict[str, pd.DataFrame]:
    period = f"{max(1, round(years)) + 1}y"
    data = {}
    for code in ETF_UNIVERSE:
        try:
            df = fetch_symbol(code, period)
            if len(df) > LOOKBACK_52W + 30:
                df["PCT_ABOVE_52W_LOW"] = (df["Close"] - df["Low"].rolling(LOOKBACK_52W).min()) / \
                                           df["Low"].rolling(LOOKBACK_52W).min() * 100
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
    return pd.DataFrame(rows).sort_values("avg_traded_value_cr_60d", ascending=False)


def rank_today(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Today's live rank table — closest to 52-week low = rank 1."""
    rows = []
    for code, df in data.items():
        if df.empty:
            continue
        last = df.iloc[-1]
        pct = last["PCT_ABOVE_52W_LOW"]
        if pd.isna(pct) or pct < 0:
            continue
        rows.append({"symbol": code, "close": round(float(last["Close"]), 2),
                     "pct_above_52w_low": round(float(pct), 2)})
    out = pd.DataFrame(rows).sort_values("pct_above_52w_low").reset_index(drop=True)
    out["rank"] = out.index + 1
    return out


def decide_todays_action(data: dict[str, pd.DataFrame], open_positions: list[dict]) -> dict | None:
    """
    Same rank-1-to-10 / skip-already-held / averaging-on-3.14%-drop logic as
    the backtest's entry step, applied to TODAY's live rank against the
    CURRENT persisted open-position set. Returns
    {"action": "NEW_ENTRY"|"AVERAGE"|"SKIP", "symbol": str|None, "reason": str}.
    """
    ranked = rank_today(data)
    held_symbols = {p["symbol"] for p in open_positions}
    top_ranks = ranked.head(RANK_DEPTH)

    for _, row in top_ranks.iterrows():
        if row["symbol"] not in held_symbols:
            return {"action": "NEW_ENTRY", "symbol": row["symbol"],
                     "reason": f"Rank {int(row['rank'])}, {row['pct_above_52w_low']:.2f}% above 52w low — "
                               f"not currently held."}

    candidates = []
    for _, row in top_ranks.iterrows():
        code = row["symbol"]
        held = next((p for p in open_positions if p["symbol"] == code), None)
        if held is None:
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
                "reason": f"All rank 1-{RANK_DEPTH} already held; {code} has fallen {drop:.2f}% "
                          f"since last buy (>= {AVERAGE_DROP_PCT}% threshold) — averaging in."}

    return {"action": "SKIP", "symbol": None,
            "reason": f"All rank 1-{RANK_DEPTH} already held, none has fallen {AVERAGE_DROP_PCT}%+ "
                      f"since last buy — no purchase today."}


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
