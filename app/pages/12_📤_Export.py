"""Export sector intelligence data to Excel."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force fresh import — avoid Streamlit's stale module cache
import importlib
import export.excel_exporter as _ee_mod
importlib.reload(_ee_mod)
generate_excel_report = _ee_mod.generate_excel_report

import io
import streamlit as st

st.set_page_config(page_title="Export FII Sector Data | Download NSDL CSV | Market Sector Analysis", layout="wide")
from app.utils.guard import enforce_deployment_gate
enforce_deployment_gate()
from app.utils.seo import inject_seo
inject_seo("Export")

from app.utils.logo import show_logo
show_logo()

st.title("\U0001f4e5 Export Dashboard Data")
st.caption("Download full sector intelligence report as Excel.")

st.markdown("""
**12 sheets included:**
| Sheet | Contents |
|-------|----------|
| 1_Summary | Dashboard overview — sector counts, FII net, history depth |
| 2_Sector_Analysis | Daily sector snapshot — RSI, EMA, MACD, momentum score, A/D ratio |
| 3_Heatmap | % returns (1W / 2W / 1M / 3M / 6M / 1Y) per sector |
| 4_Sector_Live_Scores | Live sector scores + EMA signals from market price feeds |
| 5_Index_Stocks | All index constituents — company, symbol, weightage %, market cap |
| 6_Stock_Snapshot | Individual stock indicators — RSI, EMA, FII/DII holding %, 52W high/low |
| 7_FII_DII_Daily | FII & DII daily buy/sell/net flow — full accumulated history |
| 8_NSDL_Sector_FII | Fortnightly FII sector breakdown — AUC, net flow, signal |
| 9_Market_Breadth | Advance/Decline, VIX, 52W highs/lows, EMA breadth metrics |
| 10_Smart_Money_Screener | FNO stocks with active "Buying" signal on last trading day |
| 11_Smart_Money_History | 90-day Delivery % + Action + OI history for all FNO stocks |
| 12_AI_Forecast_Signals | Prophet trend + XGBoost direction for all dashboard stocks |
""")

st.markdown("---")
if st.button("Generate Excel Report", type="primary"):
    with st.spinner("Building report (~30 seconds)..."):
        try:
            data = generate_excel_report()
            st.download_button(
                label="⬇ Download NSE_Sector_Intel.xlsx",
                data=io.BytesIO(data),
                file_name="NSE_Sector_Intel.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            st.success("Ready — click the download button above.")
        except Exception as e:
            st.error(f"Export failed: {e}")
            st.exception(e)

st.markdown("---")
if st.button("← FII Sector Watch"):
    st.switch_page("Home.py")
from app.utils.disclaimer import show_footer
show_footer()
