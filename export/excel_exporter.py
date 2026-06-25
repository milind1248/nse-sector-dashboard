"""One-click Excel export with 8 sheets."""
import io
from datetime import date
import pandas as pd
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils.dataframe import dataframe_to_rows

GREEN_FILL = PatternFill("solid", fgColor="1B5E20")
RED_FILL   = PatternFill("solid", fgColor="B71C1C")
HEADER_FILL = PatternFill("solid", fgColor="1A237E")


def _apply_pct_colors(ws, col_letters: list[str], start_row: int = 2):
    for row in ws.iter_rows(min_row=start_row, max_row=ws.max_row):
        for cell in row:
            if cell.column_letter in col_letters:
                try:
                    val = float(str(cell.value).replace("%", "").replace("+", "") or 0)
                    if val > 0:
                        cell.fill = GREEN_FILL
                        cell.font = Font(color="FFFFFF", bold=True)
                    elif val < 0:
                        cell.fill = RED_FILL
                        cell.font = Font(color="FFFFFF", bold=True)
                except Exception:
                    pass


def _write_sheet(wb: openpyxl.Workbook, name: str, df: pd.DataFrame,
                 pct_cols: list[str] = None):
    ws = wb.create_sheet(name)
    for col_num, col_name in enumerate(df.columns, 1):
        cell = ws.cell(row=1, column=col_num, value=col_name)
        cell.fill = HEADER_FILL
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center")

    for row_data in dataframe_to_rows(df, index=False, header=False):
        ws.append(row_data)

    if pct_cols:
        col_map = {col: openpyxl.utils.get_column_letter(i+1)
                   for i, col in enumerate(df.columns)}
        letters = [col_map[c] for c in pct_cols if c in col_map]
        _apply_pct_colors(ws, letters)

    # Auto-width
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 30)
    return ws


def generate_excel(
    sector_df: pd.DataFrame,
    fii_df: pd.DataFrame,
    breadth_df: pd.DataFrame,
    alerts_df: pd.DataFrame,
    heatmap_df: pd.DataFrame,
) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default sheet

    # 1. Summary
    summary_data = {
        "Generated On": [date.today().isoformat()],
        "Total Sectors": [len(sector_df)],
        "Strong Sectors (score≥70)": [len(sector_df[sector_df["momentum_score"] >= 70]) if "momentum_score" in sector_df.columns else "N/A"],
        "Weak Sectors (score≤30)":   [len(sector_df[sector_df["momentum_score"] <= 30]) if "momentum_score" in sector_df.columns else "N/A"],
        "FII Net (Last Week, Cr)":   [fii_df["fii_net"].tail(5).sum() if not fii_df.empty and "fii_net" in fii_df.columns else "N/A"],
        "DII Net (Last Week, Cr)":   [fii_df["dii_net"].tail(5).sum() if not fii_df.empty and "dii_net" in fii_df.columns else "N/A"],
    }
    _write_sheet(wb, "Summary", pd.DataFrame(summary_data).T.reset_index())

    # 2. Sector Analysis
    if not sector_df.empty:
        pct_cols = [c for c in sector_df.columns if "pct_" in c]
        _write_sheet(wb, "Sector_Analysis", sector_df, pct_cols=pct_cols)

    # 3. Heatmap
    if not heatmap_df.empty:
        hm = heatmap_df.reset_index()
        _write_sheet(wb, "Heatmap", hm,
                     pct_cols=[c for c in hm.columns if c not in ["Sector","index"]])

    # 4. FII DII
    if not fii_df.empty:
        _write_sheet(wb, "FII_DII", fii_df)

    # 5. Breadth
    if not breadth_df.empty:
        _write_sheet(wb, "Breadth", breadth_df)

    # 6. Alerts
    if not alerts_df.empty:
        _write_sheet(wb, "Alerts", alerts_df)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def generate_excel_report() -> bytes:
    """Auto-fetch all data and return Excel bytes — called by Export page."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from backend.data_ingestion.yfinance_fetcher import fetch_all_sector_prices, compute_pct_returns
    from backend.data_ingestion.nse_fetcher import fetch_fii_dii
    from backend.data_ingestion.nsdl_fetcher import get_latest_nsdl
    from backend.calculations.indicators import compute_all_indicators
    from backend.calculations.sector_score import compute_sector_score, score_label
    from backend.data_ingestion.yfinance_fetcher import _get_close
    import yfinance as yf

    # Sector data
    sector_prices = fetch_all_sector_prices()
    sector_rows = []
    for s, df in sector_prices.items():
        if df is None or df.empty: continue
        rets  = compute_pct_returns(df)
        indic = compute_all_indicators(df)
        close_s = _get_close(df)
        close   = float(close_s.iloc[-1]) if close_s is not None and not close_s.empty else None
        score   = compute_sector_score(
            rs_vs_nifty=None, pct_1w=rets.get("pct_1w"), pct_1m=rets.get("pct_1m"),
            rsi_14=indic.get("rsi_14"), close=close, ema_200=indic.get("ema_200"),
        )
        lbl, _ = score_label(score)
        sector_rows.append({"Sector": s, "Score": score, "Label": lbl,
                             "RSI_14": indic.get("rsi_14"),
                             "EMA_20": indic.get("ema_20"), "EMA_50": indic.get("ema_50"),
                             "EMA_200": indic.get("ema_200"),
                             "pct_1w": rets.get("pct_1w"), "pct_1m": rets.get("pct_1m"),
                             "pct_3m": rets.get("pct_3m"), "pct_1y": rets.get("pct_1y")})
    sector_df = pd.DataFrame(sector_rows).sort_values("Score", ascending=False)

    # NSDL FII
    curr_df, prev_df, curr_date, _ = get_latest_nsdl(periods=2)
    nsdl_df = curr_df.drop(columns=["sector"], errors="ignore") if curr_df is not None else pd.DataFrame()

    # Daily FII/DII
    fii_df = fetch_fii_dii(days=60)

    # Heatmap
    hm_rows = []
    for s, df in sector_prices.items():
        if df is None or df.empty: continue
        rets = compute_pct_returns(df)
        hm_rows.append({"Sector": s, "1W%": rets.get("pct_1w"), "1M%": rets.get("pct_1m"),
                         "3M%": rets.get("pct_3m"), "6M%": rets.get("pct_6m"), "1Y%": rets.get("pct_1y")})
    hm_df = pd.DataFrame(hm_rows).set_index("Sector") if hm_rows else pd.DataFrame()

    return generate_excel(
        sector_df=sector_df if not nsdl_df.empty else sector_df,
        fii_df=fii_df,
        breadth_df=nsdl_df,
        alerts_df=pd.DataFrame(),
        heatmap_df=hm_df,
    )
