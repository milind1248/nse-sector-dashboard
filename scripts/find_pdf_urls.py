import requests
h = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.niftyindices.com/"
}
base = "https://www.niftyindices.com/Factsheet/"

# Candidates for missing ones
candidates = {
    "NCONSDUR": [
        "ind_nifty_consumer_durables_index.pdf",
        "ind_nifty_consdur.pdf",
        "ind_niftyconsumerdurablesindex.pdf",
        "ind_nifty_consumerdurables.pdf",
        "ind_nifty_consumer_durable.pdf",
    ],
    "NIFTY_OIL_AND_GAS": [
        "ind_nifty_oil_gas.pdf",
        "ind_nifty_oilgas.pdf",
        "ind_nifty_oil&gas.pdf",
        "ind_nifty_energy.pdf",
        "ind_nifty_oil_and_gas_index.pdf",
    ],
    "NIFTY_BANK": [
        "ind_nifty_psu_bank.pdf",
        "ind_nifty_psubank.pdf",
        "ind_nifty_public_sector_bank.pdf",
        "ind_nifty_psbank.pdf",
        "ind_nifty_pse_banks.pdf",
    ],
    "NIFTY_HEALTHCARE": [
        "ind_nifty_health_care.pdf",
        "ind_nifty_healthcareindex.pdf",
        "ind_nifty_health.pdf",
        "ind_nifty_healthcare_index.pdf",
        "ind_niftyhealthcare.pdf",
    ],
}

for idx, paths in candidates.items():
    print(f"\n=== {idx} ===")
    for p in paths:
        try:
            r = requests.head(base + p, headers=h, timeout=8, allow_redirects=True)
            ct = r.headers.get("Content-Type", "")[:20]
            print(f"  {p}: {r.status_code} [{ct}]")
            if "pdf" in ct:
                print(f"  *** FOUND: {base+p}")
        except Exception as e:
            print(f"  {p}: ERROR {e}")
