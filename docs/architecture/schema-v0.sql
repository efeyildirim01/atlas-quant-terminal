-- SUPERSEDED: Phase 1 design sketch. The authoritative schema is the Alembic migration in
-- infrastructure/migrations/versions/ (generated from apps/api/app/models).

-- ATLAS QUANT TERMINAL — target schema (PostgreSQL 16 + TimescaleDB)
-- Design principles:
--   * Raw observations are immutable; corrections create new versions (point-in-time).
--   * Every fact row references its ingestion batch (lineage + licence).
--   * Adjusted prices are DERIVED from raw prices + corporate_action factors, never stored as truth.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ── Reference & lineage ──────────────────────────────────────────────────────────
CREATE TABLE data_provider (
    provider_id     TEXT PRIMARY KEY,                 -- 'evds', 'vendor_x_eod', 'demo', 'csv'
    data_mode       TEXT NOT NULL CHECK (data_mode IN ('demo','user_supplied','licensed','official')),
    licence_ref     TEXT,                             -- contract id / terms URL
    attribution     TEXT,
    redistribution  BOOLEAN NOT NULL DEFAULT FALSE,   -- may we show it to end users?
    derived_index_allowed BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE ingestion_batch (
    batch_id        BIGSERIAL PRIMARY KEY,
    provider_id     TEXT NOT NULL REFERENCES data_provider,
    dataset         TEXT NOT NULL,                    -- 'eod_bars', 'fund_nav', 'macro_series'
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','quarantined')),
    raw_object_uri  TEXT,                             -- s3://atlas-raw/...
    row_count       INT,
    validation_report JSONB
);

-- ── Instruments (survivorship-aware) ─────────────────────────────────────────────
CREATE TABLE instrument (
    instrument_id   BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,                    -- THYAO, TTE (fund code), XU100
    kind            TEXT NOT NULL CHECK (kind IN ('equity','fund','index','fx','commodity','bond','macro')),
    name            TEXT NOT NULL,
    isin            TEXT,
    currency        CHAR(3) NOT NULL DEFAULT 'TRY',
    sector          TEXT,
    fund_category   TEXT,                             -- TEFAS category for funds
    listed_on       DATE,
    delisted_on     DATE,                             -- NULL = active; keep delisted rows forever
    UNIQUE (symbol, kind, listed_on)
);

CREATE TABLE index_membership (                      -- universe-at-date, prevents survivorship bias
    index_id        BIGINT REFERENCES instrument,
    member_id       BIGINT REFERENCES instrument,
    valid_from      DATE NOT NULL,
    valid_to        DATE,
    PRIMARY KEY (index_id, member_id, valid_from)
);

-- ── Market data ──────────────────────────────────────────────────────────────────
CREATE TABLE price_bar (
    instrument_id   BIGINT NOT NULL REFERENCES instrument,
    ts              TIMESTAMPTZ NOT NULL,             -- session close for EOD
    interval        TEXT NOT NULL DEFAULT '1d',
    open NUMERIC(20,6), high NUMERIC(20,6), low NUMERIC(20,6), close NUMERIC(20,6) NOT NULL,
    volume          NUMERIC(24,2),
    turnover_try    NUMERIC(24,2),
    batch_id        BIGINT NOT NULL REFERENCES ingestion_batch,
    known_at        TIMESTAMPTZ NOT NULL,             -- when WE learned it (point-in-time)
    superseded_at   TIMESTAMPTZ,                      -- set when a correction arrives
    PRIMARY KEY (instrument_id, interval, ts, known_at)
);
SELECT create_hypertable('price_bar', 'ts', chunk_time_interval => INTERVAL '90 days');

CREATE TABLE corporate_action (
    action_id       BIGSERIAL PRIMARY KEY,
    instrument_id   BIGINT NOT NULL REFERENCES instrument,
    ex_date         DATE NOT NULL,
    action_type     TEXT NOT NULL CHECK (action_type IN
                    ('cash_dividend','bonus_issue','rights_issue','split','reverse_split','merger')),
    ratio           NUMERIC(20,10),                   -- e.g. 1.5 for %50 bedelsiz
    cash_amount     NUMERIC(20,6),
    subscription_price NUMERIC(20,6),                 -- bedelli
    price_factor    NUMERIC(20,12) NOT NULL,          -- multiplicative back-adjustment factor
    source_disclosure_id BIGINT,
    batch_id        BIGINT NOT NULL REFERENCES ingestion_batch,
    known_at        TIMESTAMPTZ NOT NULL
);

CREATE TABLE fund_nav (
    instrument_id   BIGINT NOT NULL REFERENCES instrument,
    nav_date        DATE NOT NULL,
    nav             NUMERIC(20,8) NOT NULL,
    total_value_try NUMERIC(24,2),
    shares_out      NUMERIC(24,4),
    investor_count  INT,
    batch_id        BIGINT NOT NULL REFERENCES ingestion_batch,
    known_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (instrument_id, nav_date, known_at)
);
SELECT create_hypertable('fund_nav', 'nav_date', chunk_time_interval => INTERVAL '1 year');

CREATE TABLE fund_profile_version (
    instrument_id   BIGINT NOT NULL REFERENCES instrument,
    valid_from      DATE NOT NULL,
    mgmt_fee_annual NUMERIC(8,6),
    risk_class      SMALLINT CHECK (risk_class BETWEEN 1 AND 7),
    benchmark_text  TEXT,
    allocation      JSONB,                            -- {"equity":0.85,"repo":0.10,...} as disclosed
    batch_id        BIGINT NOT NULL REFERENCES ingestion_batch,
    PRIMARY KEY (instrument_id, valid_from)
);

CREATE TABLE macro_observation (
    series_code     TEXT NOT NULL,                    -- EVDS code, e.g. TP.DK.USD.A
    obs_date        DATE NOT NULL,
    value           NUMERIC(24,8),
    batch_id        BIGINT NOT NULL REFERENCES ingestion_batch,
    known_at        TIMESTAMPTZ NOT NULL,             -- vintage: CPI revisions etc.
    PRIMARY KEY (series_code, obs_date, known_at)
);
SELECT create_hypertable('macro_observation', 'obs_date', chunk_time_interval => INTERVAL '5 years');

-- ── Fundamentals (point-in-time, basis-aware) ────────────────────────────────────
CREATE TABLE financial_statement (
    statement_id    BIGSERIAL PRIMARY KEY,
    instrument_id   BIGINT NOT NULL REFERENCES instrument,
    period_end      DATE NOT NULL,
    period_type     TEXT NOT NULL CHECK (period_type IN ('Q','H','9M','FY','TTM')),
    consolidated    BOOLEAN NOT NULL,
    inflation_adjusted BOOLEAN NOT NULL,              -- TAS 29 basis
    currency        CHAR(3) NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL,             -- KAP disclosure time = earliest usable time
    restatement_no  SMALLINT NOT NULL DEFAULT 0,
    source_disclosure_id BIGINT,
    batch_id        BIGINT NOT NULL REFERENCES ingestion_batch,
    UNIQUE (instrument_id, period_end, period_type, consolidated, inflation_adjusted, restatement_no)
);

CREATE TABLE financial_line_item (
    statement_id    BIGINT NOT NULL REFERENCES financial_statement ON DELETE CASCADE,
    item_code       TEXT NOT NULL,                    -- normalised taxonomy: revenue, ebitda, ...
    value           NUMERIC(28,4),
    PRIMARY KEY (statement_id, item_code)
);

CREATE TABLE disclosure (
    disclosure_id   BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,                    -- 'kap', 'tcmb', 'news:<vendor>'
    external_id     TEXT,
    published_at    TIMESTAMPTZ NOT NULL,
    instrument_ids  BIGINT[],
    category        TEXT,
    title           TEXT NOT NULL,
    body_uri        TEXT,
    is_confirmed    BOOLEAN NOT NULL,                 -- official disclosure vs unconfirmed report
    nlp             JSONB,                            -- entities, sentiment, materiality + model version
    UNIQUE (source, external_id)
);

-- ── Users, portfolios, research (multi-tenant) ───────────────────────────────────
CREATE TABLE app_user (
    user_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    email           CITEXT UNIQUE NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('viewer','analyst','pm','admin')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE portfolio (
    portfolio_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    owner_id        UUID NOT NULL REFERENCES app_user,
    name            TEXT NOT NULL,
    base_currency   CHAR(3) NOT NULL DEFAULT 'TRY'
);

CREATE TABLE portfolio_transaction (
    txn_id          BIGSERIAL PRIMARY KEY,
    portfolio_id    UUID NOT NULL REFERENCES portfolio ON DELETE CASCADE,
    instrument_id   BIGINT NOT NULL REFERENCES instrument,
    trade_date      DATE NOT NULL,
    quantity        NUMERIC(24,6) NOT NULL,
    price           NUMERIC(20,6) NOT NULL,
    fees            NUMERIC(20,6) NOT NULL DEFAULT 0
);
ALTER TABLE portfolio ENABLE ROW LEVEL SECURITY;    -- policies keyed on current_setting('atlas.org_id')

CREATE TABLE model_run (                             -- reproducibility for ML/backtests
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            TEXT NOT NULL CHECK (kind IN ('backtest','ml_train','ml_eval','signal_calibration')),
    code_version    TEXT NOT NULL,                    -- git sha
    params          JSONB NOT NULL,
    data_snapshot   TIMESTAMPTZ NOT NULL,             -- point-in-time cutoff used
    split_spec      JSONB,                            -- train/val/test, purge & embargo
    metrics         JSONB,
    sample_label    TEXT CHECK (sample_label IN ('in_sample','validation','out_of_sample','paper')),
    created_by      UUID REFERENCES app_user,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id         UUID,
    action          TEXT NOT NULL,
    resource        TEXT,
    detail          JSONB
);
