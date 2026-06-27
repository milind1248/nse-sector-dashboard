import requests, re
h = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.niftyindices.com/"
}

# Scrape ALL pdf links from factsheets page
r = requests.get("https://www.niftyindices.com/reports/index-factsheet", headers=h, timeout=15)
all_pdfs = re.findall(r'href="(https://www\.niftyindices\.com/Factsheet/[^"]+\.pdf)"', r.text, re.I)
print(f"Total PDFs found on page: {len(all_pdfs)}")
for url in sorted(set(all_pdfs)):
    print(url)
