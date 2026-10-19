from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from app.core.db import Base, Database
from app.integrations.base import MarketDataProvider, ProviderInstrument, ProviderStatus
from app.models import DataQualityIssue, IngestionRun, Instrument, MarketPrice
from app.models.enums import DataMode, SourceAvailability
from app.repositories.series import load_prices
from app.services.ingestion import ingest_all


class BrokenProvider(MarketDataProvider):
    """Returns one bad bar among good ones, and raises for a second instrument."""

    source_id = "csv"  # reuse a catalogued source id
    data_mode = DataMode.USER_SUPPLIED

    def status(self):
        return ProviderStatus("csv", SourceAvailability.AVAILABLE, "test")

    def list_instruments(self):
        return [ProviderInstrument("BAD", "Bad Data Co", "equity", "XTST"), ProviderInstrument("ERR", "Erroring Co", "equity", "XTST")]

    def get_series(self, symbol, start=None, end=None):
        if symbol == "ERR":
            raise RuntimeError("upstream exploded")
        idx = pd.bdate_range("2024-01-01", periods=30)
        c = np.linspace(10, 12, 30)
        df = pd.DataFrame({"open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": 1000.0}, index=idx)
        df.iloc[10, df.columns.get_loc("high")] = 1.0  # high below close → hard failure
        return df


def _db(tmp_path):
    d = Database(f"sqlite:///{(tmp_path / 'i.db').as_posix()}")
    Base.metadata.create_all(d.engine)
    return d


def test_fixture_ingestion_stores_decimal_utc_rows(seeded_db):
    database, _ = seeded_db
    with database.sessionmaker() as s:
        inst = s.scalar(select(Instrument).where(Instrument.symbol == "D-BNK1"))
        row = s.scalar(select(MarketPrice).where(MarketPrice.instrument_id == inst.instrument_id).order_by(MarketPrice.ts.desc()))
        assert isinstance(row.close, Decimal)
        assert row.ts.tzinfo is not None and row.ts.hour == 15  # 18:00 Istanbul = 15:00 UTC
        assert row.ts.date() == date(2026, 10, 15)
        assert row.quality_status == "VALIDATED" and row.source_id == "fixture"


def test_bad_rows_partial_and_errors_recorded(tmp_path):
    d = _db(tmp_path)
    with d.sessionmaker() as s:
        results = {r.symbol: r for r in ingest_all(s, [BrokenProvider()])}
        assert results["BAD"].status == "succeeded" and results["BAD"].rows_excluded == 1
        assert results["ERR"].status == "failed" and "upstream exploded" in results["ERR"].error
        inst = s.scalar(select(Instrument).where(Instrument.symbol == "BAD"))
        bundle = load_prices(s, inst)
        assert len(bundle.frame) == 29 and bundle.rows_excluded == 1  # excluded from analytics, still stored
        assert s.scalar(select(func.count()).select_from(MarketPrice)) == 30
        issue = s.scalar(select(DataQualityIssue).where(DataQualityIssue.check_code == "ohlc_inconsistent"))
        assert issue.severity == "error" and not issue.resolved
        assert s.scalar(select(func.count()).select_from(IngestionRun).where(IngestionRun.status == "failed")) == 1


def test_reingestion_is_idempotent_and_resolves_old_issues(tmp_path):
    d = _db(tmp_path)
    with d.sessionmaker() as s:
        ingest_all(s, [BrokenProvider()])
        ingest_all(s, [BrokenProvider()])
        assert s.scalar(select(func.count()).select_from(MarketPrice)) == 30
        open_issues = s.scalar(select(func.count()).select_from(DataQualityIssue).where(DataQualityIssue.resolved.is_(False)))
        all_issues = s.scalar(select(func.count()).select_from(DataQualityIssue))
        assert all_issues == 2 * open_issues
