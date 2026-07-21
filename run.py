"""
Quick launcher. Run: python run.py
Options:
  python run.py          → start Streamlit dashboard (scheduler starts automatically)
  python run.py pipeline → run data pipeline once now
  python run.py schedule → start scheduler only (blocking, no dashboard)
"""
import sys
import logging
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Logging — terminal + rotating file ───────────────────────────────────────
from logging.handlers import RotatingFileHandler

_LOG_DIR = ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / "app.log"

_fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")

_file_handler = RotatingFileHandler(
    _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(_fmt)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _console_handler])
logger = logging.getLogger(__name__)
logger.info("Logging to %s", _LOG_FILE)


def launch_dashboard():
    # Start background scheduler in this process before Streamlit boots.
    # Uses a retrying watchdog, not a single fire-and-forget attempt — if the
    # advisory lock is transiently held by a stale connection from an
    # abruptly-killed previous process, this keeps retrying every 5 min
    # instead of giving up for the rest of this process's lifetime.
    try:
        from backend.data_ingestion.scheduler import start_scheduler_watchdog
        start_scheduler_watchdog()
        logger.info("Scheduler watchdog started — will acquire the lock and start jobs once available.")
    except Exception as e:
        logger.error(f"Scheduler watchdog failed to start: {e}")

    # Launch Streamlit in the same process (no subprocess — shares memory + scheduler)
    from streamlit.web import cli as stcli
    sys.argv = [
        "streamlit", "run",
        str(ROOT / "app" / "Home.py"),
        "--server.port", "8501",
        "--server.headless", "false",
    ]
    stcli.main()


def run_pipeline():
    from backend.data_ingestion.pipeline import run_all
    run_all()


def run_scheduler():
    from backend.data_ingestion.scheduler import start_scheduler
    start_scheduler()


def _require_hm_expansion_flag():
    import config
    if not getattr(config, "ENABLE_HM_FRVP_EXPANSION_SCANNER", False):
        print(
            "H-M expansion scanner is disabled — set "
            "config.ENABLE_HM_FRVP_EXPANSION_SCANNER = True to run it. "
            "It is hidden/CLI-only by design until validated."
        )
        sys.exit(1)


def run_hm_expansion_scan(argv: list[str]):
    """python run.py hm_expansion_scan [--symbol SYM.NS] [--universe "Nifty 50"|"Nifty 500"]
                                        [--symbols A.NS,B.NS] [--period 2y] [--workers 6]
                                        [--oversold-level 9] [--oversold-mode ANY_LINE]"""
    _require_hm_expansion_flag()
    import argparse
    from backend.calculations.hm_frvp_confluence import scan_stock, scan_universe, execution_summary, ConfluenceParams
    from backend.calculations.hm_expansion import ExpansionParams
    from backend.calculations.hm_expansion_universe import load_symbols

    parser = argparse.ArgumentParser(prog="run.py hm_expansion_scan")
    parser.add_argument("--symbol", help="Single stock, e.g. RELIANCE.NS")
    parser.add_argument("--universe", choices=["Nifty 50", "Nifty 500"], help="Live universe scan")
    parser.add_argument("--symbols", help="Comma-separated custom symbol list")
    parser.add_argument("--period", default="2y")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--oversold-level", type=float, default=9.0,
                        help="RSI-line threshold that counts as the 'oversold origin' the "
                             "expansion must rise from. Pine source default is 9.0 (deep "
                             "oversold, very rare); 50.0 catches a broader/more frequent "
                             "bottom-formation-through-the-midline pattern.")
    parser.add_argument("--oversold-mode", default="ANY_LINE",
                        choices=["ANY_LINE", "WHITE_ONLY", "ALL_LINES", "RSI_SOURCE"])
    args = parser.parse_args(argv)

    params = ConfluenceParams(
        expansion=ExpansionParams(oversold_level=args.oversold_level, oversold_mode=args.oversold_mode)
    )

    if args.symbol:
        r = scan_stock(args.symbol, period=args.period, params=params)
        if r is None:
            print(f"No result for {args.symbol} (insufficient data or fetch failure).")
            return
        for k, v in r.items():
            print(f"  {k}: {v}")
        return

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    elif args.universe:
        symbols = load_symbols(args.universe)
    else:
        print("Provide --symbol, --universe, or --symbols.")
        return

    print(f"Scanning {len(symbols)} symbols ({args.workers} workers, period={args.period}, "
          f"oversold_level={args.oversold_level})...")
    df = scan_universe(symbols, period=args.period, max_workers=args.workers, params=params)
    summary = execution_summary(df, len(symbols))
    print("\n=== Execution Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if not df.empty:
        # signal_full_confluence is the ONLY authoritative "actionable" flag —
        # confluence_score/classification are a weighted research score across
        # all gates and must never be read as bypassing the mandatory boolean
        # AND-of-all-gates condition (explicit requirement in the spec).
        confluence = df[df["signal_full_confluence"]]
        print(f"\n=== Full Confluence Candidates — actionable ({len(confluence)}) ===")
        if not confluence.empty:
            print(confluence[["symbol", "confluence_score", "classification", "close",
                              "confirmed_vah", "ema20"]].to_string(index=False))
        else:
            print("  None today. (hm_bullish_expansion did not fire for any scanned stock.)")

        high_score_not_confluent = df[
            (~df["signal_full_confluence"]) & df["classification"].isin(["STRONG BUY CANDIDATE", "BUY CANDIDATE"])
        ]
        print(f"\n=== High Score but NOT Full Confluence — research/watchlist only ({len(high_score_not_confluent)}) ===")
        if not high_score_not_confluent.empty:
            print("  These pass most individual gates and score well, but hm_bullish_expansion "
                 "did not fire (see rejection_reason) — not a signal, do not treat as a buy candidate.")
            print(high_score_not_confluent[["symbol", "confluence_score", "classification",
                                            "hm_bullish_expansion", "rejection_reason"]].to_string(index=False))

        rejected = df[df["classification"] == "REJECT"]
        print(f"\n=== Rejected ({len(rejected)} of {len(df)}) — sample reasons ===")
        for _, row in rejected.head(10).iterrows():
            print(f"  {row['symbol']}: {row['rejection_reason']}")


def run_hm_expansion_backtest(argv: list[str]):
    """python run.py hm_expansion_backtest [--universe "Nifty 50"|"Nifty 500"]
                                            [--symbols A.NS,B.NS] [--period 20y]
                                            [--hold-days 20] [--entry-mode NEXT_OPEN] [--workers 6]"""
    _require_hm_expansion_flag()
    import argparse
    from backend.calculations.hm_expansion_backtest import (
        run_ablation_study, format_ablation_table,
    )
    from backend.calculations.hm_expansion_universe import load_symbols
    from backend.calculations.hm_frvp_confluence import ConfluenceParams
    from backend.calculations.hm_expansion import ExpansionParams

    parser = argparse.ArgumentParser(prog="run.py hm_expansion_backtest")
    parser.add_argument("--universe", choices=["Nifty 50", "Nifty 500"], default="Nifty 50")
    parser.add_argument("--symbols", help="Comma-separated custom symbol list (overrides --universe)")
    parser.add_argument("--period", default="20y")
    parser.add_argument("--hold-days", type=int, default=20, choices=[5, 10, 20])
    parser.add_argument("--entry-mode", default="NEXT_OPEN",
                        choices=["NEXT_OPEN", "NEXT_CLOSE", "SIGNAL_CLOSE"])
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--oversold-level", type=float, default=9.0,
                        help="See hm_expansion_scan --help. 9.0 = Pine source default (rare); "
                             "50.0 = broader bottom-formation-through-midline pattern.")
    parser.add_argument("--oversold-mode", default="ANY_LINE",
                        choices=["ANY_LINE", "WHITE_ONLY", "ALL_LINES", "RSI_SOURCE"])
    args = parser.parse_args(argv)

    symbols = ([s.strip() for s in args.symbols.split(",") if s.strip()]
              if args.symbols else load_symbols(args.universe))
    universe_label = "custom" if args.symbols else args.universe
    params = ConfluenceParams(
        expansion=ExpansionParams(oversold_level=args.oversold_level, oversold_mode=args.oversold_mode)
    )

    print(f"Running ablation study A-G on {len(symbols)} symbols, period={args.period}, "
          f"entry_mode={args.entry_mode}, oversold_level={args.oversold_level} ({universe_label})...")
    result = run_ablation_study(symbols, period=args.period, hold_days=(5, 10, 20),
                                entry_mode=args.entry_mode, max_workers=args.workers,
                                universe_label=universe_label, params=params)

    for w in result["warnings"]:
        print(f"\n*** {w} ***")

    table = format_ablation_table(result["metrics"], hold_days=args.hold_days)
    print(f"\n=== Ablation Comparison ({args.hold_days}d hold) ===")
    print(table.to_string(index=False))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dashboard"
    if cmd == "pipeline":
        run_pipeline()
    elif cmd == "schedule":
        run_scheduler()
    elif cmd == "hm_expansion_scan":
        run_hm_expansion_scan(sys.argv[2:])
    elif cmd == "hm_expansion_backtest":
        run_hm_expansion_backtest(sys.argv[2:])
    else:
        launch_dashboard()
