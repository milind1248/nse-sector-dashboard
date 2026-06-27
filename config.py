from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data" / "nse_dashboard.db"
DB_PATH.parent.mkdir(exist_ok=True)

CACHE_TTL_SECONDS = 21600  # 6 hours

SCHEDULE_TZ = "Asia/Kolkata"

# NSE sector index symbols (Yahoo Finance format)
SECTOR_INDICES = {
    "Auto":                "^CNXAUTO",
    "Bank":                "^NSEBANK",
    "Capital Goods":       "^CNXCPSE",
    "Chemicals":           "NIFTYCHEM.NS",
    "Consumer Durables":   "NIFTYCONSUM.NS",
    "Defence":             "NIFTYDEF.NS",
    "Energy":              "^CNXENERGY",
    "Financial Services":  "^CNXFINANCE",
    "FMCG":                "^CNXFMCG",
    "Healthcare":          "NIFTYHEALTH.NS",
    "Infrastructure":      "^CNXINFRA",
    "IT":                  "^CNXIT",
    "Media":               "^CNXMEDIA",
    "Metal":               "^CNXMETAL",
    "Oil & Gas":           "NIFTYOILGAS.NS",
    "Pharma":              "^CNXPHARMA",
    "Power":               "NIFTYPSE.NS",
    "Private Bank":        "NIFPVTBNK.NS",
    "PSU Bank":            "^CNXPSUBANK",
    "Real Estate":         "^CNXREALTY",
    "Telecom":             "NIFTYTELCOM.NS",   # not on yfinance; composite fallback used
}

# Top stocks per sector (Yahoo Finance .NS suffix)
SECTOR_STOCKS = {
    "Auto": [
        "MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS",
        "HEROMOOCO.NS", "TVSMOTOR.NS", "ASHOKLEY.NS", "BALKRISIND.NS", "MOTHERSON.NS",
    ],
    "Bank": [
        "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS",
        "INDUSINDBK.NS", "BANKBARODA.NS", "PNB.NS", "CANBK.NS", "FEDERALBNK.NS",
    ],
    "Capital Goods": [
        "LT.NS", "SIEMENS.NS", "ABB.NS", "BHEL.NS", "THERMAX.NS",
        "CUMMINSIND.NS", "KEC.NS", "KALPATPOWR.NS", "BEL.NS", "BEML.NS",
    ],
    "Chemicals": [
        "PIDILITIND.NS", "SRF.NS", "DEEPAKNTR.NS", "AAVAS.NS", "ATUL.NS",
        "NAVINFLUOR.NS", "ALKYLAMINE.NS", "FINEORG.NS", "TATACHEM.NS", "CLEAN.NS",
    ],
    "Consumer Durables": [
        "TITAN.NS", "HAVELLS.NS", "VGUARD.NS", "CROMPTON.NS", "BAJAJELECTR.NS",
        "WHIRLPOOL.NS", "BLUESTAR.NS", "VOLTAS.NS", "SYMPHONY.NS", "AMBER.NS",
    ],
    "Defence": [
        "BEL.NS", "HAL.NS", "BEML.NS", "GRSE.NS", "COCHINSHIP.NS",
        "MAZAGON.NS", "BHEL.NS", "PARAS.NS", "ZEN.NS", "MTAR.NS",
    ],
    "Energy": [
        "RELIANCE.NS", "ONGC.NS", "BPCL.NS", "IOC.NS", "NTPC.NS",
        "POWERGRID.NS", "ADANIGREEN.NS", "TATAPOWER.NS", "ADANIPOWER.NS", "CESC.NS",
    ],
    "Financial Services": [
        "BAJFINANCE.NS", "BAJAJFINSV.NS", "HDFC.NS", "SBILIFE.NS", "HDFCLIFE.NS",
        "ICICIGI.NS", "ICICIPRULI.NS", "MUTHOOTFIN.NS", "CHOLAFIN.NS", "M&MFIN.NS",
    ],
    "FMCG": [
        "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS",
        "GODREJCP.NS", "MARICO.NS", "COLPAL.NS", "EMAMILTD.NS", "TATACONSUM.NS",
    ],
    "Healthcare": [
        "APOLLOHOSP.NS", "FORTIS.NS", "MAXHEALTH.NS", "MEDANTA.NS", "NHLRES.NS",
        "ASTER.NS", "HEALTHCARE.NS", "METROPOLIS.NS", "THYROCARE.NS", "LALPATHLAB.NS",
    ],
    "Infrastructure": [
        "LT.NS", "ULTRACEMCO.NS", "GRASIM.NS", "ADANIPORTS.NS", "GMRAIRPORT.NS",
        "IRB.NS", "KNRCON.NS", "ASHOKA.NS", "SADBHAV.NS", "PNCINFRA.NS",
    ],
    "IT": [
        "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS",
        "LTIM.NS", "MPHASIS.NS", "COFORGE.NS", "PERSISTENT.NS", "OFSS.NS",
    ],
    "Media": [
        "ZEEL.NS", "SUNTV.NS", "PVRINOX.NS", "NETWORK18.NS", "TV18BRDCST.NS",
        "NAVNETEDUL.NS", "SAREGAMA.NS", "TIPS.NS", "BALAJITELE.NS", "IMARKETS.NS",
    ],
    "Metal": [
        "TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "SAIL.NS",
        "NATIONALUM.NS", "NMDC.NS", "HINDCOPPER.NS", "APLAPOLLO.NS", "RATNAMANI.NS",
    ],
    "Oil & Gas": [
        "RELIANCE.NS", "ONGC.NS", "BPCL.NS", "IOC.NS", "HINDPETRO.NS",
        "GAIL.NS", "OIL.NS", "PETRONET.NS", "MGL.NS", "IGL.NS",
    ],
    "Pharma": [
        "SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "BIOCON.NS",
        "AUROPHARMA.NS", "LUPIN.NS", "TORNTPHARM.NS", "ABBOTINDIA.NS", "ALKEM.NS",
    ],
    "Power": [
        "NTPC.NS", "POWERGRID.NS", "TATAPOWER.NS", "ADANIPOWER.NS", "CESC.NS",
        "TORNTPOWER.NS", "JSPL.NS", "NHPC.NS", "SJVN.NS", "IRCON.NS",
    ],
    "Private Bank": [
        "HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS", "INDUSINDBK.NS",
        "FEDERALBNK.NS", "IDFCFIRSTB.NS", "BANDHANBNK.NS", "RBLBANK.NS", "YESBANK.NS",
    ],
    "PSU Bank": [
        "SBIN.NS", "BANKBARODA.NS", "PNB.NS", "CANBK.NS", "UNIONBANK.NS",
        "INDIANB.NS", "BANKINDIA.NS", "MAHABANK.NS", "IOB.NS", "CENTRALBK.NS",
    ],
    "Real Estate": [
        "DLF.NS", "GODREJPROP.NS", "PRESTIGE.NS", "OBEROIRLTY.NS", "PHOENIXLTD.NS",
        "SOBHA.NS", "BRIGADE.NS", "MAHLIFE.NS", "KOLTEPATIL.NS", "SUNTECK.NS",
    ],
    "Telecom": [
        "INDUSTOWER.NS", "BHARTIARTL.NS", "TATACOMM.NS", "HFCL.NS", "STLTECH.NS",
        "BHARTIHEXA.NS", "TEJASNET.NS", "ITI.NS", "RAILTEL.NS",
    ],
}

# Nifty benchmark
NIFTY_SYMBOL = "^NSEI"
BANKNIFTY_SYMBOL = "^NSEBANK"
MIDCAP_SYMBOL = "^NSEMDCP50"
SMALLCAP_SYMBOL = "NIFTYSML100.NS"
VIX_SYMBOL = "^INDIAVIX"

# Momentum score weights
SCORE_WEIGHTS = {
    "relative_strength": 25,
    "momentum":          20,
    "advance_decline":   15,
    "rsi":               10,
    "price_vs_ema200":   10,
    "fii_flow":          10,
    "dii_flow":           5,
    "volume_ratio":       5,
}

SCORE_LABELS = {
    (85, 100): ("Very Strong", "#00C853"),
    (70,  84): ("Strong",      "#64DD17"),
    (45,  69): ("Neutral",     "#FFD600"),
    (25,  44): ("Weak",        "#FF6D00"),
    (0,   24): ("Very Weak",   "#D50000"),
}

PERIODS = ["Daily", "Weekly", "Fortnightly", "Monthly", "Quarterly", "Yearly"]

ALERT_TYPES = [
    "SECTOR_STRONG",
    "SECTOR_WEAK",
    "RSI_BULLISH",
    "RSI_BEARISH",
    "GOLDEN_CROSS",
    "DEATH_CROSS",
    "RANK_UP",
    "RANK_DOWN",
    "FII_SURGE",
    "BREADTH_SURGE",
    "STOCK_EMA200_CROSS",
    "STOCK_BULLISH",
]
