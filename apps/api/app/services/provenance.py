"""Builds provenance/quality metadata for envelopes, plus exchange-clock helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import DataSource
from app.models.enums import DataMode, QualityStatus
from app.repositories.series import SeriesBundle, open_issues
from app.schemas.envelope import IssueOut, Provenance, QualitySummary, SourceRef
from app.services.data_quality import series_freshness

# Türkiye has used fixed UTC+3 with no DST since 2016. Fixed offset avoids a tzdata dependency on Windows.
ISTANBUL = timezone(timedelta(hours=3), "Europe/Istanbul")


def istanbul_now() -> datetime:
    return datetime.now(ISTANBUL)


def istanbul_today() -> date:
    return istanbul_now().date()


def source_ref(src: DataSource) -> SourceRef:
    return SourceRef(source_id=src.source_id, name=src.name, data_mode=src.data_mode, attribution=src.attribution,
                     licence_note=src.licence_note)


def delay_class(src: DataSource) -> str:
    return "end-of-day (synthetic fixture)" if src.data_mode == DataMode.FIXTURE else "end-of-day"


def provenance_for(bundle: SeriesBundle, settings: Settings, today: date | None = None) -> Provenance:
    freshness, lag = series_freshness(bundle.as_of, today or istanbul_today(), settings.stale_after_business_days)
    return Provenance(
        instrument=bundle.instrument.symbol, dataset=bundle.dataset, source=source_ref(bundle.source), as_of=bundle.as_of,
        last_ingested_at=bundle.last_ingested_at, freshness=freshness, lag_business_days=lag, delay=delay_class(bundle.source),
    )


def quality_for(db: Session, bundle: SeriesBundle, settings: Settings, today: date | None = None) -> QualitySummary:
    issues = open_issues(db, bundle.instrument.instrument_id, bundle.dataset)
    freshness, _ = series_freshness(bundle.as_of, today or istanbul_today(), settings.stale_after_business_days)
    if bundle.frame.empty:
        status = QualityStatus.UNAVAILABLE
    elif freshness == QualityStatus.STALE:
        status = QualityStatus.STALE
    elif bundle.rows_excluded:
        status = QualityStatus.PARTIAL
    else:
        status = QualityStatus.VALIDATED  # VERIFIED requires a second independent source (none configured)
    return QualitySummary(status=status.value, rows_used=len(bundle.frame), rows_excluded=bundle.rows_excluded,
                          open_issues=[IssueOut.model_validate(i) for i in issues])


def market_status(now: datetime | None = None) -> dict:
    """BIST continuous-session hours (10:00–18:00 Istanbul, Mon–Fri). Exchange holidays are NOT modelled."""
    now = now or istanbul_now()
    weekday = now.weekday() < 5
    in_hours = 10 <= now.hour < 18
    return {
        "exchange": "Borsa Istanbul (equity market)",
        "local_time": now.isoformat(timespec="minutes"),
        "session": "open" if weekday and in_hours else "closed",
        "basis": "Scheduled weekday hours 10:00–18:00 Europe/Istanbul; public holidays and half-days not modelled",
        "live_feed": False,
        "note": "No live market feed is connected. Prices are end-of-day observations.",
    }
