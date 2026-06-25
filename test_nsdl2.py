import sys; sys.path.insert(0, ".")
from curl_cffi import requests as cf_requests
from bs4 import BeautifulSoup
import pandas as pd

url = "https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_June152026.html"
r = cf_requests.get(url, timeout=20, impersonate="chrome110")
print("Status:", r.status_code)

soup = BeautifulSoup(r.content, "html.parser")
tables = soup.find_all("table")
print(f"Tables found: {len(tables)}")

for i, tbl in enumerate(tables):
    rows = tbl.find_all("tr")
    print(f"\n--- Table {i}: {len(rows)} rows ---")
    for j, row in enumerate(rows[:5]):
        cells = [c.get_text(strip=True) for c in row.find_all(["td","th"])]
        print(f"  Row {j}: {cells[:8]}")
