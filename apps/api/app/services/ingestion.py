"""Ingestion: provider → quality engine → point-in-time storage, with run and issue records.

Re-ingesting replaces rows for (instrument, source) and bumps nothing silently: every run is logged in
``ingestion_runs``, and issues from earlier runs are marked resolved only after the new run succeeds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.integrations.base import MarketDataProvider, ProviderUnavailable
from app.integrations.catalog import CATALOG
from app.models import DataQualityIssue, DataSource, Fund, FundNav, IngestionRun, Instrument, MarketPrice
from app.services.data_quality import QualityReport, check_nav, check_prices

log = logging.getLogger("atlas.ingestion")

# Daily bars are stamped at the BIST session close: 18:00 Europe/Istanbul = 15:00 UTC (no DST since 2016).
SESSION_CLOSE_UTC = time(15, 0)


def _dec(x) -> Decimal | None:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return None
    return Decimal(str(round(float(x), 8)))


def session_ts(d: pd.Timestamp) -> datetime:
    return datetime.combine(d.date(), SESSION_CLOSE_UTC, tzinfo=timezone.utc)


def sync_sources(db: Session, providers: list[MarketDataProvider]) -> None:
    status = {p.source_id: p.status() for p in providers}
    for sid, meta in CATALOG.items():
        row = db.get(DataSource, sid) or DataSource(source_id=sid)
        st = status.get(sid)
        row.name, row.provider, row.data_mode = meta["name"], meta["provider"], str(meta["data_mode"])
        row.availability = str(st.availability) if st else "disabled"
        row.datasets, row.capabilities = meta["datasets"], {**meta["capabilities"], "status_detail": st.detail if st else "not configured"}
        row.licence_note, row.attribution = meta["licence_note"], meta["attribution"]
        row.redistribution_allowed, row.documentation_url = meta["redistribution_allowed"], meta["documentation_url"]
        db.merge(row)
    db.commit()


def sync_instruments(db: Session, providers: list[MarketDataProvider]) -> dict[tuple[str, str], Instrument]:
    seen: dict[tuple[str, str], Instrument] = {}
    pending_benchmarks: list[tuple[Instrument, str]] = []
    for p in providers:
        for pi in p.list_instruments():
            key = (pi.symbol, pi.instrument_type)
            if key in seen:
                continue  # earlier provider has precedence
            inst = db.scalar(
                select(Instrument).where(
                    Instrument.symbol == pi.symbol, Instrument.instrument_type == pi.instrument_type, Instrument.exchange == pi.exchange
                )
            ) or Instrument(symbol=pi.symbol, instrument_type=pi.instrument_type, exchange=pi.exchange)
            inst.name, inst.currency, inst.sector, inst.industry, inst.isin = pi.name, pi.currency, pi.sector, pi.industry, pi.isin
            inst.primary_source_id = p.source_id
            db.add(inst)
            db.flush()
            if pi.fund:
                f = inst.fund or Fund(instrument_id=inst.instrument_id)
                f.fund_code, f.fund_name, f.currency = pi.fund.get("code", pi.symbol), pi.name, pi.currency
                f.management_company, f.category = pi.fund.get("management_company"), pi.fund.get("category")
                f.benchmark = pi.fund.get("benchmark_text")
                f.inception_date = pi.fund.get("inception_date")
                f.management_fee = _dec(pi.fund.get("management_fee"))
                f.risk_classification = pi.fund.get("risk_classification")
                inst.fund = f
            if pi.benchmark_symbol:
                pending_benchmarks.append((inst, pi.benchmark_symbol))
            seen[key] = inst
    by_symbol = {k[0]: v for k, v in seen.items()}
    for inst, bm in pending_benchmarks:
        target = by_symbol.get(bm)
        inst.benchmark_instrument_id = target.instrument_id if target else None
    db.commit()
    return seen


def _record_issues(db: Session, run: IngestionRun, inst: Instrument, dataset: str, report: QualityReport) -> None:
    db.execute(
        update(DataQualityIssue)
        .where(DataQualityIssue.instrument_id == inst.instrument_id, DataQualityIssue.source_id == run.source_id,
               DataQualityIssue.dataset == dataset, DataQualityIssue.resolved.is_(False))
        .values(resolved=True)
    )
    for i in report.issues:
        db.add(DataQualityIssue(run_id=run.run_id, source_id=run.source_id, instrument_id=inst.instrument_id, dataset=dataset,
                                check_code=i.code, severity=i.severity, message=i.message, count=i.count, examples=i.examples))


@dataclass
class RunResult:
    symbol: str
    status: str
    rows_written: int
    rows_excluded: int
    error: str | None = None


def ingest_instrument(db: Session, provider: MarketDataProvider, inst: Instrument) -> RunResult:
    is_fund = inst.instrument_type == "fund"
    dataset = "fund_nav" if is_fund else "eod_bars"
    run = IngestionRun(source_id=provider.source_id, dataset=dataset, instrument_id=inst.instrument_id, status="running")
    db.add(run)
    db.flush()
    try:
        df = provider.get_series(inst.symbol)
        now = utcnow()
        if is_fund:
            report = check_nav(df)
            fund = inst.fund
            db.execute(delete(FundNav).where(FundNav.fund_id == fund.fund_id, FundNav.source_id == provider.source_id))
            rows = []
            seen_dates: set = set()
            for i, (d, r) in enumerate(zip(df.index, df.itertuples(index=False))):
                if d.date() in seen_dates:
                    continue  # first copy kept (flagged PARTIAL), later copies cannot share the primary key
                seen_dates.add(d.date())
                investors = getattr(r, "investor_count", None)
                rows.append({"fund_id": fund.fund_id, "valuation_date": d.date(), "source_id": provider.source_id,
                             "nav": _dec(r.nav), "total_assets": _dec(getattr(r, "total_assets", None)),
                             "investor_count": None if investors is None or pd.isna(investors) else int(investors),
                             "publication_timestamp": None,  # fixture/CSV sources do not publish one (reported as an issue)
                             "ingestion_timestamp": now,
                             "quality_status": report.row_status.iloc[i], "quality_flags": report.row_flags.iloc[i]})
            table = FundNav
        else:
            report = check_prices(df, instrument_currency=inst.currency, row_currency=inst.currency)
            db.execute(delete(MarketPrice).where(MarketPrice.instrument_id == inst.instrument_id, MarketPrice.source_id == provider.source_id))
            rows = []
            seen_ts: set = set()
            for i, (d, r) in enumerate(zip(df.index, df.itertuples(index=False))):
                ts = session_ts(d)
                if ts in seen_ts:
                    continue  # duplicate keys cannot be stored twice; the first copy is kept and flagged PARTIAL
                seen_ts.add(ts)
                rows.append({"instrument_id": inst.instrument_id, "ts": ts, "interval": "1d", "source_id": provider.source_id,
                             "open": _dec(r.open), "high": _dec(r.high), "low": _dec(r.low), "close": _dec(r.close),
                             "adjusted_close": None,  # no corporate-action feed yet: unadjusted, said so in methodology
                             "volume": _dec(r.volume), "currency": inst.currency, "ingestion_timestamp": now,
                             "adjustment_version": 0, "quality_status": report.row_status.iloc[i], "quality_flags": report.row_flags.iloc[i]})
            table = MarketPrice
        if rows:
            db.execute(insert(table), rows)
        _record_issues(db, run, inst, dataset, report)
        run.status, run.rows_written, run.rows_excluded, run.finished_at = "succeeded", len(rows), report.excluded, utcnow()
        db.commit()
        return RunResult(inst.symbol, "succeeded", len(rows), report.excluded)
    except ProviderUnavailable as exc:
        db.rollback()
        return _fail(db, provider, inst, dataset, str(exc), "unavailable")
    except Exception as exc:  # recorded, never swallowed silently
        db.rollback()
        log.exception("ingestion failed", extra={"event": "ingestion_failed"})
        return _fail(db, provider, inst, dataset, f"{type(exc).__name__}: {exc}", "failed")


def _fail(db: Session, provider: MarketDataProvider, inst: Instrument, dataset: str, error: str, status: str) -> RunResult:
    db.add(IngestionRun(source_id=provider.source_id, dataset=dataset, instrument_id=inst.instrument_id, status=status,
                        error=error, finished_at=utcnow()))
    db.commit()
    return RunResult(inst.symbol, status, 0, 0, error)


def ingest_all(db: Session, providers: list[MarketDataProvider]) -> list[RunResult]:
    sync_sources(db, providers)
    instruments = sync_instruments(db, providers)
    by_source = {p.source_id: p for p in providers}
    results = []
    for inst in instruments.values():
        if inst.instrument_type in ("equity", "index", "fund"):
            results.append(ingest_instrument(db, by_source[inst.primary_source_id], inst))
    return results
