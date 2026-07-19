"""
Gann Analysis — cook-once page (reads from DB; live compute on cache miss).
All 5 Gann methods: ATR range, Degree levels, Date projection,
Price-Time squaring, Natural dates.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from config import SECTOR_STOCKS

st.set_page_config(
    page_title="Gann Analysis | NSE Dashboard",
    page_icon="🔢",
    layout="wide",
)
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()
from app.utils.seo import inject_seo
inject_seo("Gann_Analysis")
from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("Gann Analysis")

st.title("🔢 Gann Analysis")
from app.utils.disclaimer import show_sebi_notice
show_sebi_notice()
st.caption(
    "ATR range completion · Degree levels (Square of Nine) · "
    "Top-to-Top / Bottom-to-Bottom date projection · "
    "Price-Time squaring · Gann natural dates. "
    "Educational and research purposes only."
)

# ── Constants ──────────────────────────────────────────────────────────────────

GANN_DATES = [
    (2, 4), (2, 5), (2, 6), (2, 7), (2, 8),
    (3, 20), (3, 21), (3, 22), (3, 23),
    (5, 3), (5, 4), (5, 5), (5, 6), (5, 7),
    (6, 20), (6, 21), (6, 22),
    (8, 5), (8, 6), (8, 7), (8, 8),
    (9, 22), (9, 23), (9, 24),
    (11, 7), (11, 8), (11, 9),
    (12, 21), (12, 22), (12, 23),
]

DEG = {"90°": 0.500, "120°": 0.667, "180°": 1.000,
       "240°": 1.333, "270°": 1.500, "360°": 2.000}

# ── Helpers ────────────────────────────────────────────────────────────────────

def _stock_list():
    seen, out = set(), []
    for sec, syms in sorted(SECTOR_STOCKS.items()):
        for sym in syms:
            s = sym.replace(".NS", "")
            if s not in seen:
                seen.add(s); out.append((s, sec))
    return out


@st.cache_data(ttl=3600)
def fetch_ohlcv(symbol: str) -> pd.DataFrame:
    df = yf.download(symbol + ".NS", period="max", interval="1d",
                     auto_adjust=True, progress=False)
    if df.empty:
        return pd.DataFrame()
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.droplevel(1)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


@st.cache_data(ttl=3600, show_spinner=False)
def find_pivots(df: pd.DataFrame, window: int) -> dict:
    highs, lows = [], []
    for i in range(window, len(df) - window):
        sl = slice(i - window, i + window + 1)
        if df["High"].iloc[i] == df["High"].iloc[sl].max():
            highs.append((str(df.index[i].date()), float(df["High"].iloc[i])))
        if df["Low"].iloc[i] == df["Low"].iloc[sl].min():
            lows.append((str(df.index[i].date()), float(df["Low"].iloc[i])))
    return {"highs": highs, "lows": lows}


def sq9_levels(price: float) -> dict:
    r = float(np.sqrt(price))
    return {
        deg: {"up": round((r + f) ** 2, 2), "dn": round(max(r - f, 0.0) ** 2, 2)}
        for deg, f in DEG.items()
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _bt_atr(df: pd.DataFrame) -> list:
    daily_rng = df["High"] - df["Low"]
    rows = []
    for i in range(34, len(df) - 1):
        atr_i = float(daily_rng.iloc[i - 34:i].mean())
        rng_i = float(daily_rng.iloc[i])
        if atr_i and rng_i / atr_i >= 1.0:
            bull  = df["Close"].iloc[i] > df["Open"].iloc[i]
            r1d   = (df["Close"].iloc[i+1] - df["Close"].iloc[i]) / df["Close"].iloc[i] * 100
            r3d   = (df["Close"].iloc[min(i+3, len(df)-1)] - df["Close"].iloc[i]) / df["Close"].iloc[i] * 100
            rows.append({"Date": str(df.index[i].date()), "Signal": "Bull" if bull else "Bear",
                         "Consumed%": round(rng_i/atr_i*100,1), "Next1d%": round(r1d,2),
                         "Next3d%": round(r3d,2), "Reversed": (bull and r1d<0) or (not bull and r1d>0)})
    return rows


@st.cache_data(ttl=3600, show_spinner=False)
def _bt_degree(df: pd.DataFrame, lvls: dict) -> list:
    rows = []
    all_levels = {f"R {d}": lr["up"] for d, lr in lvls.items()}
    all_levels.update({f"S {d}": lr["dn"] for d, lr in lvls.items()})
    for lvl_name, lvl_price in all_levels.items():
        if lvl_price <= 0:
            continue
        touches = []
        for i in range(len(df) - 3):
            h, l = float(df["High"].iloc[i]), float(df["Low"].iloc[i])
            if abs(h - lvl_price)/lvl_price <= 0.005 or abs(l - lvl_price)/lvl_price <= 0.005:
                fwd3 = df["Close"].iloc[i+3]; cl = df["Close"].iloc[i]
                bounce = (fwd3 < cl) if lvl_name.startswith("R") else (fwd3 > cl)
                touches.append({"ret3d": float(round((fwd3-cl)/cl*100,2)), "bounce": bool(bounce)})
        if touches:
            rows.append({"Level": lvl_name, "Price": lvl_price,
                         "Touches": len(touches),
                         "BounceRate": round(sum(1 for t in touches if t["bounce"])/len(touches)*100,1),
                         "Avg3dRet": round(sum(t["ret3d"] for t in touches)/len(touches),2)})
    return rows


@st.cache_data(ttl=3600, show_spinner=False)
def _bt_date_proj(ph_list: list, pl_list: list) -> tuple:
    def _proj(pivot_list, label):
        rows = []
        if len(pivot_list) < 3:
            return rows
        for i in range(len(pivot_list) - 2):
            d1 = pd.Timestamp(pivot_list[i][0]).date()
            d2 = pd.Timestamp(pivot_list[i+1][0]).date()
            d3_act = pd.Timestamp(pivot_list[i+2][0]).date()
            diff = (d2 - d1).days
            d3_hat = d2 + datetime.timedelta(days=diff)
            err = abs((d3_act - d3_hat).days)
            rows.append({"HL": label, "Pivot1": str(d1), "Pivot2": str(d2),
                         "Projected": str(d3_hat), "Actual": str(d3_act),
                         "ErrDays": err, "Within3d": err<=3, "Within7d": err<=7})
        return rows
    return _proj(ph_list, "High"), _proj(pl_list, "Low")


@st.cache_data(ttl=3600, show_spinner=False)
def _bt_pts(df: pd.DataFrame, ph_list: list, pl_list: list, pw: int) -> list:
    # Convert pivot date strings to sorted arrays for fast bisect lookup
    import bisect
    h_dates = [d for d, _ in ph_list]; h_prices = [p for _, p in ph_list]
    l_dates = [d for d, _ in pl_list]; l_prices = [p for _, p in pl_list]
    rows = []
    for i in range(pw+1, len(df)-5):
        bar_date_s = str(df.index[i].date()); bar_close = float(df["Close"].iloc[i])
        best_var = 999.0
        for dates, prices in [(h_dates, h_prices), (l_dates, l_prices)]:
            idx = bisect.bisect_left(dates, bar_date_s) - 1
            if idx < 0:
                continue
            days = (df.index[i].date() - datetime.date.fromisoformat(dates[idx])).days
            if days <= 0:
                continue
            for sd in [1, 10, 100]:
                best_var = min(best_var, abs(bar_close/sd - days)/max(days,0.01)*100)
        if best_var == 999.0:
            continue
        fwd5 = float(df["Close"].iloc[i+5])
        rows.append({"Date": bar_date_s, "Squared": best_var < 5.0,
                     "BestVar": round(best_var,1),
                     "Ret5d": round(abs((fwd5-bar_close)/bar_close*100),2)})
    return rows


@st.cache_data(ttl=3600, show_spinner=False)
def _bt_natural_dates(df: pd.DataFrame, ph_list: list, pl_list: list,
                      gann_dates: list) -> tuple:
    data_start = df.index[0].date(); data_end = df.index[-1].date()
    pivot_dates_all = set(pd.Timestamp(t).date() for t,_ in ph_list+pl_list)
    rows = []
    for year in range(data_start.year, data_end.year+1):
        for m, d in gann_dates:
            try:
                gd = datetime.date(year, m, d)
                if data_start <= gd <= data_end:
                    hit = bool({gd+datetime.timedelta(days=k) for k in range(-3,4)} & pivot_dates_all)
                    rows.append({"GannDate": str(gd), "Period": gd.strftime("%B %d"), "HitPivot": hit})
            except ValueError:
                pass
    total = len(rows); hits = sum(1 for r in rows if r["HitPivot"])
    return rows, total, hits, round(hits/total*100,1) if total else 0.0


def _chart_base(df_plot: pd.DataFrame, symbol: str) -> go.Figure:
    fig = go.Figure(go.Candlestick(
        x=df_plot.index,
        open=df_plot["Open"], high=df_plot["High"],
        low=df_plot["Low"],   close=df_plot["Close"],
        name=symbol,
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
        showlegend=False,
    ))
    fig.update_layout(
        height=380, xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,17,17,1)",
        font=dict(color="#FAFAFA"), margin=dict(l=10, r=100, t=20, b=10),
        xaxis=dict(gridcolor="#222"), yaxis=dict(gridcolor="#222", title="₹"),
    )
    return fig


def _days_style(v):
    try:
        d = int(v)
        if d < 0:   return "color:#555"
        if d <= 7:  return "color:#FF4444;font-weight:700"
        if d <= 21: return "color:#FFD700"
        return ""
    except Exception:
        return ""


# ── Stock selector ─────────────────────────────────────────────────────────────

all_stocks = _stock_list()
names      = [s for s, _ in all_stocks]

sa, sb = st.columns([3, 1])
with sa:
    default = names.index("RELIANCE") if "RELIANCE" in names else 0
    if "gn_stock" in st.session_state and st.session_state["gn_stock"] not in names:
        del st.session_state["gn_stock"]
    sel = st.selectbox("Select Stock", names, index=default, key="gn_stock")
with sb:
    pw = st.slider("Pivot window (bars)", 5, 20, 10,
                   help="Bars each side used to identify a swing high/low", key="gn_pivot_window")

# ── Data load: DB first, live fallback ─────────────────────────────────────────

from backend.storage.gann_db import load_gann, load_all_accuracy as _db_load_all_accuracy
from backend.calculations.gann import compute_gann_all


@st.cache_data(ttl=3600, show_spinner=False)
def _load_all_accuracy() -> pd.DataFrame:
    return _db_load_all_accuracy()

cached, scan_date = load_gann(sel)

if cached:
    _source = f"Cached {scan_date}"
else:
    _source = "Live (no cache yet)"

# Always fetch OHLCV for charts + UI that needs raw df (degree level chart, etc.)
with st.spinner(f"Loading {sel} data…"):
    df = fetch_ohlcv(sel)

if df.empty:
    st.error("Could not fetch data. Please try again.")
    st.stop()

cmp      = float(df["Close"].iloc[-1])
pivots   = find_pivots(df, pw)

# Backtest period label — shown on every backtest section
_bt_from  = df.index[0].strftime("%d %b %Y")
_bt_to    = df.index[-1].strftime("%d %b %Y")
_bt_bars  = len(df)
_bt_years = round(_bt_bars / 252)
_BT_LABEL = (
    f"📅 **Backtest period: {_bt_from} → {_bt_to}** "
    f"&nbsp;·&nbsp; {_bt_bars:,} trading bars (~{_bt_years} years)"
)
ph_list  = pivots["highs"]
pl_list  = pivots["lows"]
ph       = ph_list[-1] if ph_list else None
pl       = pl_list[-1] if pl_list else None
daily_rng = df["High"] - df["Low"]

# ── Live compute button ────────────────────────────────────────────────────────
col_info, col_btn = st.columns([5, 1])
col_info.caption(
    f"**{sel}** · CMP ₹{cmp:,.1f} · as of {df.index[-1].date()} · "
    f"{len(ph_list)} swing highs · {len(pl_list)} swing lows · "
    f"Data: {_source}"
)
if col_btn.button("🔄 Live", help="Recompute all methods from live data"):
    with st.spinner("Computing live Gann analysis…"):
        cached = compute_gann_all(sel, df, pw)
        scan_date = datetime.date.today().isoformat()
    _source = "Live (just computed)"

# If still no cached data, compute now silently
if not cached:
    with st.spinner("Computing Gann analysis (first run)…"):
        cached = compute_gann_all(sel, df, pw)
        scan_date = datetime.date.today().isoformat()

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_atr, tab_deg, tab_date, tab_pts, tab_gnn, tab_emb = st.tabs([
    "📏 ATR Range",
    "📐 Degree Levels",
    "📅 Date Projection",
    "⚖️ Price-Time Square",
    "🗓️ Natural Dates",
    "🌟 Gann Emblem",
])

# ── Cross-stock accuracy data (loaded once, shared across all tabs) ─────────

_all_acc = _load_all_accuracy()
_acc_ready = not _all_acc.empty and "atr_accuracy_pct" in _all_acc.columns and \
             _all_acc["atr_accuracy_pct"].notna().any()


def _acc_for(symbol: str, col: str):
    """Return pre-computed accuracy value for the current stock from DB."""
    if _all_acc.empty or col not in _all_acc.columns:
        return None
    row = _all_acc[_all_acc["symbol"] == symbol]
    if row.empty:
        return None
    v = row.iloc[0][col]
    return None if (v is None or (isinstance(v, float) and v != v)) else v


def _show_accuracy_card(method_label: str, accuracy: float | None, signals: int | None):
    """Render a small accuracy metric card coloured by performance tier."""
    if accuracy is None:
        st.caption("Backtest accuracy: — (run Gann pipeline from Admin to populate)")
        return
    color = "#26a69a" if accuracy >= 55 else ("#FFD700" if accuracy >= 50 else "#ef5350")
    tier  = "Strong" if accuracy >= 55 else ("Moderate" if accuracy >= 50 else "Below 50%")
    sig_txt = f" &nbsp;·&nbsp; {signals:,} signals" if signals else ""
    st.markdown(
        f'<div style="background:#1a1a2e;border-left:4px solid {color};'
        f'padding:8px 14px;border-radius:4px;margin-bottom:8px">'
        f'<span style="color:#aaa;font-size:0.8rem">{method_label} Backtest Accuracy'
        f'{sig_txt}</span><br>'
        f'<span style="color:{color};font-size:1.6rem;font-weight:700">{accuracy:.1f}%</span>'
        f'&nbsp;<span style="color:{color};font-size:0.85rem">— {tier}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _show_top_stocks_table(acc_col: str, sig_col: str, method_label: str, threshold: float = 50.0):
    """Expander showing all stocks >threshold% accuracy on this method."""
    label = f"📋 Top stocks on {method_label} — >{int(threshold)}% accuracy (30-year backtest)"
    with st.expander(label, expanded=False):
        if not _acc_ready:
            st.caption("No accuracy data yet. Run the Gann pipeline from Admin → Gann Cache.")
            return
        subset = _all_acc[_all_acc[acc_col].notna() & (_all_acc[acc_col] > threshold)].copy()
        if subset.empty:
            st.caption(f"No stocks exceed {threshold}% accuracy on this method.")
            return
        subset = subset.sort_values(acc_col, ascending=False).reset_index(drop=True)
        subset.index += 1
        display = subset[["symbol", acc_col, sig_col]].rename(columns={
            "symbol": "Stock",
            acc_col: "Accuracy",
            sig_col: "Signals",
        })
        display["Accuracy"] = display["Accuracy"].apply(lambda x: f"{x:.1f}%")
        st.dataframe(display, width='stretch')
        st.caption(f"{len(subset)} of {len(_all_acc)} stocks exceed {threshold}% accuracy")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — ATR RANGE COMPLETION
# ══════════════════════════════════════════════════════════════════════════════
with tab_atr:
    st.subheader(f"📏 ATR Range Completion — {sel}")
    st.caption(
        "**Rule:** ATR = mean(High−Low) of last **34 trading days**. "
        "When today's range ≥ ATR the expected move is complete — "
        "avoid entering new trades in the same direction."
    )

    atr_d = cached.get("atr", {})
    atr34       = atr_d.get("atr34") or float(daily_rng.tail(34).mean())
    today_range = atr_d.get("today_range") or float(daily_rng.iloc[-1])
    consumed    = atr_d.get("consumed_pct") or (round(today_range / atr34 * 100, 1) if atr34 else 0.0)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("34-Day ATR", f"₹{atr34:,.1f}")
    m2.metric("Today's Range", f"₹{today_range:,.1f}")
    m3.metric("Range Consumed", f"{consumed}%")
    if consumed >= 100:
        m4.error("⚠️ RANGE COMPLETE")
    elif consumed >= 75:
        m4.warning(f"🟡 {consumed}% — approaching")
    else:
        m4.success(f"✅ {consumed}% — open")

    st.markdown("---")
    st.markdown(f"#### 📊 Backtest — Range-Complete Signals | {sel}")
    st.markdown(_BT_LABEL, unsafe_allow_html=True)
    st.caption(
        "Each signal day: range consumed ≥ 100%. "
        "**Hypothesis:** if signal day was bullish (close > open) expect a down close next day; "
        "if bearish expect an up close. "
        "Reversal = next-day close moved opposite to signal-day direction."
    )

    bt_rows = _bt_atr(df)

    if bt_rows:
        bdf   = pd.DataFrame(bt_rows)
        n_sig = len(bdf)
        acc   = round(bdf["Reversed"].mean() * 100, 1)
        avg1d = round(bdf["Next1d%"].mean(), 2)
        _atr_acc_val = _acc_for(sel, "atr_accuracy_pct") or acc
        _atr_sig_val = _acc_for(sel, "atr_signals") or n_sig
        _show_accuracy_card("ATR Range", _atr_acc_val, _atr_sig_val)
        avg3d = round(bdf["Next3d%"].mean(), 2)

        ba, bb, bc, bd = st.columns(4)
        ba.metric("Total Signals", n_sig)
        bb.metric("Reversal Rate (1d)", f"{acc}%")
        bc.metric("Avg Next-Day Return", f"{avg1d}%")
        bd.metric("Avg 3-Day Return", f"{avg3d}%")

        # Show last 3 years of signals (fixed window — keeps chart readable)
        _data_max = bdf["Date"].max()
        _cutoff   = str(datetime.date.fromisoformat(_data_max) - datetime.timedelta(days=3 * 365))
        bdf_rev   = bdf[bdf["Date"] >= _cutoff].iloc[::-1].reset_index(drop=True)
        _n_shown  = len(bdf_rev)

        colors = ["#26a69a" if r else "#ef5350" for r in bdf_rev["Reversed"]]
        fig_atr = go.Figure(go.Bar(
            x=bdf_rev["Date"], y=bdf_rev["Next1d%"],
            marker_color=colors,
            hovertemplate="%{x}<br>Next 1d: %{y:.2f}%<extra></extra>",
        ))
        fig_atr.update_layout(
            height=260,
            title_text=f"Next-Day Return After Range-Complete Signal  "
                       f"(teal = reversed ✅, red = failed ❌)  — last 3 years ({_n_shown} signals)",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,17,17,1)",
            font=dict(color="#FAFAFA"),
            xaxis=dict(
                showticklabels=True,
                tickangle=-45,
                tickfont=dict(size=9),
                autorange="reversed",
            ),
            yaxis=dict(title="%"), margin=dict(l=10, r=10, t=42, b=60),
        )
        st.plotly_chart(fig_atr, width='stretch')

        # Table: latest date at top
        display_bdf = bdf.iloc[::-1].reset_index(drop=True).rename(columns={
            "Consumed%": "Consumed %", "Next1d%": "Next 1d %",
            "Next3d%": "Next 3d %", "Reversed": "Reversed ✅",
        })
        with st.expander("Signal detail table"):
            st.dataframe(display_bdf, width='stretch', hide_index=True)
    else:
        st.info("No range-complete signals found in the 2-year history for this stock.")

    st.markdown("---")
    _show_top_stocks_table("atr_accuracy_pct", "atr_signals", "ATR Range")

    # High Conviction — stocks exceeding 50% in 3+ methods
    with st.expander("🏆 High Conviction Stocks — >50% accuracy in 3+ Gann methods", expanded=False):
        if not _acc_ready:
            st.caption("No accuracy data yet. Run the Gann pipeline from Admin → Gann Cache.")
        else:
            _methods = [
                ("atr_accuracy_pct",  "ATR Range"),
                ("deg_accuracy_pct",  "Degree Levels"),
                ("proj_accuracy_pct", "Date Projection"),
                ("pts_accuracy_pct",  "Price-Time Sq"),
                ("nat_accuracy_pct",  "Natural Dates"),
            ]
            _hc = _all_acc.copy()
            _hc["methods_passed"] = sum(
                (_hc[col].notna() & (_hc[col] > 50)).astype(int)
                for col, _ in _methods
            )
            _hc = _hc[_hc["methods_passed"] >= 3].sort_values(
                "methods_passed", ascending=False
            ).reset_index(drop=True)
            if _hc.empty:
                st.caption("No stocks have >50% accuracy in 3+ methods yet.")
            else:
                disp_cols = {"symbol": "Stock"}
                for col, lbl in _methods:
                    _hc[lbl] = _hc[col].apply(
                        lambda x: f"{x:.1f}%" if (x is not None and x == x) else "—"
                    )
                    disp_cols[lbl] = lbl
                _hc["Methods Passed"] = _hc["methods_passed"].apply(lambda x: f"{x}/5")
                show_hc = _hc[["symbol"] + [lbl for _, lbl in _methods] + ["Methods Passed"]].rename(
                    columns={"symbol": "Stock"}
                )
                st.dataframe(show_hc, width='stretch', hide_index=True)
                st.caption(f"{len(_hc)} high-conviction stocks (>50% in 3+ of 5 Gann methods)")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — DEGREE LEVELS
# ══════════════════════════════════════════════════════════════════════════════
with tab_deg:
    st.subheader(f"📐 Degree Levels — Square of Nine | {sel}")
    st.caption(
        "**Formula:** (√Price ± factor)² | "
        "90° → ±0.5 · 120° → ±0.667 · 180° → ±1.0 · "
        "240° → ±1.333 · 270° → ±1.5 · 360° → ±2.0. "
        "180° and 360° ⭐ are the strongest levels."
    )

    if not ph and not pl:
        st.info("No swing pivots detected. Try reducing the pivot window.")
        st.stop()

    pivot_choice = st.radio(
        "Calculate levels from", ["Swing High", "Swing Low"], horizontal=True,
        key="gn_pivot_choice",
    )
    ref_pivot = ph if pivot_choice == "Swing High" else pl
    if ref_pivot is None:
        st.warning("Selected pivot type not found. Try the other option.")
    else:
        ref_price = ref_pivot[1]
        ref_date  = pd.Timestamp(ref_pivot[0]).strftime("%d %b %y")
        lvls      = sq9_levels(ref_price)

        rows = []
        for deg, lr in lvls.items():
            strong   = "⭐ " if deg in ("180°", "360°") else ""
            dist_up  = round((lr["up"] - cmp) / cmp * 100, 2)
            dist_dn  = round((cmp - lr["dn"]) / cmp * 100, 2)
            rows.append({
                "Degree":          strong + deg,
                "Resistance (₹)":  f"₹{lr['up']:,.1f}",
                "↑ % from CMP":    f"+{dist_up:.2f}%",
                "Support (₹)":     f"₹{lr['dn']:,.1f}",
                "↓ % from CMP":    f"-{dist_dn:.2f}%",
            })

        st.caption(f"Pivot: {pivot_choice} ₹{ref_price:,.1f} on {ref_date} · CMP ₹{cmp:,.1f}")
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

        # Chart with level overlays
        df_plot   = df.tail(126)
        fig_deg   = _chart_base(df_plot, sel)
        p_min     = float(df_plot["Low"].min())
        p_max     = float(df_plot["High"].max())
        band      = (p_max - p_min) * 0.15
        colors_up = ["#ef5350","#FF7043","#FFA726","#66BB6A","#26C6DA","#7E57C2"]
        for (deg, lr), clr in zip(lvls.items(), colors_up):
            lw = 1.5 if deg in ("180°","360°") else 1.0
            for side, val, pos in [("R", lr["up"], "right"), ("S", lr["dn"], "left")]:
                if p_min - band < val < p_max + band:
                    fig_deg.add_hline(
                        y=val, line_dash="dot", line_color=clr, line_width=lw,
                        annotation_text=f"{side} {deg}",
                        annotation_position=f"top {pos}",
                        annotation_font_color=clr, annotation_font_size=10,
                    )
        piv_ts = pd.Timestamp(ref_pivot[0])
        if piv_ts in df_plot.index:
            fig_deg.add_vline(
                x=piv_ts, line_color="#FFD700", line_dash="dot", line_width=1,
                annotation_text=pivot_choice[6:7],
                annotation_font_color="#FFD700",
            )
        st.plotly_chart(fig_deg, width='stretch')

        # Degree backtest from cache
        st.markdown("---")
        st.markdown(f"#### 📊 Backtest — Degree Level Touches | {sel}")
        st.markdown(_BT_LABEL, unsafe_allow_html=True)
        st.caption(
            "Using current degree levels (from selected pivot), scan full price history "
            "for price touches (High or Low within **0.5%** of any level). "
            "Outcome: did price move **≥ 0.5%** away from that level within the next **3 bars**?"
        )

        deg_rows = _bt_degree(df, lvls)

        if deg_rows:
            deg_bt_df = pd.DataFrame(deg_rows)
            _total_w  = sum(r.get("Touches", 0) for r in deg_rows)
            _live_deg = round(
                sum(r.get("BounceRate", 0) * r.get("Touches", 0) for r in deg_rows) / _total_w, 1
            ) if _total_w else None
            _deg_acc_val = _acc_for(sel, "deg_accuracy_pct") or _live_deg
            _deg_sig_val = _acc_for(sel, "deg_signals") or _total_w
            _show_accuracy_card("Degree Levels", _deg_acc_val, _deg_sig_val)
            display_deg = deg_bt_df.rename(columns={
                "Price": "Price (₹)", "BounceRate": "Bounce Rate %", "Avg3dRet": "Avg 3d Ret%",
            })
            st.dataframe(display_deg, width='stretch', hide_index=True)

            fig_dacc = go.Figure(go.Bar(
                x=deg_bt_df["Level"],
                y=deg_bt_df["BounceRate"],
                marker_color=["#26a69a" if v >= 50 else "#ef5350" for v in deg_bt_df["BounceRate"]],
                text=[f"{v}%" for v in deg_bt_df["BounceRate"]],
                textposition="outside",
            ))
            fig_dacc.update_layout(
                height=260, title_text="Bounce Rate (%) per Degree Level",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,17,17,1)",
                font=dict(color="#FAFAFA"), yaxis=dict(title="%", range=[0, 110]),
                margin=dict(l=10, r=10, t=38, b=10),
            )
            st.plotly_chart(fig_dacc, width='stretch')
        else:
            st.info("No price touches found for these levels in 2-year history.")

        st.markdown("---")
        _show_top_stocks_table("deg_accuracy_pct", "deg_signals", "Degree Levels")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — DATE PROJECTION
# ══════════════════════════════════════════════════════════════════════════════
with tab_date:
    st.subheader(f"📅 Top-to-Top / Bottom-to-Bottom Date Projection — {sel}")
    st.caption(
        "**Rule:** Count **calendar days** between the last two swing highs (or lows). "
        "Projected next date = most recent pivot + that same number of days. "
        "Watch ±3 trading days around the projected date for a potential trend change."
    )

    proj_d   = cached.get("proj", {})
    top_proj = proj_d.get("top_proj") or []
    bot_proj = proj_d.get("bot_proj") or []

    if not top_proj and not bot_proj:
        # Fallback compute
        def _project_list(pivot_list):
            out = []
            today = datetime.date.today()
            for i in range(len(pivot_list) - 1):
                d1   = pd.Timestamp(pivot_list[i][0]).date()
                d2   = pd.Timestamp(pivot_list[i + 1][0]).date()
                diff = (d2 - d1).days
                proj = d2 + datetime.timedelta(days=diff)
                out.append({
                    "Pivot1":    str(d1), "Price1": round(pivot_list[i][1], 1),
                    "Pivot2":    str(d2), "Price2": round(pivot_list[i + 1][1], 1),
                    "DaysApart": diff,
                    "Projected": str(proj),
                    "DaysAway":  (proj - today).days,
                })
            return out
        top_proj = _project_list(ph_list)
        bot_proj = _project_list(pl_list)
    else:
        # Recompute DaysAway since it's time-sensitive (cache may be stale by 1+ day)
        today = datetime.date.today()
        for row in top_proj + bot_proj:
            try:
                row["DaysAway"] = (datetime.date.fromisoformat(row["Projected"]) - today).days
            except Exception:
                pass

    def _rename_proj(rows):
        def _p(v):
            try: return f"{float(v):,.1f}"
            except Exception: return v
        return [{
            "Pivot 1":      r.get("Pivot1", ""),
            "Price 1 (₹)": _p(r.get("Price1", "")),
            "Pivot 2":      r.get("Pivot2", ""),
            "Price 2 (₹)": _p(r.get("Price2", "")),
            "Days Apart":   r.get("DaysApart", ""),
            "Projected":    r.get("Projected", ""),
            "Days Away":    r.get("DaysAway", ""),
        } for r in rows]

    ca, cb = st.columns(2)
    with ca:
        st.markdown("**🔴 Top → Top Projection**")
        if top_proj:
            last_tp = top_proj[-1]
            st.dataframe(
                pd.DataFrame(_rename_proj(top_proj[::-1])).style.map(_days_style, subset=["Days Away"]),
                width='stretch', hide_index=True,
            )
            da = last_tp.get("DaysAway", 999)
            if 0 <= da <= 10:
                st.error(f"🎯 Projected top: **{last_tp['Projected']}** — {da} days away")
            elif 0 <= da <= 21:
                st.warning(f"📍 Projected top: **{last_tp['Projected']}** — {da} days away")
        else:
            st.info("Need ≥ 2 swing highs. Reduce the pivot window.")

    with cb:
        st.markdown("**🟢 Bottom → Bottom Projection**")
        if bot_proj:
            last_bp = bot_proj[-1]
            st.dataframe(
                pd.DataFrame(_rename_proj(bot_proj[::-1])).style.map(_days_style, subset=["Days Away"]),
                width='stretch', hide_index=True,
            )
            da = last_bp.get("DaysAway", 999)
            if 0 <= da <= 10:
                st.error(f"🎯 Projected bottom: **{last_bp['Projected']}** — {da} days away")
            elif 0 <= da <= 21:
                st.warning(f"📍 Projected bottom: **{last_bp['Projected']}** — {da} days away")
        else:
            st.info("Need ≥ 2 swing lows. Reduce the pivot window.")

    st.markdown("---")
    st.markdown(f"#### 📊 Backtest — Projection Accuracy (Walk-Forward) | {sel}")
    st.markdown(_BT_LABEL, unsafe_allow_html=True)
    st.caption(
        "For each consecutive triplet of swing highs [H1, H2, H3]: "
        "project H3 using H1→H2 interval, compare to actual H3. "
        "Same for lows. Shows mean absolute error (days) and hit rate within ±3 / ±7 days."
    )

    bt_h, bt_l = _bt_date_proj(ph_list, pl_list)

    combined_rows = bt_h + bt_l
    if combined_rows:
        combined = pd.DataFrame(combined_rows)
        mae  = round(combined["ErrDays"].mean(), 1)
        p3   = round(combined["Within3d"].mean() * 100, 1)
        _proj_acc_val = _acc_for(sel, "proj_accuracy_pct") or p3
        _proj_sig_val = _acc_for(sel, "proj_signals") or len(combined_rows)
        _show_accuracy_card("Date Projection (Within ±3 Days)", _proj_acc_val, _proj_sig_val)
        p7   = round(combined["Within7d"].mean() * 100, 1)
        n_bt = len(combined)

        x1, x2, x3, x4 = st.columns(4)
        x1.metric("Backtest Signals", n_bt)
        x2.metric("Mean Abs Error", f"{mae} days")
        x3.metric("Within ±3 Days", f"{p3}%")
        x4.metric("Within ±7 Days", f"{p7}%")

        fig_err = go.Figure(go.Bar(
            x=combined.index + 1,
            y=combined["ErrDays"],
            marker_color=["#26a69a" if v <= 3 else "#FFD700" if v <= 7 else "#ef5350"
                          for v in combined["ErrDays"]],
            hovertemplate="Signal %{x}<br>Error: %{y} days<extra></extra>",
        ))
        fig_err.add_hline(y=3, line_dash="dot", line_color="#26a69a",
                          annotation_text="±3d", annotation_position="right")
        fig_err.add_hline(y=7, line_dash="dot", line_color="#FFD700",
                          annotation_text="±7d", annotation_position="right")
        fig_err.update_layout(
            height=240, title_text="Projection Error per Signal (days) — teal ≤3d · gold ≤7d · red >7d",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,17,17,1)",
            font=dict(color="#FAFAFA"), xaxis=dict(title="Signal #"),
            yaxis=dict(title="Error (days)"), margin=dict(l=10, r=10, t=38, b=10),
        )
        st.plotly_chart(fig_err, width='stretch')

        display_bt = combined.sort_values("Pivot2", ascending=False).rename(columns={
            "ErrDays": "Error (days)", "Within3d": "Within ±3d", "Within7d": "Within ±7d",
        })
        with st.expander("Projection detail table"):
            st.dataframe(display_bt, width='stretch', hide_index=True)
    else:
        st.info("Need ≥ 3 swing highs or lows for walk-forward backtest. Reduce the pivot window.")

    st.markdown("---")
    _show_top_stocks_table("proj_accuracy_pct", "proj_signals", "Date Projection")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — PRICE-TIME SQUARING
# ══════════════════════════════════════════════════════════════════════════════
with tab_pts:
    st.subheader(f"⚖️ Price-Time Squaring — {sel}")
    st.caption(
        "**Gann principle:** when price (in points) ≈ number of calendar days elapsed from a major pivot, "
        "a reversal is likely. Tested at three scales: Price, Price÷10, Price÷100 "
        "(to handle large-cap stocks with high absolute prices). "
        "Alert fires when best-scale variance < 5%."
    )

    pts_d = cached.get("pts", {})

    def _render_pts(sq, col):
        with col:
            st.markdown(f"**From Swing {sq['label']}**")
            ca2, cb2 = st.columns(2)
            ca2.metric("Days Elapsed", sq["days"])
            cb2.metric("CMP", f"₹{sq['cmp']:,.1f}")
            st.caption(f"Pivot: ₹{sq['pivot_price']:,.1f} · {sq['pivot_date']}")
            rows2 = [{"Scale": k, "Variance %": f"{v:.1f}%",
                      "Signal": "🎯" if v < 5 else ("⚠️" if v < 15 else "")}
                     for k, v in sq["scales"].items()]
            st.dataframe(pd.DataFrame(rows2), width='stretch', hide_index=True)
            if sq["squared"]:
                st.success(f"✅ SQUARED — {sq['best_k']} ({sq['best_v']:.1f}% variance)")
            else:
                st.info(f"Closest: {sq['best_k']} ({sq['best_v']:.1f}% off)")

    def _live_pt_square(pivot, label):
        if not pivot:
            return None
        today  = datetime.date.today()
        pdate  = pd.Timestamp(pivot[0]).date()
        days   = (today - pdate).days
        p      = cmp

        def pct(a, b):
            return round(abs(a - b) / max(b, 0.01) * 100, 2)

        scales = {
            "Price vs Days":     pct(p, days),
            "Price÷10 vs Days":  pct(p / 10, days),
            "Price÷100 vs Days": pct(p / 100, days),
        }
        best_k = min(scales, key=scales.get)
        best_v = scales[best_k]
        return {
            "label": label, "pivot_date": str(pdate), "days": days,
            "cmp": round(p, 2), "pivot_price": round(float(pivot[1]), 2),
            "scales": scales, "best_k": best_k, "best_v": best_v,
            "squared": best_v < 5.0,
        }

    # Price-Time squares are time-sensitive (days change daily) — always recompute from live
    sq_h = _live_pt_square(ph, "High")
    sq_l = _live_pt_square(pl, "Low")

    pc1, pc2 = st.columns(2)
    if sq_h: _render_pts(sq_h, pc1)
    else:    pc1.info("No swing high found.")
    if sq_l: _render_pts(sq_l, pc2)
    else:    pc2.info("No swing low found.")

    st.markdown("---")
    st.markdown(f"#### 📊 Backtest — Squaring Events vs Baseline | {sel}")
    st.markdown(_BT_LABEL, unsafe_allow_html=True)
    st.caption(
        "For each historical bar: find the most recent prior swing H and L, "
        "calculate price-time variance at 3 scales. "
        "**Signal:** best-scale variance < 5%. "
        "**Outcome:** 5-day forward return magnitude vs non-signal days baseline."
    )

    sq_rows = _bt_pts(df, ph_list, pl_list, pw)

    if sq_rows:
        sq_df     = pd.DataFrame(sq_rows)
        sq_sig    = sq_df[sq_df["Squared"]]
        sq_nosig  = sq_df[~sq_df["Squared"]]
        avg_sig   = round(sq_sig["Ret5d"].mean(), 2)   if len(sq_sig)   else 0
        avg_nosig = round(sq_nosig["Ret5d"].mean(), 2) if len(sq_nosig) else 0
        _valid_pts   = sq_df[sq_df["BestVar"] < 999]
        _live_pts    = round(len(sq_sig) / len(_valid_pts) * 100, 1) if len(_valid_pts) else None
        _pts_acc_val = _acc_for(sel, "pts_accuracy_pct") or _live_pts
        _pts_sig_val = _acc_for(sel, "pts_signals") or len(_valid_pts)
        _show_accuracy_card("Price-Time Square", _pts_acc_val, _pts_sig_val)

        s1, s2, s3 = st.columns(3)
        s1.metric("Squaring Events", len(sq_sig))
        s2.metric("Avg 5d Move (Signal)", f"{avg_sig}%")
        s3.metric("Avg 5d Move (Baseline)", f"{avg_nosig}%")

        fig_sq = go.Figure()
        fig_sq.add_trace(go.Box(
            y=sq_sig["Ret5d"].tolist(), name="Signal (squared)",
            marker_color="#FFD700", boxmean=True,
        ))
        fig_sq.add_trace(go.Box(
            y=sq_nosig["Ret5d"].tolist(), name="Baseline (not squared)",
            marker_color="#555", boxmean=True,
        ))
        fig_sq.update_layout(
            height=280, title_text="5-Day Forward Move % — Signal vs Baseline",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,17,17,1)",
            font=dict(color="#FAFAFA"), yaxis=dict(title="%"),
            margin=dict(l=10, r=10, t=38, b=10),
        )
        st.plotly_chart(fig_sq, width='stretch')
    else:
        st.info("Not enough pivot history to run price-time backtest.")

    st.markdown("---")
    _show_top_stocks_table("pts_accuracy_pct", "pts_signals", "Price-Time Square")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — NATURAL DATES
# ══════════════════════════════════════════════════════════════════════════════
with tab_gnn:
    st.subheader(f"🗓️ Gann Natural Dates — {sel}")
    st.caption(
        "Seasonal dates where trend change probability is historically higher. "
        "**Pattern:** first month of each quarter has no dates (Jan, Apr, Jul, Oct). "
        "Watch for top/bottom formation within **±3 trading days** of these dates. "
        "Direction is unknown — wait for price confirmation."
    )

    today   = datetime.date.today()
    dates_d = cached.get("dates", {})

    upcoming = dates_d.get("upcoming") or []
    if not upcoming:
        # Fallback compute
        for year in [today.year, today.year + 1]:
            for m, d in GANN_DATES:
                try:
                    dt   = datetime.date(year, m, d)
                    diff = (dt - today).days
                    if 0 <= diff <= 90:
                        upcoming.append({
                            "Date":     str(dt),
                            "Period":   dt.strftime("%B %d"),
                            "DaysAway": diff,
                        })
                except ValueError:
                    pass
        upcoming.sort(key=lambda x: x["DaysAway"])
    else:
        # Refresh DaysAway (cache may be 1+ day old)
        for row in upcoming:
            try:
                row["DaysAway"] = (datetime.date.fromisoformat(row["Date"]) - today).days
            except Exception:
                pass
        upcoming = [r for r in upcoming if r.get("DaysAway", -1) >= 0]

    if upcoming:
        udf = pd.DataFrame(upcoming).rename(columns={"DaysAway": "Days Away"})
        st.dataframe(
            udf.style.map(_days_style, subset=["Days Away"]),
            width='stretch', hide_index=True,
        )
        nxt = upcoming[0]
        if nxt.get("DaysAway", 99) <= 5:
            st.warning(
                f"🔔 **{nxt['Period']}** is a Gann natural date — "
                f"only **{nxt['DaysAway']} days away**. Watch for trend change."
            )
    else:
        st.info("No Gann natural dates in the next 90 days.")

    st.markdown("---")
    st.markdown(f"#### 📊 Backtest — Natural Date Hit Rate | {sel}")
    st.markdown(_BT_LABEL, unsafe_allow_html=True)
    st.caption(
        "For each Gann date falling within the full data window: "
        "did a swing High or Low occur within **±3 calendar days**? "
        "Shows hit rate and lists each date's outcome."
    )

    hist_rows, total, hits, hit_pct = _bt_natural_dates(df, ph_list, pl_list, GANN_DATES)

    # Accuracy card — DB value preferred, live hit_pct as fallback
    _nat_acc_val = _acc_for(sel, "nat_accuracy_pct") or (hit_pct if hist_rows else None)
    _nat_sig_val = _acc_for(sel, "nat_signals") or (total if hist_rows else None)
    _show_accuracy_card("Natural Dates Hit Rate", _nat_acc_val, _nat_sig_val)

    if hist_rows:
        gdf = pd.DataFrame(hist_rows)
        g1, g2, g3 = st.columns(3)
        g1.metric("Historical Gann Dates", total)
        g2.metric("Hit Rate (pivot ±3d)", f"{hit_pct}%")
        g3.metric("Pivot Window Used", f"±{pw} bars")

        display_gdf = gdf.sort_values("GannDate", ascending=False).rename(columns={
            "GannDate": "Gann Date",
            "HitPivot": "Pivot ±3d",
        })
        display_gdf["Pivot ±3d"] = display_gdf["Pivot ±3d"].map(
            lambda v: "✅ Hit" if v else "❌ Miss"
        )

        def _hit_style(v):
            if "Hit"  in str(v): return "color:#26a69a;font-weight:700"
            if "Miss" in str(v): return "color:#ef5350"
            return ""

        st.dataframe(
            display_gdf.style.map(_hit_style, subset=["Pivot ±3d"]),
            width='stretch', hide_index=True,
        )

        misses = total - hits
        fig_gnn = go.Figure(go.Pie(
            labels=["Hit ✅", "Miss ❌"],
            values=[hits, misses],
            marker_colors=["#26a69a", "#ef5350"],
            hole=0.5,
            textinfo="label+percent",
        ))
        fig_gnn.update_layout(
            height=260, title_text=f"Gann Date Hit Rate — {hit_pct}% of dates had a pivot within ±3 days",
            paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#FAFAFA"),
            margin=dict(l=10, r=10, t=38, b=10),
        )
        st.plotly_chart(fig_gnn, width='stretch')
    else:
        st.info("No historical Gann dates found in the 2-year data window.")

    st.markdown("---")
    _show_top_stocks_table("nat_accuracy_pct", "nat_signals", "Natural Dates")

# ── Tab 6: Gann Emblem ────────────────────────────────────────────────────────
with tab_emb:
    import math

    st.subheader("🌟 Gann Emblem — Hexagram Time Cycle")
    st.caption(
        "Two overlapping triangles (blue 0°/120°/240° · red 90°/180°/270°) mark key "
        "angular time intervals from a chosen start date. 360° = 365 calendar days. "
        "Rotate the wheel by selecting any reference date as the 0° origin."
    )

    # ── Controls ──────────────────────────────────────────────────────────────
    _default_emb = (
        pd.Timestamp(ph_list[-1][0]).date() if ph_list
        else datetime.date.today()
    )
    c1e, c2e, c3e = st.columns([2, 1, 1])
    emb_start  = c1e.date_input("📅 Start Date (0°)", value=_default_emb, key="emb_start")
    emb_window = c2e.slider("Reversal window (±days)", 3, 10, 5, key="emb_win")
    emb_labels = c3e.checkbox("Show degree labels", value=True, key="emb_lbl")

    # ── Helpers ───────────────────────────────────────────────────────────────
    KEY_ANGLES = [0, 60, 90, 120, 144, 180, 216, 240, 270, 300]
    BLUE_TRI   = [0, 120, 240]
    RED_TRI    = [90, 180, 270]
    SPOKES     = [60, 144, 216, 300]

    def _deg_to_date(start, deg):
        return pd.Timestamp(start) + pd.Timedelta(days=round(deg * 365 / 360))

    def _wheel_xy(deg, r=1.0):
        rad = math.radians(deg - 90)   # 0° at 12 o'clock
        return r * math.cos(rad), r * math.sin(rad)

    # ── Build Plotly wheel ────────────────────────────────────────────────────
    fig_emb = go.Figure()

    # Outer circle (approximated by scatter)
    circle_t = [math.radians(d) for d in range(0, 361)]
    fig_emb.add_trace(go.Scatter(
        x=[math.cos(t) for t in circle_t],
        y=[math.sin(t) for t in circle_t],
        mode="lines", line=dict(color="#444", width=1.5), showlegend=False,
    ))

    # Tick marks every 15°
    for d in range(0, 360, 15):
        x0, y0 = _wheel_xy(d, 0.91)
        x1, y1 = _wheel_xy(d, 1.0)
        fig_emb.add_trace(go.Scatter(
            x=[x0, x1], y=[y0, y1],
            mode="lines", line=dict(color="#333", width=1), showlegend=False,
        ))

    # Degree labels + date annotations at perimeter
    for deg in KEY_ANGLES:
        proj = _deg_to_date(emb_start, deg)
        xL, yL = _wheel_xy(deg, 1.28)
        date_str = proj.strftime("%b %d")
        label = f"{deg}°<br><b>{date_str}</b>" if emb_labels else f"<b>{date_str}</b>"
        fig_emb.add_annotation(
            x=xL, y=yL, text=label, showarrow=False,
            font=dict(size=10, color="#cccccc"), align="center",
        )
        # Small dot on circle at this angle
        xD, yD = _wheel_xy(deg, 1.0)
        fig_emb.add_trace(go.Scatter(
            x=[xD], y=[yD], mode="markers",
            marker=dict(size=7, color="#888"), showlegend=False,
        ))

    # Blue triangle (0°, 120°, 240°)
    _bpts = BLUE_TRI + [BLUE_TRI[0]]
    fig_emb.add_trace(go.Scatter(
        x=[_wheel_xy(d)[0] for d in _bpts],
        y=[_wheel_xy(d)[1] for d in _bpts],
        mode="lines", line=dict(color="#4a9eff", width=2.5),
        name="🔵 Triangle 1 (0° · 120° · 240°)",
    ))

    # Red triangle (90°, 180°, 270°)
    _rpts = RED_TRI + [RED_TRI[0]]
    fig_emb.add_trace(go.Scatter(
        x=[_wheel_xy(d)[0] for d in _rpts],
        y=[_wheel_xy(d)[1] for d in _rpts],
        mode="lines", line=dict(color="#FF5252", width=2.5),
        name="🔴 Triangle 2 (90° · 180° · 270°)",
    ))

    # Green dashed spokes (60°, 144°, 216°, 300°)
    for d in SPOKES:
        x1s, y1s = _wheel_xy(d)
        fig_emb.add_trace(go.Scatter(
            x=[0, x1s], y=[0, y1s], mode="lines",
            line=dict(color="#4ade80", width=1.2, dash="dot"),
            showlegend=(d == SPOKES[0]),
            name="🟢 Spokes (60° · 144° · 216° · 300°)" if d == SPOKES[0] else "",
        ))
        fig_emb.add_trace(go.Scatter(
            x=[x1s], y=[y1s], mode="markers",
            marker=dict(size=7, color="#4ade80"), showlegend=False,
        ))

    # 0° origin marker (gold)
    x0m, y0m = _wheel_xy(0)
    fig_emb.add_trace(go.Scatter(
        x=[x0m], y=[y0m], mode="markers",
        marker=dict(size=13, color="#FFD600", symbol="circle",
                    line=dict(width=2, color="#fff")),
        name=f"⭐ Start: {pd.Timestamp(emb_start).strftime('%d %b %Y')}",
    ))

    fig_emb.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(14,17,23,1)",
        font=dict(color="#FAFAFA"),
        xaxis=dict(visible=False, range=[-1.55, 1.55]),
        yaxis=dict(visible=False, range=[-1.55, 1.55], scaleanchor="x"),
        legend=dict(orientation="h", y=-0.04, font=dict(size=11)),
        margin=dict(l=10, r=10, t=10, b=10), height=540,
    )

    st.plotly_chart(fig_emb, width='stretch')

    # ── Projected dates table ─────────────────────────────────────────────────
    st.markdown("**📋 Projected Key Dates from Start**")
    _legend_rows = []
    for deg in KEY_ANGLES:
        proj = _deg_to_date(emb_start, deg)
        shape = (
            "🔵 Blue Triangle" if deg in BLUE_TRI else
            "🔴 Red Triangle"  if deg in RED_TRI  else
            "🟢 Spoke"
        )
        _legend_rows.append({
            "Angle": f"{deg}°",
            "Days from Start": round(deg * 365 / 360),
            "Projected Date": proj.strftime("%d %b %Y"),
            "Shape": shape,
        })
    st.dataframe(pd.DataFrame(_legend_rows), width='stretch', hide_index=True)

    # ── Backtest ──────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📊 Backtest — Historic Reversal Accuracy")
    st.markdown(_BT_LABEL, unsafe_allow_html=True)
    st.caption(
        f"For each past swing pivot as the 0° start, checks whether price reversed "
        f"within ±{emb_window} days of each projected key angle. "
        f"Reversal = price makes a local turning point in the window."
    )

    close_s = df["Close"].squeeze()
    _emb_bt = []
    for ptype, plist_bt in [("Swing High", ph_list), ("Swing Low", pl_list)]:
        for pdate_str, pprice in plist_bt[-10:]:
            pdate = pd.Timestamp(pdate_str)
            hits = 0
            total = 0
            for ang in KEY_ANGLES[1:]:   # skip 0° (the start itself)
                proj_d = pdate + pd.Timedelta(days=round(ang * 365 / 360))
                if proj_d > close_s.index[-1]:
                    continue
                total += 1
                win = close_s.loc[
                    (close_s.index >= proj_d - pd.Timedelta(days=emb_window)) &
                    (close_s.index <= proj_d + pd.Timedelta(days=emb_window))
                ]
                if len(win) >= 3:
                    mid = win.iloc[len(win) // 2]
                    # Local high (reversal down) or local low (reversal up)
                    if (win.iloc[0] < mid > win.iloc[-1]) or (win.iloc[0] > mid < win.iloc[-1]):
                        hits += 1
            if total > 0:
                _emb_bt.append({
                    "Pivot Type":    ptype,
                    "Pivot Date":    pdate_str,
                    "Pivot Price":   f"₹{pprice:,.1f}",
                    "Angles Tested": total,
                    "Reversals Hit": hits,
                    "Accuracy %":    round(hits / total * 100, 1),
                })

    if _emb_bt:
        _emb_df = pd.DataFrame(_emb_bt).sort_values("Pivot Date", ascending=False).reset_index(drop=True)
        avg_acc = _emb_df["Accuracy %"].mean()

        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Avg Emblem Accuracy", f"{avg_acc:.1f}%")
        mc2.metric("Pivots Tested", len(_emb_df))
        mc3.metric("Reversal Window", f"±{emb_window} days")

        def _emb_color(val):
            if val >= 60:  return "color: #4ade80"
            if val >= 40:  return "color: #FFD600"
            return "color: #FF5252"

        st.dataframe(
            _emb_df.style.map(_emb_color, subset=["Accuracy %"]),
            width='stretch', hide_index=True,
        )
    else:
        st.info("Not enough historical data to run backtest for this stock.")

    st.markdown("---")
    from app.utils.disclaimer import show_footer
    show_footer()
