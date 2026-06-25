import sys; sys.path.insert(0, ".")
from curl_cffi import requests as cf_requests
from datetime import date, timedelta
import pandas as pd

def build_nsdl_urls(n=4):
    """Generate last n fortnightly report URLs. NSDL publishes on 1st and 15th."""
    urls = []
    today = date.today()
    # Try last 8 fortnightly dates
    d = today.replace(day=15) if today.day >= 15 else today.replace(day=1)
    for _ in range(n * 2):
        month = d.strftime("%B")  # e.g. "June"
        day   = d.day
        year  = d.year
        url = (
            f"https://www.fpi.nsdl.co.in/web/StaticReports/"
            f"Fortnightly_Sector_wise_FII_Investment_Data/"
            f"FIIInvestSector_{month}{day}{year}.html"
        )
        urls.append((d, url))
        # Go back 15 days
        if d.day == 15:
            d = d.replace(day=1)
        else:
            prev_month = d.replace(day=1) - timedelta(days=1)
            d = prev_month.replace(day=15)
    return urls

urls = build_nsdl_urls(6)
print("Trying URLs:")
for d, u in urls[:6]:
    print(f"  {d}: {u}")
    try:
        r = cf_requests.get(u, timeout=15, impersonate="chrome110")
        print(f"  Status: {r.status_code}, Size: {len(r.text)}")
        if r.status_code == 200 and "<table" in r.text.lower():
            print("  --> TABLE FOUND!")
            # Try parse
            tables = pd.read_html(r.text)
            print(f"  Tables found: {len(tables)}")
            for i, t in enumerate(tables):
                print(f"    Table {i}: {t.shape} cols={list(t.columns[:5])}")
            break
    except Exception as e:
        print(f"  Error: {e}")
