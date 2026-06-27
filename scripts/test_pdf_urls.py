import requests
h = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.niftyindices.com/"
}
urls = {
    "BANKNIFTY":         "https://www.niftyindices.com/Factsheet/ind_nifty_bank.pdf",
    "NIFTY_AUTO":        "https://www.niftyindices.com/Factsheet/ind_nifty_auto.pdf",
    "NCONSDUR":          "https://www.niftyindices.com/Factsheet/ind_nifty_consumer_durables.pdf",
    "NIFTY_FMCG":        "https://www.niftyindices.com/Factsheet/ind_nifty_fmcg.pdf",
    "NIFTY_IT":          "https://www.niftyindices.com/Factsheet/ind_nifty_it.pdf",
    "NIFTY_MEDIA":       "https://www.niftyindices.com/Factsheet/ind_nifty_media.pdf",
    "NIFTY_METAL":       "https://www.niftyindices.com/Factsheet/ind_nifty_metal.pdf",
    "NIFTY_OIL_AND_GAS": "https://www.niftyindices.com/Factsheet/ind_nifty_oil_and_gas.pdf",
    "NIFTY_PHARMA":      "https://www.niftyindices.com/Factsheet/ind_nifty_pharma.pdf",
    "NIFTY_BANK":        "https://www.niftyindices.com/Factsheet/ind_nifty_pse_bank.pdf",
    "NIFTY_REALTY":      "https://www.niftyindices.com/Factsheet/ind_nifty_realty.pdf",
    "NIFTY_HEALTHCARE":  "https://www.niftyindices.com/Factsheet/ind_nifty_healthcare.pdf",
}
for k, u in urls.items():
    try:
        r = requests.head(u, headers=h, timeout=10, allow_redirects=True)
        ct = r.headers.get("Content-Type", "")[:25]
        print(f"{k}: {r.status_code}  [{ct}]")
    except Exception as e:
        print(f"{k}: ERROR {e}")
