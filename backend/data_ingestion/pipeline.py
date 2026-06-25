"""
Daily data pipeline: fetch → compute → store.
Called by the scheduler or manually via `python -m backend.data_ingestion.pipeline`.
"""
import logging
from datetime import date

from backend.data_ingestion.yfinance_fetcher import (
    fetch_all_sector_prices, fetch_sector_stocks,
    fetch_market_summary, compute_pct_returns, fetch_stock_info, _get_close,
)
from backend.data_ingestion.nse_fetcher import fetch_fii_dii, fetch_market_breadth
from backend.calculations.indicators import compute_all_indicators
from backend.calculations.sector_score import compute_sector_score
from backend.calculations.relative_strength import compute_rs_ratio, compute_rs_momentum
from backend.calculations.advance_decline import compute_sector_advance_decline
from backend.storage.database import db_session
from backend.storage.models import (
    DailySectorSnapshot, DailyStockSnapshot, FiiDiiDaily, MarketBreadthDaily,
)
from backend.storage.cache import invalidate_all
from config import NIFTY_SYMBOL, SECTOR_STOCKS

logger = logging.getLogger(__name__)


def run_sector_pipeline():
    """Phase 1: Sector indices — indicators, scores, rankings."""
    logger.info("=== Sector pipeline started ===")
    today = date.today()

    sector_prices = fetch_all_sector_prices()
    nifty_df = sector_prices.get("IT")  # will be replaced with actual Nifty below

    import yfinance as yf
    nifty_raw = yf.download(NIFTY_SYMBOL, period="1y", interval="1d",
                             progress=False, auto_adjust=True)
    if nifty_raw is None or nifty_raw.empty:
        logger.error("Cannot fetch Nifty — aborting sector pipeline")
        return

    import pandas as pd
    nifty_raw.index = pd.to_datetime(nifty_raw.index).date

    fii_df = fetch_fii_dii(days=30)
    fii_weekly = 0.0
    if not fii_df.empty and "fii_net" in fii_df.columns:
        last7 = fii_df[fii_df["date"] >= today.replace(day=today.day - 7)
                       if today.day > 7 else fii_df["date"] >= fii_df["date"].min()]
        fii_weekly = float(last7["fii_net"].sum())

    dii_weekly = 0.0
    if not fii_df.empty and "dii_net" in fii_df.columns:
        last7 = fii_df.tail(5)
        dii_weekly = float(last7["dii_net"].sum())

    scores = {}
    rows   = []

    for sector, df in sector_prices.items():
        if df is None or df.empty:
            continue
        try:
            indic  = compute_all_indicators(df)
            rets   = compute_pct_returns(df)
            rs     = compute_rs_ratio(df, nifty_raw)
            rs_mom = compute_rs_momentum(df, nifty_raw)
            close  = float(_get_close(df).iloc[-1])

            score  = compute_sector_score(
                rs_vs_nifty=rs,
                pct_1w=rets.get("pct_1w"),
                pct_1m=rets.get("pct_1m"),
                ad_ratio=None,  # will update after stock-level A/D
                rsi_14=indic.get("rsi_14"),
                close=close,
                ema_200=indic.get("ema_200"),
                fii_flow=fii_weekly,
                dii_flow=dii_weekly,
                volume_ratio=indic.get("volume_ratio"),
            )
            scores[sector] = score

            rows.append({
                "sector": sector,
                "close":  close,
                "score":  score,
                "indic":  indic,
                "rets":   rets,
                "rs":     rs,
                "rs_mom": rs_mom,
            })
        except Exception as e:
            logger.error(f"Sector {sector} pipeline error: {e}")

    # Rank by score
    rows.sort(key=lambda x: x["score"], reverse=True)
    prev_ranks = _get_previous_ranks()

    with db_session() as session:
        for rank, row in enumerate(rows, 1):
            sector = row["sector"]
            snap = DailySectorSnapshot(
                date=today,
                sector=sector,
                close=row["close"],
                pct_1d=row["rets"].get("pct_1d"),
                pct_1w=row["rets"].get("pct_1w"),
                pct_2w=row["rets"].get("pct_2w"),
                pct_1m=row["rets"].get("pct_1m"),
                pct_3m=row["rets"].get("pct_3m"),
                pct_6m=row["rets"].get("pct_6m"),
                pct_1y=row["rets"].get("pct_1y"),
                rsi_14=row["indic"].get("rsi_14"),
                ema_20=row["indic"].get("ema_20"),
                ema_50=row["indic"].get("ema_50"),
                ema_100=row["indic"].get("ema_100"),
                ema_200=row["indic"].get("ema_200"),
                macd=row["indic"].get("macd"),
                macd_signal=row["indic"].get("macd_signal"),
                adx=row["indic"].get("adx"),
                volume_ratio=row["indic"].get("volume_ratio"),
                rs_vs_nifty=row["rs"],
                rs_momentum=row["rs_mom"],
                momentum_score=row["score"],
                rank=rank,
                prev_rank=prev_ranks.get(sector),
                fii_flow=fii_weekly,
                dii_flow=dii_weekly,
            )
            session.add(snap)

    logger.info(f"Sector pipeline done — {len(rows)} sectors stored")
    return rows


def run_stock_pipeline():
    """Phase 2: Top stocks per sector."""
    logger.info("=== Stock pipeline started ===")
    today = date.today()

    for sector, symbols in SECTOR_STOCKS.items():
        try:
            stock_prices = fetch_sector_stocks(sector)
            if not stock_prices:
                continue

            ad = compute_sector_advance_decline(stock_prices, lookback_days=1)

            with db_session() as session:
                for sym, df in stock_prices.items():
                    if df is None or df.empty:
                        continue
                    try:
                        info  = fetch_stock_info(sym)
                        indic = compute_all_indicators(df)
                        rets  = compute_pct_returns(df)
                        close = float(df["Close"].dropna().iloc[-1])
                        vol   = float(df["Volume"].dropna().iloc[-1]) if "Volume" in df.columns else None

                        snap = DailyStockSnapshot(
                            date=today,
                            symbol=sym,
                            sector=sector,
                            name=info.get("name", sym),
                            close=close,
                            market_cap=info.get("market_cap"),
                            volume=vol,
                            pct_1d=rets.get("pct_1d"),
                            pct_1w=rets.get("pct_1w"),
                            pct_2w=rets.get("pct_2w"),
                            pct_1m=rets.get("pct_1m"),
                            pct_3m=rets.get("pct_3m"),
                            pct_6m=rets.get("pct_6m"),
                            pct_1y=rets.get("pct_1y"),
                            rsi_14=indic.get("rsi_14"),
                            ema_20=indic.get("ema_20"),
                            ema_50=indic.get("ema_50"),
                            ema_200=indic.get("ema_200"),
                            macd=indic.get("macd"),
                            high_52w=info.get("52w_high"),
                            low_52w=info.get("52w_low"),
                            fii_holding_pct=info.get("fii_holding_pct"),
                            dii_holding_pct=info.get("dii_holding_pct"),
                            promoter_pct=info.get("promoter_pct"),
                            mf_pct=info.get("mf_pct"),
                        )
                        session.add(snap)
                    except Exception as e:
                        logger.error(f"Stock {sym} error: {e}")
            logger.info(f"Sector {sector}: {len(stock_prices)} stocks stored")
        except Exception as e:
            logger.error(f"Stock pipeline error for {sector}: {e}")


def run_fii_dii_pipeline():
    """Store FII/DII daily data."""
    logger.info("=== FII/DII pipeline started ===")
    df = fetch_fii_dii(days=5)
    if df.empty:
        logger.warning("No FII/DII data to store")
        return
    with db_session() as session:
        for _, row in df.iterrows():
            existing = session.query(FiiDiiDaily).filter_by(date=row["date"]).first()
            if existing:
                continue
            session.add(FiiDiiDaily(
                date=row.get("date"),
                fii_buy=row.get("fii_buy"),
                fii_sell=row.get("fii_sell"),
                fii_net=row.get("fii_net"),
                dii_buy=row.get("dii_buy"),
                dii_sell=row.get("dii_sell"),
                dii_net=row.get("dii_net"),
            ))
    logger.info("FII/DII pipeline done")


def run_breadth_pipeline():
    """Store market breadth snapshot."""
    today = date.today()
    breadth = fetch_market_breadth()
    with db_session() as session:
        existing = session.query(MarketBreadthDaily).filter_by(date=today).first()
        if not existing:
            adv = breadth.get("advance", 0)
            dec = breadth.get("decline", 1)
            session.add(MarketBreadthDaily(
                date=today,
                advance=adv,
                decline=dec,
                unchanged=breadth.get("unchanged", 0),
                ad_ratio=round(adv / dec, 2) if dec > 0 else 0,
            ))


def _get_previous_ranks() -> dict[str, int]:
    """Fetch previous day's sector ranks from DB."""
    try:
        from sqlalchemy import desc
        with db_session() as session:
            from backend.storage.models import DailySectorSnapshot
            latest_date = session.query(DailySectorSnapshot.date)\
                .order_by(desc(DailySectorSnapshot.date)).first()
            if not latest_date:
                return {}
            rows = session.query(DailySectorSnapshot)\
                .filter_by(date=latest_date[0]).all()
            return {r.sector: r.rank for r in rows}
    except Exception:
        return {}


def run_all():
    """Run full daily pipeline."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    invalidate_all()
    run_fii_dii_pipeline()
    run_breadth_pipeline()
    run_sector_pipeline()
    run_stock_pipeline()
    invalidate_all()
    logger.info("=== Full pipeline complete ===")


if __name__ == "__main__":
    run_all()
