"""Analysis-ready reads. Only VERIFIED/VALIDATED rows reach analytics. Excluded rows are counted, never hidden."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DataQualityIssue, DataSource, Fund, FundNav, Instrument, MarketPrice
from app.models.enums import USABLE_FOR_ANALYTICS


@dataclass
class SeriesBundle:
    instrument: Instrument
    source: DataSource
    dataset: str
    frame: pd.DataFrame  # usable rows only, float64, DatetimeIndex (session date)
    rows_excluded: int
    last_ingested_at: datetime | None

    @property
    def as_of(self) -> date | None:
        return self.frame.index[-1].date() if len(self.frame) else None


_PRICE_COLS = ["open", "high", "low", "close", "volume"]


def load_prices(db: Session, inst: Instrument, start: date | None = None, end: date | None = None) -> SeriesBundle:
    q = select(MarketPrice.ts, MarketPrice.open, MarketPrice.high, MarketPrice.low, MarketPrice.close, MarketPrice.volume,
               MarketPrice.quality_status, MarketPrice.ingestion_timestamp).where(
        MarketPrice.instrument_id == inst.instrument_id, MarketPrice.interval == "1d",
        MarketPrice.source_id == inst.primary_source_id,
    ).order_by(MarketPrice.ts)
    rows = db.execute(q).all()
    df = pd.DataFrame(rows, columns=["ts", *_PRICE_COLS, "quality_status", "ingested"])
    return _bundle(db, inst, "eod_bars", df, "ts", _PRICE_COLS, start, end)


def load_nav(db: Session, inst: Instrument, start: date | None = None, end: date | None = None) -> SeriesBundle:
    fund = inst.fund
    q = select(FundNav.valuation_date, FundNav.nav, FundNav.total_assets, FundNav.investor_count, FundNav.quality_status,
               FundNav.ingestion_timestamp).where(
        FundNav.fund_id == fund.fund_id, FundNav.source_id == inst.primary_source_id).order_by(FundNav.valuation_date)
    df = pd.DataFrame(db.execute(q).all(), columns=["ts", "nav", "total_assets", "investor_count", "quality_status", "ingested"])
    return _bundle(db, inst, "fund_nav", df, "ts", ["nav", "total_assets", "investor_count"], start, end)


def _bundle(db: Session, inst: Instrument, dataset: str, df: pd.DataFrame, ts_col: str, value_cols: list[str],
            start: date | None, end: date | None) -> SeriesBundle:
    source = db.get(DataSource, inst.primary_source_id)
    if df.empty:
        return SeriesBundle(inst, source, dataset, pd.DataFrame(columns=value_cols), 0, None)
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop(ts_col)).map(lambda t: pd.Timestamp(t.date())))
    if start:
        df = df.loc[pd.Timestamp(start):]
    if end:
        df = df.loc[: pd.Timestamp(end)]
    usable = df["quality_status"].isin([s.value for s in USABLE_FOR_ANALYTICS])
    last_ingested = df["ingested"].max() if len(df) else None
    frame = df.loc[usable, value_cols].astype(float)
    return SeriesBundle(inst, source, dataset, frame, int((~usable).sum()), last_ingested)


def open_issues(db: Session, instrument_id: int, dataset: str) -> list[DataQualityIssue]:
    return list(db.scalars(
        select(DataQualityIssue).where(DataQualityIssue.instrument_id == instrument_id, DataQualityIssue.dataset == dataset,
                                       DataQualityIssue.resolved.is_(False)).order_by(DataQualityIssue.severity)
    ))


def latest_observation_dates(db: Session) -> dict[int, date]:
    """Last stored observation per instrument (prices and NAVs), used by the data-health dashboard."""
    out: dict[int, date] = {}
    for iid, ts in db.execute(select(MarketPrice.instrument_id, func.max(MarketPrice.ts)).group_by(MarketPrice.instrument_id)):
        out[iid] = (ts if isinstance(ts, datetime) else pd.Timestamp(ts)).date()
    q = select(Fund.instrument_id, func.max(FundNav.valuation_date)).join(FundNav, FundNav.fund_id == Fund.fund_id).group_by(Fund.instrument_id)
    for iid, d in db.execute(q):
        out[iid] = d if isinstance(d, date) else pd.Timestamp(d).date()
    return out
