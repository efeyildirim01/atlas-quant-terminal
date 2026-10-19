"""Fund ranking fairness rules and the market-overview cache."""

import numpy as np
import pandas as pd
import pytest

from app.services.fund_service import _competition_ranks, rank_funds


def nav(start: str, end: str, daily: float, seed: int = 0, vol: float = 0.0) -> pd.Series:
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    r = daily + rng.normal(0, vol, len(idx)) if vol else np.full(len(idx), daily)
    return pd.Series(np.cumprod(1 + r), index=idx)


END = "2026-10-15"


def test_competition_ranking_ties():
    assert _competition_ranks([0.3, 0.1, 0.3, 0.2], higher_is_better=True) == [1, 4, 1, 3]
    assert _competition_ranks([0.3, 0.1, 0.3], higher_is_better=False) == [2, 1, 2]


def test_short_history_and_stale_funds_are_excluded_with_reasons():
    navs = {
        "OLD": nav("2020-01-01", END, 0.0004),
        "YOUNG": nav("2025-06-02", END, 0.0010),  # better return, but too young for 3Y
        "STALE": nav("2020-01-01", "2026-09-01", 0.0008),  # stopped publishing
    }
    out = rank_funds(navs, {}, "3Y", "total_return")
    assert [r["symbol"] for r in out["rows"]] == ["OLD"]
    reasons = {e["symbol"]: e["reason"] for e in out["excluded"]}
    assert reasons["YOUNG"].startswith("insufficient history") and reasons["STALE"].startswith("stale")
    assert out["n_candidates"] == 3 and out["n_ranked"] == 1


def test_all_funds_measured_over_the_same_window():
    # B's last NAV is two business days earlier. The common window must end at B's last date for both.
    a = nav("2020-01-01", END, 0.0005)
    b = nav("2020-01-01", "2026-10-13", 0.0005)
    out = rank_funds({"A": a, "B": b}, {}, "1Y", "total_return")
    assert out["window"]["end"] == "2026-10-13"
    va, vb = (next(r["value"] for r in out["rows"] if r["symbol"] == s) for s in "AB")
    assert va == pytest.approx(vb)  # identical daily growth over an identical window
    assert out["rows"][0]["rank"] == out["rows"][1]["rank"] == 1


def test_direction_per_metric():
    calm = nav("2020-01-01", END, 0.0004, seed=1, vol=0.002)
    wild = nav("2020-01-01", END, 0.0004, seed=2, vol=0.02)
    vol = rank_funds({"CALM": calm, "WILD": wild}, {}, "3Y", "annualized_volatility")
    assert vol["rows"][0]["symbol"] == "CALM" and vol["direction"] == "lower is better"
    dd = rank_funds({"CALM": calm, "WILD": wild}, {}, "3Y", "max_drawdown")
    assert dd["rows"][0]["symbol"] == "CALM"  # shallower drawdown ranks first
    fee = rank_funds({"CALM": calm, "WILD": wild}, {"CALM": 0.02, "WILD": 0.01}, "3Y", "management_fee")
    assert fee["rows"][0]["symbol"] == "WILD"


def test_undefined_metric_excluded_not_zeroed():
    flat = nav("2020-01-01", END, 0.0)  # no drawdown → Calmar undefined (CAGR / 0)
    ok = nav("2020-01-01", END, 0.0004, seed=3, vol=0.01)
    out = rank_funds({"FLAT": flat, "OK": ok}, {}, "1Y", "calmar_ratio")
    assert [r["symbol"] for r in out["rows"]] == ["OK"]
    assert "undefined" in out["excluded"][0]["reason"]


def test_invalid_inputs():
    with pytest.raises(ValueError):
        rank_funds({"A": nav("2020-01-01", END, 0.001)}, {}, "2Y", "total_return")
    with pytest.raises(ValueError):
        rank_funds({"A": nav("2020-01-01", END, 0.001)}, {}, "1Y", "alpha")


def test_rankings_endpoint(client):
    body = client.get("/api/v1/funds/rankings", params={"horizon": "3Y", "metric": "sharpe_ratio", "rf": 0.3}).json()
    d = body["data"]
    assert d["n_candidates"] == 6 and d["rf_annual"] == 0.3
    assert [r["rank"] for r in d["rows"]] == sorted(r["rank"] for r in d["rows"])
    assert all("name" in r for r in d["rows"]) and body["is_fixture"]
    assert "common window" in body["methodology"]["window"]
    assert client.get("/api/v1/funds/rankings", params={"metric": "alpha"}).status_code == 422
    eq = client.get("/api/v1/funds/rankings", params={"category": "Money Market", "metric": "total_return"}).json()["data"]
    assert [r["symbol"] for r in eq["rows"]] == ["D-MMF"]


def test_overview_cache_reuses_until_next_ingestion(seeded_db, client):
    from app.integrations.catalog import build_providers
    from app.services.ingestion import ingest_instrument
    from app.models import Instrument
    from sqlalchemy import select

    client.get("/api/v1/market/overview")
    first = client.app.state.overview_cache
    client.get("/api/v1/market/overview")
    assert client.app.state.overview_cache is first  # served from cache
    database, settings = seeded_db
    with database.sessionmaker() as s:
        inst = s.scalar(select(Instrument).where(Instrument.symbol == "D-BNK1"))
        provider = next(p for p in build_providers(settings) if p.source_id == "fixture")
        assert ingest_instrument(s, provider, inst).status == "succeeded"
    client.get("/api/v1/market/overview")
    assert client.app.state.overview_cache is not first  # a new ingestion run invalidated it


def test_near_zero_volatility_excluded_from_ratio_rankings():
    mmf = nav("2020-01-01", END, 0.0015, seed=4, vol=0.00002)  # money-market-like: high return, ~0 vol
    eq = nav("2020-01-01", END, 0.0006, seed=5, vol=0.012)
    out = rank_funds({"MMF": mmf, "EQ": eq}, {}, "3Y", "sharpe_ratio")
    assert [r["symbol"] for r in out["rows"]] == ["EQ"]
    assert "not meaningful" in out["excluded"][0]["reason"]
    # Return rankings still include it: the exclusion is specific to volatility-denominated ratios.
    assert {r["symbol"] for r in rank_funds({"MMF": mmf, "EQ": eq}, {}, "3Y", "total_return")["rows"]} == {"MMF", "EQ"}
