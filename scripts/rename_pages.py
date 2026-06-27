"""Rename and reorder Streamlit pages to match investor workflow."""
import shutil
from pathlib import Path

pages_dir = Path(__file__).resolve().parent.parent / "app" / "pages"

# (old_filename, new_filename)
# Investor flow: Market Pulse → Sector Analysis → Index Stocks →
#                FII DII Flow → FII Sectors → FPI Sectors →
#                Stock Picker → Alerts → Export → Contact
RENAMES = [
    ("3_📡_Market_Pulse.py",       "1_📡_Market_Pulse.py"),
    ("1_📈_Sector_Analysis.py",    "2_📈_Sector_Analysis.py"),
    ("9_🏛️_Sector_Index_Stock.py", "3_🏛️_Index_Stocks.py"),
    # 4_🏦_FII_DII_Flow.py stays as 4 — no rename needed
    ("7_🌐_FII_Invest_Sector.py",  "5_🌐_FII_Sectors.py"),
    ("8_🌏_FPI_Sectors.py",        "6_🌏_FPI_Sectors.py"),
    ("2_🎯_Stock_Picker.py",       "7_🎯_Stock_Picker.py"),
    ("5_🔔_Alerts.py",             "8_🔔_Alerts.py"),
    ("6_📤_Export.py",             "9_📤_Export.py"),
    # 10_📧_Contact.py stays as 10
]

print(f"Pages dir: {pages_dir}")
print()

for old_name, new_name in RENAMES:
    src = pages_dir / old_name
    dst = pages_dir / new_name
    if not src.exists():
        print(f"MISS  {old_name}")
        continue
    shutil.copy2(src, dst)
    src.unlink()
    print(f"OK    {old_name} -> {new_name}")

print("\nFinal pages:")
for f in sorted(pages_dir.glob("*.py")):
    print(f"  {f.name}")
