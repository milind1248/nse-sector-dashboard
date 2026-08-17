from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

st.set_page_config(page_title="ETF Shop | NSE Market Sector", layout="wide")

from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.seo import inject_seo
inject_seo("ETFShop")
from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("ETF Shop")

import pandas as pd
import pytz as _pytz

from backend.calculations.etf_shop import (
    fetch_universe, rank_today, decide_todays_action, report_liquidity, run_backtest,
    PI_TARGETS, LIVE_TARGET_PCT, ETF_UNDERLYING_ASSET,
)
from backend.storage import etf_shop_db as db

_IST = _pytz.timezone("Asia/Kolkata")


@st.cache_data(ttl=1800, show_spinner=False)
def _run_universe_fetch(years: float) -> tuple:
    data = fetch_universe(years=years)
    fetch_ts = pd.Timestamp.now(tz=_IST)
    return data, fetch_ts


@st.cache_data(ttl=3600, show_spinner=False)
def _run_backtest_all(years: float, capital: float) -> tuple:
    data, _ = _run_universe_fetch(years)
    results = {label: run_backtest(data, pct, capital) for label, pct in PI_TARGETS.items()}
    fetch_ts = pd.Timestamp.now(tz=_IST)
    return results, fetch_ts


# ─── Page title & disclaimer ─────────────────────────────────────────────────
st.title("🛒 ETF Shop")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption(
    "Rank-by-52-week-low swing strategy across 65 curated equity ETFs (debt/liquid/bond/G-Sec ETFs "
    "excluded). Buy at most one ETF per day — walk rank 1 to 10, skip anything already held; if all "
    "10 are already held, average into whichever has fallen 3.14% or more since its last buy. Sell "
    "the full position when it closes at/above avg. price + 6.28% (2×π — the live book's target). "
    "**Honest backtest disclosure (5y, 65-ETF universe):** net return of +64% to +85% depending on "
    "target (3.14%/4.71%/6.28%), but capital deployed at peak ran **1.4x to 1.9x over** the "
    "strategy's own stated '40 parts' capital budget — a real risk if you follow the video's capital "
    "sizing literally. There is no stop-loss: every closed trade shows a 100% win rate by "
    "construction (it only closes AT its target), and the real risk sits entirely in open positions "
    "that haven't hit target yet, some held for many months. Educational discovery tool, not a "
    "recommendation to buy or sell."
)

tab_signal, tab_log, tab_backtest = st.tabs(["🎯 Today's Signal", "📖 Trade Log", "📊 Backtest Results"])

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — TODAY'S SIGNAL
# ═════════════════════════════════════════════════════════════════════════════
with tab_signal:
    run_scan = st.button("▶ Refresh Today's Rank & Signal", type="primary", key="run_etf_shop_scan_btn")

    if run_scan:
        _run_universe_fetch.clear()
        with st.spinner("Fetching 65 ETFs and computing today's rank..."):
            data, fetch_ts = _run_universe_fetch(5.0)
        st.session_state["etf_shop_data_ts"] = fetch_ts
        st.session_state["etf_shop_rank"] = rank_today(data)
        st.session_state["etf_shop_decision"] = decide_todays_action(data, db.list_open_positions())

    fetch_ts = st.session_state.get("etf_shop_data_ts")
    if fetch_ts is not None:
        age_mins = int((pd.Timestamp.now(tz=_IST) - fetch_ts).total_seconds() // 60)
        st.caption(f"📡 Scanned at **{fetch_ts.strftime('%d-%b-%Y %H:%M:%S')} IST** · "
                   f"{age_mins} min ago · Cache refreshes every 30 min on next Run")

    decision = st.session_state.get("etf_shop_decision")
    if decision is not None:
        icon = {"NEW_ENTRY": "🟢", "AVERAGE": "🟡", "SKIP": "⚪"}.get(decision["action"], "")
        st.markdown(f"### {icon} Today's Action: **{decision['action']}**"
                    + (f" — {decision['symbol']}" if decision["symbol"] else ""))
        st.caption(decision["reason"])

    rank_df = st.session_state.get("etf_shop_rank")
    _rank_required_cols = {"rank", "symbol", "underlying_asset", "close", "low_52w",
                            "pct_above_52w_low", "volume", "day_change_pct",
                            "sma20", "sma50", "sma200", "rsi14", "liquidity_rank"}
    if rank_df is not None and not rank_df.empty and not _rank_required_cols.issubset(rank_df.columns):
        # Stale session-state from before a column set was added — clear and
        # prompt a fresh scan instead of crashing (same guard pattern used on
        # HM Scanner's Positional Setup tab).
        st.session_state.pop("etf_shop_rank", None)
        st.session_state.pop("etf_shop_decision", None)
        st.session_state.pop("etf_shop_data_ts", None)
        rank_df = None
        st.info("Rank data format was updated — click **Refresh Today's Rank & Signal** above to reload.")

    _ETF_TABLE_COLS = ["rank_display", "symbol", "underlying_asset", "close", "low_52w",
                        "pct_above_52w_low", "volume", "day_change_pct",
                        "sma20", "sma50", "sma200", "rsi14", "liquidity_rank"]
    _ETF_TABLE_RENAME = {
        "rank_display": "Rank", "symbol": "Symbol", "underlying_asset": "Underlying Asset",
        "close": "Close", "low_52w": "52W Low", "pct_above_52w_low": "% Above 52W Low",
        "volume": "Volume", "day_change_pct": "% Change", "sma20": "20 MA", "sma50": "50 MA",
        "sma200": "200 MA", "rsi14": "RSI", "liquidity_rank": "Liquidity Rank",
    }
    _GREEN = "color:#00C853;font-weight:600"
    _RED = "color:#D50000"

    def _style_ma_rsi_row(row):
        styles = pd.Series("", index=row.index)
        close = row.get("Close")
        if pd.notna(close):
            for col in ("20 MA", "50 MA", "200 MA"):
                ma = row.get(col)
                if pd.notna(ma):
                    styles[col] = _GREEN if close > ma else _RED
        rsi = row.get("RSI")
        if pd.notna(rsi):
            styles["RSI"] = _GREEN if rsi > 50 else _RED
        return styles

    def _render_etf_table(df: pd.DataFrame, rank_col_source: str):
        show = df.reindex(columns=_ETF_TABLE_COLS[1:] + [rank_col_source])
        show = show.rename(columns={rank_col_source: "rank_display"})[_ETF_TABLE_COLS]
        show = show.rename(columns=_ETF_TABLE_RENAME)
        st.dataframe(
            show.style
                .apply(_style_ma_rsi_row, axis=1)
                .format({"Close": "₹{:,.2f}", "52W Low": "₹{:,.2f}", "% Above 52W Low": "{:.2f}%",
                          "Volume": "{:,.0f}", "% Change": "{:+.2f}%", "20 MA": "₹{:,.2f}",
                          "50 MA": "₹{:,.2f}", "200 MA": "₹{:,.2f}", "RSI": "{:.1f}",
                          "Liquidity Rank": "{:.0f}"}, na_rep="—"),
            width='stretch', hide_index=True,
        )

    if rank_df is not None and not rank_df.empty:
        st.markdown("##### Top 10 by proximity to 52-week low")
        st.caption("20/50/200 MA and RSI columns are green when Close is above that MA (RSI green when >50).")
        _render_etf_table(rank_df.head(10), "rank")
    elif run_scan:
        st.info("No usable rank data — try again.")

    if rank_df is not None and not rank_df.empty and "day_change_pct" in rank_df.columns:
        st.markdown("##### 📉 Top 10 Biggest Fallers Today")
        st.caption("Matches the sheet's 'Details on which is more down' table — sorted by today's "
                   "% change (most negative first), useful for spotting averaging-down candidates "
                   "among ETFs that have fallen 3.14%+ since your last buy.")
        fallers_df = rank_df.dropna(subset=["day_change_pct"]).sort_values("day_change_pct").head(10).copy()
        fallers_df["faller_rank"] = range(1, len(fallers_df) + 1)
        _render_etf_table(fallers_df, "faller_rank")

    st.markdown("---")
    st.markdown("##### Current Open Positions (live, from the tracked book)")
    open_positions = db.list_open_positions()
    if not open_positions:
        st.info("No open positions yet — the daily scheduler job (8:15 PM IST Mon-Fri) will populate this "
                "once it makes its first purchase.")
    else:
        data_for_mtm = st.session_state.get("etf_shop_last_fetch_data")
        rows = []
        for p in open_positions:
            rows.append({
                "Symbol": p["symbol"], "Units": round(p["units"], 2), "Avg Price": p["avg_price"],
                "Target Price (6.28%)": round(p["avg_price"] * (1 + LIVE_TARGET_PCT / 100), 2),
                "First Buy": p["first_buy_date"], "N Buys": p["n_buys"],
            })
        st.dataframe(pd.DataFrame(rows).style.format({"Avg Price": "₹{:,.2f}", "Target Price (6.28%)": "₹{:,.2f}"}),
                     width='stretch', hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — TRADE LOG (closed + open, cook-once DB read)
# ═════════════════════════════════════════════════════════════════════════════
with tab_log:
    age = db.last_update_age_days()
    if age is None:
        st.info("No trade history yet — the daily scheduler job (8:15 PM IST Mon-Fri) will populate "
                "this tab once it runs for the first time.")
    else:
        if age == 0:
            st.caption("✅ Book updated **today**.")
        elif age <= 2:
            st.caption(f"✅ Last updated **{age} day(s) ago**.")
        else:
            st.caption(f"⚠️ Last updated **{age} day(s) ago** — scheduler may be offline.")

    st.markdown("##### 🚪 Closed Trades")
    closed = db.list_closed_trades()
    if not closed:
        st.info("No closed trades yet.")
    else:
        closed_df = pd.DataFrame(closed)
        m1, m2, m3 = st.columns(3)
        m1.metric("Closed Trades", len(closed_df))
        m2.metric("Total Realized P&L", f"₹{closed_df['pnl_rs'].sum():,.0f}")
        m3.metric("Win Rate", f"{(closed_df['pnl_pct'] > 0).mean() * 100:.0f}%")
        show_cols = ["symbol", "entry_date", "exit_date", "hold_days", "avg_entry_price",
                     "exit_price", "pnl_pct", "pnl_rs", "n_buys"]
        st.dataframe(
            closed_df[show_cols].rename(columns={
                "symbol": "Symbol", "entry_date": "Entry Date", "exit_date": "Exit Date",
                "hold_days": "Hold Days", "avg_entry_price": "Avg Entry", "exit_price": "Exit Price",
                "pnl_pct": "P&L %", "pnl_rs": "P&L ₹", "n_buys": "N Buys",
            }).style.format({"Avg Entry": "₹{:,.2f}", "Exit Price": "₹{:,.2f}",
                              "P&L %": "{:+.2f}%", "P&L ₹": "₹{:,.0f}"}),
            width='stretch', hide_index=True,
        )

    st.markdown("---")
    st.markdown("##### 📂 Open Trades")
    open_positions = db.list_open_positions()
    if not open_positions:
        st.info("No open positions.")
    else:
        open_df = pd.DataFrame(open_positions)
        open_df["target_price"] = open_df["avg_price"] * (1 + LIVE_TARGET_PCT / 100)
        st.metric("Open Positions", len(open_df))
        st.dataframe(
            open_df[["symbol", "units", "avg_price", "target_price", "first_buy_date", "n_buys"]]
                .rename(columns={"symbol": "Symbol", "units": "Units", "avg_price": "Avg Price",
                                  "target_price": "Target (6.28%)", "first_buy_date": "First Buy",
                                  "n_buys": "N Buys"})
                .style.format({"Avg Price": "₹{:,.2f}", "Target (6.28%)": "₹{:,.2f}", "Units": "{:.2f}"}),
            width='stretch', hide_index=True,
        )


# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — BACKTEST RESULTS (button-triggered, all 3 Pi targets)
# ═════════════════════════════════════════════════════════════════════════════
with tab_backtest:
    c1, c2 = st.columns(2)
    with c1:
        bt_years = st.slider("Backtest years", min_value=2.0, max_value=6.0, value=5.0, step=0.5, key="etf_bt_years")
    with c2:
        bt_capital = st.number_input("Starting capital (₹)", min_value=50_000, max_value=5_000_000,
                                      value=200_000, step=50_000, key="etf_bt_capital")

    run_bt = st.button("▶ Run Backtest (all 3 targets)", type="primary", key="run_etf_shop_bt_btn")

    if run_bt:
        _run_backtest_all.clear()
        with st.spinner("Fetching 65 ETFs and running walk-forward backtest for all 3 targets "
                         "(this can take a few minutes)..."):
            results, fetch_ts = _run_backtest_all(bt_years, float(bt_capital))
        st.session_state["etf_shop_bt_results"] = results
        st.session_state["etf_shop_bt_ts"] = fetch_ts

    results = st.session_state.get("etf_shop_bt_results")
    fetch_ts_bt = st.session_state.get("etf_shop_bt_ts")

    if fetch_ts_bt is not None:
        st.caption(f"📡 Backtest run at **{fetch_ts_bt.strftime('%d-%b-%Y %H:%M:%S')} IST**")

    if results:
        summary_rows = []
        for label, r in results.items():
            n_closed = len(r["trades"])
            pnl = r["trades"]["pnl_rs"].sum() if not r["trades"].empty else 0
            n_open = len(r["open_positions"])
            parts = r["capital_parts_used_at_peak"]
            summary_rows.append({"Target": label, "Closed Trades": n_closed, "Realized P&L (₹)": round(pnl, 0),
                                  "Open Positions": n_open, "Peak Capital Parts Used (of 40)": round(parts, 1)})
        st.markdown("##### Summary — all 3 targets")
        st.dataframe(pd.DataFrame(summary_rows).style.format({"Realized P&L (₹)": "₹{:,.0f}"}),
                     width='stretch', hide_index=True)

        st.markdown("---")
        st.markdown("##### Liquidity / Volume (last 60 trading days)")
        data_cached, _ = _run_universe_fetch(bt_years)
        liq = report_liquidity(data_cached)
        st.dataframe(
            liq.style.format({"avg_traded_value_cr_60d": "₹{:.2f} Cr", "avg_price": "₹{:,.2f}"}),
            width='stretch', hide_index=True, height=400,
        )

        st.markdown("---")
        st.markdown("##### 🔍 Deep Dive — every entry & exit for one symbol")
        st.caption("Answers: if I'd bought this ETF whenever the strategy signalled it, how many days "
                   "did it actually take to hit the profit target each time (and did it vary trade to "
                   "trade)?")
        dc1, dc2 = st.columns(2)
        with dc1:
            target_label = st.selectbox("Target", list(results.keys()),
                                         index=list(results.keys()).index("6.28% (2xPi)")
                                         if "6.28% (2xPi)" in results else 0,
                                         key="etf_deep_dive_target")
        target_trades = results[target_label]["trades"]
        target_open = results[target_label]["open_positions"]
        all_symbols = sorted(set(target_trades["symbol"]).union({p["symbol"] for p in target_open})) \
            if not target_trades.empty or target_open else []
        with dc2:
            symbol_pick = st.selectbox("Symbol", all_symbols, key="etf_deep_dive_symbol") if all_symbols else None

        if symbol_pick:
            sym_trades = target_trades[target_trades["symbol"] == symbol_pick].sort_values("exit_date").copy()
            sym_open = [p for p in target_open if p["symbol"] == symbol_pick]

            if not sym_trades.empty:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Completed Trades", len(sym_trades))
                m2.metric("Avg Days to Target", f"{sym_trades['hold_days'].mean():.0f}")
                m3.metric("Fastest / Slowest", f"{sym_trades['hold_days'].min()} / {sym_trades['hold_days'].max()} days")
                m4.metric("Total Realized P&L", f"₹{sym_trades['pnl_rs'].sum():,.0f}")

                display_trades = sym_trades.copy()
                display_trades["first_entry"] = display_trades["entry_dates"].apply(
                    lambda d: d[0].date() if isinstance(d, list) and d else None)
                display_trades["all_entries"] = display_trades["entry_dates"].apply(
                    lambda d: ", ".join(str(x.date()) for x in d) if isinstance(d, list) else "")
                show_cols = ["first_entry", "exit_date", "hold_days", "n_buys", "avg_entry_price",
                             "exit_price", "pnl_pct", "pnl_rs", "all_entries"]
                st.dataframe(
                    display_trades[show_cols].rename(columns={
                        "first_entry": "First Entry", "exit_date": "Exit Date", "hold_days": "Days to Target",
                        "n_buys": "N Buys (incl. averaging)", "avg_entry_price": "Avg Entry Price",
                        "exit_price": "Exit Price (Target)", "pnl_pct": "P&L %", "pnl_rs": "P&L ₹",
                        "all_entries": "All Buy Dates",
                    }).style.format({"Avg Entry Price": "₹{:,.2f}", "Exit Price (Target)": "₹{:,.2f}",
                                      "P&L %": "{:+.2f}%", "P&L ₹": "₹{:,.0f}"}),
                    width='stretch', hide_index=True,
                )
            else:
                st.info(f"No completed (target-hit) trades for {symbol_pick} at this target in the "
                        f"backtest window — see below if it's still an open position.")

            if sym_open:
                p = sym_open[0]
                st.warning(
                    f"⚠️ **{symbol_pick} was still an OPEN position at the end of the backtest** "
                    f"(bought {p['first_buy']}, {p['n_buys']} buy(s), avg price ₹{p['avg_price']:,.2f}) — "
                    f"it had NOT reached its {PI_TARGETS[target_label]:.2f}% target by the last day of "
                    f"the backtest window. This is exactly the real risk this page's own disclaimer "
                    f"flags: not every trade resolves in a predictable number of days — some just sit "
                    f"open indefinitely waiting for the target."
                )

        st.markdown("---")
        st.markdown("##### ⚡ Fastest-to-Target ETFs — quick-turnover ranking")
        st.caption(
            "Ranks every ETF that had at least one COMPLETED (target-hit) trade at the selected "
            "target, by average days-to-target — fastest first. Useful for picking ETFs that "
            "historically cycled quick profits rather than sitting open for months. Every completed "
            "trade in this table always hit its full target % (that's what 'completed' means here) — "
            "the difference between rows is purely SPEED, not size of profit. Symbols with only 1-2 "
            "trades are a much less reliable speed estimate than ones with 5+ — check the Trades "
            "column before trusting a fast average."
        )
        speed_target_label = st.selectbox(
            "Target", list(results.keys()),
            index=list(results.keys()).index("6.28% (2xPi)") if "6.28% (2xPi)" in results else 0,
            key="etf_speed_target",
        )
        speed_trades = results[speed_target_label]["trades"]
        if speed_trades.empty:
            st.info("No completed trades at this target in the backtest window.")
        else:
            speed_agg = speed_trades.groupby("symbol").agg(
                trades=("hold_days", "count"), avg_days=("hold_days", "mean"),
                median_days=("hold_days", "median"), fastest_days=("hold_days", "min"),
                slowest_days=("hold_days", "max"), total_pnl_rs=("pnl_rs", "sum"),
            ).reset_index()
            speed_agg["underlying_asset"] = speed_agg["symbol"].map(ETF_UNDERLYING_ASSET).fillna(speed_agg["symbol"])
            speed_agg = speed_agg.merge(
                liq[["symbol", "liquidity_rank", "avg_traded_value_cr_60d"]], on="symbol", how="left")
            speed_agg = speed_agg.sort_values("avg_days").reset_index(drop=True)
            speed_agg["rank"] = speed_agg.index + 1
            show_speed_cols = ["rank", "symbol", "underlying_asset", "trades", "avg_days",
                               "median_days", "fastest_days", "slowest_days", "total_pnl_rs",
                               "liquidity_rank", "avg_traded_value_cr_60d"]
            st.dataframe(
                speed_agg[show_speed_cols].rename(columns={
                    "rank": "Rank", "symbol": "Symbol", "underlying_asset": "Underlying Asset",
                    "trades": "Trades", "avg_days": "Avg Days to Target", "median_days": "Median Days",
                    "fastest_days": "Fastest (days)", "slowest_days": "Slowest (days)",
                    "total_pnl_rs": "Total P&L ₹", "liquidity_rank": "Liquidity Rank",
                    "avg_traded_value_cr_60d": "Avg Traded Value (₹Cr/day)",
                }).style.format({"Avg Days to Target": "{:.0f}", "Median Days": "{:.0f}",
                                  "Total P&L ₹": "₹{:,.0f}", "Liquidity Rank": "{:.0f}",
                                  "Avg Traded Value (₹Cr/day)": "₹{:.2f} Cr"}, na_rep="—"),
                width='stretch', hide_index=True, height=450,
            )
    elif run_bt:
        st.info("No backtest results — try again.")
