import sys
sys.path.insert(0, ".")
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

from backend.data_ingestion.yfinance_fetcher import fetch_index_ohlcv, compute_pct_returns, _get_close
from backend.calculations.indicators import compute_all_indicators
from backend.calculations.sector_score import compute_sector_score, score_label

df = fetch_index_ohlcv("^CNXIT", period="3mo")
if df is not None and not df.empty:
    rets  = compute_pct_returns(df)
    indic = compute_all_indicators(df)
    close_s = _get_close(df)
    close = float(close_s.iloc[-1])
    score = compute_sector_score(
        pct_1w=rets.get("pct_1w"), pct_1m=rets.get("pct_1m"),
        rsi_14=indic.get("rsi_14"), close=close, ema_200=indic.get("ema_200"),
    )
    label, color = score_label(score)
    print(f"IT Sector close : {close:.2f}")
    print(f"Returns         : {rets}")
    print(f"RSI(14)         : {indic.get('rsi_14')}")
    print(f"EMA20           : {indic.get('ema_20')}")
    print(f"Momentum Score  : {score} ({label})")
else:
    print("ERROR: could not fetch IT index")
