"""
Daily scheduler job for the ETF Shop page's live tracked book. Checks
exits (target touched today) then decides at most one new/averaging buy
for today, against the LIVE_TARGET_PCT (6.28%, 2xPi) tracked book. Writes
to etf_shop_open_positions / etf_shop_closed_trades via
backend/storage/etf_shop_db.py.

Runs at 20:15 IST Mon-Fri (backend/data_ingestion/scheduler.py).

Simplification, stated explicitly (vs. the backtest's next-day-open entry
convention): this is a once-daily batch job running after market close, so
a fresh buy is priced at TODAY's close, not tomorrow's open — there's no
practical way to defer execution to "tomorrow morning" in a once-daily
batch. The backtest (backend/calculations/etf_shop.py::run_backtest) still
uses the stricter next-day-open convention for its own historical
validation; this live-tracking simplification is a deliberate, documented
difference, not an inconsistency.
"""
import logging
from datetime import date

from backend.calculations.etf_shop import fetch_universe, decide_todays_action, check_exits, LIVE_TARGET_PCT
from backend.storage import etf_shop_db as db

logger = logging.getLogger(__name__)

CAPITAL_PART_RS = 5000.0  # capital / 40 parts, using the video's own Rs 2 lakh / 40 example


def run_etf_shop_daily_update(triggered_by: str = "scheduler") -> dict:
    today_str = date.today().isoformat()
    logger.info("ETF Shop daily update started — %s, triggered_by=%s", today_str, triggered_by)

    data = fetch_universe(years=5.0)
    if not data:
        logger.warning("ETF Shop update: no data fetched, aborting")
        return {"date": today_str, "closed": 0, "action": "SKIP", "reason": "no data fetched"}

    open_positions = db.list_open_positions()

    # ---- Exits ----
    exits = check_exits(data, open_positions, target_pct=LIVE_TARGET_PCT)
    for ex in exits:
        pos = next(p for p in open_positions if p["symbol"] == ex["symbol"])
        db.record_closed_trade(
            symbol=ex["symbol"], entry_date=pos["first_buy_date"], exit_date=today_str,
            units=ex["units"], avg_entry_price=ex["avg_entry_price"], exit_price=ex["exit_price"],
            pnl_pct=ex["pnl_pct"], pnl_rs=ex["pnl_rs"],
            hold_days=(date.today() - date.fromisoformat(pos["first_buy_date"])).days,
            n_buys=ex["n_buys"],
        )
        db.remove_open_position(ex["symbol"])
    if exits:
        logger.info("ETF Shop: closed %d position(s) — %s", len(exits), [e["symbol"] for e in exits])
        open_positions = db.list_open_positions()  # refresh after closes

    # ---- Entry decision ----
    decision = decide_todays_action(data, open_positions)
    if decision["action"] in ("NEW_ENTRY", "AVERAGE"):
        code = decision["symbol"]
        df = data[code]
        entry_price = float(df.iloc[-1]["Close"])
        if entry_price > 0:
            units_bought = CAPITAL_PART_RS / entry_price
            existing = next((p for p in open_positions if p["symbol"] == code), None)
            if existing:
                total_units = existing["units"] + units_bought
                new_avg = (existing["avg_price"] * existing["units"] + entry_price * units_bought) / total_units
                db.upsert_open_position(code, total_units, new_avg, entry_price,
                                         existing["first_buy_date"], existing["n_buys"] + 1)
            else:
                db.upsert_open_position(code, units_bought, entry_price, entry_price, today_str, 1)
            logger.info("ETF Shop: %s %s @ %.2f", decision["action"], code, entry_price)

    logger.info("ETF Shop daily update complete — %s, closed=%d, action=%s",
                today_str, len(exits), decision["action"])
    return {"date": today_str, "closed": len(exits), "action": decision["action"],
            "symbol": decision.get("symbol"), "reason": decision["reason"]}
