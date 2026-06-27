import requests, re
h = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.niftyindices.com/"}
r = requests.get("https://www.niftyindices.com/reports/index-factsheet", headers=h, timeout=15)
pdfs = re.findall(r'href="(https://www\.niftyindices\.com/Factsheet/[^"]+\.pdf)"', r.text, re.I)
pdfs = sorted(set(pdfs))

terms = {
    "capital_goods":    ["capital"],
    "power":            ["power"],
    "construction":     ["construct"],
    "cement":           ["cement"],
    "chemicals":        ["chem"],
    "comm_transport":   ["commercial", "transport"],
    "consumer_services":["consumer_serv"],
    "nbfc":             ["nbfc"],
    "retail":           ["retail"],
    "telecom":          ["telecom"],
    "midsmall_fin":     ["midsmall_fin"],
    "midsmall_health":  ["midsmall_health"],
    "midsmall_it":      ["midsmall_it"],
    "500_healthcare":   ["500health"],
    "housing_finance":  ["housing"],
    "insurance":        ["insur"],
    "hospitals":        ["hospital"],
    "reits":            ["reit"],
}

print("=== MATCHES ===")
for key, search_terms in terms.items():
    hits = [p for p in pdfs if any(t in p.lower() for t in search_terms)]
    if hits:
        for h2 in hits[:3]:
            print(f"  {key}: {h2}")
    else:
        print(f"  {key}: NOT FOUND")

print("\n=== ALL PDFs (search manually) ===")
for p in pdfs:
    name = p.split("/")[-1].lower()
    if any(x in name for x in ["sector","nifty_c","nifty_p","nifty_r","nifty_t","nifty_n","nifty_h","midsmall","500health"]):
        print(" ", p)
