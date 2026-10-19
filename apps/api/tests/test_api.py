"""API contract tests over the seeded fixture database (the vertical slice end to end)."""


def test_health_ready_and_request_id(client):
    r = client.get("/health")
    assert r.status_code == 200 and len(r.headers["x-request-id"]) >= 8
    ready = client.get("/ready").json()
    assert ready["status"] == "ready" and ready["checks"]["database"] == "ok"
    assert ready["checks"]["schema"] == "unversioned" and ready["checks"]["rate_limiter"] == "ok (memory)"
    assert client.get("/health", headers={"X-Request-ID": "abc12345-req"}).headers["x-request-id"] == "abc12345-req"


def test_search_groups_highlight_and_typo_tolerance(client):
    body = client.get("/api/v1/search", params={"q": "bank"}).json()
    assert {h["symbol"] for h in body["groups"]["equities"]} == {"D-BNK1", "D-BNK2"}
    hit = body["groups"]["equities"][0]
    assert hit["is_fixture"] and hit["match_field"] == "name"
    start, end = hit["highlight"][0]
    assert hit["name"][start:end].lower() == "bank"
    typo = client.get("/api/v1/search", params={"q": "defnce"}).json()
    assert typo["corrected"] and typo["groups"]["equities"][0]["symbol"] == "D-DEFN"
    funds = client.get("/api/v1/search", params={"q": "fixture asset"}).json()
    assert len(funds["groups"]["funds"]) == 6 and funds["groups"]["funds"][0]["match_field"] == "management_company"
    assert client.get("/api/v1/search", params={"q": "d-idx"}).json()["groups"]["indices"][0]["symbol"] == "D-IDX"


def test_equity_profile_envelope(client):
    body = client.get("/api/v1/equities/D-BNK1").json()
    assert body["is_fixture"] is True and body["request_id"] != "-"
    prov = body["provenance"][0]
    assert prov["source"]["source_id"] == "fixture" and prov["source"]["data_mode"] == "fixture"
    assert prov["as_of"] == "2026-10-15" and prov["delay"].startswith("end-of-day")
    assert body["quality"]["status"] in {"VALIDATED", "STALE"} and body["quality"]["rows_excluded"] == 0
    q = body["data"]["quote"]
    assert q["available"] and abs(q["change"] - (q["close"] - q["previous_close"])) < 1e-6
    assert q["low_52w"]["value"] <= q["close"] <= q["high_52w"]["value"]
    assert q["market_cap"] is None and "Unavailable" in q["market_cap_note"]
    assert body["data"]["benchmark"] == "D-IDX"


def test_prices_windows_and_resampling(client):
    d = client.get("/api/v1/equities/D-BNK1/prices", params={"window": "3M"}).json()["data"]
    assert 55 <= len(d["dates"]) <= 70 and d["dates"][-1] == "2026-10-15"
    w = client.get("/api/v1/equities/D-BNK1/prices", params={"window": "MAX", "interval": "1w"}).json()["data"]
    assert 390 <= len(w["dates"]) <= 410
    assert w["dates"][-1] == "2026-10-15"  # weekly bar labelled with its last real session, never a future date
    assert all(h >= max(o, c) for o, h, c in zip(w["open"], w["high"], w["close"]))
    assert client.get("/api/v1/equities/D-BNK1/prices", params={"interval": "5m"}).status_code == 422
    assert client.get("/api/v1/equities/NOPE/prices").status_code == 404


def test_technicals_research_is_descriptive(client):
    body = client.get("/api/v1/equities/D-DEFN/technicals", params={"window": "1Y"}).json()
    d = body["data"]
    assert d["signal"]["classification"] == "insufficient_evidence"
    assert d["series"]["sma_200"][0] is not None  # warm-up computed on full history
    assert d["research"]["multi_timeframe"]["alignment"] in {"aligned_up", "aligned_down", "mixed"}
    assert "score" in body["methodology"]["scores"]


def test_risk_endpoint_structured_metrics(client):
    body = client.get("/api/v1/equities/D-BNK1/risk", params={"rf": 0.4, "window": "3Y"}).json()
    met = body["data"]["metrics"]
    assert met["sharpe_ratio"]["methodology"]["rf_annual"] == 0.4 and met["sharpe_ratio"]["status"] == "ok"
    assert 0 < met["beta"]["value"] < 3 and met["beta"]["detail"]["correlation"] is not None
    assert met["var_99"]["status"] == "ok"  # 3Y ≈ 780 obs ≥ 500 required
    assert body["data"]["benchmark"] == "D-IDX" and len(body["provenance"]) == 2
    assert sum(body["data"]["distribution"]["counts"]) == body["data"]["distribution"]["n_obs"]
    assert "rf" in body["methodology"]


def test_unavailable_datasets_are_explicit(client):
    f = client.get("/api/v1/equities/D-BNK1/fundamentals").json()
    assert f["status"] == "UNAVAILABLE" and "KAP" in f["required_source"]
    v = client.get("/api/v1/equities/D-BNK1/valuation").json()
    assert v["status"] == "UNAVAILABLE"


def test_funds_list_detail_performance(client):
    lst = client.get("/api/v1/funds").json()
    assert lst["data"]["total"] == 6 and lst["is_fixture"]
    mmf = next(r for r in lst["data"]["items"] if r["symbol"] == "D-MMF")
    assert mmf["category"] == "Money Market" and mmf["holdings"] is None
    perf = client.get("/api/v1/funds/D-EQF/performance").json()["data"]
    assert perf["benchmark_symbol"] == "D-IDX" and perf["benchmark"]["alignment"].startswith("common")
    assert perf["period_returns"]["1Y"]["return"] is not None and perf["since_inception"]["annualized"] is not None
    assert perf["inflation_adjusted"]["status"] == "UNAVAILABLE"
    risk = client.get("/api/v1/funds/D-EQF/risk", params={"rf": 0.35}).json()["data"]["metrics"]
    assert risk["capture_ratios"]["detail"]["upside_capture"] is not None


def test_fund_compare_limits_and_alignment(client):
    r = client.post("/api/v1/funds/compare", json={"codes": ["D-EQF", "D-GLD", "D-MMF"]}).json()["data"]
    assert r["available"] and set(r["metrics"]) == {"D-EQF", "D-GLD", "D-MMF"}
    assert all(v[0] == 100 for v in r["rebased"].values())
    assert client.post("/api/v1/funds/compare", json={"codes": ["D-EQF"]}).status_code == 422
    assert client.post("/api/v1/funds/compare", json={"codes": ["D-EQF"] * 11}).status_code == 422


def test_market_overview_and_system(client):
    ov = client.get("/api/v1/market/overview").json()
    d = ov["data"]
    assert len(d["equities"]) == 12 and sum(d["breadth"].values()) == 12
    assert d["macro"]["usd_try"]["status"] == "UNAVAILABLE"
    assert ov["provenance"][0]["instrument"] == "D-IDX"
    health = client.get("/api/v1/system/data-health").json()
    states = {p["source_id"]: p["availability"] for p in health["providers"]}
    assert states["fixture"] == "available" and states["bist"] == "unavailable" and states["evds"] == "disabled"
    assert all(i["last_run_status"] == "succeeded" for i in health["instruments"])
    assert any(i["check_code"] == "missing_publication_timestamp" for i in health["open_issues"])
    status = client.get("/api/v1/system/market-status").json()
    assert status["live_feed"] is False and status["fixture_mode"] is True
    srcs = client.get("/api/v1/system/sources").json()
    assert {s["source_id"] for s in srcs} >= {"bist", "kap", "tefas", "evds", "tuik", "fixture", "csv"}


def test_instruments_pagination(client):
    p1 = client.get("/api/v1/instruments", params={"page": 1, "page_size": 5}).json()
    p2 = client.get("/api/v1/instruments", params={"page": 2, "page_size": 5}).json()
    assert p1["total"] == 19 and len(p1["items"]) == 5
    assert not {i["symbol"] for i in p1["items"]} & {i["symbol"] for i in p2["items"]}


def test_research_readings_do_not_change_with_chart_interval(client):
    daily = client.get("/api/v1/equities/D-BNK1/technicals", params={"window": "1Y", "interval": "1d"}).json()["data"]
    weekly = client.get("/api/v1/equities/D-BNK1/technicals", params={"window": "MAX", "interval": "1w"}).json()["data"]
    assert daily["research"] == weekly["research"] and weekly["research_basis"] == "daily bars"
    assert weekly["periods_per_year"] == 52
    # Weekly HV annualised with sqrt(52) must be of the same order as daily HV (sqrt(252)), not ~2x larger.
    d_hv = daily["research"]["volatility"]["hv_20"]
    w_hv = [x for x in weekly["series"]["hv_20"] if x is not None][-1]
    assert 0.4 < w_hv / d_hv < 2.0


def test_unhandled_errors_keep_request_id(seeded_db):
    from fastapi.testclient import TestClient
    from app.main import create_app

    database, settings = seeded_db
    app = create_app(settings, database)

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    r = TestClient(app, raise_server_exceptions=False).get("/boom", headers={"X-Request-ID": "trace-12345678"})
    assert r.status_code == 500 and r.json() == {"detail": "Internal error", "request_id": "trace-12345678"}
    assert "kaboom" not in r.text  # no internal detail leaks to clients
