"""Test pdfplumber extraction of niftyindices factsheet."""
import sys, requests, io
import pdfplumber

h = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.niftyindices.com/"
}

url = "https://www.niftyindices.com/Factsheet/ind_nifty_it.pdf"
print(f"Downloading {url} ...")
r = requests.get(url, headers=h, timeout=30)
print(f"Status: {r.status_code}, Size: {len(r.content)} bytes")

with pdfplumber.open(io.BytesIO(r.content)) as pdf:
    print(f"Pages: {len(pdf.pages)}")
    for pno, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        text_sample = (page.extract_text() or "")[:300]
        print(f"\n--- Page {pno+1} ---")
        print("Text sample:", text_sample[:200])
        print(f"Tables found: {len(tables)}")
        for ti, t in enumerate(tables):
            print(f"  Table {ti+1} ({len(t)} rows):")
            for row in t[:8]:
                print("   ", row)
