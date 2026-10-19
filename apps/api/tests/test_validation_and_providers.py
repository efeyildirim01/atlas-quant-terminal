from datetime import date

import httpx
import pandas as pd
import pytest

from app.integrations.base import ProviderError, ProviderUnavailable
from app.integrations.catalog import CATALOG, build_providers
from app.integrations.csv_provider import CsvProvider
from app.integrations.evds import EvdsProvider
from app.integrations.fixture import FixtureProvider
from app.integrations.gates import UnavailableSource
from app.models.enums import DataMode, SourceAvailability
from tests.conftest import FIXTURE_END, make_settings


def test_fixture_is_deterministic_and_labelled(fixture_provider):
    a = fixture_provider.get_series("D-BNK1")
    b = FixtureProvider(FIXTURE_END).get_series("D-BNK1")
    pd.testing.assert_frame_equal(a, b)
    insts = fixture_provider.list_instruments()
    assert all(i.symbol.startswith("D-") and i.exchange == "FIXTURE" for i in insts)
    assert fixture_provider.data_mode == DataMode.FIXTURE


def test_catalog_covers_every_provider_and_unavailable_sources_refuse():
    providers = build_providers(make_settings("sqlite://"))
    assert {p.source_id for p in providers} <= set(CATALOG)
    for p in providers:
        if isinstance(p, UnavailableSource):
            assert p.status().availability == SourceAvailability.UNAVAILABLE
            with pytest.raises(ProviderUnavailable):
                p.get_series("ANY")


def test_csv_provider(tmp_path):
    (tmp_path / "instruments.csv").write_text("symbol,instrument_type,name,exchange\nABC,equity,Abc Co,XIST\n")
    (tmp_path / "ABC.csv").write_text("date,open,high,low,close,volume\n2024-01-03,10,11,9,10.5,100\n2024-01-02,9,10,8,9.5,100\n")
    p = CsvProvider(tmp_path)
    assert p.status().availability == SourceAvailability.AVAILABLE
    df = p.get_series("ABC")
    assert df.index.is_monotonic_increasing and df["close"].iloc[-1] == 10.5
    assert p.list_instruments()[0].exchange == "XIST"


def _evds(handler, key="k"):
    return EvdsProvider(key, "https://example.invalid/service/evds/", client=httpx.Client(transport=httpx.MockTransport(handler)), retries=1)


def test_evds_parses_and_sends_key_in_header_not_url():
    seen = {}

    def handler(req: httpx.Request):
        seen["key"], seen["url"] = req.headers.get("key"), str(req.url)
        return httpx.Response(200, json={"items": [{"Tarih": "02-01-2024", "TP_DK_USD_A": "29.70"},
                                                   {"Tarih": "01-01-2024", "TP_DK_USD_A": None}]})

    df = _evds(handler, key="secret-key").get_series("TP.DK.USD.A", date(2024, 1, 1), date(2024, 1, 2))
    assert seen["key"] == "secret-key" and "secret-key" not in seen["url"]
    assert "startDate=01-01-2024" in seen["url"]
    assert df["close"].tolist() == [29.70] and df.attrs["null_observations"] == 1


def test_evds_errors_and_disabled_state():
    with pytest.raises(ProviderError, match="403"):
        _evds(lambda r: httpx.Response(403)).get_series("TP.DK.USD.A")
    with pytest.raises(ProviderError, match="after retries"):
        _evds(lambda r: httpx.Response(500)).get_series("TP.DK.USD.A")
    disabled = _evds(lambda r: httpx.Response(200), key=None)
    assert disabled.status().availability == SourceAvailability.DISABLED
    with pytest.raises(ProviderUnavailable):
        disabled.get_series("TP.DK.USD.A")
