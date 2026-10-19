"""TCMB EVDS macro series adapter.

Built from the EVDS 2 Web Service Usage Guide: ``series=<codes>&startDate=dd-mm-yyyy&endDate=dd-mm-yyyy&type=json``.
JSON rows sit under ``items``, with a ``Tarih`` date column and one column per series whose dots become
underscores. The API key goes in an HTTP header (``key``), so it never appears in URLs or access logs.

NOT VERIFIED against a live key. EVDS 3 is in beta (2026), and the base URL and header name must be confirmed
(docs/data-sources/SOURCE_INVENTORY.md). Both are configurable.
"""

from __future__ import annotations

from datetime import date

import httpx
import pandas as pd

from app.integrations.base import MarketDataProvider, ProviderError, ProviderInstrument, ProviderStatus, ProviderUnavailable
from app.models.enums import DataMode, SourceAvailability

# Explicit catalogue. Codes must be confirmed in the EVDS series browser before enabling in production.
SERIES = {"TP.DK.USD.A": ("USD/TRY indicative buying rate (TCMB)", "fx")}


class EvdsProvider(MarketDataProvider):
    source_id = "evds"
    data_mode = DataMode.OFFICIAL

    def __init__(self, api_key: str | None, base_url: str, client: httpx.Client | None = None, retries: int = 2):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") + "/"
        self.client = client or httpx.Client(timeout=15.0)
        self.retries = retries

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            source_id=self.source_id,
            availability=SourceAvailability.AVAILABLE if self.api_key else SourceAvailability.DISABLED,
            datasets=["macro_series"],
            detail="Key configured; not yet verified against the live service" if self.api_key else "Set ATLAS_EVDS_API_KEY to enable",
        )

    def list_instruments(self) -> list[ProviderInstrument]:
        if not self.api_key:
            return []
        return [ProviderInstrument(symbol=c, name=n, instrument_type=k, exchange="TCMB") for c, (n, k) in SERIES.items()]

    def get_series(self, symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        if not self.api_key:
            raise ProviderUnavailable("EVDS disabled: no API key configured")
        start = start or date(2019, 1, 1)
        end = end or date.today()
        url = f"{self.base_url}series={symbol}&startDate={start:%d-%m-%Y}&endDate={end:%d-%m-%Y}&type=json"
        last_exc: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                resp = self.client.get(url, headers={"key": self.api_key})
                if resp.status_code == 403:
                    raise ProviderError("EVDS rejected the API key (403)")
                resp.raise_for_status()
                return self._parse(resp.json(), symbol)
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
        raise ProviderError(f"EVDS request failed after retries: {last_exc}")

    @staticmethod
    def _parse(payload: dict, symbol: str) -> pd.DataFrame:
        col = symbol.replace(".", "_")
        items = payload.get("items")
        if items is None:
            raise ProviderError("Unexpected EVDS payload: no 'items'")
        df = pd.DataFrame([(r.get("Tarih"), r.get(col)) for r in items], columns=["date", "close"])
        df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y", errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["date"]).set_index("date").sort_index()
        df.attrs["null_observations"] = int(df["close"].isna().sum())  # holidays come back as nulls
        return df.dropna()
