import os
import shutil
import logging
from pathlib import Path

_log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
_REPO_DB  = BASE_DIR / "data" / "nse_dashboard.db"
_TMP_DB   = Path("/tmp/nse_dashboard.db")

def _resolve_db_path() -> Path:
    """
    Legacy SQLite path resolver. The live app now reads/writes Supabase
    Postgres exclusively via backend.storage.db.get_conn() — nothing in
    app/ or backend/ imports DB_PATH anymore. This is kept only as the
    *source* path for the one-time scripts/migrate_sqlite_to_supabase.py
    backfill and for local historical reference; safe to delete once that
    script is no longer needed.

    Streamlit Cloud always mounts the repo under /mount/src/ (read-only at
    the SQLite write-lock level — os.access and open() both succeed but
    SQLite SQLITE_READONLY is raised on first write). Detect this by path
    prefix and route all writes to /tmp instead.
    Locally the repo DB is writable — use it directly.
    """
    _REPO_DB.parent.mkdir(exist_ok=True)
    on_streamlit_cloud = str(_REPO_DB).startswith("/mount/src/")
    if not on_streamlit_cloud:
        _log.info("[config] DB_PATH → %s (local)", _REPO_DB)
        return _REPO_DB          # local dev — writable
    # Streamlit Cloud: copy seed DB to /tmp and use that
    if not _TMP_DB.exists() and _REPO_DB.exists():
        shutil.copy2(_REPO_DB, _TMP_DB)
        _log.info("[config] seed DB copied to %s", _TMP_DB)
    if _TMP_DB.exists():
        _TMP_DB.chmod(0o644)
    _log.info("[config] DB_PATH → %s (Streamlit Cloud)", _TMP_DB)
    return _TMP_DB

DB_PATH = _resolve_db_path()

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
        "MARUTI.NS", "TMCV.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS",
        "HEROMOTOCO.NS", "TVSMOTOR.NS", "ASHOKLEY.NS", "BALKRISIND.NS", "MOTHERSON.NS",
    ],
    "Bank": [
        "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS",
        "INDUSINDBK.NS", "BANKBARODA.NS", "PNB.NS", "CANBK.NS", "FEDERALBNK.NS",
    ],
    "Capital Goods": [
        "LT.NS", "SIEMENS.NS", "ABB.NS", "BHEL.NS", "THERMAX.NS",
        "CUMMINSIND.NS", "KEC.NS", "KALPATARU.NS", "BEL.NS", "BEML.NS",
    ],
    "Chemicals": [
        "PIDILITIND.NS", "SRF.NS", "DEEPAKNTR.NS", "AAVAS.NS", "ATUL.NS",
        "NAVINFLUOR.NS", "ALKYLAMINE.NS", "FINEORG.NS", "TATACHEM.NS", "CLEAN.NS",
    ],
    "Consumer Durables": [
        "TITAN.NS", "HAVELLS.NS", "VGUARD.NS", "CROMPTON.NS", "BAJAJELEC.NS",
        "WHIRLPOOL.NS", "BLUESTARCO.NS", "VOLTAS.NS", "SYMPHONY.NS", "AMBER.NS",
    ],
    "Defence": [
        "BEL.NS", "HAL.NS", "BEML.NS", "GRSE.NS", "COCHINSHIP.NS",
        "MAZDOCK.NS", "BHEL.NS", "PARAS.NS", "ZENTEC.NS", "MTARTECH.NS",
    ],
    "Energy": [
        "RELIANCE.NS", "ONGC.NS", "BPCL.NS", "IOC.NS", "NTPC.NS",
        "POWERGRID.NS", "ADANIGREEN.NS", "TATAPOWER.NS", "ADANIPOWER.NS", "CESC.NS",
    ],
    "Financial Services": [
        "BAJFINANCE.NS", "BAJAJFINSV.NS", "HDFCBANK.NS", "SBILIFE.NS", "HDFCLIFE.NS",
        "ICICIGI.NS", "ICICIPRULI.NS", "MUTHOOTFIN.NS", "CHOLAFIN.NS", "M&MFIN.NS",
    ],
    "FMCG": [
        "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS",
        "GODREJCP.NS", "MARICO.NS", "COLPAL.NS", "EMAMILTD.NS", "TATACONSUM.NS",
    ],
    "Healthcare": [
        "APOLLOHOSP.NS", "FORTIS.NS", "MAXHEALTH.NS", "MEDANTA.NS", "NH.NS",
        "ASTERDM.NS", "HEALTHCARE.NS", "METROPOLIS.NS", "THYROCARE.NS", "LALPATHLAB.NS",
    ],
    "Infrastructure": [
        "LT.NS", "ULTRACEMCO.NS", "GRASIM.NS", "ADANIPORTS.NS", "GMRAIRPORT.NS",
        "IRB.NS", "KNRCON.NS", "ASHOKA.NS", "SADBHAV.NS", "PNCINFRA.NS",
    ],
    "IT": [
        "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS",
        "LTTS.NS", "MPHASIS.NS", "COFORGE.NS", "PERSISTENT.NS", "OFSS.NS",
    ],
    "Media": [
        "ZEEL.NS", "SUNTV.NS", "PVRINOX.NS", "NETWORK18.NS", "HATHWAY.NS",
        "NAVNETEDUL.NS", "SAREGAMA.NS", "TIPSFILMS.NS", "BALAJITELE.NS", "INDIAMART.NS",
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
        "TORNTPOWER.NS", "JINDALSTEL.NS", "NHPC.NS", "SJVN.NS", "IRCON.NS",
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

# ── H-M Bullish Expansion + Adaptive FRVP Confluence Scanner ─────────────────
# Research-only, CLI-gated (see run.py hm_expansion_scan/hm_expansion_backtest).
# Not wired into any Streamlit page — flip to True only once validated.
ENABLE_HM_FRVP_EXPANSION_SCANNER = False

HM_EXPANSION_DEFAULTS = {
    # Oversold origin
    "oversold_level": 9.0, "oversold_lookback": 10, "oversold_mode": "ANY_LINE",
    # Ordering / rising
    "ordering_confirmation_bars": 2, "rising_confirmation_bars": 2,
    # Separation / touch
    "min_white_green_gap": 0.50, "min_green_red_gap": 0.50, "min_total_gap": 1.25,
    "touch_tolerance": 0.25, "non_touch_confirmation_bars": 2,
    # Gap expansion
    "gap_expansion_mode": "STABLE_OR_EXPANDING", "max_gap_contraction": 0.10,
    # Slope
    "slope_lookback": 3, "slope_mode": "ABSOLUTE",
    "min_white_slope": 1.00, "min_green_slope": 0.60, "min_red_slope": 0.25,
    "require_slope_order": False,
    # Adaptive FRVP (matches the Pine source's input.* defaults exactly)
    "frvp_lookback": 300, "frvp_n_bins": 40, "frvp_va_pct": 0.70,
    "frvp_cut_tolerance_pct": 0.30, "frvp_min_profile_bars": 10,
    # EMA20
    "ema_slope_lookback": 5, "min_ema_slope_pct": 0.25, "require_consecutive_ema_rise": True,
    "ema_pullback_lookback": 5, "ema_touch_tolerance_above": 0.01, "ema_break_tolerance_below": 0.02,
    "respect_mode": "BASIC", "max_close_above_ema_pct": 5.0,
    # Scoring
    "min_score": 70,
}
