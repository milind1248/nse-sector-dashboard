import sys; sys.path.insert(0, ".")
from curl_cffi import requests as cf_requests
from bs4 import BeautifulSoup

url = "https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_June152026.html"
r = cf_requests.get(url, timeout=20, impersonate="chrome110")
soup = BeautifulSoup(r.content, "html.parser")
table = soup.find_all("table")[0]
rows = table.find_all("tr")

print("=== ROW 0 (period headers) ===")
for td in rows[0].find_all(["td","th"]):
    print(f"  [{td.get('colspan','1')}] {td.get_text(strip=True)[:60]}")

print("\n=== ROW 1 (INR/USD) ===")
for td in rows[1].find_all(["td","th"]):
    print(f"  [{td.get('colspan','1')}] {td.get_text(strip=True)[:40]}")

print("\n=== ROW 2 (asset class) ===")
for td in rows[2].find_all(["td","th"]):
    print(f"  [{td.get('colspan','1')}] {td.get_text(strip=True)[:40]}")

print("\n=== ROW 3 (sub-headers) ===")
r3_cells = []
for td in rows[3].find_all(["td","th"]):
    r3_cells.append(td.get_text(strip=True))
print(f"Total cells: {len(r3_cells)}")
for i, c in enumerate(r3_cells):
    print(f"  [{i}] {c}")

print("\n=== ROW 4 (Automobile) ===")
r4_cells = [td.get_text(strip=True) for td in rows[4].find_all(["td","th"])]
print(f"Total cells: {len(r4_cells)}")
for i, c in enumerate(r4_cells):
    print(f"  [{i}] {c}")
