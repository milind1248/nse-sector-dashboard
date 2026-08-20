"""
Daily scheduler job for the ETF Dukan 3 page's live tracked book. Checks
exits (target touched today) then decides at most one new/averaging buy
for today, against the curated 45-ETF RSI-rotation strategy.

Runs at 20:30 IST Mon-Fri (backend/data_ingestion/scheduler.py), right
after ETF Shop's own 20:15 job.

Same live-pricing simplification as ETF Shop's pipeline: this is a once-daily
batch job running after market close, so a fresh buy is priced at TODAY's
close, not tomorrow's open - there's no practical way to defer execution in
a once-daily batch. The backtest (backend/calculations/etf_dukan3.py's
BACKTEST_SUMMARY, from etfshop_rsi_backtest.py) uses month-open/month-close-
free daily-close execution too, so this matches the validated backtest.
"""
import logging
from datetime import date

from backend.calculations.etf_dukan3 import (
    fetch_universe, decide_todays_action, check_exits, apply_compounding,
)
from backend.storage import etf_dukan3_db as db

logger = logging.getLogger(__name__)


def run_etf_dukan3_daily_update(triggered_by: str = "scheduler") -> dict:
    today_str = date.today().isoformat()
    logger.info("ETF Dukan 3 daily update started - %s, triggered_by=%s", today_str, triggered_by)

    data = fetch_universe(years=2.0)
    if not data:
        logger.warning("ETF Dukan 3 update: no data fetched, aborting")
        return {"date": today_str, "closed": 0, "action": "SKIP", "reason": "no data fetched"}

    config = db.get_config()
    open_positions = db.list_open_positions()

    # ---- Exits ----
    exits = check_exits(data, open_positions, target_pct=config["target_pct"])
    for ex in exits:
        comp = apply_compounding(
            ex["gross_profit_rs"], ex["invested_cost"],
            proceeds=ex["units"] * ex["exit_price"],
            apply_tax_dividend=config["apply_tax_dividend"],
        )
        db.record_closed_trade(
            symbol=ex["symbol"], entry_date=ex["first_buy_date"], exit_date=today_str,
            units=ex["units"], avg_entry_price=ex["avg_price"], exit_price=ex["exit_price"],
            gross_profit_pct=ex["pnl_pct"], gross_profit_rs=ex["gross_profit_rs"],
            net_profit_rs=comp["net_profit_rs"], self_dividend_rs=comp["self_dividend_rs"],
            n_buys=ex["n_buys"],
        )
        db.remove_open_position(ex["symbol"])
        if comp["self_dividend_rs"] > 0:
            db.add_self_dividend(comp["self_dividend_rs"])
        # growth_added_rs already accounts for txn cost (and tax/self-dividend if enabled) minus
        # the original invested_cost's own contribution (which returns to capital via the sell
        # proceeds regardless) - only the NET GAIN portion needs to be added back on top of the base.
        gain_over_cost = comp["net_profit_rs"] - comp["self_dividend_rs"]
        if gain_over_cost != 0:
            db.update_config(total_capital_rs=config["total_capital_rs"] + gain_over_cost)
            config["total_capital_rs"] += gain_over_cost
    if exits:
        logger.info("ETF Dukan 3: closed %d position(s) - %s", len(exits), [e["symbol"] for e in exits])
        open_positions = db.list_open_positions()

    # Book working capital = total_capital_rs (bumped by growth on each closed trade,
    # see apply_compounding's growth_added_rs -> config update below); cash-availability
    # for a new buy is enforced implicitly by decide_todays_action's part_size sizing.
    working_capital = config["total_capital_rs"]

    decision = decide_todays_action(data, open_positions, working_capital=working_capital,
                                     capital_parts=config["capital_parts"])
    if decision["action"] in ("NEW_ENTRY", "AVERAGE"):
        code = decision["symbol"]
        entry_price = decision["price"]
        part_size = decision["part_size"]
        if entry_price and entry_price > 0:
            units_bought = part_size / entry_price
            existing = next((p for p in open_positions if p["symbol"] == code), None)
            if existing:
                total_units = existing["units"] + units_bought
                new_cost = existing["invested_cost"] + part_size
                new_avg = new_cost / total_units
                db.upsert_open_position(code, total_units, new_avg, entry_price, new_cost,
                                         existing["first_buy_date"], existing["n_buys"] + 1)
            else:
                db.upsert_open_position(code, units_bought, entry_price, entry_price, part_size,
                                         today_str, 1)
            logger.info("ETF Dukan 3: %s %s @ %.2f", decision["action"], code, entry_price)

    logger.info("ETF Dukan 3 daily update complete - %s, closed=%d, action=%s",
                today_str, len(exits), decision["action"])
    return {"date": today_str, "closed": len(exits), "action": decision["action"],
            "symbol": decision.get("symbol"), "reason": decision["reason"]}
