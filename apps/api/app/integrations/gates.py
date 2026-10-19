"""Integration boundaries for sources without permitted access. They refuse every data call."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.integrations.base import MarketDataProvider, ProviderInstrument, ProviderStatus, ProviderUnavailable
from app.models.enums import DataMode, SourceAvailability


class UnavailableSource(MarketDataProvider):
    data_mode = DataMode.LICENSED

    def __init__(self, source_id: str, datasets: list[str], requirement: str):
        self.source_id = source_id
        self.datasets = datasets
        self.requirement = requirement

    def status(self) -> ProviderStatus:
        return ProviderStatus(self.source_id, SourceAvailability.UNAVAILABLE, self.requirement, self.datasets)

    def list_instruments(self) -> list[ProviderInstrument]:
        return []

    def get_series(self, symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        raise ProviderUnavailable(f"{self.source_id}: {self.requirement}")
