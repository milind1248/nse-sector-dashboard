import sys; sys.path.insert(0, ".")
import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
from backend.data_ingestion.nsdl_fetcher import get_latest_nsdl

curr, prev, cd, pd_ = get_latest_nsdl(periods=2)
if curr is not None:
    print(f"\n=== Current period: {cd} ===")
    cols = ["nsdl_sector","auc_prev_eq","net_prev_eq","net_curr_eq","auc_curr_eq","net_flow_change","signal"]
    print(curr[cols].to_string())
    print(f"\nPrev period: {pd_}")
else:
    print("Failed")
