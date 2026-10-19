"""Reference data, prices, corporate actions, fundamentals, funds, macro. Point-in-time aware."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, Money, UTCDateTime, utcnow

BigId = BigInteger().with_variant(Integer, "sqlite")  # SQLite autoincrement needs INTEGER PRIMARY KEY


class DataSource(Base):
    __tablename__ = "data_sources"

    source_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(200))
    data_mode: Mapped[str] = mapped_column(String(20))
    availability: Mapped[str] = mapped_column(String(20))
    datasets: Mapped[list] = mapped_column(JSON, default=list)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)  # api, auth, frequency, latency, history...
    licence_note: Mapped[str] = mapped_column(Text, default="")
    attribution: Mapped[str | None] = mapped_column(Text)
    redistribution_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    documentation_url: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("symbol", "instrument_type", "exchange", name="uq_instruments_identity"),)

    instrument_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(300))
    instrument_type: Mapped[str] = mapped_column(String(20), index=True)
    exchange: Mapped[str] = mapped_column(String(20))  # MIC (XIST) for real listings, FIXTURE for synthetic
    currency: Mapped[str] = mapped_column(String(3), default="TRY")
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    listing_status: Mapped[str] = mapped_column(String(20), default="listed")  # listed | delisted | suspended
    isin: Mapped[str | None] = mapped_column(String(12))
    primary_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"))
    benchmark_instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.instrument_id"))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    source: Mapped[DataSource] = relationship(lazy="joined")
    fund: Mapped[Fund | None] = relationship(back_populates="instrument", uselist=False)


class MarketPrice(Base):
    __tablename__ = "market_prices"
    __table_args__ = (Index("ix_market_prices_lookup", "instrument_id", "interval", "ts"),)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.instrument_id", ondelete="CASCADE"), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(UTCDateTime, primary_key=True)  # session close, UTC
    interval: Mapped[str] = mapped_column(String(8), primary_key=True, default="1d")
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"), primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(Money)
    high: Mapped[Decimal | None] = mapped_column(Money)
    low: Mapped[Decimal | None] = mapped_column(Money)
    close: Mapped[Decimal | None] = mapped_column(Money)
    adjusted_close: Mapped[Decimal | None] = mapped_column(Money)
    volume: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    ingestion_timestamp: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    adjustment_version: Mapped[int] = mapped_column(Integer, default=0)
    quality_status: Mapped[str] = mapped_column(String(12), index=True)
    quality_flags: Mapped[list] = mapped_column(JSON, default=list)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"

    action_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.instrument_id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(30))  # cash_dividend | bonus_issue | rights_issue | split | ...
    announcement_date: Mapped[dt.date | None] = mapped_column(Date)
    ex_date: Mapped[dt.date] = mapped_column(Date)
    effective_date: Mapped[dt.date | None] = mapped_column(Date)
    cash_amount: Mapped[Decimal | None] = mapped_column(Money)
    adjustment_factor: Mapped[Decimal] = mapped_column(Money)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"))
    ingestion_timestamp: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class FinancialStatementItem(Base):
    __tablename__ = "financial_statement_items"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "fiscal_period", "period_type", "statement_type", "line_item", "revision_version", "source_id",
            name="uq_fin_stmt_item_version",
        ),
        Index("ix_fin_stmt_lookup", "instrument_id", "statement_type", "fiscal_period"),
    )

    item_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.instrument_id", ondelete="CASCADE"))
    fiscal_period: Mapped[str] = mapped_column(String(12))  # e.g. 2025FY, 2025Q2
    period_type: Mapped[str] = mapped_column(String(4))  # Q | H | 9M | FY
    filing_date: Mapped[dt.date | None] = mapped_column(Date)
    publication_timestamp: Mapped[dt.datetime] = mapped_column(UTCDateTime)  # earliest point-in-time usability
    accounting_standard: Mapped[str] = mapped_column(String(30))  # TFRS | TFRS-IAS29 ...
    reporting_currency: Mapped[str] = mapped_column(String(3))
    statement_type: Mapped[str] = mapped_column(String(20))  # income | balance | cashflow
    line_item: Mapped[str] = mapped_column(String(80))
    value: Mapped[Decimal | None] = mapped_column(Money)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"))
    revision_version: Mapped[int] = mapped_column(Integer, default=0)


class Fund(Base):
    __tablename__ = "funds"

    fund_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.instrument_id", ondelete="CASCADE"), unique=True)
    fund_code: Mapped[str] = mapped_column(String(12), index=True)
    fund_name: Mapped[str] = mapped_column(String(300))
    management_company: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    benchmark: Mapped[str | None] = mapped_column(Text)  # disclosed benchmark text
    currency: Mapped[str] = mapped_column(String(3), default="TRY")
    inception_date: Mapped[dt.date | None] = mapped_column(Date)
    management_fee: Mapped[Decimal | None] = mapped_column(Money)  # annual, decimal fraction
    risk_classification: Mapped[int | None] = mapped_column(Integer)  # 1..7
    status: Mapped[str] = mapped_column(String(20), default="active")

    instrument: Mapped[Instrument] = relationship(back_populates="fund")


class FundNav(Base):
    __tablename__ = "fund_nav"
    __table_args__ = (Index("ix_fund_nav_lookup", "fund_id", "valuation_date"),)

    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.fund_id", ondelete="CASCADE"), primary_key=True)
    valuation_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"), primary_key=True)
    nav: Mapped[Decimal | None] = mapped_column(Money)
    total_assets: Mapped[Decimal | None] = mapped_column(Money)
    investor_count: Mapped[int | None] = mapped_column(BigInteger)
    publication_timestamp: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    ingestion_timestamp: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    quality_status: Mapped[str] = mapped_column(String(12), index=True)
    quality_flags: Mapped[list] = mapped_column(JSON, default=list)


class MacroSeries(Base):
    __tablename__ = "macro_series"

    series_id: Mapped[str] = mapped_column(String(60), primary_key=True)  # e.g. EVDS code TP.DK.USD.A
    name: Mapped[str] = mapped_column(String(300))
    unit: Mapped[str] = mapped_column(String(40))
    frequency: Mapped[str] = mapped_column(String(10))
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"))


class MacroObservation(Base):
    __tablename__ = "macro_observations"
    __table_args__ = (UniqueConstraint("series_id", "observation_date", "revision_timestamp", "source_id", name="uq_macro_obs_vintage"),)

    obs_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    series_id: Mapped[str] = mapped_column(ForeignKey("macro_series.series_id", ondelete="CASCADE"), index=True)
    observation_date: Mapped[dt.date] = mapped_column(Date)
    publication_timestamp: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    revision_timestamp: Mapped[dt.datetime] = mapped_column(UTCDateTime)  # vintage
    value: Mapped[Decimal | None] = mapped_column(Money)
    unit: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"))


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    run_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"), index=True)
    dataset: Mapped[str] = mapped_column(String(40))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.instrument_id", ondelete="SET NULL"))
    started_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(12))  # running | succeeded | failed
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    rows_excluded: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    __table_args__ = (Index("ix_dq_open", "resolved", "severity"),)

    issue_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.run_id", ondelete="SET NULL"))
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.instrument_id", ondelete="CASCADE"), index=True)
    dataset: Mapped[str] = mapped_column(String(40))
    check_code: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))  # info | warning | error
    message: Mapped[str] = mapped_column(Text)
    count: Mapped[int] = mapped_column(Integer, default=1)
    examples: Mapped[list] = mapped_column(JSON, default=list)
    detected_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
