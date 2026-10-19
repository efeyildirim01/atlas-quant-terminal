"""Provider adapter contract. Adapters do I/O only. Validation and storage happen in services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app.models.enums import DataMode, SourceAvailability


class ProviderError(RuntimeError):
    pass


class ProviderUnavailable(ProviderError):
    """The source has no permitted access (licence missing) or is not configured."""


class InstrumentNotFound(ProviderError):
    pass


@dataclass(frozen=True)
class ProviderInstrument:
    symbol: str
    name: str
    instrument_type: str  # InstrumentType value
    exchange: str
    currency: str = "TRY"
    sector: str | None = None
    industry: str | None = None
    isin: str | None = None
    benchmark_symbol: str | None = None
    fund: dict | None = None  # code, management_company, category, fee, risk_class, benchmark_text, inception_date


@dataclass(frozen=True)
class ProviderStatus:
    source_id: str
    availability: SourceAvailability
    detail: str
    datasets: list[str] = field(default_factory=list)


class MarketDataProvider(ABC):
    """``get_series`` returns a DataFrame indexed by session date (tz-naive DatetimeIndex) with columns
    ``open, high, low, close, volume`` for equities/indices, or ``nav`` (+ ``total_assets``, ``investor_count``)
    for funds. Missing values stay NaN; adapters never fill or repair data.
    """

    source_id: str
    data_mode: DataMode

    @abstractmethod
    def status(self) -> ProviderStatus: ...

    @abstractmethod
    def list_instruments(self) -> list[ProviderInstrument]: ...

    @abstractmethod
    def get_series(self, symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame: ...


def slice_dates(df: pd.DataFrame, start: date | None, end: date | None) -> pd.DataFrame:
    if start is not None:
        df = df.loc[pd.Timestamp(start) :]
    if end is not None:
        df = df.loc[: pd.Timestamp(end)]
    return df
