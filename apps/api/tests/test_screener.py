"""Screener: filter language, missing-data rule, point-in-time snapshots, CSV, saved-screen isolation."""

import uuid

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.analytics.screen import MAX_CONDITIONS, ScreenError, evaluate, sort_rows
from app.auth.deps import CSRF_COOKIE

TYPES = {"x": "number", "cat": "category", "flag": "boolean"}
DF = pd.DataFrame({
    "symbol": ["A", "B", "C", "D"],
    "x": [1.0, 5.0, np.nan, 10.0],
    "cat": ["eq", "fx", "eq", None],
    "flag": [True, False, None, True],
})


def run(node):
    mask, diag = evaluate(DF, node, TYPES)
    return list(DF.loc[mask, "symbol"]), diag


def C(field, op, value=None, value2=None):
    return {"field": field, "operator": op, "value": value, "value2": value2}


def test_and_or_nesting_and_operators():
    assert run({"op": "and", "conditions": [C("x", "gt", 2), C("cat", "eq", "fx")]})[0] == ["B"]
    assert run({"op": "or", "conditions": [C("x", "lt", 2), C("flag", "is_true")]})[0] == ["A", "D"]
    nested = {"op": "or", "conditions": [{"op": "and", "conditions": [C("x", "between", 4, 11), C("flag", "is_true")]}, C("cat", "in", ["fx"])]}
    assert run(nested)[0] == ["B", "D"]
    assert run({"op": "and", "conditions": [C("cat", "not_in", ["eq"])]})[0] == ["B"]
    assert run({"op": "and", "conditions": []})[0] == ["A", "B", "C", "D"]


def test_missing_values_never_pass_and_are_counted():
    syms, diag = run({"op": "and", "conditions": [C("x", "lte", 100)]})
    assert syms == ["A", "B", "D"] and diag.missing_by_condition[0]["excluded_missing"] == 1
    # Complement operators also exclude missing, so "missing" can never sneak in through either side.
    assert run({"op": "and", "conditions": [C("flag", "is_false")]})[0] == ["B"]
    assert run({"op": "and", "conditions": [C("cat", "neq", "eq")]})[0] == ["B"]


@pytest.mark.parametrize("node, msg", [
    ({"op": "and", "conditions": [C("nope", "gt", 1)]}, "unknown or unavailable field"),
    ({"op": "and", "conditions": [C("cat", "gt", 1)]}, "not valid for category"),
    ({"op": "and", "conditions": [C("x", "between", 5, 1)]}, "value ≤ value2"),
    ({"op": "and", "conditions": [C("x", "gt", "5")]}, "numeric value"),
    ({"op": "and", "conditions": [C("cat", "in", [])]}, "non-empty list"),
    ({"op": "xor", "conditions": [C("x", "gt", 1)]}, "'and' or 'or'"),
    ({"op": "and", "conditions": [{"op": "and", "conditions": [{"op": "and", "conditions": [{"op": "and", "conditions": [C("x", "gt", 1)]}]}]}]}, "nested at most"),
    ({"op": "and", "conditions": [C("x", "gt", i) for i in range(MAX_CONDITIONS + 1)]}, "at most"),
])
def test_invalid_screens_rejected(node, msg):
    with pytest.raises(ScreenError, match=msg):
        evaluate(DF, node, TYPES)


def test_sort_missing_last_both_directions():
    assert list(sort_rows(DF, "x", True)["symbol"]) == ["D", "B", "A", "C"]
    assert list(sort_rows(DF, "x", False)["symbol"]) == ["A", "B", "D", "C"]


# ── API ───────────────────────────────────────────────────────────────────────────────────────────
def test_catalog_marks_unavailable_fields(client):
    fields = {f["id"]: f for f in client.get("/api/v1/screener/equities/fields").json()}
    assert fields["pe"]["available"] is False and "KAP" in fields["pe"]["reason"]
    r = client.post("/api/v1/screener/equities", json={"filter": {"op": "and", "conditions": [C("pe", "lt", 10)]}})
    assert r.status_code == 422 and "unavailable" in r.json()["detail"]


def test_presets_are_valid_and_run(client):
    for u in ("equities", "funds"):
        for p in client.get(f"/api/v1/screener/{u}/presets").json():
            r = client.post(f"/api/v1/screener/{u}", json={"filter": p["filter"], "sort": p["sort"]})
            assert r.status_code == 200, (u, p["id"], r.text)


def test_pagination_sort_and_envelope(client):
    body = {"sort": {"field": "chg_1y", "descending": True}, "page_size": 5}
    p1 = client.post("/api/v1/screener/equities", json={**body, "page": 1}).json()
    p3 = client.post("/api/v1/screener/equities", json={**body, "page": 3}).json()
    d1 = p1["data"]
    assert d1["total_matches"] == 12 and len(d1["rows"]) == 5 and len(p3["data"]["rows"]) == 2
    vals = [r["chg_1y"] for r in d1["rows"]]
    assert vals == sorted(vals, reverse=True)
    assert p1["is_fixture"] and d1["snapshot_id"] == p3["data"]["snapshot_id"]
    assert "missing" in p1["methodology"]["missing_values"]


def test_point_in_time_screen_uses_only_data_up_to_as_of(client, fixture_provider):
    r = client.post("/api/v1/screener/equities", json={"as_of": "2025-06-30", "page_size": 50}).json()["data"]
    row = next(x for x in r["rows"] if x["symbol"] == "D-BNK1")
    raw = fixture_provider.get_series("D-BNK1").loc[:"2025-06-30"]
    assert row["data_as_of"] == "2025-06-30" and row["close"] == pytest.approx(raw["close"].iloc[-1])
    assert row["chg_1m"] == pytest.approx(raw["close"].iloc[-1] / raw["close"].iloc[-22] - 1)
    latest = client.post("/api/v1/screener/equities", json={}).json()["data"]
    assert latest["snapshot_id"] != r["snapshot_id"]
    assert client.post("/api/v1/screener/equities", json={"as_of": "2099-01-01"}).status_code == 422


def test_fund_screen_matches_fund_pages(client):
    """Regression: the same field name must give the same number on every screen."""
    scr = {r["symbol"]: r for r in client.post("/api/v1/screener/funds", json={}).json()["data"]["rows"]}
    lst = {r["symbol"]: r for r in client.get("/api/v1/funds").json()["data"]["items"]}
    for sym in scr:
        assert scr[sym]["ret_1y"] == pytest.approx(lst[sym]["ret_1y"])
        assert scr[sym]["ret_3y_ann"] == pytest.approx(lst[sym]["ret_3y_ann"])


def test_csv_export_contains_all_matches_and_provenance(client):
    r = client.post("/api/v1/screener/funds/export", json={"filter": {"op": "and", "conditions": [C("management_fee", "lte", 0.025)]},
                                                         "columns": ["category", "management_fee", "ret_1y"], "page_size": 1})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "_FIXTURE.csv" in r.headers["content-disposition"]
    lines = r.text.lstrip("﻿").strip().split("\r\n")
    assert lines[0].startswith("# snapshot_id,") and any(l.startswith('# fixture_data,"YES') for l in lines)
    header_i = lines.index("symbol,name,category,management_fee,ret_1y")
    # Fees ≤ 2.5%: D-EQF (2.5%), D-PRT, D-FGN, D-GLD, D-MMF; D-TCH (2.8%) excluded.
    assert len(lines) - header_i - 1 == 5  # page_size ignored: export contains every match
    assert "# matches,5 of 6" in lines


def test_saved_screens_crud_and_isolation(client):
    def user():
        c = TestClient(client.app)
        assert c.post("/api/v1/auth/register", json={"email": f"s-{uuid.uuid4().hex[:8]}@example.com", "password": "correct horse battery"}).status_code == 201
        return c, {"X-CSRF-Token": c.cookies.get(CSRF_COOKIE)}

    a, ha = user()
    definition = {"filter": {"op": "and", "conditions": [C("vol_1y", "lt", 0.5)]}, "sort": {"field": "vol_1y", "descending": False}, "columns": ["vol_1y"]}
    r = a.post("/api/v1/screener/saved", json={"name": "Calm", "universe": "equities", "definition": definition}, headers=ha)
    assert r.status_code == 201, r.text
    sid = r.json()["screen_id"]
    bad = {"filter": {"op": "and", "conditions": [C("pe", "lt", 5)]}}
    assert a.post("/api/v1/screener/saved", json={"name": "x", "universe": "equities", "definition": bad}, headers=ha).status_code == 422
    assert [s["name"] for s in a.get("/api/v1/screener/saved").json()] == ["Calm"]

    b, hb = user()
    assert b.get("/api/v1/screener/saved").json() == []
    assert b.delete(f"/api/v1/screener/saved/{sid}", headers=hb).status_code == 404
    assert TestClient(client.app).get("/api/v1/screener/saved").status_code == 401
    assert a.delete(f"/api/v1/screener/saved/{sid}", headers=ha).status_code == 204


def test_category_values_offered_for_builder(client):
    d = client.post("/api/v1/screener/funds", json={}).json()["data"]
    assert "Money Market" in d["category_values"]["category"]
    assert d["category_values"]["management_company"] == ["Fixture Asset Management (synthetic)"]
