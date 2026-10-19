"""Research reports: consistency with analytics, rule-based narrative, PDF, reproducibility check, isolation."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.auth.deps import CSRF_COOKIE
from app.models import Fund, FundNav, Instrument
from app.services.report_pdf import fmt, scope_text
from app.services.report_service import compare_facts


def user(client):
    c = TestClient(client.app)
    assert c.post("/api/v1/auth/register", json={"email": f"r-{uuid.uuid4().hex[:8]}@example.com", "password": "correct horse battery"}).status_code == 201
    return c, {"X-CSRF-Token": c.cookies.get(CSRF_COOKIE)}


@pytest.fixture
def portfolio(client):
    c, h = user(client)
    pid = c.post("/api/v1/portfolios", json={"name": "Concentrated"}, headers=h).json()["portfolio_id"]
    for b in [dict(transaction_type="deposit", transaction_date="2024-01-02", amount="100000"),
              dict(transaction_type="buy", transaction_date="2024-01-02", symbol="D-DEFN", quantity="1500", price="40"),
              dict(transaction_type="buy", transaction_date="2024-01-03", symbol="D-GLD", quantity="10000", price="2.4")]:
        assert c.post(f"/api/v1/portfolios/{pid}/transactions", json=b, headers=h).status_code == 201
    return c, h, pid


def test_portfolio_report_matches_analytics_and_flags_risks(portfolio):
    c, h, pid = portfolio
    r = c.post("/api/v1/reports/generate", json={"report_type": "portfolio_risk", "portfolio_id": pid, "rf": 0.3}, headers=h)
    assert r.status_code == 201 and r.json()["is_fixture"] is True
    doc = c.get(f"/api/v1/reports/{r.json()['report_id']}").json()["document"]
    an = c.get(f"/api/v1/portfolios/{pid}/analytics", params={"rf": 0.3}).json()["data"]
    assert doc["facts"]["summary.value"] == pytest.approx(an["summary"]["value"])
    assert doc["facts"]["summary.twr"] == pytest.approx(an["summary"]["twr"])
    assert doc["facts"]["metric.sharpe_ratio"] == pytest.approx(an["risk"]["metrics"]["sharpe_ratio"]["value"])
    assert any("Concentration: D-DEFN" in f for f in doc["risk_factors"])
    assert any(f"{an['summary']['twr'] * 100:+.1f}%" in s for s in doc["executive_summary"])
    headings = [s["heading"] for s in doc["sections"]]
    assert {"Performance", "Holdings and allocation", "Risk metrics (TWR series)", "Risk decomposition"} <= set(headings)
    assert doc["data_snapshot"]["as_of"] == "2026-10-15" and doc["limitations"] and doc["sources"]
    assert all(len(s["dates"]) <= 401 for sec in doc["sections"] if sec.get("chart") for s in sec["chart"]["series"])


def test_fund_comparison_report_and_validation(client):
    c, h = user(client)
    r = c.post("/api/v1/reports/generate", json={"report_type": "fund_comparison", "codes": ["D-EQF", "D-MMF"], "rf": 0.35}, headers=h)
    assert r.status_code == 201
    doc = c.get(f"/api/v1/reports/{r.json()['report_id']}").json()["document"]
    assert doc["facts"]["fund.D-EQF.cagr"] > -1
    assert "fund.D-MMF.sharpe" not in doc["facts"]  # omitted below 1% volatility, never shown as a huge number
    assert any("categories" in f for f in doc["risk_factors"])
    assert c.post("/api/v1/reports/generate", json={"report_type": "fund_comparison", "codes": ["D-EQF"]}, headers=h).status_code == 422
    assert c.post("/api/v1/reports/generate", json={"report_type": "portfolio_risk"}, headers=h).status_code == 422


def test_pdf_export(portfolio):
    c, h, pid = portfolio
    rid = c.post("/api/v1/reports/generate", json={"report_type": "portfolio_risk", "portfolio_id": pid}, headers=h).json()["report_id"]
    r = c.get(f"/api/v1/reports/{rid}/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-" and len(r.content) > 20_000
    assert r.headers["content-disposition"].endswith('_FIXTURE.pdf"')


def test_verify_reproduces_then_detects_changed_data(client, seeded_db):
    c, h = user(client)
    rid = c.post("/api/v1/reports/generate", json={"report_type": "fund_comparison", "codes": ["D-EQF", "D-GLD"]}, headers=h).json()["report_id"]
    v = c.post(f"/api/v1/reports/{rid}/verify", headers=h).json()
    assert v["status"] == "reproduced" and v["n_differences"] == 0 and v["facts_checked"] > 10
    database, _ = seeded_db
    with database.sessionmaker() as s:  # simulate a vendor correction to the latest D-GLD NAV
        fund_id = s.scalar(select(Fund.fund_id).join(Instrument).where(Instrument.symbol == "D-GLD"))
        last = s.scalar(select(FundNav.valuation_date).where(FundNav.fund_id == fund_id).order_by(FundNav.valuation_date.desc()))
        original = s.scalar(select(FundNav.nav).where(FundNav.fund_id == fund_id, FundNav.valuation_date == last))
        s.execute(update(FundNav).where(FundNav.fund_id == fund_id, FundNav.valuation_date == last).values(nav=original * 2))
        s.commit()
    try:
        v2 = c.post(f"/api/v1/reports/{rid}/verify", headers=h).json()
        assert v2["status"] == "differs" and any(d["fact"].startswith("fund.D-GLD") for d in v2["differences"])
        assert c.get(f"/api/v1/reports/{rid}").json()["verification_status"] == "differs"
    finally:
        with database.sessionmaker() as s:
            s.execute(update(FundNav).where(FundNav.fund_id == fund_id, FundNav.valuation_date == last).values(nav=original))
            s.commit()


def test_reports_are_private(client, portfolio):
    c, h, pid = portfolio
    rid = c.post("/api/v1/reports/generate", json={"report_type": "portfolio_risk", "portfolio_id": pid}, headers=h).json()["report_id"]
    other, ho = user(client)
    assert other.get(f"/api/v1/reports/{rid}").status_code == 404
    assert other.get(f"/api/v1/reports/{rid}/pdf").status_code == 404
    assert other.post(f"/api/v1/reports/{rid}/verify", headers=ho).status_code == 404
    assert other.post("/api/v1/reports/generate", json={"report_type": "portfolio_risk", "portfolio_id": pid}, headers=ho).status_code == 404
    assert other.get("/api/v1/reports").json() == []
    assert TestClient(client.app).get("/api/v1/reports").status_code == 401
    assert c.delete(f"/api/v1/reports/{rid}", headers=h).status_code == 204


def test_formatting_contract_and_fact_diff():
    assert fmt(0.12345, "pct1") == "12.3%" and fmt(None, "num2") == "—" and fmt({"pct": -0.05}, "auto") == "-5.00%"
    assert fmt(1234.5, "num2") == "1,234.50" and fmt(3, "int") == "3"
    assert scope_text({"funds": ["A", "B"], "window": {"start": "2020-01-01", "end": "2021-01-01"}}) == "funds: A, B · window: 2020-01-01 to 2021-01-01"
    assert compare_facts({"a": 1.0, "b": 2.0}, {"a": 1.0, "b": 2.0000001}) == [{"fact": "b", "stored": 2.0, "regenerated": 2.0000001}]
    assert compare_facts({"a": 1.0}, {"a": 1.0 + 1e-12}) == []
