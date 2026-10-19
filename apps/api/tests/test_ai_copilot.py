"""Copilot orchestration with a scripted fake Anthropic client (no network, no API key needed)."""

import json
import uuid
from types import SimpleNamespace as NS

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from app.ai.copilot import FALLBACK_BETA, Copilot, CopilotUnavailable
from app.ai.tools import Context
from app.auth.deps import CSRF_COOKIE


def usage():
    return NS(input_tokens=100, output_tokens=20, cache_read_input_tokens=50, cache_creation_input_tokens=0)


def msg(content, stop="end_turn", model="claude-opus-5-5", details=None):
    return NS(content=content, stop_reason=stop, usage=usage(), model=model, stop_details=details)


def tool_use(i, name, inp):
    return NS(type="tool_use", id=f"tu{i}", name=name, input=inp)


def text(t):
    return NS(type="text", text=t)


class FakeClient:
    """Implements client.beta.messages.stream(**kwargs) → context manager with get_final_message()."""

    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        step = self.script.pop(0)
        result = step(kwargs) if callable(step) else step
        client = self

        class _S:
            def __enter__(self):
                if isinstance(result, Exception):
                    raise result
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return result

        return _S()


def last_results(kwargs) -> list[dict]:
    return [json.loads(b["content"]) for b in kwargs["messages"][-1]["content"]]


@pytest.fixture
def ctx(seeded_db):
    database, settings = seeded_db
    with database.sessionmaker() as s:
        yield Context(s, settings, None)


def test_tool_loop_parallel_calls_and_verified_answer(ctx):
    def answer(kwargs):
        res = last_results(kwargs)  # both results arrive in ONE user message
        risk = next(r for r in res if r["evidence_id"] == "E1")
        cagr = risk["data"]["metrics"]["cagr"]["value"]
        vol = risk["data"]["metrics"]["annualized_volatility"]["value"]
        return msg([text(f"Synthetic fixture data. D-EQF compounded at {cagr * 100:.1f}% a year [E1] with "
                         f"{vol * 100:.2f}% volatility [E1], as of {risk['as_of']}.")])

    fake = FakeClient([
        msg([text("Let me look."), tool_use(1, "calculate_risk_metrics", {"symbol": "D-EQF", "window": "3Y", "rf": 0.35}),
             tool_use(2, "get_fund_profile", {"code": "D-EQF"})], stop="tool_use"),
        answer,
    ])
    r = Copilot(fake, "claude-opus-5-5", "medium").run(ctx, "How risky is D-EQF?")
    assert [e.id for e in r.evidence] == ["E1", "E2"] and all(e.status == "ok" for e in r.evidence)
    assert r.verification["status"] == "verified" and r.verification["counts"] == {"verified": 2}
    assert r.rounds == 2 and r.usage["input_tokens"] == 200 and r.usage["cache_read_input_tokens"] == 100
    assert r.evidence[0].is_fixture and "FIXTURE" in json.dumps(r.evidence[0].for_model())
    # Second request carries assistant content unchanged, then one user message with both tool_results.
    second = fake.calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and len(second[-1]["content"]) == 2
    assert {b["tool_use_id"] for b in second[-1]["content"]} == {"tu1", "tu2"}


def test_request_shape(ctx):
    fake = FakeClient([msg([text("No figures needed.")])])
    Copilot(fake, "claude-opus-5-5", "medium").run(ctx, "hello")
    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["output_config"] == {"effort": "medium"}
    assert kw["betas"] == [FALLBACK_BETA] and kw["fallbacks"] == "default"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"} and "Every figure" in kw["system"][0]["text"]
    assert "thinking" not in kw and "tool_choice" not in kw  # adaptive thinking by default; auto tool choice
    for t in kw["tools"]:
        assert t["strict"] is True and t["input_schema"]["additionalProperties"] is False
        assert set(t["input_schema"]["required"]) == set(t["input_schema"]["properties"])


def test_invented_numbers_are_flagged(ctx):
    fake = FakeClient([
        msg([tool_use(1, "get_fund_profile", {"code": "D-GLD"})], stop="tool_use"),
        msg([text("D-GLD returned 99.9% last year [E1]. It will likely rise 15% next year.")]),
    ])
    r = Copilot(fake, "claude-opus-5-5", "medium").run(ctx, "D-GLD?")
    statuses = [c["status"] for c in r.verification["claims"]]
    assert statuses == ["mismatch", "unsupported"] and r.verification["status"] == "unverified_claims"


def test_invalid_tool_input_returns_error_result(ctx):
    fake = FakeClient([
        msg([tool_use(1, "calculate_risk_metrics", {"symbol": "D-EQF", "window": "2Y", "rf": 0})], stop="tool_use"),
        lambda kw: msg([text("Could not compute: " + last_results(kw)[0]["error"])]),
    ])
    r = Copilot(fake, "claude-opus-5-5", "medium").run(ctx, "risk?")
    assert r.evidence[0].status == "error" and "INVALID_INPUT" in r.evidence[0].error
    assert fake.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_refusal_and_round_limit(ctx):
    refused = Copilot(FakeClient([msg([], stop="refusal", details=NS(category="cyber", explanation="x"))]), "claude-opus-5-5", "medium")
    r = refused.run(ctx, "q")
    assert r.stop_reason == "refusal" and r.refusal == {"category": "cyber", "explanation": "x"} and r.answer == ""

    loop = [msg([tool_use(i, "search_instruments", {"query": "bank"})], stop="tool_use") for i in range(2)]
    fake = FakeClient(loop + [msg([text("Final answer from evidence so far.")])])
    r = Copilot(fake, "claude-opus-5-5", "medium", max_rounds=3).run(ctx, "q")
    assert fake.calls[-1]["tool_choice"] == {"type": "none"} and "tool_choice" not in fake.calls[0]
    assert r.answer == "Final answer from evidence so far." and len(r.evidence) == 2


def test_auth_error_maps_to_unavailable(ctx):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.AuthenticationError("invalid x-api-key", response=httpx2.Response(401, request=req), body=None)
    with pytest.raises(CopilotUnavailable):
        Copilot(FakeClient([err]), "claude-opus-5-5", "medium").run(ctx, "q")


# ── HTTP layer ────────────────────────────────────────────────────────────────────────────────────
def signed_in(client, factory=None):
    c = TestClient(client.app)
    assert c.post("/api/v1/auth/register", json={"email": f"ai-{uuid.uuid4().hex[:8]}@example.com", "password": "correct horse battery"}).status_code == 201
    client.app.state.ai_client_factory = factory
    return c, {"X-CSRF-Token": c.cookies.get(CSRF_COOKIE)}


def test_query_endpoint_stores_evidence_and_history(client):
    fake = FakeClient([
        msg([tool_use(1, "get_portfolio_analytics", {"portfolio_name": None})], stop="tool_use"),
        msg([text("You have no portfolio yet.")]),
    ])
    c, h = signed_in(client, lambda: fake)
    try:
        r = c.post("/api/v1/research/query", json={"question": "How is my portfolio doing?"}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["evidence"][0]["status"] == "error" and "No matching portfolio" in body["evidence"][0]["error"]
        assert body["verification"]["status"] == "no_numeric_claims" and "Not investment advice" in body["disclaimer"]
        hist = c.get("/api/v1/research/history").json()
        assert hist[0]["query_id"] == body["query_id"]
        assert c.get(f"/api/v1/research/history/{body['query_id']}").json()["answer"] == "You have no portfolio yet."
        other, _ = signed_in(client, lambda: fake)
        assert other.get(f"/api/v1/research/history/{body['query_id']}").status_code == 404
    finally:
        client.app.state.ai_client_factory = None


def test_unconfigured_and_auth_required(client, monkeypatch):
    for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(v, raising=False)

    def no_creds():
        raise CopilotUnavailable("no credentials")

    c, h = signed_in(client, no_creds)
    try:
        r = c.post("/api/v1/research/query", json={"question": "anything at all"}, headers=h)
        assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    finally:
        client.app.state.ai_client_factory = None
    st = TestClient(client.app).get("/api/v1/research/status").json()
    assert st["model"] == "claude-opus-5-5" and len(st["tools"]) == 13
    assert {t["name"] for t in st["tools"] if not t["available"]} == {"get_financial_statements", "get_valuation_metrics", "get_macro_series", "get_disclosures"}
    assert TestClient(client.app).post("/api/v1/research/query", json={"question": "anything"}).status_code == 401


def test_rate_limit_per_user(client):
    c, h = signed_in(client, lambda: FakeClient([msg([text("ok")]) for _ in range(10)]))
    try:
        codes = [c.post("/api/v1/research/query", json={"question": "quick question"}, headers=h).status_code for _ in range(8)]
        assert codes[:6] == [200] * 6 and codes[6:] == [429, 429]
    finally:
        client.app.state.ai_client_factory = None
