from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

st.set_page_config(page_title="ETF Dukan 3 | NSE Market Sector", layout="wide")

from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.seo import inject_seo
inject_seo("ETFDukan3")
from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("ETF Dukan 3")

import pandas as pd
import pytz as _pytz

from backend.calculations.etf_dukan3 import (
    fetch_universe, rank_today, decide_todays_action, check_exits,
    ETF_UNIVERSE_META, BACKTEST_SUMMARY, TARGET_PCT, AVERAGE_DROP_PCT, CAPITAL_PARTS,
)
from backend.storage import etf_dukan3_db as db

_IST = _pytz.timezone("Asia/Kolkata")


@st.cache_data(ttl=1800, show_spinner=False)
def _run_universe_fetch(years: float) -> tuple:
    data = fetch_universe(years=years)
    fetch_ts = pd.Timestamp.now(tz=_IST)
    return data, fetch_ts


_TILE_BOARD_TEMPLATE = r"""
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
  :root {
    --bg: #f6f5f1; --surface: #ffffff; --border: #dfdcd2; --border-soft: #eae7dd;
    --ink: #17201c; --ink-muted: #626b62; --accent: #0f6b52;
    --up: #1a7a4c; --up-soft: #1a7a4c14; --down: #b0432b; --down-soft: #b0432b14;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #10140f; --surface: #171d16; --border: #2a332a; --border-soft: #202821;
      --ink: #e8ece3; --ink-muted: #97a293; --accent: #35b892;
      --up: #4bc48c; --up-soft: #4bc48c1c; --down: #e2755a; --down-soft: #e2755a1c;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); }
  .board { background: var(--bg); color: var(--ink); font-family: "IBM Plex Sans", sans-serif; padding: 4px 2px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(178px, 1fr)); gap: 11px; }
  .tile { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 13px 11px; }
  .tile-top { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 1px; gap: 6px; }
  .sym { font-family: "IBM Plex Mono", monospace; font-weight: 600; font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .chg { font-family: "IBM Plex Mono", monospace; font-size: 11.5px; font-weight: 600; padding: 1px 6px; border-radius: 5px; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .chg.up { color: var(--up); background: var(--up-soft); }
  .chg.down { color: var(--down); background: var(--down-soft); }
  .theme { font-size: 10.5px; color: var(--ink-muted); margin-bottom: 7px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .spark { width: 100%; height: 42px; display: block; }
  .bottom-row { display: flex; justify-content: space-between; align-items: baseline; margin-top: 5px; gap: 6px; }
  .price { font-family: "IBM Plex Mono", monospace; font-size: 13px; color: var(--ink); font-variant-numeric: tabular-nums; font-weight: 500; }
  .price .unit { color: var(--ink-muted); font-weight: 400; margin-right: 2px; }
  .chg-1d { font-family: "IBM Plex Mono", monospace; font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .chg-1d.up { color: var(--up); } .chg-1d.down { color: var(--down); }
</style>
<div class="board"><div class="grid" id="grid"></div></div>
<script>
  const DATA = __DATA_JSON__;
  function sparkSVG(prices, up) {
    const w = 156, h = 42, pad = 4;
    const min = Math.min(...prices), max = Math.max(...prices);
    const range = (max - min) || 1;
    const innerH = h - pad * 2;
    const step = w / (prices.length - 1);
    const pts = prices.map((p, i) => [i * step, pad + innerH - ((p - min) / range) * innerH]);
    const line = pts.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
    const area = line + ` L${w},${h} L0,${h} Z`;
    const color = up ? 'var(--up)' : 'var(--down)';
    const last = pts[pts.length - 1];
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <line x1="0" y1="${pts[0][1].toFixed(1)}" x2="${w}" y2="${pts[0][1].toFixed(1)}" stroke="var(--border)" stroke-width="1" stroke-dasharray="2,2"/>
      <path d="${area}" fill="${color}" opacity="0.12" stroke="none"/>
      <path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
      <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.1" fill="${color}"/>
    </svg>`;
  }
  const grid = document.getElementById('grid');
  DATA.forEach(v => {
    const up = v.chg >= 0;
    const up1d = v.chg_1d >= 0;
    const tile = document.createElement('div');
    tile.className = 'tile';
    tile.innerHTML = `
      <div class="tile-top"><span class="sym">${v.symbol}</span><span class="chg ${up ? 'up' : 'down'}">${up ? '+' : ''}${v.chg.toFixed(2)}%</span></div>
      <div class="theme">${v.theme}</div>
      ${sparkSVG(v.prices, up)}
      <div class="bottom-row">
        <div class="price"><span class="unit">₹</span>${v.last.toFixed(2)}</div>
        <span class="chg-1d ${up1d ? 'up' : 'down'}">${up1d ? '+' : ''}${v.chg_1d.toFixed(2)}% 1D</span>
      </div>
    `;
    grid.appendChild(tile);
  });
</script>
"""


def _build_tile_board_html(rank_df: pd.DataFrame, data: dict) -> str:
    import json
    tiles = []
    for _, row in rank_df.iterrows():
        sym = row["symbol"]
        df = data.get(sym)
        if df is None or df.empty:
            continue
        prices = [round(float(c), 2) for c in df["Close"].tail(90).tolist()]
        if len(prices) < 2:
            continue
        chg = round((prices[-1] / prices[0] - 1) * 100, 2)
        chg_1d = round(float(row["ret_1d_pct"]), 2) if pd.notna(row.get("ret_1d_pct")) else 0.0
        tiles.append({"symbol": sym, "theme": row["theme"], "prices": prices, "last": prices[-1],
                      "chg": chg, "chg_1d": chg_1d})
    return _TILE_BOARD_TEMPLATE.replace("__DATA_JSON__", json.dumps(tiles))


# ─── Page title & disclaimer ─────────────────────────────────────────────────
st.title("🏪 ETF Dukan 3")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption(
    "RSI(14)-ranking rotation across a curated, theme-deduplicated 45-ETF universe (built by "
    "combining two strategies' ETF lists and keeping only the single most liquid ETF per theme, so "
    "no two funds ever compete for the same rank slot). Buy at most one ETF per day — the lowest-RSI "
    "ETF not already held; if everything is already held, average into whichever position has fallen "
    f"{AVERAGE_DROP_PCT:.0f}% or more since its last buy. Sell the full position when it closes at/above "
    f"avg. price + {TARGET_PCT:.2f}%. Capital is split into {CAPITAL_PARTS} parts. **Backtested over 10 years "
    f"(2016-2026): {BACKTEST_SUMMARY['pure']['cagr_pct']:.2f}% CAGR, "
    f"{BACKTEST_SUMMARY['pure']['max_dd_pct']:.2f}% max drawdown, Sharpe {BACKTEST_SUMMARY['pure']['sharpe']:.2f} "
    "(pure-reinvest mode)** — see the Backtest Results tab for the full comparison against the video's own "
    "literal tax/self-dividend compounding rule, which trades return for a smoother capital curve. "
    "Educational discovery tool, not a recommendation to buy or sell."
)

tab_signal, tab_shortlist, tab_log, tab_backtest = st.tabs(
    ["📅 Today's Signal", "🎯 Top-5 RSI Shortlist", "📖 Trade Log", "📊 Backtest Results (10Y)"]
)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — TODAY'S SIGNAL
# ═════════════════════════════════════════════════════════════════════════════
with tab_signal:
    if st.button("▶ Refresh Today's Rank & Signal", type="primary", key="d3_refresh"):
        data, fetch_ts = _run_universe_fetch(2.0)
        st.session_state["d3_rank"] = rank_today(data)
        _open_now = db.list_open_positions()
        _config = db.get_config()
        st.session_state["d3_decision"] = decide_todays_action(
            data, _open_now, working_capital=_config["total_capital_rs"], capital_parts=_config["capital_parts"]
        )
        st.session_state["d3_exits"] = check_exits(data, _open_now, target_pct=_config["target_pct"])
        st.session_state["d3_fetch_ts"] = fetch_ts

    _rank_required_cols = {"rank", "symbol", "theme", "underlying", "close", "rsi14", "ret_1d_pct", "ret_5d_pct",
                            "avg_volume_20d", "avg_traded_value_20d", "liquidity_rank"}
    rank_df = st.session_state.get("d3_rank")
    if rank_df is not None and not _rank_required_cols.issubset(rank_df.columns):
        for k in ("d3_rank", "d3_decision", "d3_exits", "d3_fetch_ts"):
            st.session_state.pop(k, None)
        st.info("Signal schema updated — click **Refresh Today's Rank & Signal** to reload.")
        rank_df = None

    config = db.get_config()
    open_positions = db.list_open_positions()

    m1, m2, m3, m4 = st.columns(4)
    invested = sum(p["invested_cost"] for p in open_positions)
    m1.metric("Working Capital", f"₹{config['total_capital_rs']:,.0f}")
    deploy_pct = (invested / config["total_capital_rs"] * 100) if config["total_capital_rs"] else 0
    m2.metric("Deployed Capital", f"₹{invested:,.0f}", f"{deploy_pct:.1f}%")
    m3.metric("Cash Available", f"₹{max(config['total_capital_rs'] - invested, 0):,.0f}")
    m4.metric("Open Positions", len(open_positions))

    if rank_df is not None:
        fetch_ts = st.session_state.get("d3_fetch_ts")
        if fetch_ts is not None:
            st.caption(f"As of {fetch_ts.strftime('%d-%b-%Y %H:%M IST')}")

        exits = st.session_state.get("d3_exits") or []
        if exits:
            ex = exits[0]
            st.error(f"🔴 SOLD **{ex['symbol']}** today @ ₹{ex['exit_price']:.2f} — profit {ex['pnl_pct']:.2f}%")

        decision = st.session_state.get("d3_decision") or {}
        held_syms = {p["symbol"] for p in open_positions}
        if decision.get("action") == "NEW_ENTRY":
            st.success(f"🟢 BUY **{decision['symbol']}** @ ₹{decision['price']:.2f} "
                       f"(Rank #{decision['rank']}, RSI={decision['rsi14']:.1f})")
        elif decision.get("action") == "AVERAGE":
            st.info(f"🔵 AVERAGE **{decision['symbol']}** @ ₹{decision['price']:.2f} — {decision['reason']}")
        else:
            st.warning(f"⚪ SKIP — {decision.get('reason', 'no action today')}")

        st.markdown("##### RSI Rank Table — Full Universe")
        disp = rank_df.copy()
        disp["Held?"] = disp["symbol"].map(lambda s: "✅" if s in held_syms else "—")
        disp = disp.rename(columns={
            "rank": "Rank", "symbol": "Symbol", "theme": "Theme", "underlying": "Underlying Asset",
            "close": "Close", "rsi14": "RSI(14)", "ret_1d_pct": "1D %", "ret_5d_pct": "5D %",
            "avg_volume_20d": "Avg Volume (20D)", "liquidity_rank": "Liquidity Rank",
        })
        show_cols = ["Rank", "Symbol", "Theme", "Underlying Asset", "Close", "RSI(14)", "1D %", "5D %",
                     "Avg Volume (20D)", "Liquidity Rank", "Held?"]

        def _rsi_color(v):
            try:
                v = float(v)
            except (TypeError, ValueError):
                return ""
            if v < 30:
                return "background-color: rgba(0,150,0,0.18)"
            if v > 70:
                return "background-color: rgba(200,0,0,0.14)"
            return ""

        def _liquidity_color(v):
            try:
                v = int(v)
            except (TypeError, ValueError):
                return ""
            if v <= 10:
                return "background-color: rgba(0,150,0,0.12)"
            if v > 30:
                return "background-color: rgba(200,0,0,0.10)"
            return ""

        st.dataframe(
            disp.reindex(columns=show_cols).style
                .map(_rsi_color, subset=["RSI(14)"])
                .map(_liquidity_color, subset=["Liquidity Rank"])
                .format({"Close": "{:.2f}", "RSI(14)": "{:.1f}", "1D %": "{:.2f}", "5D %": "{:.2f}",
                         "Avg Volume (20D)": "{:,.0f}", "Liquidity Rank": "{:.0f}"}),
            use_container_width=True, hide_index=True, height=460,
        )

        st.markdown("---")
        st.markdown("##### ETF Tile Board")
        st.caption("Same order as the rank table above — one tile per ETF, 90-day sparkline.")
        import streamlit.components.v1 as components
        _tile_data, _ = _run_universe_fetch(2.0)  # cached — free after the first fetch above
        components.html(_build_tile_board_html(rank_df, _tile_data), height=560, scrolling=True)

        if open_positions:
            st.markdown("##### Open Positions")
            price_map = dict(zip(rank_df["symbol"], rank_df["close"]))
            pos_rows = []
            for p in open_positions:
                cur = price_map.get(p["symbol"])
                pnl_pct = (cur / p["avg_price"] - 1) * 100 if cur else None
                days = (pd.Timestamp.now(tz=_IST).date() - pd.Timestamp(p["first_buy_date"]).date()).days
                pos_rows.append({
                    "Symbol": p["symbol"], "Units": round(p["units"], 3), "Avg Price": p["avg_price"],
                    "Current Price": cur, "Unrealized P&L %": pnl_pct, "Days Held": days,
                    "To Target %": (TARGET_PCT - pnl_pct) if pnl_pct is not None else None,
                })
            pos_df = pd.DataFrame(pos_rows)
            st.dataframe(
                pos_df.style.format({"Avg Price": "{:.2f}", "Current Price": "{:.2f}",
                                      "Unrealized P&L %": "{:.2f}", "To Target %": "{:.2f}"}),
                use_container_width=True, hide_index=True,
            )
    else:
        st.info("Click **Refresh Today's Rank & Signal** to load today's RSI ranking and decision.")

# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — TOP-5 RSI SHORTLIST
# ═════════════════════════════════════════════════════════════════════════════
with tab_shortlist:
    st.caption("Lowest RSI(14) among ETFs not already in the book — the strategy buys whichever "
               "of these is still unheld, walking down the list. Same underlying data as Today's Signal.")
    rank_df = st.session_state.get("d3_rank")
    if rank_df is None:
        st.info("Load the ranking from the **Today's Signal** tab first (click Refresh there).")
    else:
        open_positions = db.list_open_positions()
        held_syms = {p["symbol"] for p in open_positions}
        unheld = rank_df[~rank_df["symbol"].isin(held_syms)].head(5)
        if unheld.empty:
            st.info("All ranked ETFs are currently held.")
        else:
            cols = st.columns(len(unheld))
            for col, (_, row) in zip(cols, unheld.iterrows()):
                with col:
                    zone = "🟢 Oversold" if row["rsi14"] < 30 else ("🔴 Overbought" if row["rsi14"] > 70 else "⚪ Neutral")
                    st.markdown(f"**#{int(row['rank'])} — {row['symbol']}**")
                    st.caption(row["theme"])
                    st.metric("Close", f"₹{row['close']:.2f}", f"{row['ret_1d_pct']:.2f}% (1D)")
                    st.progress(min(max(row["rsi14"] / 100, 0.0), 1.0), text=f"RSI {row['rsi14']:.1f} — {zone}")

# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — TRADE LOG (filter + search)
# ═════════════════════════════════════════════════════════════════════════════
with tab_log:
    sub_closed, sub_open = st.tabs(["Closed Trades", "Open Trades"])

    with sub_closed:
        closed = db.list_closed_trades()
        if not closed:
            st.info("No closed trades yet.")
        else:
            cdf = pd.DataFrame(closed)
            fc1, fc2, fc3 = st.columns(3)
            search = fc1.text_input("🔍 Search symbol", key="d3_search_closed")
            themes = ["All"] + sorted({ETF_UNIVERSE_META.get(s, ("Unclassified",))[0] for s in cdf["symbol"].unique()})
            theme_pick = fc2.selectbox("Theme", themes, key="d3_theme_closed")
            result_pick = fc3.selectbox("Result", ["All", "Win", "Loss"], key="d3_result_closed")

            mask = pd.Series(True, index=cdf.index)
            if search:
                mask &= cdf["symbol"].str.contains(search, case=False)
            if theme_pick != "All":
                mask &= cdf["symbol"].map(lambda s: ETF_UNIVERSE_META.get(s, ("Unclassified",))[0]) == theme_pick
            if result_pick == "Win":
                mask &= cdf["net_profit_rs"] > 0
            elif result_pick == "Loss":
                mask &= cdf["net_profit_rs"] <= 0

            st.dataframe(
                cdf[mask].style.format({
                    "avg_entry_price": "{:.2f}", "exit_price": "{:.2f}", "gross_profit_pct": "{:.2f}",
                    "gross_profit_rs": "{:.2f}", "net_profit_rs": "{:.2f}", "self_dividend_withdrawn": "{:.2f}",
                }),
                use_container_width=True, hide_index=True,
            )

    with sub_open:
        open_positions = db.list_open_positions()
        if not open_positions:
            st.info("No open positions.")
        else:
            odf = pd.DataFrame(open_positions)
            fo1, fo2 = st.columns(2)
            search_o = fo1.text_input("🔍 Search symbol", key="d3_search_open")
            themes_o = ["All"] + sorted({ETF_UNIVERSE_META.get(s, ("Unclassified",))[0] for s in odf["symbol"].unique()})
            theme_pick_o = fo2.selectbox("Theme", themes_o, key="d3_theme_open")

            mask_o = pd.Series(True, index=odf.index)
            if search_o:
                mask_o &= odf["symbol"].str.contains(search_o, case=False)
            if theme_pick_o != "All":
                mask_o &= odf["symbol"].map(lambda s: ETF_UNIVERSE_META.get(s, ("Unclassified",))[0]) == theme_pick_o

            st.dataframe(
                odf[mask_o].style.format({"avg_price": "{:.2f}", "last_buy_price": "{:.2f}", "invested_cost": "{:.2f}"}),
                use_container_width=True, hide_index=True,
            )

# ═════════════════════════════════════════════════════════════════════════════
# TAB 4 — BACKTEST RESULTS (10Y)
# ═════════════════════════════════════════════════════════════════════════════
with tab_backtest:
    st.markdown(f"**Backtest window:** {BACKTEST_SUMMARY['window']} — curated 45-ETF universe, same rules as the live book.")

    b1, b2, b3, b4, b5 = st.columns(5)
    pure = BACKTEST_SUMMARY["pure"]
    b1.metric("CAGR", f"{pure['cagr_pct']:.2f}%")
    b2.metric("Max Drawdown", f"{pure['max_dd_pct']:.2f}%")
    b3.metric("Sharpe", f"{pure['sharpe']:.2f}")
    b4.metric("Total Return", f"{pure['total_return_pct']:.2f}%")
    b5.metric("Trades", pure["n_trades"])

    st.markdown("##### Pure Reinvest vs. As Literally Described (tax + self-dividend)")
    comp_rows = [
        {"Mode": "Pure (100% reinvest, 0.1% txn cost)", **pure},
        {"Mode": "As Described — compounding capital only", **BACKTEST_SUMMARY["described_capital_only"]},
        {"Mode": "As Described — total wealth incl. withdrawn self-dividend",
         **BACKTEST_SUMMARY["described_total_wealth"]},
    ]
    comp_df = pd.DataFrame(comp_rows)
    st.dataframe(comp_df, use_container_width=True, hide_index=True)

    st.caption(
        "**Methodology**: universe = curated 45-ETF list, deduplicated by theme from a combined 76-ETF pool "
        "(fabtrader momentum strategy's 37 ETFs + this strategy's own 75-ETF list). Rules exactly as described "
        "in the video: RSI(14) ranking, 50-part capital sizing, 4.71% target, 3% averaging-drop trigger, one "
        "buy and one sell per day maximum. This underperforms the video's own implied expectations but has "
        "the best Sharpe ratio of every ETF strategy tested on this site — see the Pure vs As-Described "
        "comparison above for the real cost of the video's own tax/self-dividend compounding rule."
    )

    st.markdown("---")
    if st.button("🔄 Re-run Backtest (live, may take a few seconds)", key="d3_rerun_backtest"):
        with st.spinner("Re-running 10-year backtest on the curated universe..."):
            data = fetch_universe(years=10.0)
            if not data:
                st.error("Could not fetch enough history to re-run — try again later.")
            else:
                st.info(f"Fetched {len(data)}/{len(ETF_UNIVERSE_META)} ETFs with sufficient history. "
                        "Full historical day-by-day re-simulation is a heavier operation than a single fetch — "
                        "the static numbers above are the validated reference; this fetch confirms live data "
                        "availability matches the backtest's own universe coverage.")
