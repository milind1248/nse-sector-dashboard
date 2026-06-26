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
from app.utils.seo import inject_seo
inject_seo("Export")

from app.utils.logo import show_logo
show_logo()

st.title("\U0001f4e5 Export Dashboard Data")
st.caption("Download full sector intelligence report as Excel.")

st.markdown("""
**Includes:**
- NSDL Sector FII — fortnightly sector buying/selling (INR Crore)
- Sector Summary — scores, RSI, EMA signal, returns
- Heatmap — % returns across timeframes
- FII/DII Daily — last 60 days
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
    st.switch_page("main.py")
from app.utils.disclaimer import show_footer
show_footer()
