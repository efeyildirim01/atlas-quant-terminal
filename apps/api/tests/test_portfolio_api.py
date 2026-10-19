"""Portfolio transactions & analytics over the seeded fixture DB, including authorization boundaries."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth.deps import CSRF_COOKIE

PW = "correct horse battery"


def login(client: TestClient, email: str) -> TestClient:
    c = TestClient(client.app)
    r = c.post("/api/v1/auth/register", json={"email": email, "password": PW})
    assert r.status_code == 201, r.text
    return c


def h(c: TestClient) -> dict:
    return {"X-CSRF-Token": c.cookies.get(CSRF_COOKIE)}


def post(c: TestClient, pid: str, **body):
    return c.post(f"/api/v1/portfolios/{pid}/transactions", json=body, headers=h(c))


@pytest.fixture
def investor(client):
    import uuid

    c = login(client, f"inv-{uuid.uuid4().hex[:8]}@example.com")
    pid = c.post("/api/v1/portfolios", json={"name": "Core"}, headers=h(c)).json()["portfolio_id"]
    return c, pid


def test_full_workflow_with_reconciling_numbers(investor):
    c, pid = investor
    assert post(c, pid, transaction_type="deposit", transaction_date="2025-01-02", amount="100000").status_code == 201
    r = post(c, pid, transaction_type="buy", transaction_date="2025-01-02", symbol="d-bnk1", quantity="1000", price="20", commission="10")
    assert r.status_code == 201 and r.json()["symbol"] == "D-BNK1"
    assert post(c, pid, transaction_type="buy", transaction_date="2025-01-03", symbol="D-EQF", quantity="5000", price="3.5").status_code == 201
    assert post(c, pid, transaction_type="sell", transaction_date="2025-06-02", symbol="D-BNK1", quantity="400", price="25", commission="5").status_code == 201
    assert post(c, pid, transaction_type="deposit", transaction_date="2025-09-01", amount="20000").status_code == 201
    assert post(c, pid, transaction_type="fee", transaction_date="2025-12-31", amount="50").status_code == 201

    txns = c.get(f"/api/v1/portfolios/{pid}/transactions").json()
    assert [t["transaction_type"] for t in txns] == ["deposit", "buy", "buy", "sell", "deposit", "fee"]

    body = c.get(f"/api/v1/portfolios/{pid}/analytics", params={"rf": 0.3}).json()
    d, s = body["data"], body["data"]["summary"]
    assert d["available"] and d["as_of"] == "2026-10-15" and body["is_fixture"]
    # Accounting identities
    assert s["net_contributions"] == pytest.approx(120000)
    assert s["value"] == pytest.approx(s["cash"] + s["holdings_value"])
    assert s["total_pnl"] == pytest.approx(s["value"] - s["net_contributions"])
    assert s["total_pnl"] == pytest.approx(s["realized_pnl"] + s["unrealized_pnl"] + s["dividends"] - s["fees"])
    # FIFO realised P&L on the sell: proceeds 400·25 − 5 = 9995; cost 400 · (20 + 10/1000) = 8004
    assert d["realized"][0]["realized_pnl"] == pytest.approx(9995 - 8004)
    assert {h["symbol"] for h in d["holdings"]} == {"D-BNK1", "D-EQF"}
    assert sum(a["weight"] for a in d["allocation"]["asset_class"]) == pytest.approx(1.0)
    perf = d["performance"]
    assert perf["benchmark"]["symbol"] == "D-IDX"  # first point reflects day-1 gain vs the entered buy price
    assert s["twr"] == pytest.approx(perf["twr_index"][-1] / 100 - 1, abs=1e-4)
    assert s["mwr_annualized"] is not None and s["twr_annualized"] is not None
    rc = d["risk"]["decomposition"]["risk_contribution"]
    assert sum(r["contribution"] for r in rc) == pytest.approx(1.0)
    assert d["risk"]["metrics"]["sharpe_ratio"]["methodology"]["rf_annual"] == 0.3
    assert {p["instrument"] for p in body["provenance"]} >= {"D-BNK1", "D-EQF", "D-IDX"}


def test_ledger_rules_enforced_by_api(investor):
    c, pid = investor
    r = post(c, pid, transaction_type="buy", transaction_date="2025-01-02", symbol="D-BNK1", quantity="1", price="20")
    assert r.status_code == 422 and "first transaction must be a deposit" in r.json()["detail"]
    post(c, pid, transaction_type="deposit", transaction_date="2025-01-02", amount="1000")
    r = post(c, pid, transaction_type="buy", transaction_date="2025-01-03", symbol="D-BNK1", quantity="100", price="20")
    assert r.status_code == 422 and "exceeds cash" in r.json()["detail"]
    r = post(c, pid, transaction_type="sell", transaction_date="2025-01-03", symbol="D-BNK1", quantity="1", price="20")
    assert r.status_code == 422 and "no shorting" in r.json()["detail"]
    future = (date.today() + timedelta(days=10)).isoformat()
    assert post(c, pid, transaction_type="deposit", transaction_date=future, amount="1").status_code == 422
    # Schema-level shape checks
    assert post(c, pid, transaction_type="buy", transaction_date="2025-01-03", symbol="D-BNK1", quantity="1").status_code == 422
    assert post(c, pid, transaction_type="deposit", transaction_date="2025-01-03", amount="-5").status_code == 422
    assert post(c, pid, transaction_type="buy", transaction_date="2025-01-03", symbol="NOPE", quantity="1", price="1").status_code == 404


def test_delete_that_would_break_ledger_is_rejected(investor):
    c, pid = investor
    dep = post(c, pid, transaction_type="deposit", transaction_date="2025-01-02", amount="1000").json()
    post(c, pid, transaction_type="buy", transaction_date="2025-01-03", symbol="D-BNK1", quantity="10", price="20")
    r = c.delete(f"/api/v1/portfolios/{pid}/transactions/{dep['transaction_id']}", headers=h(c))
    assert r.status_code == 422 and "remaining ledger would be invalid" in r.json()["detail"]
    buy = c.get(f"/api/v1/portfolios/{pid}/transactions").json()[1]
    assert c.delete(f"/api/v1/portfolios/{pid}/transactions/{buy['transaction_id']}", headers=h(c)).status_code == 204


def test_empty_portfolio_analytics(investor):
    c, pid = investor
    d = c.get(f"/api/v1/portfolios/{pid}/analytics").json()["data"]
    assert d["available"] is False and "deposit" in d["reason"]


def test_other_users_cannot_read_or_write_transactions(client, investor):
    c, pid = investor
    post(c, pid, transaction_type="deposit", transaction_date="2025-01-02", amount="1000")
    tid = c.get(f"/api/v1/portfolios/{pid}/transactions").json()[0]["transaction_id"]
    import uuid

    other = login(client, f"other-{uuid.uuid4().hex[:8]}@example.com")
    assert other.get(f"/api/v1/portfolios/{pid}/transactions").status_code == 404
    assert other.get(f"/api/v1/portfolios/{pid}/analytics").status_code == 404
    assert post(other, pid, transaction_type="deposit", transaction_date="2025-01-02", amount="1").status_code == 404
    assert other.delete(f"/api/v1/portfolios/{pid}/transactions/{tid}", headers=h(other)).status_code == 404
    anon = TestClient(client.app)
    assert anon.get(f"/api/v1/portfolios/{pid}/analytics").status_code == 401
    # CSRF still required on the owner's writes
    assert c.post(f"/api/v1/portfolios/{pid}/transactions", json={"transaction_type": "deposit", "transaction_date": "2025-01-02", "amount": "1"}).status_code == 403
