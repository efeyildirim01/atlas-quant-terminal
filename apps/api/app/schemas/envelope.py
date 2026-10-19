"""Response contracts. Every financial payload travels inside ``Envelope`` with provenance, quality and methodology."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class SourceRef(BaseModel):
    source_id: str
    name: str
    data_mode: str  # fixture | user_supplied | licensed | official
    attribution: str | None = None
    licence_note: str | None = None


class Provenance(BaseModel):
    instrument: str | None = None
    dataset: str
    source: SourceRef
    as_of: date | None = Field(description="Date of the latest usable observation")
    last_ingested_at: datetime | None = None
    freshness: Literal["FRESH", "STALE", "UNAVAILABLE"]
    lag_business_days: int | None = None
    delay: str = Field(description="Market-data delay class, e.g. 'end-of-day'")


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    check_code: str
    severity: str
    message: str
    count: int
    examples: list[str] = []


class QualitySummary(BaseModel):
    status: str = Field(description="VERIFIED | VALIDATED | PARTIAL | STALE | CONFLICTED | UNAVAILABLE")
    rows_used: int
    rows_excluded: int
    open_issues: list[IssueOut] = []


class Envelope(BaseModel, Generic[T]):
    data: T
    provenance: list[Provenance] = []
    quality: QualitySummary | None = None
    methodology: dict[str, Any] = {}
    units: dict[str, str] = {}
    is_fixture: bool = Field(False, description="True when any input is synthetic fixture data")
    request_id: str = "-"


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    instrument_id: int
    symbol: str
    name: str
    instrument_type: str
    exchange: str
    currency: str
    sector: str | None = None
    industry: str | None = None
    listing_status: str
    isin: str | None = None
    primary_source_id: str


class SearchHit(BaseModel):
    instrument_id: int
    symbol: str
    name: str
    instrument_type: str
    exchange: str
    subtitle: str | None = None
    score: float
    match_field: Literal["symbol", "name", "management_company"]
    highlight: list[tuple[int, int]] = Field(default_factory=list, description="[start, end) spans in the matched field")
    is_fixture: bool


class SearchResult(BaseModel):
    query: str
    groups: dict[str, list[SearchHit]]
    corrected: bool = Field(False, description="True when only fuzzy (typo-tolerant) matches were found")


class UnavailableData(BaseModel):
    status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    dataset: str
    reason: str
    required_source: str
