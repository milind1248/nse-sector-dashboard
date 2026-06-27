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

# ── Raw data fetchers (shared) ────────────────────────────────────────────────

def _get_headers():
    return {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _fetch_cm_bhav(dt: date) -> pd.DataFrame | None:
    import requests, zipfile, io
    url = (f"https://nsearchives.nseindia.com/content/cm/"
           f"BhavCopy_NSE_CM_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip")
    try:
        r = requests.get(url, headers=_get_headers(), timeout=15)
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
    url = f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{dt.strftime('%d%m%Y')}.DAT"
    try:
        r = requests.get(url, headers=_get_headers(), timeout=10)
        if r.status_code != 200:
            return None
        lines = [l for l in r.text.splitlines() if l.startswith("20,")]
        df = pd.read_csv(io.StringIO("\n".join(lines)), header=None,
                         names=["rec", "sr", "symbol", "series", "qty_traded", "dlv_qty", "dlv_pct"])
        eq = df[df["series"] == "EQ"].copy()
        eq["dlv_pct"] = pd.to_numeric(eq["dlv_pct"], errors="coerce")
        return eq[["symbol", "dlv_pct"]].dropna().rename(columns={"symbol": "TckrSymb"})
    except Exception:
        return None


def _fetch_fo_bhav(dt: date) -> pd.DataFrame | None:
    """Return nearest-expiry stock futures OI + trade data only."""
    import requests, zipfile, io
    url = (f"https://nsearchives.nseindia.com/content/fo/"
           f"BhavCopy_NSE_FO_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip")
    try:
        r = requests.get(url, headers=_get_headers(), timeout=15)
        if r.status_code != 200:
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        df = pd.read_csv(z.open(z.namelist()[0]))
        stf = df[df["FinInstrmTp"] == "STF"].copy()
        stf["XpryDt"] = pd.to_datetime(stf["XpryDt"], errors="coerce")
        for c in ["OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "TtlNbOfTxsExctd"]:
            stf[c] = pd.to_numeric(stf[c], errors="coerce")
        # Nearest expiry per symbol
        nearest = stf.loc[stf.groupby("TckrSymb")["XpryDt"].idxmin()].copy()
        # Return ONLY OI + FO trade data — no price columns to avoid merge conflict with CM
        return nearest[["TckrSymb", "XpryDt", "OpnIntrst", "ChngInOpnIntrst",
                         "TtlTradgVol", "TtlNbOfTxsExctd"]].dropna(subset=["OpnIntrst"])
    except Exception:
        return None


# ── Smart Money calculations ──────────────────────────────────────────────────

def _oi_signal(price_chg: float, oi_chg: float) -> str:
    """OI + Price direction signal (Long Buildup / Short Covering etc.)"""
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


def _smart_money_label(dlv_pct, action, avg_dlv, avg_action, oi_sig):
    """
    Excel formula: IF(Delivery% > avg AND Action > avg, 'Buying', '')
    Combined with OI signal for full context.
    """
    cash_buying = (pd.notna(dlv_pct) and dlv_pct > avg_dlv and
                   pd.notna(action) and action > avg_action)
    if cash_buying and oi_sig in ("Long Buildup", "Short Covering"):
        return "Strong Buy"
    if cash_buying:
        return "Buying"
    if oi_sig in ("Long Buildup", "Short Covering"):
        return "Bullish OI"
    if oi_sig in ("Long Unwinding", "Short Buildup"):
        return "Bearish OI"
    return "–"


def _compute_metrics(fo: pd.DataFrame, cm: pd.DataFrame, mto: pd.DataFrame | None) -> pd.DataFrame:
    """
    Merge FO (OI) + CM (price/volume) + MTO (delivery) and compute all metrics.
    FO has: TckrSymb, OpnIntrst, ChngInOpnIntrst, TtlTradgVol (FO), TtlNbOfTxsExctd (FO)
    CM has: TckrSymb, ClsPric, PrvsClsgPric, TtlTradgVol (CM), TtlNbOfTxsExctd (CM)
    Action = FO TtlTradgVol / FO TtlNbOfTxsExctd  (futures lot ratio — Excel formula J/K)
    """
    # Rename FO trade cols before merge to avoid conflict with CM
    fo2 = fo.rename(columns={"TtlTradgVol": "FO_Vol", "TtlNbOfTxsExctd": "FO_Trades"})
    merged = fo2.merge(cm, on="TckrSymb", how="left")
    if mto is not None:
        merged = merged.merge(mto, on="TckrSymb", how="left")
    else:
        merged["dlv_pct"] = float("nan")

    # % Price CHG — Excel: ((Close_today / Close_prev) - 1) * 100
    merged["pct_price_chg"] = (
        (merged["ClsPric"] - merged["PrvsClsgPric"]) / merged["PrvsClsgPric"] * 100
    ).round(2)

    # % OI Change — Excel: ((OI_today / OI_prev) - 1) * 100
    prev_oi = merged["OpnIntrst"] - merged["ChngInOpnIntrst"]
    merged["pct_oi_chg"] = (
        merged["ChngInOpnIntrst"] / prev_oi.replace(0, float("nan")) * 100
    ).round(2)

    # Action = FO TradeQty / FO TotTrade  (Excel: J/K — futures lot ratio)
    merged["action"] = (
        merged["FO_Vol"] / merged["FO_Trades"].replace(0, float("nan"))
    ).round(1)

    # Delivery % Action label
    merged["dlv_action"] = merged["dlv_pct"].apply(
        lambda x: _dlv_action(x) if pd.notna(x) else "–"
    )

    # OI signal
    merged["oi_signal"] = merged.apply(
        lambda r: _oi_signal(r["pct_price_chg"], r["pct_oi_chg"])
        if pd.notna(r["pct_price_chg"]) and pd.notna(r["pct_oi_chg"]) else "Neutral",
        axis=1,
    )

    # Smart Money label (Excel formula + OI context)
    avg_dlv = merged["dlv_pct"].median()
    avg_act = merged["action"].median()
    merged["smart_money"] = merged.apply(
        lambda r: _smart_money_label(r["dlv_pct"], r["action"], avg_dlv, avg_act, r["oi_signal"]),
        axis=1,
    )

    merged["is_bullish"] = merged["oi_signal"].isin({"Long Buildup", "Short Covering"})
    return merged.sort_values("TckrSymb").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def load_today_data() -> tuple[pd.DataFrame, date | None]:
    """Load latest trading day — merge FO OI + CM price + MTO delivery."""
    for offset in range(7):
        dt = date.today() - timedelta(days=offset)
        if dt.weekday() >= 5:
            continue
        fo  = _fetch_fo_bhav(dt)
        cm  = _fetch_cm_bhav(dt)
        mto = _fetch_mto_delivery(dt)
        if fo is None or cm is None:
            continue
        merged = _compute_metrics(fo, cm, mto)
        if len(merged) > 10:
            return merged, dt
    return pd.DataFrame(), None


@st.cache_data(ttl=3600, show_spinner=False)
def load_price_history(symbol: str) -> pd.DataFrame:
    """90-day price history via yfinance (fast single call)."""
    try:
        import yfinance as yf
        df = yf.download(f"{symbol}.NS", period="3mo", interval="1d",
                         auto_adjust=True, progress=False)
        if df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        close = df["Close"].squeeze()
        prev  = close.shift(1)
        result = pd.DataFrame({
            "Date":          df["Date"].dt.date,
            "Close":         close.values,
            "% Price CHG":   ((close - prev) / prev * 100).round(2).values,
            "Volume":        df["Volume"].squeeze().values,
        })
        return result.dropna().sort_values("Date", ascending=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


# ── Page header ───────────────────────────────────────────────────────────────
col_h, col_ref = st.columns([6, 1])
col_h.title("💰 Smart Money Tracker")
col_h.caption("FII/DII position detection via Futures OI signals + Cash Delivery % analysis")
if col_ref.button("🔄 Refresh", use_container_width=True):
    load_today_data.clear()
    load_price_history.clear()
    st.rerun()

# ── Legend ────────────────────────────────────────────────────────────────────
with st.expander("📖 How to read Smart Money signals", expanded=False):
    st.markdown("""
**Smart Money label** (based on Excel formula: Delivery % > median AND Action ratio > median):

| Label | Meaning |
|-------|---------|
| **Strong Buy** | High delivery % + High action ratio + Bullish OI signal → Strong institutional accumulation |
| **Buying** | High delivery % + High action ratio → Cash market institutional buying |
| **Bullish OI** | Bullish OI signal (Long Buildup / Short Covering) without confirmed cash delivery |
| **Bearish OI** | Bearish OI signal (Long Unwinding / Short Buildup) |
| **–** | No clear smart money signal |

**OI Signals** (% Price CHG vs % OI Change):

| Signal | Price | OI | Trend |
|--------|-------|----|-------|
| Long Buildup | ↑ | ↑ | 🟢 Bullish — new longs being added |
| Short Covering | ↑ | ↓ | 🟢 Bullish — shorts being squared off |
| Long Unwinding | ↓ | ↓ | 🔴 Bearish — longs booking profit |
| Short Buildup | ↓ | ↑ | 🔴 Bearish — new shorts being added |

**Action** = Futures Contracts Traded ÷ Number of Trades. High ratio = large lot sizes = institutional activity.
**Delivery %** = % of cash market volume taken as physical delivery. High delivery (>40%) = institutional conviction.
""")

# ── Load today's data ─────────────────────────────────────────────────────────
with st.status("🌐 Loading Smart Money data…", expanded=False) as _sts:
    st.write("Fetching NSE FO Bhav Copy (Futures OI), CM Bhav Copy (prices), MTO Delivery file…")
    today_df, data_date = load_today_data()
    if today_df is not None and not today_df.empty:
        _sts.update(
            label=f"✅ {len(today_df)} FNO stocks loaded · Data: {data_date.strftime('%d %b %Y')}",
            state="complete", expanded=False,
        )
    else:
        _sts.update(label="⚠️ Could not load data — NSE archives available after ~6 PM IST", state="error")

if today_df is None or today_df.empty:
    st.error("Smart Money data unavailable. NSE archives publish data after ~6 PM IST on trading days.")
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

        SM_COLOR = {
            "Strong Buy":   ("#00C853", "💰"),
            "Buying":       ("#64DD17", "🟢"),
            "Bullish OI":   ("#00BCD4", "🔵"),
            "Bearish OI":   ("#FF5252", "🔴"),
            "–":            ("#888888", "⚪"),
        }
        OI_COLOR = {
            "Long Buildup":   "#00C853",
            "Short Covering": "#64DD17",
            "Long Unwinding": "#FF5252",
            "Short Buildup":  "#D50000",
            "Neutral":        "#888888",
        }
        sm = r["smart_money"]
        oi_sig = r["oi_signal"]
        sm_color, sm_icon = SM_COLOR.get(sm, ("#888", "⚪"))
        oi_color = OI_COLOR.get(oi_sig, "#888")

        col_sm, col_oi = st.columns(2)
        col_sm.markdown(
            f"<div style='background:{sm_color}22;border-left:5px solid {sm_color};"
            f"padding:12px 18px;border-radius:6px'>"
            f"<div style='font-size:11px;color:#aaa;margin-bottom:2px'>Smart Money Signal</div>"
            f"<span style='font-size:20px;font-weight:700;color:{sm_color}'>{sm_icon} {sm}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        col_oi.markdown(
            f"<div style='background:{oi_color}22;border-left:5px solid {oi_color};"
            f"padding:12px 18px;border-radius:6px'>"
            f"<div style='font-size:11px;color:#aaa;margin-bottom:2px'>OI Signal</div>"
            f"<span style='font-size:20px;font-weight:700;color:{oi_color}'>{oi_sig}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)

        # Metric cards
        c1, c2, c3, c4 = st.columns(4)
        _close = r.get("ClsPric")
        c1.metric("Close Price", f"₹{_close:,.2f}" if pd.notna(_close) else "–")
        _pp = r["pct_price_chg"]
        c2.metric("% Price CHG", f"{_pp:+.2f}%" if pd.notna(_pp) else "–",
                  f"{_pp:+.2f}%" if pd.notna(_pp) else None, delta_color="normal")
        _dlv = r.get("dlv_pct")
        c3.metric("Delivery %", f"{_dlv:.1f}%" if pd.notna(_dlv) else "–")
        c4.metric("Dlv Action", r["dlv_action"])

        c5, c6, c7, c8 = st.columns(4)
        _oi = r["OpnIntrst"]
        c5.metric("Futures OI", f"{int(_oi):,}" if pd.notna(_oi) else "–")
        _oichg = r["ChngInOpnIntrst"]
        c6.metric("OI Change", f"{int(_oichg):+,}" if pd.notna(_oichg) else "–",
                  f"{int(_oichg):+,}" if pd.notna(_oichg) else None, delta_color="normal")
        _poichg = r["pct_oi_chg"]
        c7.metric("% OI Change", f"{_poichg:+.2f}%" if pd.notna(_poichg) else "–",
                  f"{_poichg:+.2f}%" if pd.notna(_poichg) else None, delta_color="normal")
        _act = r["action"]
        c8.metric("Action (Lot Ratio)", f"{_act:.1f}" if pd.notna(_act) else "–")

        st.markdown("---")
        st.subheader(f"📅 Last 90 days — {symbol}")
        st.caption("Price history from Yahoo Finance (fast). OI snapshot is today's data only.")

        with st.spinner(f"Loading 90-day price history for {symbol}…"):
            hist_df = load_price_history(symbol)

        if not hist_df.empty:
            col_ch1, col_ch2 = st.columns(2)
            with col_ch1:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=hist_df["Date"].astype(str), y=hist_df["Close"],
                    name="Close", line=dict(color="#2979FF", width=2),
                ))
                if pd.notna(_close):
                    fig.add_hline(y=float(_close), line_dash="dot",
                                  line_color="#FFD600", annotation_text="Today")
                fig.update_layout(
                    template="plotly_dark", height=280,
                    title=f"{symbol} — 90-Day Close Price", margin=dict(t=40, b=20),
                )
                st.plotly_chart(fig, use_container_width=True)

            with col_ch2:
                colors = ["#00C853" if v >= 0 else "#D50000"
                          for v in hist_df["% Price CHG"].fillna(0)]
                fig2 = go.Figure(go.Bar(
                    x=hist_df["Date"].astype(str), y=hist_df["% Price CHG"],
                    marker_color=colors, name="% Price CHG",
                ))
                fig2.update_layout(
                    template="plotly_dark", height=280,
                    title=f"{symbol} — Daily % Price Change", margin=dict(t=40, b=20),
                )
                st.plotly_chart(fig2, use_container_width=True)

            def _cn(v):
                if not isinstance(v, (int, float)): return ""
                return "color:#00C853" if v > 0 else "color:#D50000" if v < 0 else ""

            st.dataframe(
                hist_df.style
                    .map(_cn, subset=["% Price CHG"])
                    .format({"Close": "₹{:,.2f}", "% Price CHG": "{:+.2f}%",
                             "Volume": "{:,.0f}"}, na_rep="–"),
                use_container_width=True, hide_index=True, height=400,
            )
        else:
            st.info(f"Price history unavailable for {symbol} via Yahoo Finance.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Smart Money Screener
# ══════════════════════════════════════════════════════════════════════════════
with tab_screener:
    st.subheader(f"📊 All FNO Stocks — Smart Money Screener · {data_date.strftime('%d %b %Y')}")

    fc1, fc2, fc3 = st.columns([3, 2, 2])
    with fc1:
        sm_filter = st.radio(
            "Smart Money filter",
            ["All", "Strong Buy", "Buying", "Bullish OI", "Bearish OI", "High Delivery (≥40%)"],
            horizontal=True, index=0,
        )
    with fc2:
        sort_col = st.selectbox(
            "Sort by",
            ["% OI Change", "% Price CHG", "Delivery %", "Action", "Symbol"],
            index=0,
        )
    with fc3:
        sort_asc = st.radio("Order", ["Descending", "Ascending"], horizontal=True, index=0)

    scr = today_df.copy()
    if sm_filter == "High Delivery (≥40%)":
        scr = scr[scr["dlv_pct"] >= 40]
    elif sm_filter != "All":
        scr = scr[scr["smart_money"] == sm_filter]

    sort_map = {
        "% OI Change": "pct_oi_chg", "% Price CHG": "pct_price_chg",
        "Delivery %": "dlv_pct", "Action": "action", "Symbol": "TckrSymb",
    }
    scr = scr.sort_values(sort_map[sort_col], ascending=(sort_asc == "Ascending")).reset_index(drop=True)

    st.caption(f"Showing {len(scr)} of {len(today_df)} FNO stocks")

    display = pd.DataFrame({
        "Symbol":        scr["TckrSymb"],
        "Close (₹)":     scr["ClsPric"],
        "% Price CHG":   scr["pct_price_chg"],
        "Delivery %":    scr["dlv_pct"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "–"),
        "Dlv Action":    scr["dlv_action"],
        "Futures OI":    scr["OpnIntrst"].apply(lambda x: int(x) if pd.notna(x) else 0),
        "OI Change":     scr["ChngInOpnIntrst"].apply(lambda x: int(x) if pd.notna(x) else 0),
        "% OI Change":   scr["pct_oi_chg"],
        "Action":        scr["action"],
        "OI Signal":     scr["oi_signal"],
        "Smart Money":   scr["smart_money"],
    })

    SM_COLORS = {
        "Strong Buy":   "color:#00C853;font-weight:700",
        "Buying":       "color:#64DD17;font-weight:600",
        "Bullish OI":   "color:#00BCD4",
        "Bearish OI":   "color:#FF5252",
        "–":            "color:#555",
    }
    OI_COLORS = {
        "Long Buildup":   "color:#00C853;font-weight:600",
        "Short Covering": "color:#64DD17;font-weight:600",
        "Long Unwinding": "color:#FF5252;font-weight:600",
        "Short Buildup":  "color:#D50000;font-weight:600",
        "Neutral":        "color:#888",
    }

    def _csm(v): return SM_COLORS.get(v, "")
    def _coi(v): return OI_COLORS.get(v, "")
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
            .map(_cn,  subset=["% Price CHG", "OI Change", "% OI Change"])
            .map(_cd,  subset=["Dlv Action"])
            .map(_coi, subset=["OI Signal"])
            .map(_csm, subset=["Smart Money"])
            .format({
                "Close (₹)":   "₹{:,.2f}",
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
