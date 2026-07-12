import sys; sys.path.insert(0, ".")
import backend.data_ingestion.sector_sync as s
from backend.storage.db import get_conn

orig = dict(s.NSE_INDEX_SOURCES)
s.NSE_INDEX_SOURCES = {k: orig[k] for k in ["NIFTY_IT", "NIFTY_CAPITAL_GOODS", "NIFTY_POWER"]}
result = s.sync_all()
s.NSE_INDEX_SOURCES = orig

print("OK:", result["indices_ok"], "| Failed:", result["indices_failed"])
print("Errors:", result["errors"])

con = get_conn()
rows = con.execute(
    "SELECT index_display, company_name, symbol, weightage_pct "
    "FROM sector_intelligence ORDER BY index_name, weightage_pct DESC"
).fetchall()
cur = ""
for r in rows:
    if r[0] != cur:
        cur = r[0]
        print(f"\n--- {cur} ---")
    sym = str(r[2]) if r[2] else "?"
    print(f"  {r[1][:38]:38} {sym:12} {r[3]:.2f}%")
con.close()
