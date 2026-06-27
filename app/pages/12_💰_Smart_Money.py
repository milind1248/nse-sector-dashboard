"""Smart Money Tracker — FII/DII position detection via Delivery % + Futures OI."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

st.set_page_config(page_title="Smart Money Tracker | FII/DII OI + Delivery | Market Sector Analysis", layout="wide")

from app.utils.seo import inject_seo
inject_seo("Smart_Money")

from app.utils.logo import show_logo
show_logo()

# ── Data fetchers ─────────────────────────────────────────────────────────────

def _fetch_cm_bhav(dt: date) -> pd.DataFrame | None:
    import requests, zipfile, io
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    url = (f"https://nsearchives.nseindia.com/content/cm/"
           f"BhavCopy_NSE_CM_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip")
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        df = pd.read_csv(z.open(z.namelist()[0]))
        eq = df[df["SctySrs"].isin({"EQ", "BE", "BZ", "SM", "ST"})].copy()
        for c in ["ClsPric", "PrvsClsgPric", "TtlTradgVol", "TtlNbOfTxsExctd"]:
            eq[c] = pd.to_numeric(eq[c], errors="coerce")
        return eq[["TckrSymb", "ClsPric", "PrvsClsgPric", "TtlTradgVol", "TtlNbOfTxsExctd"]].dropna()
    except Exception:
        return None


def _fetch_mto_delivery(dt: date) -> pd.DataFrame | None:
    import requests, io
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    url = f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{dt.strftime('%d%m%Y')}.DAT"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        lines = [l for l in r.text.splitlines() if l.startswith("20,")]
        df = pd.read_csv(io.StringIO("\n".join(lines)), header=None,
                         names=["rec", "sr", "symbol", "series", "qty_traded", "dlv_qty", "dlv_pct"])
        eq = df[df["series"] == "EQ"].copy()
        eq["dlv_pct"] = pd.to_numeric(eq["dlv_pct"], errors="coerce")
        return eq[["symbol", "dlv_pct"]].dropna()
    except Exception:
        return None


def _fetch_fo_bhav(dt: date) -> pd.DataFrame | None:
    import requests, zipfile, io
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    url = (f"https://nsearchives.nseindia.com/content/fo/"
           f"BhavCopy_NSE_FO_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip")
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        df = pd.read_csv(z.open(z.namelist()[0]))
        stf = df[df["FinInstrmTp"] == "STF"].copy()
        stf["XpryDt"] = pd.to_datetime(stf["XpryDt"], errors="coerce")
        for c in ["ClsPric", "PrvsClsgPric", "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "TtlNbOfTxsExctd"]:
            stf[c] = pd.to_numeric(stf[c], errors="coerce")
        # Keep only nearest expiry per symbol
        nearest = stf.loc[stf.groupby("TckrSymb")["XpryDt"].idxmin()].copy()
        return nearest[["TckrSymb", "XpryDt", "OpnIntrst", "ChngInOpnIntrst"]].dropna(subset=["OpnIntrst"])
    except Exception:
        return None


def _smart_money_signal(price_chg: float, oi_chg: float) -> str:
    if price_chg > 0 and oi_chg > 0:
        return "Long Buildup"
    if price_chg > 0 and oi_chg < 0:
        return "Short Covering"
    if price_chg < 0 and oi_chg < 0:
        return "Long Unwinding"
    if price_chg < 0 and oi_chg > 0:
        return "Short Buildup"
    return "Neutral"


def _dlv_action(pct: float) -> str:
    if pct >= 40:
        return "High"
    if pct >= 20:
        return "Medium"
    return "Low"


@st.cache_data(ttl=3600, show_spinner=False)
def load_today_data() -> tuple[pd.DataFrame, date | None]:
    """Load today's (latest trading day) merged Smart Money data for all FNO stocks."""
    for offset in range(7):
        dt = date.today() - timedelta(days=offset)
        cm  = _fetch_cm_bhav(dt)
        mto = _fetch_mto_delivery(dt)
        fo  = _fetch_fo_bhav(dt)
        if cm is None or fo is None:
            continue

        # Merge: FO (FNO stocks only) ← CM price/action ← MTO delivery
        merged = fo.merge(cm, on="TckrSymb", how="left")
        if mto is not None:
            merged = merged.merge(mto.rename(columns={"symbol": "TckrSymb"}), on="TckrSymb", how="left")
        else:
            merged["dlv_pct"] = None

        # Calculations
        merged["pct_price_chg"] = (
            (merged["ClsPric"] - merged["PrvsClsgPric"]) / merged["PrvsClsgPric"] * 100
        ).round(2)
        prev_oi = merged["OpnIntrst"] - merged["ChngInOpnIntrst"]
        merged["pct_oi_chg"] = (merged["ChngInOpnIntrst"] / prev_oi.replace(0, float("nan")) * 100).round(2)
        merged["action"]     = (merged["TtlTradgVol"] / merged["TtlNbOfTxsExctd"].replace(0, float("nan"))).round(1)
        merged["dlv_action"] = merged["dlv_pct"].apply(
            lambda x: _dlv_action(x) if pd.notna(x) else "–"
        )
        merged["signal"] = merged.apply(
            lambda r: _smart_money_signal(r["pct_price_chg"], r["pct_oi_chg"])
            if pd.notna(r["pct_price_chg"]) and pd.notna(r["pct_oi_chg"]) else "Neutral",
            axis=1,
        )
        merged["is_bullish"] = merged["signal"].isin({"Long Buildup", "Short Covering"})
        merged = merged.sort_values("TckrSymb").reset_index(drop=True)
        return merged, dt
    return pd.DataFrame(), None


@st.cache_data(ttl=3600, show_spinner=False)
def load_history(symbol: str, days: int = 90) -> pd.DataFrame:
    """Load last N trading days of Smart Money data for a single symbol."""
    rows = []
    checked = 0
    offset = 0
    while len(rows) < days and checked < days + 40:
        dt = date.today() - timedelta(days=offset)
        offset += 1
        if dt.weekday() >= 5:   # skip weekends
            continue
        checked += 1
        cm  = _fetch_cm_bhav(dt)
        mto = _fetch_mto_delivery(dt)
        fo  = _fetch_fo_bhav(dt)
        if cm is None or fo is None:
            continue
        fo_row = fo[fo["TckrSymb"] == symbol]
        cm_row = cm[cm["TckrSymb"] == symbol]
        if fo_row.empty or cm_row.empty:
            continue
        oi       = float(fo_row["OpnIntrst"].iloc[0])
        oi_chg   = float(fo_row["ChngInOpnIntrst"].iloc[0])
        close    = float(cm_row["ClsPric"].iloc[0])
        prev_cl  = float(cm_row["PrvsClsgPric"].iloc[0])
        vol      = float(cm_row["TtlTradgVol"].iloc[0])
        trades   = float(cm_row["TtlNbOfTxsExctd"].iloc[0])
        prev_oi  = oi - oi_chg
        pct_oi   = round(oi_chg / prev_oi * 100, 2) if prev_oi else 0.0
        pct_pr   = round((close - prev_cl) / prev_cl * 100, 2) if prev_cl else 0.0
        act      = round(vol / trades, 1) if trades else 0.0
        dlv_pct  = None
        if mto is not None:
            m = mto[mto["symbol"] == symbol]
            if not m.empty:
                dlv_pct = float(m["dlv_pct"].iloc[0])
        rows.append({
            "Date":          dt,
            "Close":         close,
            "% Price CHG":   pct_pr,
            "Delivery %":    dlv_pct,
            "Dlv Action":    _dlv_action(dlv_pct) if dlv_pct is not None else "–",
            "Futures OI":    int(oi),
            "OI Change":     int(oi_chg),
            "% OI Change":   pct_oi,
            "Action":        act,
            "Signal":        _smart_money_signal(pct_pr, pct_oi),
        })
    return pd.DataFrame(rows)


# ── Page header ───────────────────────────────────────────────────────────────
col_h, col_ref = st.columns([6, 1])
col_h.title("💰 Smart Money Tracker")
col_h.caption("Track FII/DII positions via Futures Open Interest + Cash Delivery % analysis")
if col_ref.button("🔄 Refresh", use_container_width=True):
    load_today_data.clear()
    load_history.clear()
    st.rerun()

# ── Legend ────────────────────────────────────────────────────────────────────
with st.expander("📖 How to read Smart Money signals", expanded=False):
    st.markdown("""
| Signal | Price | OI | Meaning | Trend |
|--------|-------|-----|---------|-------|
| **Long Buildup** | ↑ Up | ↑ Up | New longs being added — institutions entering buy | 🟢 Bullish |
| **Short Covering** | ↑ Up | ↓ Down | Shorts being squared off — bearish positions exiting | 🟢 Bullish |
| **Long Unwinding** | ↓ Down | ↓ Down | Longs being squared off — bulls booking profit | 🔴 Bearish |
| **Short Buildup** | ↓ Down | ↑ Up | New shorts being added — institutions entering sell | 🔴 Bearish |

**Delivery %** — % of traded volume taken as physical delivery (cash market). High delivery (>40%) alongside Long Buildup = strong institutional conviction.
**Action** = Total Traded Qty ÷ Number of Trades. High ratio means large lot sizes → institutional (FII/DII) activity.
""")

# ── Load today's data ─────────────────────────────────────────────────────────
with st.status("🌐 Loading Smart Money data…", expanded=False) as _sts:
    st.write("Fetching NSE CM Bhav Copy, MTO Delivery file, and FO Bhav Copy…")
    today_df, data_date = load_today_data()
    if today_df is not None and not today_df.empty:
        _sts.update(
            label=f"✅ {len(today_df)} FNO stocks loaded · Data: {data_date.strftime('%d %b %Y')}",
            state="complete", expanded=False,
        )
    else:
        _sts.update(label="⚠️ Could not load data — try refreshing", state="error")

if today_df is None or today_df.empty:
    st.error("Smart Money data unavailable. NSE archives may not have today's data yet (available after ~6 PM IST).")
    st.stop()

fno_symbols = sorted(today_df["TckrSymb"].tolist())

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_stock, tab_screener = st.tabs(["🔍 Stock Analysis", "📊 Smart Money Screener"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Single Stock Deep Dive
# ══════════════════════════════════════════════════════════════════════════════
with tab_stock:
    symbol = st.selectbox("Search stock symbol (type to filter)", fno_symbols, index=0)

    row = today_df[today_df["TckrSymb"] == symbol]
    if row.empty:
        st.warning("No data for selected symbol.")
    else:
        r = row.iloc[0]

        # Signal badge
        SIG_COLOR = {
            "Long Buildup":   ("#00C853", "🟢"),
            "Short Covering": ("#64DD17", "🟢"),
            "Long Unwinding": ("#FF5252", "🔴"),
            "Short Buildup":  ("#D50000", "🔴"),
            "Neutral":        ("#888888", "⚪"),
        }
        sig = r["signal"]
        sig_color, sig_icon = SIG_COLOR.get(sig, ("#888", "⚪"))
        st.markdown(
            f"<div style='background:{sig_color}22;border-left:5px solid {sig_color};"
            f"padding:14px 20px;border-radius:6px;margin:8px 0 16px'>"
            f"<span style='font-size:22px;font-weight:700;color:{sig_color}'>"
            f"{sig_icon} {sig}</span>"
            f"<span style='color:#aaa;font-size:13px;margin-left:16px'>"
            f"{'Bullish — institutional accumulation signal' if r['is_bullish'] else 'Bearish — institutional distribution signal' if sig != 'Neutral' else 'No clear directional signal'}"
            f"</span></div>",
            unsafe_allow_html=True,
        )

        # Metric cards
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Close Price",   f"₹{r['ClsPric']:,.2f}" if pd.notna(r.get("ClsPric")) else "–")
        _pp = r["pct_price_chg"]
        c2.metric("% Price CHG",   f"{_pp:+.2f}%" if pd.notna(_pp) else "–",
                  f"{_pp:+.2f}%" if pd.notna(_pp) else None, delta_color="normal")
        _dlv = r["dlv_pct"]
        c3.metric("Delivery %",    f"{_dlv:.1f}%" if pd.notna(_dlv) else "–")
        c4.metric("Dlv Action",    r["dlv_action"])

        c5, c6, c7, c8 = st.columns(4)
        _oi = r["OpnIntrst"]
        c5.metric("Futures OI",    f"{int(_oi):,}" if pd.notna(_oi) else "–")
        _oichg = r["ChngInOpnIntrst"]
        c6.metric("OI Change",     f"{int(_oichg):+,}" if pd.notna(_oichg) else "–",
                  f"{int(_oichg):+,}" if pd.notna(_oichg) else None, delta_color="normal")
        _poichg = r["pct_oi_chg"]
        c7.metric("% OI Change",   f"{_poichg:+.2f}%" if pd.notna(_poichg) else "–",
                  f"{_poichg:+.2f}%" if pd.notna(_poichg) else None, delta_color="normal")
        c8.metric("Action (Lot Ratio)", f"{r['action']:.1f}" if pd.notna(r["action"]) else "–")

        st.markdown("---")
        st.subheader(f"📅 Last 90 trading days — {symbol}")

        with st.status(f"🌐 Loading 90-day history for {symbol}…", expanded=False) as _sh:
            st.write("Fetching daily CM + MTO + FO Bhav Copies from NSE archives…")
            hist_df = load_history(symbol, days=90)
            if not hist_df.empty:
                _sh.update(label=f"✅ {len(hist_df)} trading days loaded", state="complete", expanded=False)
            else:
                _sh.update(label="⚠️ History unavailable", state="error")

        if not hist_df.empty:
            # Charts
            col_ch1, col_ch2 = st.columns(2)
            with col_ch1:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=hist_df["Date"].astype(str), y=hist_df["Close"],
                    name="Close", line=dict(color="#2979FF", width=2),
                ))
                fig.update_layout(
                    template="plotly_dark", height=260,
                    title=f"{symbol} — Close Price", margin=dict(t=40, b=20),
                )
                st.plotly_chart(fig, use_container_width=True)

            with col_ch2:
                oi_colors = ["#00C853" if v >= 0 else "#D50000" for v in hist_df["OI Change"]]
                fig2 = go.Figure(go.Bar(
                    x=hist_df["Date"].astype(str), y=hist_df["OI Change"],
                    marker_color=oi_colors, name="OI Change",
                ))
                fig2.update_layout(
                    template="plotly_dark", height=260,
                    title=f"{symbol} — Futures OI Change", margin=dict(t=40, b=20),
                )
                st.plotly_chart(fig2, use_container_width=True)

            # Color functions for table
            def _c_sig(v):
                m = {"Long Buildup": "color:#00C853;font-weight:600",
                     "Short Covering": "color:#64DD17;font-weight:600",
                     "Long Unwinding": "color:#FF5252;font-weight:600",
                     "Short Buildup":  "color:#D50000;font-weight:600",
                     "Neutral":        "color:#888"}
                return m.get(v, "")

            def _c_num(v):
                if not isinstance(v, (int, float)): return ""
                return "color:#00C853" if v > 0 else "color:#D50000" if v < 0 else ""

            def _c_dlv(v):
                if v == "High":   return "color:#00C853;font-weight:600"
                if v == "Medium": return "color:#FFD600"
                if v == "Low":    return "color:#FF5252"
                return ""

            display_hist = hist_df.copy()
            display_hist["Date"] = display_hist["Date"].astype(str)
            display_hist["Delivery %"] = display_hist["Delivery %"].apply(
                lambda x: f"{x:.1f}%" if pd.notna(x) else "–"
            )
            st.dataframe(
                display_hist.style
                    .map(_c_num,  subset=["% Price CHG", "OI Change", "% OI Change"])
                    .map(_c_dlv,  subset=["Dlv Action"])
                    .map(_c_sig,  subset=["Signal"])
                    .format({
                        "Close":       "₹{:,.2f}",
                        "% Price CHG": "{:+.2f}%",
                        "% OI Change": "{:+.2f}%",
                        "OI Change":   "{:+,}",
                        "Futures OI":  "{:,}",
                        "Action":      "{:.1f}",
                    }, na_rep="–"),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("Historical data could not be loaded. NSE archives keep data for ~3 months.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Smart Money Screener
# ══════════════════════════════════════════════════════════════════════════════
with tab_screener:
    st.subheader(f"📊 All FNO Stocks — Smart Money Signals · {data_date.strftime('%d %b %Y')}")

    # Filter row
    fc1, fc2, fc3 = st.columns([3, 2, 2])
    with fc1:
        sig_filter = st.radio(
            "Signal filter", ["All", "Bullish Only", "Bearish Only", "High Delivery (≥40%)"],
            horizontal=True, index=0,
        )
    with fc2:
        sort_col = st.selectbox("Sort by", ["% OI Change", "% Price CHG", "Delivery %", "Action", "TckrSymb"], index=0)
    with fc3:
        sort_asc = st.radio("Order", ["Descending", "Ascending"], horizontal=True, index=0)

    scr = today_df.copy()
    if sig_filter == "Bullish Only":
        scr = scr[scr["signal"].isin({"Long Buildup", "Short Covering"})]
    elif sig_filter == "Bearish Only":
        scr = scr[scr["signal"].isin({"Long Unwinding", "Short Buildup"})]
    elif sig_filter == "High Delivery (≥40%)":
        scr = scr[scr["dlv_pct"] >= 40]

    sort_map = {"% OI Change": "pct_oi_chg", "% Price CHG": "pct_price_chg",
                "Delivery %": "dlv_pct", "Action": "action", "TckrSymb": "TckrSymb"}
    scr = scr.sort_values(sort_map[sort_col], ascending=(sort_asc == "Ascending")).reset_index(drop=True)

    st.caption(f"Showing {len(scr)} of {len(today_df)} FNO stocks")

    # Build display DataFrame
    display = pd.DataFrame({
        "Symbol":        scr["TckrSymb"],
        "Close":         scr["ClsPric"],
        "% Price CHG":   scr["pct_price_chg"],
        "Delivery %":    scr["dlv_pct"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "–"),
        "Dlv Action":    scr["dlv_action"],
        "Futures OI":    scr["OpnIntrst"].apply(lambda x: int(x) if pd.notna(x) else 0),
        "OI Change":     scr["ChngInOpnIntrst"].apply(lambda x: int(x) if pd.notna(x) else 0),
        "% OI Change":   scr["pct_oi_chg"],
        "Action":        scr["action"],
        "Signal":        scr["signal"],
    })

    def _cs(v):
        m = {"Long Buildup":   "color:#00C853;font-weight:600",
             "Short Covering": "color:#64DD17;font-weight:600",
             "Long Unwinding": "color:#FF5252;font-weight:600",
             "Short Buildup":  "color:#D50000;font-weight:600",
             "Neutral":        "color:#888"}
        return m.get(v, "")

    def _cn(v):
        if not isinstance(v, (int, float)): return ""
        return "color:#00C853" if v > 0 else "color:#D50000" if v < 0 else ""

    def _cd(v):
        if v == "High":   return "color:#00C853;font-weight:600"
        if v == "Medium": return "color:#FFD600"
        if v == "Low":    return "color:#FF5252"
        return ""

    st.dataframe(
        display.style
            .map(_cn, subset=["% Price CHG", "OI Change", "% OI Change"])
            .map(_cd, subset=["Dlv Action"])
            .map(_cs, subset=["Signal"])
            .format({
                "Close":       "₹{:,.2f}",
                "% Price CHG": "{:+.2f}%",
                "% OI Change": "{:+.2f}%",
                "OI Change":   "{:+,}",
                "Futures OI":  "{:,}",
                "Action":      "{:.1f}",
            }, na_rep="–"),
        use_container_width=True, hide_index=True, height=600,
    )

from app.utils.disclaimer import show_footer
show_footer()
