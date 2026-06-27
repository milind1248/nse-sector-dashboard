"""Probe NSE archives for CSV constituent files for all new indices."""
import requests

h = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"}
base = "https://archives.nseindia.com/content/indices/"

# (index_key, [candidate csv filenames])
probes = {
    "NIFTY_CAPITAL_GOODS":      ["ind_niftycapgoodslist.csv", "ind_niftycapitalgoods.csv", "ind_niftycapgoodsindex.csv"],
    "NIFTY_CEMENT":             ["ind_niftycementlist.csv", "ind_niftycement.csv"],
    "NIFTY_CHEMICALS":          ["ind_niftychemicalslist.csv", "ind_niftychem.csv"],
    "NIFTY_COMM_TRANSPORT":     ["ind_niftycommercialandtransportservicelist.csv", "ind_niftycommandarttservlist.csv", "ind_niftycommtransportlist.csv"],
    "NIFTY_CONSTRUCTION":       ["ind_niftyconstructionlist.csv", "ind_niftyconstruction.csv"],
    "NIFTY_CONSUMER_SERVICES":  ["ind_niftyconsumerserviceslist.csv", "ind_niftyconsumerservices.csv"],
    "NIFTY_FIN_SERVICES":       ["ind_niftyfinancialserviceslist.csv", "ind_niftyfinservlist.csv"],
    "NIFTY_FIN_SERVICES_2550":  ["ind_niftyfinancialservices2550list.csv", "ind_niftyfinsrv2550list.csv"],
    "NIFTY_FIN_SERVICES_EXBNK": ["ind_niftyfinancialservicesexbankindex.csv", "ind_niftyfinservexbanklist.csv"],
    "NIFTY_HOSPITALS":          ["ind_niftyhospitalslist.csv", "ind_niftyhospitals.csv"],
    "NIFTY_HOUSING_FINANCE":    ["ind_niftyhousingfinancelist.csv", "ind_niftyhousingfinance.csv"],
    "NIFTY_INSURANCE":          ["ind_niftyinsurancelist.csv", "ind_niftyinsurance.csv"],
    "NIFTY_NBFC":               ["ind_niftynbfclist.csv", "ind_niftynbfc.csv"],
    "NIFTY_OIL_AND_GAS":        ["ind_niftyoilgaslist.csv", "ind_niftyoil&gaslist.csv"],
    "NIFTY_POWER":              ["ind_niftypowerlist.csv", "ind_niftypower.csv"],
    "NIFTY_PRIVATE_BANK":       ["ind_niftyprivatebanklist.csv", "ind_niftypvtbanklist.csv"],
    "NIFTY_REITS_REALTY":       ["ind_niftyreitsinvitslist.csv", "ind_niftyrealtylist.csv"],
    "NIFTY_RETAIL":             ["ind_niftyretaillist.csv", "ind_niftyretail.csv"],
    "NIFTY_TELECOM":            ["ind_niftytelecom.csv", "ind_niftytelecommunicationslist.csv"],
    "NIFTY500_HEALTHCARE":      ["ind_nifty500healthcarelist.csv", "ind_nifty500healthcare.csv"],
    "NIFTY_MIDSMALL_FIN":       ["ind_niftymidsmallfinancialserviceslist.csv"],
    "NIFTY_MIDSMALL_HEALTH":    ["ind_niftymidsmalllhealthcarelist.csv", "ind_niftymidsmallhealthcarelist.csv"],
    "NIFTY_MIDSMALL_IT":        ["ind_niftymidsmallitandtelecomlist.csv", "ind_niftymidsmallittelecomlist.csv"],
}

found = {}
for key, candidates in probes.items():
    for f in candidates:
        r = requests.head(base + f, headers=h, timeout=8, allow_redirects=True)
        ct = r.headers.get("Content-Type", "")
        if "text/plain" in ct or "application/octet" in ct or "text/csv" in ct or (r.status_code == 200 and "html" not in ct):
            print(f"FOUND  {key}: {f}")
            found[key] = f
            break
    else:
        # try GET to see content
        for f in candidates:
            r = requests.get(base + f, headers=h, timeout=8)
            if r.status_code == 200 and "Company Name" in r.text[:200]:
                print(f"FOUND  {key}: {f}")
                found[key] = f
                break
        else:
            print(f"MISS   {key}")

print("\n=== FOUND ===")
for k, v in found.items():
    print(f'  "{k}": "{v}",')
