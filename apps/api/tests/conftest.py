"""Test fixtures. All market data here is the explicitly labelled synthetic FIXTURE universe."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ATLAS_LOG_JSON", "false")

from app.core.config import Settings  # noqa: E402
from app.core.db import Base, Database  # noqa: E402
from app.integrations.catalog import build_providers  # noqa: E402
from app.integrations.fixture import FixtureProvider  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.ingestion import ingest_all  # noqa: E402

FIXTURE_END = date(2026, 10, 15)


@pytest.fixture(scope="session")
def fixture_provider() -> FixtureProvider:
    return FixtureProvider(FIXTURE_END)


@pytest.fixture(scope="session")
def bars(fixture_provider) -> pd.DataFrame:
    return fixture_provider.get_series("D-AIRL")


@pytest.fixture
def random_walk() -> pd.Series:
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2020-01-01", periods=400)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, len(idx)))), index=idx)


def make_settings(db_url: str, **overrides) -> Settings:
    base = Settings()
    return replace(base, database_url=db_url, enable_fixtures=True, fixture_end=FIXTURE_END, csv_dir=None, evds_api_key=None,
                   rate_limit_per_minute=10_000, auth_rate_limit_per_minute=1_000, **overrides)


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory) -> tuple[Database, Settings]:
    path = tmp_path_factory.mktemp("db") / "atlas_test.db"
    settings = make_settings(f"sqlite:///{path.as_posix()}")
    database = Database(settings.database_url)
    Base.metadata.create_all(database.engine)
    with database.sessionmaker() as s:
        results = ingest_all(s, build_providers(settings))
    assert all(r.status == "succeeded" for r in results), results
    return database, settings


@pytest.fixture(scope="session")
def client(seeded_db) -> TestClient:
    database, settings = seeded_db
    return TestClient(create_app(settings, database))


@pytest.fixture
def fresh_client(tmp_path) -> TestClient:
    """Empty database, for auth/portfolio tests that must not share users."""
    settings = make_settings(f"sqlite:///{(tmp_path / 'auth.db').as_posix()}")
    database = Database(settings.database_url)
    Base.metadata.create_all(database.engine)
    return TestClient(create_app(settings, database))
