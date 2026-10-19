"""User-supplied files, e.g. EOD exports from a vendor the user is licensed with.

Layout of ``ATLAS_CSV_DIR``::

    instruments.csv   symbol,instrument_type,name,exchange,currency,sector,benchmark_symbol
    <SYMBOL>.csv      date,open,high,low,close,volume                 (equity / index)
                      date,nav[,total_assets,investor_count]          (fund)
"""

from __future__ import annotations

from datetime import date
from functools import cached_property
from pathlib import Path

import pandas as pd

from app.integrations.base import (
    InstrumentNotFound, MarketDataProvider, ProviderError, ProviderInstrument, ProviderStatus, slice_dates,
)
from app.models.enums import DataMode, SourceAvailability


class CsvProvider(MarketDataProvider):
    source_id = "csv"
    data_mode = DataMode.USER_SUPPLIED

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)

    def status(self) -> ProviderStatus:
        ok = (self.dir / "instruments.csv").is_file()
        return ProviderStatus(
            source_id=self.source_id,
            availability=SourceAvailability.AVAILABLE if ok else SourceAvailability.DISABLED,
            datasets=["eod_bars", "fund_nav"],
            detail=f"{len(self._instruments)} instruments from {self.dir.name}" if ok else "instruments.csv not found",
        )

    @cached_property
    def _instruments(self) -> dict[str, ProviderInstrument]:
        path = self.dir / "instruments.csv"
        if not path.is_file():
            return {}
        rows = pd.read_csv(path, dtype=str).fillna("").to_dict("records")
        out = {}
        for r in rows:
            itype = r["instrument_type"]
            out[r["symbol"]] = ProviderInstrument(
                symbol=r["symbol"], name=r.get("name") or r["symbol"], instrument_type=itype,
                exchange=r.get("exchange") or "UNKNOWN", currency=r.get("currency") or "TRY",
                sector=r.get("sector") or None, benchmark_symbol=r.get("benchmark_symbol") or None,
                fund={"code": r["symbol"]} if itype == "fund" else None,
            )
        return out

    def list_instruments(self) -> list[ProviderInstrument]:
        return list(self._instruments.values())

    def get_series(self, symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        if symbol not in self._instruments:
            raise InstrumentNotFound(symbol)
        path = self.dir / f"{symbol}.csv"
        if not path.is_file():
            raise ProviderError(f"Series file missing: {path.name}")
        df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
        df.columns = [c.lower() for c in df.columns]
        return slice_dates(df, start, end)
