from sqlalchemy import Column, String, Float, Integer, Date, DateTime, Text
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class DailySectorSnapshot(Base):
    __tablename__ = "daily_sector_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    sector = Column(String(64), nullable=False, index=True)
    close = Column(Float)
    open_ = Column(Float)
    high = Column(Float)
    low = Column(Float)
    volume = Column(Float)

    pct_1d  = Column(Float)
    pct_1w  = Column(Float)
    pct_2w  = Column(Float)
    pct_1m  = Column(Float)
    pct_3m  = Column(Float)
    pct_6m  = Column(Float)
    pct_1y  = Column(Float)

    rsi_14       = Column(Float)
    ema_20       = Column(Float)
    ema_50       = Column(Float)
    ema_100      = Column(Float)
    ema_200      = Column(Float)
    macd         = Column(Float)
    macd_signal  = Column(Float)
    adx          = Column(Float)
    volume_ratio = Column(Float)  # vs 20d avg

    rs_vs_nifty   = Column(Float)
    rs_momentum   = Column(Float)  # rate of change of RS (for RRG)
    momentum_score = Column(Float)

    rank      = Column(Integer)
    prev_rank = Column(Integer)

    advance_count = Column(Integer)
    decline_count = Column(Integer)
    ad_ratio      = Column(Float)

    fii_flow = Column(Float)
    dii_flow = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)


class DailyStockSnapshot(Base):
    __tablename__ = "daily_stock_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    sector = Column(String(64), index=True)
    name   = Column(String(128))

    close      = Column(Float)
    market_cap = Column(Float)
    volume     = Column(Float)
    delivery_pct = Column(Float)

    pct_1d = Column(Float)
    pct_1w = Column(Float)
    pct_2w = Column(Float)
    pct_1m = Column(Float)
    pct_3m = Column(Float)
    pct_6m = Column(Float)
    pct_1y = Column(Float)

    rsi_14   = Column(Float)
    ema_20   = Column(Float)
    ema_50   = Column(Float)
    ema_200  = Column(Float)
    macd     = Column(Float)

    fii_holding_pct      = Column(Float)
    dii_holding_pct      = Column(Float)
    promoter_pct         = Column(Float)
    mf_pct               = Column(Float)

    high_52w = Column(Float)
    low_52w  = Column(Float)
    rs_vs_nifty = Column(Float)
    momentum_score = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)


class FiiDiiDaily(Base):
    __tablename__ = "fii_dii_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date     = Column(Date, nullable=False, unique=True, index=True)
    fii_buy  = Column(Float)
    fii_sell = Column(Float)
    fii_net  = Column(Float)
    dii_buy  = Column(Float)
    dii_sell = Column(Float)
    dii_net  = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


class MarketBreadthDaily(Base):
    __tablename__ = "market_breadth_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date          = Column(Date, nullable=False, unique=True, index=True)
    nifty_close   = Column(Float)
    advance       = Column(Integer)
    decline       = Column(Integer)
    unchanged     = Column(Integer)
    ad_ratio      = Column(Float)
    high_52w      = Column(Integer)
    low_52w       = Column(Integer)
    above_ema20_pct  = Column(Float)
    above_ema50_pct  = Column(Float)
    above_ema200_pct = Column(Float)
    vix           = Column(Float)
    total_volume  = Column(Float)
    created_at    = Column(DateTime, default=datetime.utcnow)


class NsdlFiiSector(Base):
    """One row per (report_date, nsdl_sector). Populated once per NSDL publication."""
    __tablename__ = "nsdl_fii_sector"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    report_date  = Column(Date,    nullable=False, index=True)   # NSDL publication date
    nsdl_sector  = Column(String(128), nullable=False)
    sector       = Column(String(64))                            # internal sector name

    # Equity INR Crore
    auc_prev_eq      = Column(Float)   # AUC previous period
    net_prev_eq      = Column(Float)   # net investment previous fortnight
    net_curr_eq      = Column(Float)   # net investment CURRENT fortnight  ← key
    auc_curr_eq      = Column(Float)   # AUC current period

    # Derived
    auc_change       = Column(Float)
    auc_pct_change   = Column(Float)
    net_flow_change  = Column(Float)
    signal           = Column(String(16))  # buying/light_buy/light_sell/selling/neutral

    created_at = Column(DateTime, default=datetime.utcnow)


class AlertsLog(Base):
    __tablename__ = "alerts_log"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    date       = Column(Date, nullable=False, index=True)
    alert_type = Column(String(64))
    sector     = Column(String(64))
    symbol     = Column(String(32))
    message    = Column(Text)
    severity   = Column(String(16))  # HIGH / MEDIUM / LOW
    created_at = Column(DateTime, default=datetime.utcnow)
