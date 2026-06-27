import requests
h = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.niftyindices.com/"
}
base = "https://www.niftyindices.com/Factsheet/"
candidates = {
    "NCONSDUR": [
        "ind_nifty_consumer_durable_sector.pdf",
        "ind_nifty_india_consumption.pdf",
        "ind_nifty_consumption.pdf",
        "ind_nifty_consdurable.pdf",
        "ind_nifty_consumer.pdf",
    ],
    "NIFTY_HEALTHCARE": [
        "ind_nifty_healthcare_sector.pdf",
        "ind_nifty_india_healthcare.pdf",
        "ind_nifty_pharma_healthcare.pdf",
        "ind_nifty_health_sector.pdf",
        "ind_niftyhealthcare_sector.pdf",
    ],
}
for idx, paths in candidates.items():
    print(f"\n=== {idx} ===")
    for p in paths:
        try:
            r = requests.head(base + p, headers=h, timeout=8, allow_redirects=True)
            ct = r.headers.get("Content-Type", "")[:30]
            mark = " *** FOUND" if "pdf" in ct else ""
            print(f"  {p}: {r.status_code} [{ct}]{mark}")
        except Exception as e:
            print(f"  {p}: ERROR")

# Also try fetching the factsheets index page to scrape actual URLs
print("\n=== Scraping factsheets page ===")
r = requests.get("https://www.niftyindices.com/reports/index-factsheet", headers=h, timeout=15)
text = r.text
for term in ["consumer_dur","consdur","healthcare","health_care","oil_gas","oilgas"]:
    import re
    matches = re.findall(r'href="([^"]*' + term + r'[^"]*\.pdf)"', text, re.I)
    if matches:
        print(f"Found for '{term}': {matches}")
