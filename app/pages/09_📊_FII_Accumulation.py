"""FII Accumulation Screener — quarterly shareholding change analysis across NSE sectors."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.utils.auth import is_admin
from backend.storage.db import get_conn

st.set_page_config(
    page_title="FII Accumulation Screener | Quarterly Shareholding | Market Sector Analysis",
    layout="wide",
)
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()

from app.utils.seo import inject_seo
inject_seo("FII_Accumulation")

from app.utils.logo import show_logo
show_logo()

with st.sidebar:
    from app.utils.user_session import render_auth_sidebar
    render_auth_sidebar()

from app.utils.access_control import require_page_access
require_page_access("FII Accumulation")

from app.utils.disclaimer import show_sebi_notice, show_footer

# ── DB ────────────────────────────────────────────────────────────────────────
def _db():
    return get_conn()


# ── Sector map ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _build_sector_map() -> dict:
    try:
        con = _db()
        rows = con.execute(
            "SELECT DISTINCT symbol, sector FROM sector_intelligence WHERE symbol IS NOT NULL"
        ).fetchall()
        con.close()
        return {r[0].replace(".NS", "").upper(): r[1] for r in rows if r[0]}
    except Exception:
        return {}


def _sym_sector(symbol: str) -> str:
    return _build_sector_map().get(symbol.replace(".NS", "").upper(), "–")


# ── Shareholding fetch (reuses screener.in logic from Smart Money page) ────────
def _fetch_shareholding(symbol: str) -> list[dict]:
    """
    Retrieve up to 12 quarters of shareholding pattern from public company filings.
    Data sourced from quarterly BSE/NSE disclosures (SEBI mandate). Educational reference only.
    """
    import requests
    from bs4 import BeautifulSoup
    from datetime import datetime

    for suffix in ["/consolidated/", "/"]:
        url = f"https://www.screener.in/company/{symbol}{suffix}"
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            sh_section = soup.find("section", {"id": "shareholding"})
            if not sh_section:
                continue
            table = sh_section.find("table")
            if not table:
                continue
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
            quarters = headers[1:]
            cat_map = {
                "Promoters": "promoter",
                "FIIs":      "fii",
                "DIIs":      "dii",
                "Government":"government",
                "Public":    "public_retail",
            }
            data: dict[str, list] = {}
            for row in rows[1:]:
                cells = row.find_all(["th", "td"])
                if not cells:
                    continue
                label = cells[0].get_text(strip=True).replace("+", "").strip()
                key = cat_map.get(label)
                if not key:
                    continue
                vals = []
                for c in cells[1:]:
                    txt = c.get_text(strip=True).replace("%", "").replace(",", "").strip()
                    try:
                        vals.append(float(txt))
                    except ValueError:
                        vals.append(None)
                data[key] = vals
            if not data:
                continue
            num_q  = len(quarters)
            start  = max(0, num_q - 12)
            now_ts = datetime.utcnow().isoformat()
            result = []
            for i in range(num_q - 1, start - 1, -1):
                if i >= len(quarters):
                    continue
                result.append({
                    "symbol":        symbol,
                    "quarter":       quarters[i],
                    "promoter":      data.get("promoter",      [None] * num_q)[i],
                    "fii":           data.get("fii",           [None] * num_q)[i],
                    "dii":           data.get("dii",           [None] * num_q)[i],
                    "government":    data.get("government",    [None] * num_q)[i],
                    "public_retail": data.get("public_retail", [None] * num_q)[i],
                    "fetched_at":    now_ts,
                })
            return result
        except Exception:
            continue
    return []


def _get_last_refresh() -> str | None:
    try:
        con = _db()
        row = con.execute(
            "SELECT value FROM shareholding_refresh_meta WHERE key='last_full_refresh'"
        ).fetchone()
        con.close()
        return row[0] if row else None
    except Exception:
        return None


def _set_last_refresh():
    from datetime import datetime
    ts = datetime.utcnow().isoformat()
    con = _db()
    con.execute(
        "INSERT INTO shareholding_refresh_meta (key, value) VALUES ('last_full_refresh', %s) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
        (ts,)
    )
    con.commit()
    con.close()


def _next_scheduled_refresh() -> str:
    """
    SEBI mandates shareholding filing within 21 days of quarter end.
    We pull 6 days after that deadline (27th of Jan/Apr/Jul/Oct) to ensure
    all companies have filed. Returns next scheduled pull date as string.
    """
    from datetime import date
    today = date.today()
    # Scheduled pull dates: 27 Jan, 27 Apr, 27 Jul, 27 Oct
    candidates = [
        date(today.year, 1,  27),
        date(today.year, 4,  27),
        date(today.year, 7,  27),
        date(today.year, 10, 27),
        date(today.year + 1, 1, 27),  # wrap to next year
    ]
    future = [d for d in candidates if d > today]
    nxt = future[0] if future else candidates[-1]
    return nxt.strftime("%d %B %Y").lstrip("0")


def _save_shareholding(rows: list[dict]):
    if not rows:
        return
    con = _db()
    con.executemany("""
        INSERT INTO shareholding_pattern
        (symbol, quarter, promoter, fii, dii, government, public_retail, fetched_at)
        VALUES (%(symbol)s, %(quarter)s, %(promoter)s, %(fii)s, %(dii)s,
                %(government)s, %(public_retail)s, %(fetched_at)s)
        ON CONFLICT (symbol, quarter) DO UPDATE SET
            promoter=EXCLUDED.promoter, fii=EXCLUDED.fii, dii=EXCLUDED.dii,
            government=EXCLUDED.government, public_retail=EXCLUDED.public_retail,
            fetched_at=EXCLUDED.fetched_at
    """, rows)
    con.commit()
    con.close()


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_symbols_in_db() -> set:
    try:
        con = _db()
        rows = con.execute("SELECT DISTINCT symbol FROM shareholding_pattern").fetchall()
        con.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


# ── All sector symbols list ────────────────────────────────────────────────────
def _all_sector_symbols() -> list[str]:
    """Return all .NS symbols defined across all sectors in config."""
    from config import SECTOR_STOCKS
    seen = set()
    out = []
    for syms in SECTOR_STOCKS.values():
        for s in syms:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


# ── Build screener dataframe ────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def _build_screener() -> pd.DataFrame:
    """
    Read shareholding_pattern table. For each symbol compute:
    - Latest FII%, previous quarter FII%, QoQ delta
    - Consecutive quarters of FII increase (streak)
    - DII QoQ delta (for divergence signal)
    Returns DataFrame sorted by QoQ delta descending.
    """
    con = _db()
    try:
        df = pd.read_sql_query(
            "SELECT symbol, quarter, fii, dii, promoter FROM shareholding_pattern",
            con
        )
    except Exception:
        return pd.DataFrame()
    finally:
        con.close()

    if df.empty:
        return df

    # Parse quarter strings to sortable dates
    df["_q_date"] = pd.to_datetime(df["quarter"], format="%b %Y", errors="coerce")
    df = df.dropna(subset=["_q_date"])

    rows = []
    for sym, grp in df.groupby("symbol"):
        grp = grp.sort_values("_q_date", ascending=False).reset_index(drop=True)
        if len(grp) < 2:
            continue
        fii_now  = grp.at[0, "fii"]
        fii_prev = grp.at[1, "fii"]
        dii_now  = grp.at[0, "dii"]
        dii_prev = grp.at[1, "dii"]

        if pd.isna(fii_now) or pd.isna(fii_prev):
            continue

        qoq     = round(float(fii_now) - float(fii_prev), 2)
        dii_qoq = round(float(dii_now) - float(dii_prev), 2) if (
            not pd.isna(dii_now) and not pd.isna(dii_prev)
        ) else None

        # Consecutive quarters where FII kept rising
        streak = 0
        for i in range(len(grp) - 1):
            fi = grp.at[i, "fii"]
            fn = grp.at[i + 1, "fii"]
            if not pd.isna(fi) and not pd.isna(fn) and float(fi) > float(fn):
                streak += 1
            else:
                break

        if qoq > 0:
            signal = "Accumulating"
        elif qoq < 0:
            signal = "Reducing"
        else:
            signal = "Stable"

        divergence = (
            qoq > 0 and dii_qoq is not None and dii_qoq < 0
        )

        rows.append({
            "Symbol":     sym.replace(".NS", ""),
            "_sym_full":  sym,
            "Sector":     _sym_sector(sym),
            "FII %":      round(float(fii_now), 2),
            "Prev FII %": round(float(fii_prev), 2),
            "QoQ Δ": qoq,
            "Streak":     streak,
            "DII %":      round(float(dii_now), 2) if not pd.isna(dii_now) else None,
            "DII Δ": dii_qoq,
            "Signal":     signal,
            "Divergence": divergence,
            "Latest Qtr": grp.at[0, "quarter"],
        })

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("QoQ Δ", ascending=False).reset_index(drop=True)
    return result


# ── Color styling ──────────────────────────────────────────────────────────────
def _color_delta(val):
    if pd.isna(val):
        return ""
    if val > 0:
        return "color: #43A047; font-weight:600"
    if val < 0:
        return "color: #E53935; font-weight:600"
    return ""


def _color_signal(val):
    if val == "Accumulating":
        return "color: #43A047; font-weight:600"
    if val == "Reducing":
        return "color: #E53935; font-weight:600"
    return "color: #888"


# ── 4-Quarter trend chart ─────────────────────────────────────────────────────
def _trend_chart(symbol_full: str):
    con = _db()
    df = pd.read_sql_query(
        "SELECT quarter, promoter, fii, dii FROM shareholding_pattern WHERE symbol=%s",
        con, params=(symbol_full,)
    )
    con.close()
    if df.empty:
        return None
    df["_q"] = pd.to_datetime(df["quarter"], format="%b %Y", errors="coerce")
    df = df.dropna(subset=["_q"]).sort_values("_q").tail(6)
    labels = df["quarter"].tolist()

    # Compute Y-axis range across all three series with 5% padding
    all_vals = (
        df["fii"].dropna().tolist()
        + df["dii"].dropna().tolist()
        + df["promoter"].dropna().tolist()
    )
    y_min = max(0, min(all_vals) - 5)
    y_max = max(all_vals) + 5

    def _fmt(vals):
        return [f"{v:.2f}%" if v is not None and not pd.isna(v) else "N/A" for v in vals]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=df["fii"].tolist(),
        mode="lines+markers+text",
        name="FII %",
        line=dict(color="#43A047", width=2),
        marker=dict(size=7),
        text=_fmt(df["fii"].tolist()),
        textposition="top center",
        textfont=dict(size=10, color="#43A047"),
        hovertemplate="<b>FII %</b>: %{y:.2f}%<br>Quarter: %{x}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=df["dii"].tolist(),
        mode="lines+markers+text",
        name="DII %",
        line=dict(color="#FB8C00", width=2),
        marker=dict(size=7),
        text=_fmt(df["dii"].tolist()),
        textposition="bottom center",
        textfont=dict(size=10, color="#FB8C00"),
        hovertemplate="<b>DII %</b>: %{y:.2f}%<br>Quarter: %{x}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=df["promoter"].tolist(),
        mode="lines+markers+text",
        name="Promoter %",
        line=dict(color="#5C6BC0", width=2, dash="dot"),
        marker=dict(size=6),
        text=_fmt(df["promoter"].tolist()),
        textposition="top center",
        textfont=dict(size=10, color="#5C6BC0"),
        hovertemplate="<b>Promoter %</b>: %{y:.2f}%<br>Quarter: %{x}<extra></extra>",
    ))
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=1.12),
        hovermode="x unified",
        xaxis=dict(showgrid=False),
        yaxis=dict(
            title="Shareholding %",
            gridcolor="#2a2a2a",
            ticksuffix="%",
            range=[y_min, y_max],
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc", size=12),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# PAGE
# ══════════════════════════════════════════════════════════════════════════════
show_sebi_notice()

st.title("📊 FII Accumulation Screener")
st.caption(
    "Track quarterly FII/FPI shareholding changes across NSE sector stocks. "
    "Data derived from quarterly BSE/NSE company filings (SEBI-mandated disclosures). "
    "**For research and educational reference only — not investment advice.**"
)

# ── Data availability & refresh ────────────────────────────────────────────────
all_syms   = _all_sector_symbols()
cached_set = _cached_symbols_in_db()
missing    = [s for s in all_syms if s not in cached_set]

last_refresh = _get_last_refresh()
next_refresh  = _next_scheduled_refresh()

col_info, col_btn = st.columns([3, 1])
with col_info:
    status_parts = [
        f"Shareholding data available for **{len(cached_set)}** of **{len(all_syms)}** sector stocks.",
        f"{'**' + str(len(missing)) + ' stocks not yet loaded** — click Refresh to fetch all.' if missing else 'All stocks loaded.'}",
        f"Last full refresh: **{last_refresh[:10] if last_refresh else 'Never'}**",
        f"Next auto-refresh scheduled: **{next_refresh}**",
    ]
    st.markdown(
        "<div style='background:#1a3a4a;border-left:4px solid #4da6d4;padding:10px 14px;"
        "border-radius:4px;font-size:0.78rem;line-height:1.6'>"
        + "<br>".join(
            p.replace("**", "<b>", 1).replace("**", "</b>", 1)
             .replace("**", "<b>", 1).replace("**", "</b>", 1)
            for p in status_parts
        )
        + "</div>",
        unsafe_allow_html=True,
    )
with col_btn:
    if is_admin():
        refresh = st.button(
            "🔄 Refresh Data", type="primary", width='stretch',
            help="Fetches all shareholding data from public quarterly filings. Takes 3–5 min. Auto-runs 4× per year.",
        )
    else:
        st.caption("🔒 Data refresh is admin-only.")
        refresh = False

if refresh:
    to_fetch = all_syms
    st.warning(f"Fetching shareholding data for {len(to_fetch)} stocks from public quarterly filings. Please wait…")
    from backend.data_ingestion.job_logger import log_start, log_finish
    _job_row = log_start("shareholding_quarterly", "Quarterly Shareholding Refresh (Admin)", triggered_by="admin")
    prog   = st.progress(0, text="Starting…")
    errors = []

    def _fetch_and_save(sym: str) -> str:
        rows = _fetch_shareholding(sym)
        if rows:
            _save_shareholding(rows)
            return "ok"
        return "miss"

    done = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(_fetch_and_save, s): s for s in to_fetch}
        for fut in as_completed(futs):
            done += 1
            sym = futs[fut]
            try:
                result = fut.result()
                if result == "miss":
                    errors.append(sym)
            except Exception:
                errors.append(sym)
            prog.progress(done / len(to_fetch), text=f"Fetched {done}/{len(to_fetch)} — {sym.replace('.NS', '')}")
            time.sleep(0.3)  # polite rate-limiting

    prog.empty()
    _set_last_refresh()
    _ok = len(to_fetch) - len(errors)
    log_finish(_job_row, "success" if not errors else "failed",
               records_done=_ok,
               error_msg=f"{len(errors)} symbols failed" if errors else None)
    st.cache_data.clear()
    if errors:
        st.warning(f"Could not fetch data for: {', '.join(e.replace('.NS','') for e in errors[:10])}")
    else:
        st.success("All shareholding data refreshed successfully.")
    st.rerun()

# ── Load screener data ─────────────────────────────────────────────────────────
with st.spinner("Building FII accumulation screener…"):
    scr = _build_screener()

if scr.empty:
    st.warning(
        "No shareholding data found in database yet. "
        "Visit the **Smart Money** page to load individual stocks, "
        "or click **Refresh All Data** above to bulk-load all sector stocks."
    )
    show_footer()
    st.stop()

# ── Summary metrics ────────────────────────────────────────────────────────────
accum_count = (scr["Signal"] == "Accumulating").sum()
streak2_count = (scr["Streak"] >= 2).sum()
div_count   = scr["Divergence"].sum()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Stocks tracked", len(scr))
m2.metric("FII Increasing (QoQ)", int(accum_count))
m3.metric("2+ Consecutive Qtrs ↑", int(streak2_count))
m4.metric("FII↑ while DII↓", int(div_count))

st.markdown("---")

# ── Filters ────────────────────────────────────────────────────────────────────
fc1, fc2, fc3 = st.columns(3)
with fc1:
    sectors_avail = sorted(scr["Sector"].dropna().unique().tolist())
    sector_options = ["All"] + sectors_avail
    if "fa_sector" in st.session_state and st.session_state["fa_sector"] not in sector_options:
        del st.session_state["fa_sector"]
    sel_sector = st.selectbox("Sector", sector_options, key="fa_sector")
with fc2:
    min_streak = st.selectbox("Min Streak (consecutive qtrs FII ↑)", [0, 1, 2, 3], index=0,
                               format_func=lambda x: f"{x}Q+" if x > 0 else "Any", key="fa_min_streak")
with fc3:
    signal_filter = st.selectbox("Signal", ["All", "Accumulating", "Reducing", "Stable"], key="fa_signal")

disp = scr.copy()
if sel_sector != "All":
    disp = disp[disp["Sector"] == sel_sector]
if min_streak > 0:
    disp = disp[disp["Streak"] >= min_streak]
if signal_filter != "All":
    disp = disp[disp["Signal"] == signal_filter]

st.caption(f"Showing {len(disp)} stocks after filters.")

# ── Main screener table ────────────────────────────────────────────────────────
st.subheader("FII Shareholding Change — All Stocks")

display_cols = ["Symbol", "Sector", "FII %", "Prev FII %", "QoQ Δ", "Streak", "DII %", "DII Δ", "Signal", "Latest Qtr"]
table = disp[display_cols].copy()
table["Streak"] = table["Streak"].apply(lambda x: f"{x}Q↑" if x > 0 else "–")

styled = (
    table.style
    .map(_color_delta, subset=["QoQ Δ", "DII Δ"])
    .map(_color_signal, subset=["Signal"])
    .format({
        "FII %":      "{:.2f}%",
        "Prev FII %": "{:.2f}%",
        "QoQ Δ": lambda v: f"+{v:.2f}%" if v > 0 else f"{v:.2f}%",
        "DII %":      lambda v: f"{v:.2f}%" if v is not None and not pd.isna(v) else "–",
        "DII Δ": lambda v: f"+{v:.2f}%" if (v is not None and not pd.isna(v) and v > 0) else (f"{v:.2f}%" if (v is not None and not pd.isna(v)) else "–"),
    }, na_rep="–")
)

st.dataframe(styled, width='stretch', height=420, hide_index=True)

st.caption(
    "QoQ Δ = FII shareholding % change vs prior quarter. "
    "Streak = consecutive quarters where FII % increased. "
    "Data sourced from public quarterly company filings. "
    "Not investment advice."
)

# ── FII↑ DII↓ Divergence table ────────────────────────────────────────────────
st.markdown("---")
st.subheader("FII Rising + DII Reducing (Divergence Signals)")
st.caption(
    "Stocks where FII increased holdings while DII simultaneously reduced, in the latest reported quarter. "
    "This pattern — tracked for research purposes — may indicate differing views between foreign and domestic institutions. "
    "Historical pattern only. Not a recommendation."
)

div_df = scr[scr["Divergence"] == True][display_cols].copy()
div_df["Streak"] = div_df["Streak"].apply(lambda x: f"{x}Q↑" if x > 0 else "–")

if div_df.empty:
    st.info("No divergence signals in current data. Refresh data to update.")
else:
    div_styled = (
        div_df.style
        .map(_color_delta, subset=["QoQ Δ", "DII Δ"])
        .map(_color_signal, subset=["Signal"])
        .format({
            "FII %":      "{:.2f}%",
            "Prev FII %": "{:.2f}%",
            "QoQ Δ": lambda v: f"+{v:.2f}%" if v > 0 else f"{v:.2f}%",
            "DII %":      lambda v: f"{v:.2f}%" if v is not None and not pd.isna(v) else "–",
            "DII Δ": lambda v: f"+{v:.2f}%" if (v is not None and not pd.isna(v) and v > 0) else (f"{v:.2f}%" if (v is not None and not pd.isna(v)) else "–"),
        }, na_rep="–")
    )
    st.dataframe(div_styled, width='stretch', height=300, hide_index=True)

# ── Stock drilldown ────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("Stock Detail — Quarterly Trend")
st.caption("Select a stock to view FII, DII, and Promoter shareholding trend over the last 6 quarters.")

sym_list = sorted(scr["Symbol"].tolist())
sel_sym  = st.selectbox("Select stock", sym_list, key="drill_sym")

if sel_sym:
    row = scr[scr["Symbol"] == sel_sym].iloc[0]
    sym_full = row["_sym_full"]

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Latest FII %", f"{row['FII %']:.2f}%")
    d2.metric("QoQ Change", f"{row['QoQ Δ']:+.2f}%")
    d3.metric("Streak", f"{row['Streak']}Q↑" if row["Streak"] > 0 else "No streak")
    d4.metric("Signal", row["Signal"])

    fig = _trend_chart(sym_full)
    if fig:
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("Quarterly trend data not available for this stock yet.")

    st.caption(
        f"Shareholding data for {sel_sym} is derived from quarterly BSE/NSE regulatory filings. "
        "Changes in institutional holding shown here are mathematical computations — not buy/sell recommendations."
    )

show_footer()
