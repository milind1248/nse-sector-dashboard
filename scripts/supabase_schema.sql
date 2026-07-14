-- Supabase (Postgres) schema for NSE Sector Dashboard.
-- Source of truth: live introspection of data/nse_dashboard.db (sqlite_master),
-- not the source-code CREATE TABLE statements alone — a few tables
-- (daily_sector_snapshot, daily_stock_snapshot, fii_dii_daily,
-- market_breadth_daily, nsdl_fii_sector, alerts_log, site_stats) only exist
-- because of the now-deleted SQLAlchemy ORM layer (backend/storage/database.py
-- + models.py) and are written to by raw SQL elsewhere that assumes they
-- already exist — this script recreates them explicitly for Postgres.
--
-- Run once against a fresh Supabase project (SQL Editor, or `psql "$CONN" -f
-- scripts/supabase_schema.sql`) BEFORE running scripts/migrate_sqlite_to_supabase.py
-- or any migrated application code.
--
-- Date/time columns are upgraded from SQLite TEXT to native DATE/TIMESTAMPTZ
-- per project decision — existing Python .isoformat() write code needs no
-- changes (Postgres parses ISO-8601 text on INSERT), but code reading these
-- columns back gets datetime.date/datetime objects instead of strings.

-- ── Paper Trading (the tables that motivated this migration) ──────────────────

CREATE TABLE IF NOT EXISTS paper_orders (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trader_id     TEXT        NOT NULL,
    segment       TEXT        NOT NULL,   -- STOCK | OPTION | FUTURE
    symbol        TEXT        NOT NULL,
    side          TEXT        NOT NULL,   -- BUY | SELL
    qty           INTEGER     NOT NULL,
    order_type    TEXT        NOT NULL,   -- MARKET | LIMIT
    limit_price   DOUBLE PRECISION,
    status        TEXT        NOT NULL,   -- PENDING | FILLED | CANCELLED
    fill_price    DOUBLE PRECISION,
    realized_pnl  DOUBLE PRECISION,
    order_time    TIMESTAMPTZ NOT NULL,
    fill_time     TIMESTAMPTZ,
    expiry        TEXT,
    strike        DOUBLE PRECISION,
    option_type   TEXT                    -- CE | PE
);

CREATE TABLE IF NOT EXISTS paper_holdings (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trader_id       TEXT    NOT NULL,
    segment         TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    qty             INTEGER NOT NULL,
    avg_price       DOUBLE PRECISION NOT NULL,
    mark_price      DOUBLE PRECISION,
    expiry          TEXT,
    strike          DOUBLE PRECISION,
    option_type     TEXT,
    last_order_type TEXT,   -- MARKET | LIMIT
    UNIQUE(trader_id, segment, symbol, expiry, strike, option_type)
);

-- ── AI Forecast / AI Scan ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ai_forecast_cache (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol                  TEXT NOT NULL,
    sector                  TEXT,
    scan_date               DATE NOT NULL,
    price                   DOUBLE PRECISION,
    xgb_prob                DOUBLE PRECISION,
    xgb_direction           TEXT,
    xgb_signal              TEXT,
    xgb_accuracy            DOUBLE PRECISION,
    n_train_bars            INTEGER,
    n_features              INTEGER,
    backtest_monthly_json   TEXT,
    feature_importance_json TEXT,
    prophet_trend           TEXT,
    prophet_trend_pct       DOUBLE PRECISION,
    prophet_forecast_json   TEXT,
    close_6m_json           TEXT,
    ema_json                TEXT,
    arima_direction         TEXT,
    arima_trend_pct         DOUBLE PRECISION,
    arima_forecast_json     TEXT,
    computed_at             TIMESTAMPTZ,
    UNIQUE(symbol, scan_date)
);

CREATE TABLE IF NOT EXISTS ai_scan_results (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scan_date   DATE NOT NULL,
    symbol      TEXT NOT NULL,
    sector      TEXT,
    price       DOUBLE PRECISION,
    xgb_prob    DOUBLE PRECISION,
    direction   TEXT,
    trend       TEXT,
    signal      TEXT,
    UNIQUE(scan_date, symbol)
);

-- ── Gann Analysis ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gann_cache (
    symbol           TEXT NOT NULL,
    scan_date        DATE NOT NULL,
    atr_json         TEXT,
    deg_json         TEXT,
    proj_json        TEXT,
    pts_json         TEXT,
    dates_json       TEXT,
    updated_at       TIMESTAMPTZ,
    atr_accuracy_pct DOUBLE PRECISION,
    atr_signals      INTEGER,
    deg_accuracy_pct DOUBLE PRECISION,
    deg_signals      INTEGER,
    proj_accuracy_pct DOUBLE PRECISION,
    proj_signals     INTEGER,
    pts_accuracy_pct DOUBLE PRECISION,
    pts_signals      INTEGER,
    nat_accuracy_pct DOUBLE PRECISION,
    nat_signals      INTEGER,
    PRIMARY KEY (symbol, scan_date)
);

-- ── Market Pulse ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS market_breadth (
    trade_date  DATE PRIMARY KEY,
    advance     INTEGER,
    decline     INTEGER,
    unchanged   INTEGER,
    ad_ratio    DOUBLE PRECISION,
    updated_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sector_heatmap (
    trade_date  DATE,
    sector      TEXT,
    ret_1w      DOUBLE PRECISION,
    ret_2w      DOUBLE PRECISION,
    ret_1m      DOUBLE PRECISION,
    ret_3m      DOUBLE PRECISION,
    ret_6m      DOUBLE PRECISION,
    ret_1y      DOUBLE PRECISION,
    updated_at  TIMESTAMPTZ,
    PRIMARY KEY (trade_date, sector)
);

CREATE TABLE IF NOT EXISTS rrg_snapshot (
    trade_date  DATE,
    sector      TEXT,
    rs_ratio    DOUBLE PRECISION,
    rs_momentum DOUBLE PRECISION,
    quadrant    TEXT,
    trail_json  TEXT,
    updated_at  TIMESTAMPTZ,
    PRIMARY KEY (trade_date, sector)
);

-- ── Legacy ORM-created tables (schema preserved 1:1, per project decision) ────

CREATE TABLE IF NOT EXISTS daily_sector_snapshot (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date            DATE NOT NULL,
    sector          VARCHAR(64) NOT NULL,
    close           DOUBLE PRECISION,
    open_           DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    volume          DOUBLE PRECISION,
    pct_1d          DOUBLE PRECISION,
    pct_1w          DOUBLE PRECISION,
    pct_2w          DOUBLE PRECISION,
    pct_1m          DOUBLE PRECISION,
    pct_3m          DOUBLE PRECISION,
    pct_6m          DOUBLE PRECISION,
    pct_1y          DOUBLE PRECISION,
    rsi_14          DOUBLE PRECISION,
    ema_20          DOUBLE PRECISION,
    ema_50          DOUBLE PRECISION,
    ema_100         DOUBLE PRECISION,
    ema_200         DOUBLE PRECISION,
    macd            DOUBLE PRECISION,
    macd_signal     DOUBLE PRECISION,
    adx             DOUBLE PRECISION,
    volume_ratio    DOUBLE PRECISION,
    rs_vs_nifty     DOUBLE PRECISION,
    rs_momentum     DOUBLE PRECISION,
    momentum_score  DOUBLE PRECISION,
    rank            INTEGER,
    prev_rank       INTEGER,
    advance_count   INTEGER,
    decline_count   INTEGER,
    ad_ratio        DOUBLE PRECISION,
    fii_flow        DOUBLE PRECISION,
    dii_flow        DOUBLE PRECISION,
    created_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS daily_stock_snapshot (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date            DATE NOT NULL,
    symbol          VARCHAR(32) NOT NULL,
    sector          VARCHAR(64),
    name            VARCHAR(128),
    close           DOUBLE PRECISION,
    market_cap      DOUBLE PRECISION,
    volume          DOUBLE PRECISION,
    delivery_pct    DOUBLE PRECISION,
    pct_1d          DOUBLE PRECISION,
    pct_1w          DOUBLE PRECISION,
    pct_2w          DOUBLE PRECISION,
    pct_1m          DOUBLE PRECISION,
    pct_3m          DOUBLE PRECISION,
    pct_6m          DOUBLE PRECISION,
    pct_1y          DOUBLE PRECISION,
    rsi_14          DOUBLE PRECISION,
    ema_20          DOUBLE PRECISION,
    ema_50          DOUBLE PRECISION,
    ema_200         DOUBLE PRECISION,
    macd            DOUBLE PRECISION,
    fii_holding_pct DOUBLE PRECISION,
    dii_holding_pct DOUBLE PRECISION,
    promoter_pct    DOUBLE PRECISION,
    mf_pct          DOUBLE PRECISION,
    high_52w        DOUBLE PRECISION,
    low_52w         DOUBLE PRECISION,
    rs_vs_nifty     DOUBLE PRECISION,
    momentum_score  DOUBLE PRECISION,
    created_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS fii_dii_daily (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date        DATE NOT NULL,
    fii_buy     DOUBLE PRECISION,
    fii_sell    DOUBLE PRECISION,
    fii_net     DOUBLE PRECISION,
    dii_buy     DOUBLE PRECISION,
    dii_sell    DOUBLE PRECISION,
    dii_net     DOUBLE PRECISION,
    created_at  TIMESTAMPTZ,
    UNIQUE(date)
);

CREATE TABLE IF NOT EXISTS market_breadth_daily (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date              DATE NOT NULL,
    nifty_close       DOUBLE PRECISION,
    advance           INTEGER,
    decline           INTEGER,
    unchanged         INTEGER,
    ad_ratio          DOUBLE PRECISION,
    high_52w          INTEGER,
    low_52w           INTEGER,
    above_ema20_pct   DOUBLE PRECISION,
    above_ema50_pct   DOUBLE PRECISION,
    above_ema200_pct  DOUBLE PRECISION,
    vix               DOUBLE PRECISION,
    total_volume      DOUBLE PRECISION,
    created_at        TIMESTAMPTZ,
    UNIQUE(date)
);

CREATE TABLE IF NOT EXISTS nsdl_fii_sector (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_date     DATE NOT NULL,
    nsdl_sector     VARCHAR(128) NOT NULL,
    sector          VARCHAR(64),
    auc_prev_eq     DOUBLE PRECISION,
    net_prev_eq     DOUBLE PRECISION,
    net_curr_eq     DOUBLE PRECISION,
    auc_curr_eq     DOUBLE PRECISION,
    auc_change      DOUBLE PRECISION,
    auc_pct_change  DOUBLE PRECISION,
    net_flow_change DOUBLE PRECISION,
    signal          VARCHAR(16),
    created_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS site_stats (
    key         VARCHAR(64) PRIMARY KEY,
    value       INTEGER NOT NULL,
    updated_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS alerts_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date        DATE NOT NULL,
    alert_type  VARCHAR(64),
    sector      VARCHAR(64),
    symbol      VARCHAR(32),
    message     TEXT,
    severity    VARCHAR(16),
    created_at  TIMESTAMPTZ
);

-- ── Sector Sync / Index Stocks ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sector_intelligence (
    company_name    TEXT,
    symbol          TEXT,
    industry        TEXT,
    series          TEXT,
    isin            TEXT,
    sector          TEXT,
    index_name      TEXT,
    index_display   TEXT,
    market_cap_cr   DOUBLE PRECISION,
    weightage_pct   DOUBLE PRECISION,
    weight_source   TEXT
);
CREATE INDEX IF NOT EXISTS idx_si_sector ON sector_intelligence(sector);
CREATE INDEX IF NOT EXISTS idx_si_index  ON sector_intelligence(index_name);

CREATE TABLE IF NOT EXISTS sector_sync_log (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    synced_at       TIMESTAMPTZ NOT NULL,
    source          TEXT,
    indices_synced  INTEGER,
    stocks_total    INTEGER,
    changes         TEXT,
    factsheet_date  TEXT   -- comma-joined list of dates, not a single date — kept as TEXT
);

-- ── Smart Money ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS smart_money_history (
    symbol        TEXT NOT NULL,
    trade_date    DATE NOT NULL,
    close_price   DOUBLE PRECISION,
    pct_price_chg DOUBLE PRECISION,
    trade_qty     DOUBLE PRECISION,
    tot_trade     DOUBLE PRECISION,
    action        DOUBLE PRECISION,
    dlv_pct       DOUBLE PRECISION,
    futures_oi    DOUBLE PRECISION,
    oi_change     DOUBLE PRECISION,
    pct_oi_chg    DOUBLE PRECISION,
    PRIMARY KEY (symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS fno_symbols (
    symbol      TEXT PRIMARY KEY,
    updated_at  TIMESTAMPTZ NOT NULL
);

-- ── FII Accumulation / Shareholding ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS shareholding_pattern (
    symbol          TEXT NOT NULL,
    quarter         TEXT NOT NULL,   -- fiscal-quarter label (e.g. "Mar 2024"), not an ISO date
    promoter        DOUBLE PRECISION,
    fii             DOUBLE PRECISION,
    dii             DOUBLE PRECISION,
    government      DOUBLE PRECISION,
    public_retail   DOUBLE PRECISION,
    fetched_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol, quarter)
);

CREATE TABLE IF NOT EXISTS shareholding_refresh_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL   -- schemaless key/value store, kept as TEXT
);

-- ── Admin / diagnostics ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS job_run_log (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id       TEXT NOT NULL,
    job_name     TEXT NOT NULL,
    triggered_by TEXT NOT NULL DEFAULT 'scheduler',
    started_at   TIMESTAMPTZ NOT NULL,
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running',
    records_done INTEGER DEFAULT 0,
    error_msg    TEXT
);

CREATE TABLE IF NOT EXISTS page_test_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      INTEGER NOT NULL,
    page_name   TEXT NOT NULL,
    page_file   TEXT NOT NULL,
    status      TEXT NOT NULL,
    load_time_s DOUBLE PRECISION,
    tabs_count  INTEGER DEFAULT 0,
    errors_json TEXT,
    tested_at   TIMESTAMPTZ NOT NULL
);

-- ── User Profiles (Supabase Auth) ──────────────────────────────────────────────
-- id = Supabase Auth's auth.users.id (UUID). Verify the db_connection_string's
-- role can see the `auth` schema (SELECT count(*) FROM auth.users;) before
-- relying on the FK — if it fails, drop REFERENCES and keep a plain UUID PK.
CREATE TABLE IF NOT EXISTS profiles (
    id                   UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email                TEXT NOT NULL,
    full_name            TEXT,
    avatar_url           TEXT,
    auth_provider        TEXT NOT NULL,             -- 'google' | 'email'
    subscription_tier    TEXT NOT NULL DEFAULT 'free',
    subscription_status  TEXT NOT NULL DEFAULT 'active',
    created_at           TIMESTAMPTZ,
    last_login_at        TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_profiles_email ON profiles(email);

-- Server-side PKCE verifier storage for the Google OAuth flow. Not a browser
-- cookie: on Streamlit Cloud the app renders inside nested iframes and the
-- OAuth round trip completes in a new tab, and a cookie set that deep did
-- not reliably survive the trip in production testing. The flow_id instead
-- travels in redirect_to's query string, which Supabase's PKCE redirect
-- preserves alongside its own "code" param (confirmed against GoTrue's
-- prepPKCERedirectURL) — the verifier itself never leaves the server.
CREATE TABLE IF NOT EXISTS oauth_pkce_flow (
    flow_id       TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL
);

-- ── Admin-configurable settings (replaces data/*.json) ─────────────────────────
-- Both used to be plain files in the git working tree. Streamlit Cloud's
-- filesystem rebuilds fresh from git on every push (every push auto-deploys),
-- so any edit the Admin page wrote to those files while running on Cloud was
-- silently wiped out on the next deploy. A DB row survives that rebuild.

CREATE TABLE IF NOT EXISTS schedule_config (
    job_id      TEXT PRIMARY KEY,      -- matches job_run_log.job_id / scheduler add_job(id=...)
    hour        SMALLINT NOT NULL,
    minute      SMALLINT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO schedule_config (job_id, hour, minute) VALUES
    ('sector_snapshot',       18, 0),
    ('stock_snapshot',        18, 30),
    ('smart_money',           19, 0),
    ('market_pulse_snapshot', 19, 30),
    ('ai_scan_daily',         20, 0),
    ('gann_daily',            20, 30)
ON CONFLICT (job_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS announcement (
    id          TEXT PRIMARY KEY DEFAULT 'home_page',
    enabled     BOOLEAN NOT NULL DEFAULT false,
    text        TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO announcement (id, enabled, text) VALUES
    ('home_page', true, 'New Feature Added: Gann analysis - > Gann Emblem is now live.')
ON CONFLICT (id) DO NOTHING;
